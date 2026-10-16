"""支持 CJK 感知的 token 估算器。"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED_BUDGETS = [500, 1000, 2000, 4000, 8000]
DEFAULT_BUDGET = 2000

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """按 CJK 感知估算 token 数。

    经验比例：英文约 4 字符/token，中文约 1.5 字符/token——
    中文信息密度高，BPE 分词下几乎每字独占 token，比例远小于英文。
    """
    if not text:
        return 0
    cjk_chars = len(_CJK_RE.findall(text))
    other_chars = len(text) - cjk_chars
    return int(other_chars / 4 + cjk_chars / 1.5)


def normalize_budget(budget: int | None) -> int:
    """将 token 预算归一到最近的受支持档位。

    请求值不在支持列表时，返回不超过它的最大档位；
    小于最小档位时返回 500。
    """
    if budget is None:
        return DEFAULT_BUDGET
    for supported in sorted(SUPPORTED_BUDGETS):
        if budget <= supported:
            return supported
    return SUPPORTED_BUDGETS[-1]


def within_budget(memories: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    """过滤出预算内的记忆子集。

    假定已按优先级排序。顺序累加，一旦某条会超出预算即停止选择，
    保证高优先级记忆优先入选。

    Args:
        memories: 按优先级排序的记忆字典列表。
        budget: token 上限。

    Returns:
        预算内的记忆子集。
    """
    if budget <= 0:
        return []
    result: list[dict[str, Any]] = []
    total = 0
    for mem in memories:
        tokens = estimate_tokens(mem.get("content", ""))
        if total + tokens > budget:
            break
        result.append(mem)
        total += tokens
    return result
