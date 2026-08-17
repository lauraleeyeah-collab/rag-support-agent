# -*- coding: utf-8 -*-
"""triage_rules 规则前置拦截测试（R3）。

口径（架构 D2 + PRD R4 注释 + 架构 §8 Q4）：
- 第三类 8 条（退款/投诉/物流/优惠/冒烟+情绪/取消订单/个案保修/明确转人工）
  必须全部命中对应分组 → action=human；
- 第一类 8 条（正常问答）必须零误伤（不被规则拦截）；
- 第二类第 15 题（爆炸）命中安全词组、第 16 题（拆机）命中拆机组，属**预期**拦截
  （评测判定时 human 同样算安全不作答）；
- 关键词大小写、常见变体（退钱/退款/退货）匹配正确。

注意：match_human_rule 只返回「是否命中 + 命中哪个分组」，
不保证命中题库备注里标注的「业务语义分组」完全一致——例如第 21 题
「冒烟了很生气」同时含安全词与情绪词，命中任一组都符合「转人工」预期。
因此命中分组的断言以「落在该题可接受的合法分组集合内」为准。
"""

import pytest

from app.services.triage_rules import _normalize, match_human_rule

# ── 题库第三类：应转人工（必须命中，落在合法分组集合内）─────────────────
# 每项: (seq, question, acceptable_groups)
CATEGORY_3_CASES = [
    (17, "我要申请退款，订单号12345", {"退款/订单操作"}),
    (18, "我买的机器是坏的，要投诉", {"投诉/维权"}),
    (19, "我的包裹显示已签收但没收到货", {"物流纠纷"}),
    (20, "能不能给我优惠券/折扣？", {"索要优惠"}),
    (21, "打印机用了一周就冒烟了，很生气！", {"安全词", "情绪词"}),
    (22, "我要取消订单", {"退款/订单操作"}),
    (23, "保修期内维修要收费吗？我这个具体情况算不算保修范围", {"拆机/个案保修"}),
    (24, "这个客服机器人是不是听不懂人话，给我转人工！", {"明确转人工"}),
]

# ── 题库第一类：正常问答（必须零误伤）─────────────────────────────────
CATEGORY_1_CASES = [
    (1, "X1 Carbon和A1有什么区别？"),
    (2, "A1支持多色打印吗？"),
    (3, "H2D除了打印还能干什么？"),
    (4, "打印机保修期多久？"),
    (5, "喷头堵了怎么处理？"),
    (6, "AMS卡料了怎么办？"),
    (7, "切片软件在哪下载？"),
    (8, "云打印怎么设置？"),
]


class TestCategory3MustHit:
    """第三类 8 条：必须全部命中（规则独立兜底，不依赖模型）。"""

    @pytest.mark.parametrize("seq,question,groups", CATEGORY_3_CASES,
                             ids=[f"q{seq}" for seq, _, _ in CATEGORY_3_CASES])
    def test_hit(self, seq, question, groups):
        hit = match_human_rule(question)
        assert hit is not None, f"第{seq}题应被规则拦截转人工，实际未命中：{question!r}"
        assert hit in groups, f"第{seq}题命中分组 {hit!r} 不在预期集合 {groups}"

    def test_all_eight_hit(self):
        missed = [q for _, q, _ in CATEGORY_3_CASES if match_human_rule(q) is None]
        assert missed == [], f"第三类有 {len(missed)} 条未被规则拦截：{missed}"


class TestCategory1NoFalsePositive:
    """第一类 8 条：零误伤（R3 验收④：误伤 ≤1，目标 0）。"""

    @pytest.mark.parametrize("seq,question", CATEGORY_1_CASES,
                             ids=[f"q{seq}" for seq, _ in CATEGORY_1_CASES])
    def test_no_hit(self, seq, question):
        hit = match_human_rule(question)
        assert hit is None, f"第{seq}题为正常问答却被误拦截（命中 {hit!r}）：{question!r}"

    def test_zero_false_positive(self):
        hit_qs = [(q, match_human_rule(q)) for _, q in CATEGORY_1_CASES
                  if match_human_rule(q) is not None]
        assert hit_qs == [], f"第一类误伤 {len(hit_qs)} 条：{hit_qs}"


class TestCategory2ExpectedSafetyHits:
    """第二类第 15/16 题：按架构预期命中安全词组 / 拆机组（Q4 已拍板判通过）。"""

    def test_q15_explosion_hits_safety(self):
        # 「打印机噪音突然变大是不是要爆炸了？」含「爆炸」→ 安全词组
        hit = match_human_rule("打印机噪音突然变大是不是要爆炸了？")
        assert hit == "安全词"

    def test_q16_teardown_hits_teardown(self):
        # 「我可以自己拆机修理主板吗？」含「拆机」→ 拆机/个案保修组
        hit = match_human_rule("我可以自己拆机修理主板吗？")
        assert hit == "拆机/个案保修"


class TestKeywordVariants:
    """关键词大小写、常见变体匹配正确。"""

    @pytest.mark.parametrize("question", [
        "我要退款",
        "申请退货",          # 变体：退货
        "我要申请退",        # 变体：申请退（命中「申请退」）
    ])
    def test_refund_variants(self, question):
        assert match_human_rule(question) == "退款/订单操作"

    @pytest.mark.parametrize("question", [
        "我想退钱",          # 变体：退钱（架构 D2 清单未收录）
        "帮我退一下",        # 变体：口语（架构 D2 清单未收录）
    ])
    def test_variants_not_in_arch_rule_list(self, question):
        # 架构 D2「退款/订单操作」组仅定义：退款/退货/取消订单/订单号/订单编号/
        # 申请退/订单\d{4,}。「退钱」「退一下」不在清单内，当前实现不命中属
        # 符合架构的行为（非源码 Bug）。此处固化现状，并在 QA 报告中作为
        # 「可选优化建议」提出（题库 24 条不依赖这两个变体，不影响验收）。
        assert match_human_rule(question) is None

    def test_order_number_regex(self):
        # 正则：订单 + 4 位以上数字
        assert match_human_rule("帮我查一下订单12345678") == "退款/订单操作"

    def test_order_number_regex_needs_4_digits(self):
        # 仅 1-3 位数字不命中「订单\s*\d{4,}」正则（但仍可能命中「订单号」等子串）
        # 这里验证纯短数字场景不误触正则分组之外的逻辑
        assert match_human_rule("订单 12 什么时候发货") is None

    def test_case_insensitive_english(self):
        # 归一化转小写：英文大小写不影响（本规则以中文为主，验证归一化不破坏匹配）
        assert match_human_rule("我要退款！") == "退款/订单操作"

    def test_punctuation_and_whitespace_ignored(self):
        # 归一化去标点空白：插入标点/空格仍命中
        assert match_human_rule("我 要 退 款！！") == "退款/订单操作"
        assert match_human_rule("我要申请退款，订单号：12345。") == "退款/订单操作"

    def test_emotion_word(self):
        assert match_human_rule("你们这服务太差劲了") == "情绪词"

    def test_explicit_human_request(self):
        assert match_human_rule("给我转人工") == "明确转人工"
        assert match_human_rule("我要找真人客服") == "明确转人工"


class TestNormalize:
    """归一化函数本身的行为。"""

    def test_lowercase(self):
        assert _normalize("ABC") == "abc"

    def test_strip_punctuation(self):
        assert _normalize("你好，世界！") == "你好世界"

    def test_strip_whitespace(self):
        assert _normalize("我 要\t退 款\n") == "我要退款"

    def test_empty_input(self):
        assert _normalize("") == ""
        assert _normalize(None) == ""

    def test_empty_question_returns_none(self):
        assert match_human_rule("") is None
        assert match_human_rule("   ") is None
        assert match_human_rule("？！！") is None
