"""记忆生命周期状态转换校验（Epic 4）。

定义合法状态转换表，禁止未经验证的状态字符串直接写入。
"""

from __future__ import annotations


class InvalidStatusTransition(Exception):
    """非法状态转换。"""

    def __init__(self, current: str, target: str, allowed: list[str]):
        self.current = current
        self.target = target
        self.allowed = allowed
        super().__init__(
            f"非法状态转换: {current!r} → {target!r}，"
            f"允许的目标状态: {allowed}"
        )


# 正式记忆合法状态转换表
# active: 可更新、归档、取代、标记冲突/废弃
# superseded: 可恢复为 active（需显式撤销取代）
# conflicted: 冲突解决后可恢复 active 或归档
# archived: 可恢复为 active
# deprecated: 可归档
MEMORY_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "active": ["superseded", "conflicted", "archived", "deprecated"],
    "superseded": ["active", "archived"],
    "conflicted": ["active", "superseded", "archived"],
    "archived": ["active"],
    "deprecated": ["archived"],
}

# 候选记忆合法状态转换表
CANDIDATE_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "pending_review": ["approved", "rejected", "merged", "deferred", "needs_enrichment"],
    "needs_enrichment": ["pending_review", "rejected"],
    "deferred": ["pending_review", "rejected"],
    "approved": [],  # 终态
    "rejected": ["pending_review"],  # 允许重新审核
    "merged": [],  # 终态
    "quarantined": ["pending_review", "rejected"],  # 历史兼容
    "discarded": ["pending_review"],  # 历史兼容
}


def validate_memory_status_transition(current: str, target: str) -> None:
    """校验正式记忆状态转换是否合法。

    Raises:
        InvalidStatusTransition: 转换不在合法表中。
    """
    allowed = MEMORY_STATUS_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidStatusTransition(current, target, allowed)


def validate_candidate_status_transition(current: str, target: str) -> None:
    """校验候选记忆状态转换是否合法。

    Raises:
        InvalidStatusTransition: 转换不在合法表中。
    """
    allowed = CANDIDATE_STATUS_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidStatusTransition(current, target, allowed)


def get_allowed_memory_transitions(current: str) -> list[str]:
    """获取正式记忆当前状态允许的目标状态列表。"""
    return MEMORY_STATUS_TRANSITIONS.get(current, [])


def get_allowed_candidate_transitions(current: str) -> list[str]:
    """获取候选记忆当前状态允许的目标状态列表。"""
    return CANDIDATE_STATUS_TRANSITIONS.get(current, [])
