# -*- coding: utf-8 -*-
"""分诊层服务（R2）：独立轻量 LLM 调用，输出结构化分诊 JSON。

设计要点（架构 D1）：
- 与生成链路分离：分诊用 qwen-turbo + JSON mode，结构化稳定且延迟低；
- 输入为用户问题 + Top-K 检索片段（含相似度分数）；
- 输出四字段：question_type / kb_coverage / action / reason；
- 任何异常（调用失败、JSON 非法、字段缺失）都兜底为 cautious，
  保证分诊失败时用户仍能拿到基于知识库的回答而非报错。
"""

import json
from http import HTTPStatus
from typing import List

import dashscope
from dashscope import Generation

from app.core.config import settings
from app.core.constants import (
    QUESTION_TYPES,
    KB_COVERAGE,
    TRIAGE_ACTIONS,
    COVERAGE_COVERED,
    COVERAGE_UNCOVERED,
    ACTION_CAUTIOUS,
    DEFAULT_QUESTION_TYPE,
)
from app.schemas.schemas import TriageResult

dashscope.api_key = settings.DASHSCOPE_API_KEY

# 分诊系统提示词：要求模型只输出 JSON，不输出任何多余文本
TRIAGE_SYSTEM_PROMPT = """你是企业客服系统的问题分诊器。根据用户问题和知识库检索片段，判断问题类型、知识库覆盖度和建议处理方式。

【输出要求】
只输出一个 JSON 对象，不要输出任何其他文字、解释或 markdown 代码块标记：
{
  "question_type": "产品选型 | 故障排查 | 售后政策 | 其他",
  "kb_coverage": "covered | partial | uncovered",
  "action": "direct | cautious | human",
  "reason": "一句话判断依据，不超过50字"
}

【字段含义】
- question_type：产品选型=参数对比/选购建议；故障排查=使用问题/维修排障；售后政策=保修/退换/下载等服务政策；其他=不属于以上三类
- kb_coverage：covered=检索片段完整覆盖问题；partial=部分覆盖或涉及政策边界；uncovered=检索片段与问题无关
- action：direct=完整覆盖可直接作答；cautious=部分覆盖或涉及政策/安全边界需谨慎作答；human=涉及个案核实、退款投诉、安全事故等必须人工处理

【判定约束】
- 检索最高相似度分数 ≥ {covered_score} 时倾向 covered；分数很低且内容无关时必须 uncovered
- 安全相关（冒烟/异响/发热/拆机）或个案核实类问题，action 必须为 human
"""


def _build_prompt(question: str, items: List[dict]) -> str:
    """构建分诊用户提示词：问题 + Top-K 片段（含分数）。"""
    lines = [f"用户问题：{question}", "", f"知识库检索片段（共 {len(items)} 条，附相似度分数）："]
    for i, item in enumerate(items):
        lines.append(f"[片段{i + 1}] 相似度={item['score']:.3f} 来源={item.get('source', '')}")
        lines.append(item["content"][:400])  # 截断长片段，控制 token 消耗
        lines.append("")
    top1 = items[0]["score"] if items else 0.0
    lines.append(f"检索最高相似度分数：{top1:.3f}")
    return "\n".join(lines)


def _call_triage_llm(prompt: str) -> dict:
    """调用 qwen-turbo 分诊（JSON mode），返回解析后的字典。

    Raises:
        RuntimeError: LLM 调用失败或返回内容不是合法 JSON。
    """
    resp = Generation.call(
        model=settings.TRIAGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        system=TRIAGE_SYSTEM_PROMPT.format(covered_score=settings.TRIAGE_COVERED_SCORE),
        result_format="message",
        response_format={"type": "json_object"},  # JSON mode，强制结构化输出
        max_tokens=256,
        temperature=0.1,  # 分诊是判断任务，低温保证稳定
    )
    if resp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"分诊 LLM 调用失败: {resp.message}")

    content = resp.output.choices[0].message.content
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"分诊结果不是合法 JSON: {content!r}") from e


def _sanitize(raw: dict) -> TriageResult:
    """清洗分诊结果：非法取值一律回退到安全默认值。"""
    question_type = raw.get("question_type", DEFAULT_QUESTION_TYPE)
    if question_type not in QUESTION_TYPES:
        question_type = DEFAULT_QUESTION_TYPE

    kb_coverage = raw.get("kb_coverage", "partial")
    if kb_coverage not in KB_COVERAGE:
        kb_coverage = "partial"

    action = raw.get("action", ACTION_CAUTIOUS)
    if action not in TRIAGE_ACTIONS:
        action = ACTION_CAUTIOUS

    reason = str(raw.get("reason", ""))[:100]

    return TriageResult(
        question_type=question_type,
        kb_coverage=kb_coverage,
        action=action,
        reason=reason,
    )


def triage(question: str, items: List[dict]) -> TriageResult:
    """分诊入口：对已通过检索阈值的问题做类型/覆盖度/动作判断。

    Args:
        question: 用户问题原文。
        items: 重排后的 Top-K 检索片段（含 content/source/score）。

    Returns:
        TriageResult；任何异常都兜底为 cautious（保守作答），不抛错。
    """
    # 空检索结果（理论上调用方已做阈值短路，防御性处理）
    if not items:
        return TriageResult(
            question_type=DEFAULT_QUESTION_TYPE,
            kb_coverage=COVERAGE_UNCOVERED,
            action=ACTION_CAUTIOUS,
            reason="无检索结果",
        )

    # 硬分数线索：Top-1 明显低于 covered 线时，提示模型倾向保守
    try:
        prompt = _build_prompt(question, items)
        raw = _call_triage_llm(prompt)
        return _sanitize(raw)
    except Exception:
        # 分诊失败兜底：按分数给一个保守结果，保证链路不中断
        top1 = items[0]["score"]
        coverage = COVERAGE_COVERED if top1 >= settings.TRIAGE_COVERED_SCORE else "partial"
        return TriageResult(
            question_type=DEFAULT_QUESTION_TYPE,
            kb_coverage=coverage,
            action=ACTION_CAUTIOUS,  # 兜底谨慎回答（后端会自动追加尾缀）
            reason="分诊服务异常，兜底谨慎回答",
        )
