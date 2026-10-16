"""记忆效用分计算（PRD 第 31 节）。

utility = 0.30 * retrieval_success
        + 0.25 * agent_usage
        + 0.20 * human_feedback
        + 0.15 * freshness
        + 0.10 * evidence_strength
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from packages.domain.time_utils import days_since
from packages.memory.mastery import is_mastery_coupled_decay_enabled


@dataclass
class UtilityScore:
    retrieval_success: float
    agent_usage: float
    human_feedback: float
    freshness: float
    evidence_strength: float
    utility: float

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


def compute_utility_score(
    retrieval_count: int,
    used_count: int,
    cited_count: int,
    useful_votes: int,
    not_useful_votes: int,
    last_used_at: datetime | None,
    evidence_count: int,
    *,
    ease_factor: float = 2.5,
) -> UtilityScore:
    # 比率统一用 max(…, 1) 防除零、min(…, 1.0) 封顶，保证各分量都落在 [0, 1]
    retrieval_success = min(used_count / max(retrieval_count, 1), 1.0)

    agent_usage = min(cited_count / max(retrieval_count, 1), 1.0)

    total_votes = useful_votes + not_useful_votes
    # 无投票时取中性先验 0.5，不因缺少反馈而惩罚
    human_feedback = useful_votes / total_votes if total_votes > 0 else 0.5

    freshness = _compute_freshness(last_used_at, ease_factor=ease_factor)

    # 5 条证据即满分，更多证据边际收益为 0
    evidence_strength = min(evidence_count / 5.0, 1.0)

    utility = (
        0.30 * retrieval_success
        + 0.25 * agent_usage
        + 0.20 * human_feedback
        + 0.15 * freshness
        + 0.10 * evidence_strength
    )

    return UtilityScore(
        retrieval_success=retrieval_success,
        agent_usage=agent_usage,
        human_feedback=human_feedback,
        freshness=freshness,
        evidence_strength=evidence_strength,
        utility=utility,
    )


def _compute_freshness(last_used_at: datetime | None, *, ease_factor: float = 2.5) -> float:
    # 从未使用：给 0.3 的非零底分（低于「最近用过」，高于「长期弃用」）
    if not last_used_at:
        return 0.3

    days = days_since(last_used_at)
    days = max(days, 0)
    # 掌握度耦合：按 ease_factor 对数放大时间尺度（EF 下限 1.3，保证 scale ≥ 1，
    # 新知识不会比固定档位衰减更快）
    if is_mastery_coupled_decay_enabled():
        scale = 1 + math.log(max(ease_factor, 1.3))
    else:
        scale = 1.0
    # 分档衰减：1 天内满分，之后按 7/30/90 天阶梯下降
    if days < 1 * scale:
        return 1.0
    if days < 7 * scale:
        return 0.9
    if days < 30 * scale:
        return 0.7
    if days < 90 * scale:
        return 0.5
    return 0.2
