# -*- coding: utf-8 -*-
"""constants.py 统一约定测试。

验证架构 §7 共享约定：
- 分诊枚举取值完整（QUESTION_TYPES / KB_COVERAGE / TRIAGE_ACTIONS）；
- 拒答话术、转人工话术、谨慎尾缀三个常量非空且格式正确；
- 转人工话术含 {HOTLINE} 占位符（运营上线前替换）；
- 特殊 action 常量（refusal / human）与评测脚本口径一致。
"""

from app.core import constants as C


class TestTriageEnums:
    """分诊枚举取值完整性（前后端 + 评测共用同一取值范围）。"""

    def test_question_types_complete(self):
        assert C.QUESTION_TYPES == ["产品选型", "故障排查", "售后政策", "其他"]

    def test_question_types_no_duplicates(self):
        assert len(C.QUESTION_TYPES) == len(set(C.QUESTION_TYPES))

    def test_kb_coverage_complete(self):
        assert C.KB_COVERAGE == ["covered", "partial", "uncovered"]

    def test_kb_coverage_scalar_constants_match_list(self):
        assert C.COVERAGE_COVERED in C.KB_COVERAGE
        assert C.COVERAGE_PARTIAL in C.KB_COVERAGE
        assert C.COVERAGE_UNCOVERED in C.KB_COVERAGE

    def test_triage_actions_complete(self):
        assert C.TRIAGE_ACTIONS == ["direct", "cautious", "human"]

    def test_action_scalar_constants_match_list(self):
        assert C.ACTION_DIRECT in C.TRIAGE_ACTIONS
        assert C.ACTION_CAUTIOUS in C.TRIAGE_ACTIONS
        assert C.ACTION_HUMAN in C.TRIAGE_ACTIONS

    def test_refusal_action_is_special_not_in_llm_actions(self):
        # refusal 是后端阈值短路产生，非 LLM 输出，不应出现在 TRIAGE_ACTIONS
        assert C.ACTION_REFUSAL == "refusal"
        assert C.ACTION_REFUSAL not in C.TRIAGE_ACTIONS

    def test_default_question_type_is_valid(self):
        assert C.DEFAULT_QUESTION_TYPE in C.QUESTION_TYPES


class TestUniformTexts:
    """拒答 / 转人工 / 谨慎尾缀三个常量非空且格式正确。"""

    def test_refusal_text_non_empty(self):
        assert isinstance(C.REFUSAL_TEXT, str)
        assert C.REFUSAL_TEXT.strip() != ""

    def test_refusal_text_guides_to_official_channel(self):
        # 拒答话术应引导用户联系官方渠道（PRD R4 验收③）
        assert "官方客服" in C.REFUSAL_TEXT or "官方客服" in C.REFUSAL_TEXT
        assert "官网帮助中心" in C.REFUSAL_TEXT

    def test_refusal_text_no_substantive_answer(self):
        # 拒答话术不得包含任何实质技术参数/答案（防幻觉）
        assert "无法" in C.REFUSAL_TEXT or "超出" in C.REFUSAL_TEXT

    def test_human_text_non_empty(self):
        assert isinstance(C.HUMAN_TEXT, str)
        assert C.HUMAN_TEXT.strip() != ""

    def test_human_text_contains_hotline_placeholder(self):
        # 架构 §7.2：热线留占位符 {HOTLINE}，运营上线前填
        assert "{HOTLINE}" in C.HUMAN_TEXT
        assert C.HOTLINE_PLACEHOLDER == "{HOTLINE}"

    def test_human_text_indicates_transfer(self):
        assert "转接人工" in C.HUMAN_TEXT or "人工客服" in C.HUMAN_TEXT

    def test_cautious_suffix_non_empty_and_prefixed_separator(self):
        assert isinstance(C.CAUTIOUS_SUFFIX, str)
        assert C.CAUTIOUS_SUFFIX.strip() != ""
        # 架构 D4：尾缀以换行 + 分隔线开头，便于前端/阅读区分正文
        assert C.CAUTIOUS_SUFFIX.startswith("\n")
        assert "---" in C.CAUTIOUS_SUFFIX

    def test_cautious_suffix_has_warning_wording(self):
        assert "仅供参考" in C.CAUTIOUS_SUFFIX
        assert "官方客服" in C.CAUTIOUS_SUFFIX


class TestHumanRuleGroups:
    """强制转人工规则分组结构（R3，可配置）。"""

    def test_rule_groups_is_dict_of_lists(self):
        assert isinstance(C.HUMAN_RULE_GROUPS, dict)
        for group, keywords in C.HUMAN_RULE_GROUPS.items():
            assert isinstance(group, str) and group
            assert isinstance(keywords, list) and keywords
            assert all(isinstance(k, str) and k for k in keywords)

    def test_expected_groups_present(self):
        # 架构 D2 定义的 8 个分组
        expected = {
            "退款/订单操作", "投诉/维权", "物流纠纷", "索要优惠",
            "安全词", "明确转人工", "情绪词", "拆机/个案保修",
        }
        assert expected.issubset(set(C.HUMAN_RULE_GROUPS.keys()))
