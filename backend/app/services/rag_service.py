# -*- coding: utf-8 -*-
"""RAG 主链路服务（客服版，T4 重构）。

链路顺序（架构 §4 时序图）：
    ① 规则前置拦截（triage_rules，命中 → action=human，不进检索）
    ② 检索层（ChromaDB Top-20 → 重排 Top-5）
    ③ 拒答阈值短路（Top-1 < RETRIEVAL_MIN_SCORE → action=refusal，不调 LLM）
    ④ 分诊层（triage_service，qwen-turbo JSON）
    ⑤ 分支生成：
        direct   → qwen-max 生成（企业 SYSTEM_PROMPT）
        cautious → qwen-max 生成 + 程序性追加谨慎尾缀（R5，100% 附带）
        human    → 不调 LLM，返回转人工常量文案
        refusal  → 不调 LLM，返回拒答常量文案

关键设计：转人工与拒答两个分支完全不经过 LLM 生成，回答是后端常量，
让 R3（100% 拦截）与 R4（100% 拒答、零编造）成为确定性逻辑。
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import List, Optional

import dashscope
from dashscope import Generation

from app.core.config import settings
from app.core.constants import (
    REFUSAL_TEXT,
    HUMAN_TEXT,
    CAUTIOUS_SUFFIX,
    ACTION_DIRECT,
    ACTION_CAUTIOUS,
    ACTION_HUMAN,
    ACTION_REFUSAL,
    COVERAGE_UNCOVERED,
    DEFAULT_QUESTION_TYPE,
)
from app.services.doc_service import get_collection, embed_texts
from app.services.triage_rules import match_human_rule
from app.services.triage_service import triage
from app.schemas.schemas import Citation, TriageResult

dashscope.api_key = settings.DASHSCOPE_API_KEY

logger = logging.getLogger("rag_service")

# ── 客服 SYSTEM_PROMPT（R10）─────────────────────────────
SYSTEM_PROMPT = """你是企业官方智能客服助手，为 3D 打印机用户提供售前咨询与售后支持。

【回答依据 — 最高优先级】
1. 你只能基于下方【知识库内容】作答，严禁使用你自身训练知识中的任何信息
2. 知识库未提及的内容（公司股价、高管信息、未发布产品、竞品对比、个案核实等）必须回答"暂时无法确认"，严禁推测、编造、给出口头承诺
3. 涉及设备安全（冒烟、异响、发热、拆机）的问题，不得给出"没有危险/可以继续使用"等结论，一律建议联系官方客服核实

【回答风格】
- 直接回答：知识库完整覆盖时，简洁准确地作答，可适当引用参数、步骤
- 谨慎回答：知识库部分覆盖或涉及政策边界时，基于已有内容作答，不延伸推测
- 多产品对比时逐一列明差异；故障排查给出可执行的分步操作

【知识库内容】
{context}
"""


# ── 返回结构 ────────────────────────────────────────────────

@dataclass
class AnswerBundle:
    """一次问答的完整产出（含分诊信息，供入库/缓存/前端渲染）。"""
    answer: str
    citations: List[Citation] = field(default_factory=list)
    triage_type: str = DEFAULT_QUESTION_TYPE
    triage_action: str = ACTION_DIRECT
    retrieved_sources: List[str] = field(default_factory=list)

    def to_cache_dict(self) -> dict:
        """序列化为可写 Redis 的字典（缓存整个 Bundle，保证命中缓存时分诊一致）。"""
        return {
            "answer": self.answer,
            "citations": [c.model_dump() for c in self.citations],
            "triage_type": self.triage_type,
            "triage_action": self.triage_action,
            "retrieved_sources": self.retrieved_sources,
        }

    @classmethod
    def from_cache_dict(cls, data: dict) -> "AnswerBundle":
        """从缓存字典还原（兼容旧版无分诊字段的缓存，默认 direct）。"""
        return cls(
            answer=data.get("answer", ""),
            citations=[Citation(**c) for c in data.get("citations", [])],
            triage_type=data.get("triage_type", DEFAULT_QUESTION_TYPE),
            triage_action=data.get("triage_action", ACTION_DIRECT),
            retrieved_sources=data.get("retrieved_sources", []),
        )


# ── 检索层 ──────────────────────────────────────────────────

def _retrieve(question: str, top_k: int = 20) -> List[dict]:
    """从 ChromaDB 检索相关片段（score = 1 - cosine_distance）。"""
    q_embedding = embed_texts([question])[0]
    collection = get_collection()
    if collection.count() == 0:
        return []
    results = collection.query(
        query_embeddings=[q_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"]
    )
    items = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        items.append({
            "content": doc,
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "score": 1 - dist,
        })
    return items


def _rerank(items: List[dict], top_k: int = 5) -> List[dict]:
    """按相关度降序，取前 top_k 个。"""
    items.sort(key=lambda x: x["score"], reverse=True)
    return items[:top_k]


def _extract_sources(items: List[dict]) -> List[str]:
    """提取检索来源（URL 优先，其次 source 名），去重保持顺序。"""
    seen = set()
    sources = []
    for item in items:
        label = item.get("url") or item.get("source") or ""
        if label and label not in seen:
            seen.add(label)
            sources.append(label)
    return sources


# ── 生成层 ──────────────────────────────────────────────────

def _call_llm(question: str, context: str, history: List[dict]) -> str:
    """调用 qwen-max 生成回答（企业 SYSTEM_PROMPT）。

    注意：qwen-max 对独立的 system= 参数不生效（会忽略知识库上下文、按自身训练知识作答），
    必须把 system 提示词作为 messages[0] 传入才会遵守。实测两种方式差异明显，见 README 排障。
    """
    messages = []
    # system 提示词（含知识库上下文）放在 messages[0]，保证模型严格基于知识库作答
    messages.append({"role": "system", "content": SYSTEM_PROMPT.format(context=context)})
    # 带入历史消息（最多最近 6 条）
    for msg in history[-6:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    resp = Generation.call(
        model=settings.LLM_MODEL,
        messages=messages,
        result_format="message",
        max_tokens=2048,
    )
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"LLM 调用失败: {resp.message}")
    return resp.output.choices[0].message.content


def _build_context(top_items: List[dict]) -> str:
    """把 Top-K 片段拼成知识库上下文。"""
    return "\n\n".join(
        [f"[片段{i + 1}] 来源：{item['source']}\n{item['content']}"
         for i, item in enumerate(top_items)]
    )


def _build_citations(top_items: List[dict], min_score: float = 0.3) -> List[Citation]:
    """构造引用列表（相关度过低的不展示）。"""
    return [
        Citation(content=item["content"], source=item["source"])
        for item in top_items
        if item["score"] > min_score
    ]


def _log_triage(question: str, action: str, qtype: str, score_top1: Optional[float],
                rule_hit: Optional[str]) -> None:
    """单行 JSON 日志（R12 基础版）：问题/分诊/Top1 分数/命中规则。"""
    logger.info(json.dumps({
        "event": "triage",
        "question": question[:100],
        "triage_action": action,
        "triage_type": qtype,
        "score_top1": round(score_top1, 4) if score_top1 is not None else None,
        "rule_hit": rule_hit,
    }, ensure_ascii=False))


# ── 主入口 ──────────────────────────────────────────────────

async def answer_question(question: str, history: List[dict]) -> AnswerBundle:
    """问答主入口：规则拦截 → 检索 → 阈值短路 → 分诊 → 分支生成。

    Args:
        question: 用户问题原文。
        history: 会话历史消息 [{"role": ..., "content": ...}]。

    Returns:
        AnswerBundle（answer/citations/triage_type/triage_action/retrieved_sources）。
    """
    # ① 规则前置拦截（R3）：命中 → 直接转人工，不检索/不分诊/不生成
    rule_hit = match_human_rule(question)
    if rule_hit is not None:
        _log_triage(question, ACTION_HUMAN, DEFAULT_QUESTION_TYPE, None, rule_hit)
        return AnswerBundle(
            answer=HUMAN_TEXT,
            citations=[],
            triage_type=DEFAULT_QUESTION_TYPE,
            triage_action=ACTION_HUMAN,
            retrieved_sources=[],
        )

    # ② 检索层
    raw_items = await asyncio.to_thread(_retrieve, question, 20)
    top_items = _rerank(raw_items, top_k=settings.RETRIEVAL_TOP_K) if raw_items else []
    top1_score = top_items[0]["score"] if top_items else None
    sources = _extract_sources(top_items)

    # ③ 拒答阈值短路（R4）：知识库为空或 Top-1 低于阈值 → 拒答，不调 LLM
    if top1_score is None or top1_score < settings.RETRIEVAL_MIN_SCORE:
        _log_triage(question, ACTION_REFUSAL, DEFAULT_QUESTION_TYPE, top1_score, None)
        return AnswerBundle(
            answer=REFUSAL_TEXT,
            citations=[],
            triage_type=DEFAULT_QUESTION_TYPE,
            triage_action=ACTION_REFUSAL,
            retrieved_sources=sources,
        )

    # ④ 分诊层（R2）
    triage_result: TriageResult = await asyncio.to_thread(triage, question, top_items)
    _log_triage(question, triage_result.action, triage_result.question_type, top1_score, None)

    # ⑤ 分支生成
    # 5a. 分诊判定 uncovered 或仍需人工 → 拒答 / 转人工，均不调 LLM
    if triage_result.kb_coverage == COVERAGE_UNCOVERED:
        return AnswerBundle(
            answer=REFUSAL_TEXT,
            citations=[],
            triage_type=triage_result.question_type,
            triage_action=ACTION_REFUSAL,
            retrieved_sources=sources,
        )
    if triage_result.action == ACTION_HUMAN:
        return AnswerBundle(
            answer=HUMAN_TEXT,
            citations=[],
            triage_type=triage_result.question_type,
            triage_action=ACTION_HUMAN,
            retrieved_sources=sources,
        )

    # 5b. direct / cautious → 正常 RAG 生成
    context = _build_context(top_items)
    answer = await asyncio.to_thread(_call_llm, question, context, history)
    citations = _build_citations(top_items)

    # cautious：程序性追加谨慎尾缀（R5，不靠模型自觉，保证 100% 附带）
    if triage_result.action == ACTION_CAUTIOUS:
        answer = answer + CAUTIOUS_SUFFIX

    return AnswerBundle(
        answer=answer,
        citations=citations,
        triage_type=triage_result.question_type,
        triage_action=triage_result.action,
        retrieved_sources=sources,
    )
