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
    """相关性主导排序，类型优先级与效用只在带内微调。

    排序键为 ``score + band × ((1-utility_weight)×类型优先级 + utility_weight×utility)``：
    低相关但类型「更重要」的记忆不能跨带压过高相关记忆；类型与效用
    只用于翻转相关性差 ≤band 的候选，避免检索结果被类型标签整体重排。

    Args:
        memories: 含 'type' 与 'score' 键的记忆字典列表，可选 'utility_score'。
        intent: 查询分析器给出的意图。

    Returns:
        排序后的列表（相关性最高在前）。
    """
    order = get_priority_order(intent)
    priority_map = {t: i for i, t in enumerate(order)}
    band = min(max(settings.reranker_relevance_band, 0.0), 1.0)
    utility_weight = min(max(settings.utility_weight, 0.0), 1.0)
    last_index = max(0, len(order) - 1)

    def sort_key(mem: dict[str, Any]) -> float:
        type_index = min(priority_map.get(mem.get("type", "fact"), last_index), last_index)
        prio_norm = 1.0 - (type_index / last_index) if last_index else 1.0
        utility = min(max(float(mem.get("utility_score", 0.0) or 0.0), 0.0), 1.0)
        meta = (1.0 - utility_weight) * prio_norm + utility_weight * utility
        score = float(mem.get("score", 0.0) or 0.0)
        return -(score + band * meta)

    return sorted(memories, key=sort_key)
