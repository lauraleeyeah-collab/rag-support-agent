# -*- coding: utf-8 -*-
"""拒答短路逻辑测试（R4）。

核心验证（架构 D3/D4 + PRD R4 底线）：
- 检索 Top-1 相似度 < RETRIEVAL_MIN_SCORE 时**不调用 LLM**，直接返回拒答话术；
- 返回的 triage_action == "refusal"；
- 拒答话术与 constants.REFUSAL_TEXT 逐字一致；
- 知识库为空（无检索结果）同样走拒答短路；
- 转人工 / 拒答分支均不调 LLM（机制性保证零编造）。

实现说明：
rag_service 顶层 import 了 dashscope / doc_service（chromadb）/ triage_service /
schemas（pydantic）等重依赖。本测试在导入 rag_service 之前用轻量 stub 替换这些
模块（conftest 已 stub dashscope），随后 monkeypatch 检索层 `_retrieve` 与分诊层，
从而可在无 LLM / 无 ChromaDB / 无网络环境下确定性地验证短路分支。
"""

import asyncio
import sys
import types
from unittest import mock


from app.core import constants as C


# ── 在导入 rag_service 之前，stub 掉它的重型依赖模块 ─────────────────────
def _install_stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# app.services.doc_service：提供 get_collection / embed_texts（短路测试不会触达）
_install_stub(
    "app.services.doc_service",
    get_collection=lambda: (_ for _ in ()).throw(RuntimeError("不应连接 ChromaDB")),
    embed_texts=lambda texts: [[0.0] * 8 for _ in texts],
)

# app.schemas.schemas：rag_service 只需 Citation / TriageResult 两个可构造类型
class _Citation:
    def __init__(self, content="", source=""):
        self.content = content
        self.source = source

    def model_dump(self):
        return {"content": self.content, "source": self.source}


class _TriageResult:
    def __init__(self, question_type="其他", kb_coverage="partial",
                 action="cautious", reason=""):
        self.question_type = question_type
        self.kb_coverage = kb_coverage
        self.action = action
        self.reason = reason


_install_stub("app.schemas.schemas", Citation=_Citation, TriageResult=_TriageResult)

# app.services.triage_service：triage 占位（短路分支不应调用，统一用 mock 替换）
_install_stub("app.services.triage_service", triage=lambda q, items: _TriageResult())

# app.core.config：真实 config.py 依赖 pydantic_settings（本机未安装）。
# rag_service 仅从 settings 读取若干标量配置，这里提供一个等价的轻量 settings。
import app.core  # noqa: F401,E402  确保真实 app.core 包已加载，再覆盖其 config 子模块


class _Settings:
    DASHSCOPE_API_KEY = ""
    LLM_MODEL = "qwen-max"
    TRIAGE_MODEL = "qwen-turbo"
    RETRIEVAL_TOP_K = 5
    RETRIEVAL_MIN_SCORE = 0.45   # 与 config.py 默认一致，供边界测试引用
    TRIAGE_COVERED_SCORE = 0.55


_install_stub("app.core.config", settings=_Settings())
setattr(sys.modules["app.core"], "config", sys.modules["app.core.config"])

# 现在安全导入 rag_service（dashscope / config / 检索与分诊层均已 stub）
import app.services.rag_service as rag  # noqa: E402


# ── 工具 ────────────────────────────────────────────────────────────────
def _items(top1_score: float):
    """构造按分数降序的检索结果（Top-1 分数为 top1_score）。"""
    return [
        {"content": f"片段{i}", "source": f"来源{i}", "url": f"http://x/{i}",
         "score": top1_score - i * 0.01}
        for i in range(3)
    ]


def _run(coro):
    return asyncio.run(coro)


# ── 拒答短路：低相似度 ─────────────────────────────────────────────────
class TestRefusalShortCircuit:
    """Top-1 < RETRIEVAL_MIN_SCORE → 不调 LLM，直接拒答。"""

    def test_low_score_returns_refusal_action(self, monkeypatch):
        monkeypatch.setattr(rag, "_retrieve",
                            lambda q, top_k=20: _items(0.30))
        # 确保分诊与 LLM 若被调用则报错（短路分支不应触达）
        monkeypatch.setattr(rag, "triage",
                            mock.Mock(side_effect=AssertionError("不应调用分诊")))
        monkeypatch.setattr(rag, "_call_llm",
                            mock.Mock(side_effect=AssertionError("不应调用 LLM")))

        bundle = _run(rag.answer_question("企业公司股票代码多少？", []))
        assert bundle.triage_action == C.ACTION_REFUSAL == "refusal"

    def test_low_score_returns_exact_refusal_text(self, monkeypatch):
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(0.20))
        monkeypatch.setattr(rag, "triage",
                            mock.Mock(side_effect=AssertionError("不应调用分诊")))
        bundle = _run(rag.answer_question("企业CEO叫什么名字？", []))
        assert bundle.answer == C.REFUSAL_TEXT  # 逐字一致

    def test_low_score_does_not_call_llm(self, monkeypatch):
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(0.10))
        llm_mock = mock.Mock(side_effect=AssertionError("拒答分支不应调用 LLM"))
        triage_mock = mock.Mock(side_effect=AssertionError("拒答短路不应调用分诊"))
        monkeypatch.setattr(rag, "_call_llm", llm_mock)
        monkeypatch.setattr(rag, "triage", triage_mock)

        bundle = _run(rag.answer_question("X1系列下一代什么时候发布？", []))
        assert bundle.triage_action == "refusal"
        llm_mock.assert_not_called()
        triage_mock.assert_not_called()

    def test_empty_knowledge_base_refuses(self, monkeypatch):
        # 知识库为空：_retrieve 返回 []，top1_score 为 None → 拒答
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: [])
        monkeypatch.setattr(rag, "_call_llm",
                            mock.Mock(side_effect=AssertionError("不应调用 LLM")))
        bundle = _run(rag.answer_question("随便一个问题", []))
        assert bundle.triage_action == "refusal"
        assert bundle.answer == C.REFUSAL_TEXT

    def test_boundary_score_exactly_at_threshold_refuses(self, monkeypatch):
        # 阈值边界：score < MIN 才拒答；恰好等于阈值则**不**拒答（进入分诊）。
        # 这里验证「低于阈值」一侧（= MIN - ε）确实拒答。
        eps = 0.001
        below = rag.settings.RETRIEVAL_MIN_SCORE - eps
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(below))
        monkeypatch.setattr(rag, "triage",
                            mock.Mock(side_effect=AssertionError("低于阈值不应分诊")))
        bundle = _run(rag.answer_question("金属能打印吗", []))
        assert bundle.triage_action == "refusal"


# ── 分诊判定 uncovered 也走拒答（不调 LLM）─────────────────────────────
class TestTriageUncoveredRefusal:
    """分诊返回 kb_coverage=uncovered → 拒答分支，不调生成 LLM。"""

    def test_triage_uncovered_refuses_without_llm(self, monkeypatch):
        high = rag.settings.RETRIEVAL_MIN_SCORE + 0.1  # 高于硬阈值，进入分诊
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(high))
        monkeypatch.setattr(
            rag, "triage",
            lambda q, items: _TriageResult(
                question_type="其他", kb_coverage="uncovered", action="cautious"))
        llm_mock = mock.Mock(side_effect=AssertionError("uncovered 不应调生成 LLM"))
        monkeypatch.setattr(rag, "_call_llm", llm_mock)

        bundle = _run(rag.answer_question("竞品对比怎么样", []))
        assert bundle.triage_action == "refusal"
        assert bundle.answer == C.REFUSAL_TEXT
        llm_mock.assert_not_called()


# ── 转人工分支：规则命中 / 分诊 human 均不调 LLM ───────────────────────
class TestHumanBranchNoLLM:
    def test_rule_hit_returns_human_text_no_llm(self, monkeypatch):
        # 规则前置命中（「我要退款，订单号12345」含退款）→ 不检索/不分诊/不生成
        retrieve_mock = mock.Mock(side_effect=AssertionError("规则命中不应检索"))
        llm_mock = mock.Mock(side_effect=AssertionError("规则命中不应调 LLM"))
        monkeypatch.setattr(rag, "_retrieve", retrieve_mock)
        monkeypatch.setattr(rag, "_call_llm", llm_mock)

        bundle = _run(rag.answer_question("我要退款，订单号12345", []))
        assert bundle.triage_action == "human"
        assert bundle.answer == C.HUMAN_TEXT
        retrieve_mock.assert_not_called()
        llm_mock.assert_not_called()

    def test_triage_human_returns_human_text_no_llm(self, monkeypatch):
        high = rag.settings.RETRIEVAL_MIN_SCORE + 0.1
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(high))
        monkeypatch.setattr(
            rag, "triage",
            lambda q, items: _TriageResult(
                question_type="售后政策", kb_coverage="partial", action="human"))
        llm_mock = mock.Mock(side_effect=AssertionError("human 分支不应调 LLM"))
        monkeypatch.setattr(rag, "_call_llm", llm_mock)

        bundle = _run(rag.answer_question("我这个具体情况算不算保修范围", []))
        assert bundle.triage_action == "human"
        assert bundle.answer == C.HUMAN_TEXT
        llm_mock.assert_not_called()


# ── cautious 分支：程序性追加尾缀（R5）────────────────────────────────
class TestCautiousSuffix:
    def test_cautious_appends_suffix(self, monkeypatch):
        high = rag.settings.RETRIEVAL_MIN_SCORE + 0.1
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(high))
        monkeypatch.setattr(
            rag, "triage",
            lambda q, items: _TriageResult(
                question_type="故障排查", kb_coverage="partial", action="cautious"))
        monkeypatch.setattr(rag, "_call_llm", lambda q, ctx, hist: "这是排查步骤。")

        bundle = _run(rag.answer_question("喷头堵了咋办", []))
        assert bundle.triage_action == "cautious"
        assert bundle.answer.endswith(C.CAUTIOUS_SUFFIX)
        assert "这是排查步骤。" in bundle.answer

    def test_direct_does_not_append_suffix(self, monkeypatch):
        high = rag.settings.RETRIEVAL_MIN_SCORE + 0.1
        monkeypatch.setattr(rag, "_retrieve", lambda q, top_k=20: _items(high))
        monkeypatch.setattr(
            rag, "triage",
            lambda q, items: _TriageResult(
                question_type="产品选型", kb_coverage="covered", action="direct"))
        monkeypatch.setattr(rag, "_call_llm", lambda q, ctx, hist: "X1 与 A1 区别如下。")

        bundle = _run(rag.answer_question("X1和A1区别", []))
        assert bundle.triage_action == "direct"
        assert not bundle.answer.endswith(C.CAUTIOUS_SUFFIX)
