"""优先级排序——按类型优先级排序，并随查询意图调整。"""

from __future__ import annotations

from typing import Any

from packages.domain.config import settings

# 默认类型优先级：约束/决策类对 Agent 行为影响最大，排在事实/参考类之前
DEFAULT_PRIORITY = [
    "constraint",
    "decision",
    "rule",
    "lesson",
    "fact",
    "convention",
    "pattern",
    "procedure",
    "feedback",
    "reference",
]

_INTENT_PRIORITY_OVERRIDES: dict[str, list[str]] = {
    "constraint": [
        "constraint",
        "rule",
        "decision",
        "lesson",
        "fact",
        "convention",
        "pattern",
        "procedure",
        "feedback",
        "reference",
    ],
    "project_rule": [
        "rule",
        "constraint",
        "decision",
        "lesson",
        "fact",
        "convention",
        "pattern",
        "procedure",
        "feedback",
        "reference",
    ],
    "decision": [
        "decision",
        "constraint",
        "rule",
        "lesson",
        "fact",
        "convention",
        "pattern",
        "procedure",
        "feedback",
        "reference",
    ],
    "lesson": [
        "lesson",
        "constraint",
        "rule",
        "decision",
        "fact",
        "convention",
        "pattern",
        "procedure",
        "feedback",
        "reference",
    ],
    "procedure": [
        "procedure",
        "rule",
        "lesson",
        "constraint",
        "fact",
        "decision",
        "convention",
        "pattern",
        "feedback",
        "reference",
    ],
    "fact": [
        "fact",
        "decision",
        "rule",
        "lesson",
        "constraint",
        "convention",
        "pattern",
        "procedure",
        "feedback",
        "reference",
    ],
}


def get_priority_order(intent: str = "unknown") -> list[str]:
    """获取记忆类型的优先级顺序（按查询意图调整）。"""
    return _INTENT_PRIORITY_OVERRIDES.get(intent, DEFAULT_PRIORITY)


def rank_by_priority(
    memories: list[dict[str, Any]],
    intent: str = "unknown",
) -> list[dict[str, Any]]:
    """按类型优先级（随意图调整）排序，同优先级内按 score + w×utility 降序。

    Args:
        memories: 含 'type' 与 'score' 键的记忆字典列表，可选 'utility_score'。
        intent: 查询分析器给出的意图。

    Returns:
        排序后的列表（优先级最高在前）。
    """
    order = get_priority_order(intent)
    priority_map = {t: i for i, t in enumerate(order)}
    # 效用分参与同优先级内部排序：让「检索到且实际有用」的记忆更靠前。
    # utility 键缺省按 0 计，此时退化为纯 score 排序，与历史行为完全一致
    utility_weight = settings.utility_weight

    return sorted(
        memories,
        key=lambda m: (
            priority_map.get(m.get("type", "fact"), 99),
            -(m.get("score", 0) + utility_weight * m.get("utility_score", 0)),
        ),
    )
