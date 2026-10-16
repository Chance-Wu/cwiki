"""记忆健康度计算（PRD 第 39 节）。

健康状态：healthy、needs_review、suspicious、conflicted

设计：
- 基础分从 1.0 起步，被负向信号扣减。
- 每个信号按重要性加权，贡献一个 [0, 1] 区间内的惩罚。
- 惩罚按加权平均（而非累加）合并，新增信号不会因过度扣减把分数打到 0 以下。
- ``is_permanent`` 记忆有保底分（此类记忆是人工精选的）。
- 仅当某信号实际拉低了分数时才输出对应 reason。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from packages.domain.time_utils import days_since
from packages.memory.mastery import is_mastery_coupled_decay_enabled


@dataclass
class MemoryHealth:
    status: str
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


# 各信号权重——总和无需为 1.0，内部会归一化。
_W_FEEDBACK = 3.0  # 人工投票信号，但需考虑样本量
_W_UTILITY = 3.0  # 效用分本身已综合了检索 + 新鲜度
_W_STALENESS = 2.5  # 使用的新旧程度
_W_CONFIDENCE = 2.0  # 创建/复习时的自评置信度
_W_IMPORTANCE = 1.5  # 重要度只是弱正向信号

# 永久记忆经人工整理，分数不得低于该下限。
_PERMANENT_FLOOR = 0.6


def compute_health(
    memory_status: str,
    utility_score: float,
    conflict_count: int,
    feedback_useful: int,
    feedback_not_useful: int,
    last_used_at: datetime | None,
    created_at: datetime | None,
    usage_count: int,
    *,
    confidence: float = 0.5,
    importance: float = 0.5,
    is_permanent: bool = False,
    ease_factor: float = 2.5,
) -> MemoryHealth:
    # ---- 硬性拦截：存在未解决冲突 ----------------------------------------
    if memory_status == "conflicted" or conflict_count > 0:
        # 冲突越多扣得越重，下限 0.05
        score = 0.2 if conflict_count <= 1 else max(0.2 - 0.05 * (conflict_count - 1), 0.05)
        return MemoryHealth(
            status="conflicted",
            score=score,
            reasons=[f"{conflict_count} unresolved conflict(s)"],
        )

    reasons: list[str] = []

    # ---- 信号 1：人工反馈 ---------------------------------------------------
    # 置信度感知：只有 1 票的样本几乎无信息量
    feedback_penalty, _fb_reason = _feedback_penalty(feedback_useful, feedback_not_useful)

    # ---- 信号 2：效用分 ----------------------------------------------------
    # utility ∈ [0, 1]；惩罚是到健康基线（0.5）的距离
    utility_baseline = 0.5
    utility_penalty = max(0.0, utility_baseline - utility_score) / utility_baseline
    if utility_penalty > 0.3:
        reasons.append(f"Low utility score: {utility_score:.2f}")

    # ---- 信号 3：陈旧度 ----------------------------------------------------
    staleness_penalty, stale_reason = _staleness_penalty(
        last_used_at, created_at, usage_count, ease_factor=ease_factor
    )
    if stale_reason:
        reasons.append(stale_reason)

    # ---- 信号 4：创建/复习时的置信度 ---------------------------------------
    # 高置信度加分，低置信度扣分
    # 范围：-0.5（低）到 +0.5（高）
    confidence_signal = (confidence - 0.5) * 2.0  # 映射到 -1 到 +1，以 0.5 为中心
    confidence_penalty = max(0.0, -confidence_signal)  # 仅在为负时惩罚
    confidence_bonus = max(0.0, confidence_signal)  # 仅在为正时奖励
    if confidence < 0.3:
        reasons.append(f"Low confidence: {confidence:.2f}")
    elif confidence > 0.85:
        reasons.append(f"High confidence: {confidence:.2f}")

    # ---- 信号 5：重要度（高重要度有保护作用） ------------------------------
    # 高重要度加分，低重要度扣分
    # 范围：-0.5（低）到 +0.5（高）
    importance_signal = (importance - 0.5) * 2.0  # 映射到 -1 到 +1，以 0.5 为中心
    importance_penalty = max(0.0, -importance_signal)  # 仅在为负时惩罚
    importance_bonus = max(0.0, importance_signal)  # 仅在为正时奖励

    # ---- 加权平均合并 -------------------------------------------------------
    penalties = [
        (_W_FEEDBACK, feedback_penalty),
        (_W_UTILITY, utility_penalty),
        (_W_STALENESS, staleness_penalty),
        (_W_CONFIDENCE, confidence_penalty),
        (_W_IMPORTANCE, importance_penalty),
    ]
    bonuses = [
        (_W_CONFIDENCE, confidence_bonus),
        (_W_IMPORTANCE, importance_bonus),
    ]

    total_weight = sum(w for w, _ in penalties) or 1.0
    weighted_penalty = sum(w * p for w, p in penalties) / total_weight
    weighted_bonus = sum(w * b for w, b in bonuses) / total_weight

    # 净效果：惩罚减奖励，截断到 [0, 1]
    net_penalty = max(0.0, weighted_penalty - weighted_bonus)
    score = max(1.0 - net_penalty, 0.0)

    if is_permanent and score < _PERMANENT_FLOOR:
        score = _PERMANENT_FLOOR
        reasons.append("Pinned: permanent memory floor applied")

    # ---- 按分数分档 ---------------------------------------------------------
    if score >= 0.7:
        status = "healthy"
    elif score >= 0.4:
        status = "needs_review"
    else:
        status = "suspicious"

    return MemoryHealth(status=status, score=score, reasons=reasons)


def _feedback_penalty(useful: int, not_useful: int) -> tuple[float, str | None]:
    """带样本量折扣的贝叶斯平滑「无用」占比。

    零投票时先验为 50/50，但会被大幅折扣——把「没有反馈」当作中性，
    而非可疑。
    """
    total = useful + not_useful
    if total == 0:
        return 0.0, None

    # 拉普拉斯平滑，弱先验（有用 1 票、无用 1 票）
    smoothed_not_useful = (not_useful + 1) / (total + 2)

    # 样本量置信度：1 票 → 0.2 权重，10 票以上 → 约 0.9
    confidence = 1 - 1 / (1 + total / 5)

    # 「无用」占比超过 40% 才启动惩罚，并按置信度缩放
    excess = max(0.0, smoothed_not_useful - 0.4) / 0.6  # 40% 时为 0，100% 时为 1
    penalty = excess * confidence
    if penalty > 0.2:
        return penalty, f"Majority feedback: not useful ({not_useful}/{total})"
    return penalty, None


def _staleness_penalty(
    last_used_at: datetime | None,
    created_at: datetime | None,
    usage_count: int,
    *,
    ease_factor: float = 2.5,
) -> tuple[float, str | None]:
    """连续衰减：最近使用为 0，一年未用趋近 1。

    ease_factor（来自 SM-2）调节半衰期：EF 越高衰减越慢。
    已掌握（EF=3.0）→ 半衰期约 173 天；新知识（EF=1.3）→ 约 56 天。
    """
    if last_used_at:
        days = days_since(last_used_at)
        if days <= 0:
            return 0.0, None
        # 掌握度耦合衰减：半衰期随 EF 对数增长（下限 30 天）；未启用时固定 90 天
        if is_mastery_coupled_decay_enabled():
            half_life = max(30, int(90 * (1 + math.log(max(ease_factor, 1.3)))))
        else:
            half_life = 90
        penalty = 1 - 2 ** (-days / half_life)
        if penalty > 0.3:
            return penalty, f"Not used for {int(days)} days"
        return penalty, None

    if created_at and usage_count == 0:
        days = days_since(created_at)
        if days <= 30:
            return 0.0, None  # 新记忆的宽限期
        # 宽限期过后，「从未使用」惩罚在 180 天内线性爬升到 1
        penalty = min(1.0, (days - 30) / 180)
        if penalty > 0.05:
            return penalty, f"Never used in {int(days)} days"
        return penalty, None

    return 0.0, None
