"""SM-2 间隔重复算法实现。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class ReviewResult:
    """一次复习后 SM-2 算法产出的新调度参数。"""

    ease_factor: float
    interval_days: int
    repetitions: int
    next_review: datetime


def sm2_algorithm(
    ease_factor: float,
    interval_days: int,
    repetitions: int,
    quality: int,
    review_time: datetime | None = None,
) -> ReviewResult:
    """
    应用 SM-2 算法计算下一次复习计划。

    Args:
        ease_factor: 当前难度系数 EF，初始为 2.5
        interval_days: 当前复习间隔（天）
        repetitions: 连续成功复习的次数
        quality: 本次复习质量（0-5）：
            5 - 完美回忆
            4 - 犹豫后答对
            3 - 艰难答对
            2 - 答错，但看答案后想起了
            1 - 答错，但认识正确答案
            0 - 完全想不起来
        review_time: 复习发生时间（默认当前时间）

    Returns:
        更新后的调度参数 ReviewResult
    """
    if review_time is None:
        review_time = datetime.now(UTC)

    # 将 quality 限制在合法区间 [0, 5]
    quality = max(0, min(5, int(quality)))

    if quality < 3:
        # 复习失败（quality<3）：重置进度，间隔回到 1 天
        new_repetitions = 0
        new_interval = 1
    else:
        # 复习成功
        new_repetitions = repetitions + 1

        # SM-2 标准间隔序列：前两次固定 1、6 天，之后按 EF 指数增长
        if repetitions == 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            new_interval = round(interval_days * ease_factor)

    # 更新难度系数 EF（SM-2 原始公式）
    # EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
    ef_delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    # EF 下限 1.3 为 SM-2 规定值，防止低质量复习把间隔推得无限增长
    new_ease_factor = max(1.3, ease_factor + ef_delta)

    next_review = review_time + timedelta(days=new_interval)

    return ReviewResult(
        ease_factor=round(new_ease_factor, 4),
        interval_days=new_interval,
        repetitions=new_repetitions,
        next_review=next_review,
    )


def get_initial_schedule(first_review_time: datetime | None = None) -> ReviewResult:
    """
    为新记忆生成初始复习计划（默认参数，等待首次复习）。
    """
    if first_review_time is None:
        first_review_time = datetime.now(UTC)

    return ReviewResult(
        ease_factor=2.5,
        interval_days=1,
        repetitions=0,
        next_review=first_review_time,
    )


def calculate_mastery_level(repetitions: int, ease_factor: float) -> str:
    """
    根据复习历史计算掌握度等级。

    等级：
    - new：从未复习
    - learning：1-2 次
    - familiar：3-5 次
    - proficient：6-10 次
    - mastered：10 次以上且 EF 较高（≥2.5）
    """
    if repetitions == 0:
        return "new"
    elif repetitions <= 2:
        return "learning"
    elif repetitions <= 5:
        return "familiar"
    elif repetitions <= 10:
        return "proficient"
    elif ease_factor >= 2.5:
        return "mastered"
    else:
        # 次数够了但 EF 偏低，说明记忆仍不稳定，不授予 mastered
        return "proficient"
