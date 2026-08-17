# -*- coding: utf-8 -*-
"""强制转人工规则前置拦截（R3）。

纯函数模块，无外部依赖（不连数据库/LLM/网络），可独立单元测试。
规则命中即由调用方短路返回 action=human，完全不进检索/分诊/生成链路，
从机制上保证「规则命中即 100% 转人工」。
"""

import re
import string
from typing import Optional

from app.core.constants import HUMAN_RULE_GROUPS

# 归一化时剔除的字符表：英文标点 + 常见中英文标点 + 全部空白字符
_PUNCT_TABLE = str.maketrans("", "", string.punctuation + "，。！？、；：（）【】《》“”‘’—…·　")


def _normalize(text: str) -> str:
    """归一化用户问题：转小写 + 去除标点与空白，便于稳定的子串匹配。"""
    if not text:
        return ""
    normalized = text.lower().translate(_PUNCT_TABLE)
    # 去除所有剩余空白字符（空格、制表符、换行等）
    return re.sub(r"\s+", "", normalized)


def _match_one(normalized_question: str, keyword: str) -> bool:
    """判断单条规则是否命中。

    以 ``re:`` 开头的条目按正则表达式匹配（对归一化后的问题串匹配）；
    其余按归一化后的子串包含匹配。
    """
    if keyword.startswith("re:"):
        pattern = keyword[3:]
        try:
            return re.search(pattern, normalized_question) is not None
        except re.error:
            # 非法正则不阻断流程，视为不命中
            return False
    return _normalize(keyword) in normalized_question


def match_human_rule(question: str) -> Optional[str]:
    """匹配强制转人工规则。

    Args:
        question: 用户原始问题文本。

    Returns:
        命中时返回规则分组名（如 "退款/订单操作"），未命中返回 None。
    """
    normalized = _normalize(question)
    if not normalized:
        return None

    for group_name, keywords in HUMAN_RULE_GROUPS.items():
        for keyword in keywords:
            if _match_one(normalized, keyword):
                return group_name
    return None
