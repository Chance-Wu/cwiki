"""间隔重复复习服务。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, ReviewHistory, ReviewSchedule
from packages.memory.spaced_repetition import (
    calculate_mastery_level,
    get_initial_schedule,
    sm2_algorithm,
)

logger = logging.getLogger(__name__)

# 掌握度升级阈值（进入下一等级所需的复习次数）
_MASTERY_THRESHOLDS = {
    "new": 1,  # 复习 1 次后 → learning
    "learning": 3,  # 复习 3 次后 → familiar
    "familiar": 6,  # 复习 6 次后 → proficient
    "proficient": 11,  # 复习 11 次后 → mastered（还需 EF≥2.5）
    "mastered": 11,  # 已是最高级
}


def _calculate_priority(
    days_overdue: int,
    interval_days: int,
    repetitions: int,
    ease_factor: float,
) -> float:
    """
    计算复习优先级得分（越高越紧急）。

    三路信号加权：
    1. 紧急度：逾期比例（主信号，权重 10）
    2. 掌握进度：距下一等级升级的接近程度（权重 3）
    3. 难度：ease_factor 越低优先级略高（权重 1）
    """
    # 紧急度：逾期天数与间隔之比（+1 保证当天到期也有非零优先级）
    urgency = (days_overdue + 1) / max(interval_days, 1)

    # 掌握进度：距下一升级阈值的比例
    mastery = calculate_mastery_level(repetitions, ease_factor)
    threshold = _MASTERY_THRESHOLDS.get(mastery, 11)
    progress = min(repetitions / max(threshold, 1), 1.0)

    # 难度：EF∈[1.3, 3.0]，归一化到约 [0, 0.85]
    difficulty = (3.0 - ease_factor) / 2.0

    return urgency * 10.0 + progress * 3.0 + difficulty * 1.0


class ReviewService:
    """管理间隔重复复习的服务。"""

    async def get_due_reviews(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取到期待复习的记忆。

        返回带复习计划信息的记忆列表。
        """
        # 用 naive UTC 对齐 SQLite 存储（存库时已去除 tzinfo）
        now = datetime.now(UTC).replace(tzinfo=None)

        # 多取一批到期项（最多 5 倍 limit），供优先级排序后截断
        fetch_limit = max(limit * 5, 100)
        stmt = (
            select(ReviewSchedule, Memory)
            .join(Memory, ReviewSchedule.memory_id == Memory.id)
            .where(
                ReviewSchedule.workspace_id == workspace_id,
                ReviewSchedule.next_review <= now,
                Memory.status == "active",
            )
            .limit(fetch_limit)
        )

        result = await db.execute(stmt)
        rows = result.all()

        due_items = []
        for schedule, memory in rows:
            days_overdue = (now - schedule.next_review).days
            mastery = calculate_mastery_level(schedule.repetitions, schedule.ease_factor)

            due_items.append(
                {
                    "memory_id": str(memory.id),
                    "title": memory.title,
                    "content": memory.content,
                    "memory_type": memory.type,
                    "ease_factor": schedule.ease_factor,
                    "interval_days": schedule.interval_days,
                    "repetitions": schedule.repetitions,
                    "next_review": schedule.next_review.isoformat(),
                    "last_review": schedule.last_review.isoformat()
                    if schedule.last_review
                    else None,
                    "days_overdue": days_overdue,
                    "mastery_level": mastery,
                    "total_reviews": schedule.total_reviews,
                }
            )

        # 按多信号优先级排序（紧急度 + 掌握进度 + 难度）
        def _sort_key(item: dict[str, Any]) -> float:
            return _calculate_priority(
                item["days_overdue"],
                item["interval_days"],
                item["repetitions"],
                item["ease_factor"],
            )

        due_items.sort(key=_sort_key, reverse=True)

        return due_items[:limit]

    async def submit_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        quality: int,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """
        提交某条记忆的复习结果。

        Args:
            memory_id: 被复习的记忆
            quality: 质量评分（0-5）
            workspace_id: 可选 workspace，用于隔离校验

        Returns:
            更新后的计划信息
        """
        if not 0 <= quality <= 5:
            raise ValueError("Quality must be between 0 and 5")

        # 读取已有复习计划
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory_id)
        if workspace_id is not None:
            stmt = stmt.where(ReviewSchedule.workspace_id == workspace_id)
        result = await db.execute(stmt)
        schedule = result.scalar_one_or_none()

        # 用 naive UTC 对齐 SQLite 存储（存库时已去除 tzinfo）
        now = datetime.now(UTC).replace(tzinfo=None)

        # 写入端单调性保证：Windows 时钟粒度约 1ms，同粒度内的连续提交会产生相同的
        # reviewed_at，undo_review 按 (reviewed_at, id) 降序取最近一条时会因 id 为随机
        # UUID 而随机选中错误记录。若新时间戳不大于该记忆已有的最大 reviewed_at，则 +1μs。
        max_result = await db.execute(
            select(func.max(ReviewHistory.reviewed_at)).where(ReviewHistory.memory_id == memory_id)
        )
        max_reviewed_at = max_result.scalar()
        if max_reviewed_at is not None and now <= max_reviewed_at:
            now = max_reviewed_at + timedelta(microseconds=1)

        if schedule is None:
            # 该记忆尚无计划：新建
            memory_stmt = select(Memory).where(Memory.id == memory_id)
            if workspace_id is not None:
                memory_stmt = memory_stmt.where(Memory.workspace_id == workspace_id)
            mem_result = await db.execute(memory_stmt)
            memory = mem_result.scalar_one_or_none()

            if memory is None:
                raise ValueError(f"Memory {memory_id} not found")

            initial = get_initial_schedule(now)

            # 记录复习前状态，供历史与撤销使用
            before_ef = initial.ease_factor
            before_interval = initial.interval_days
            before_reps = initial.repetitions
            before_next = initial.next_review
            before_mastery = calculate_mastery_level(before_reps, before_ef)

            review_result = sm2_algorithm(
                ease_factor=initial.ease_factor,
                interval_days=initial.interval_days,
                repetitions=initial.repetitions,
                quality=quality,
                review_time=now,
            )

            schedule = ReviewSchedule(
                id=uuid.uuid4(),
                workspace_id=memory.workspace_id,
                memory_id=memory_id,
                ease_factor=review_result.ease_factor,
                interval_days=review_result.interval_days,
                repetitions=review_result.repetitions,
                next_review=review_result.next_review,
                last_review=now,
                total_reviews=1,
            )
            db.add(schedule)

            # 写入新计划的历史记录
            after_mastery = calculate_mastery_level(
                review_result.repetitions, review_result.ease_factor
            )
            history = ReviewHistory(
                id=uuid.uuid4(),
                workspace_id=memory.workspace_id,
                memory_id=memory_id,
                quality=quality,
                ease_factor_before=before_ef,
                interval_before=before_interval,
                repetitions_before=before_reps,
                next_review_before=before_next,
                mastery_level_before=before_mastery,
                ease_factor_after=review_result.ease_factor,
                interval_after=review_result.interval_days,
                repetitions_after=review_result.repetitions,
                next_review_after=review_result.next_review,
                mastery_level_after=after_mastery,
                reviewed_at=now,
            )
            db.add(history)
        else:
            # 记录复习前状态，供历史与撤销使用
            before_ef = schedule.ease_factor
            before_interval = schedule.interval_days
            before_reps = schedule.repetitions
            before_next = schedule.next_review
            before_mastery = calculate_mastery_level(before_reps, before_ef)

            # 应用 SM-2 算法更新计划
            review_result = sm2_algorithm(
                ease_factor=schedule.ease_factor,
                interval_days=schedule.interval_days,
                repetitions=schedule.repetitions,
                quality=quality,
                review_time=now,
            )

            schedule.ease_factor = review_result.ease_factor
            schedule.interval_days = review_result.interval_days
            schedule.repetitions = review_result.repetitions
            schedule.next_review = review_result.next_review
            schedule.last_review = now
            schedule.total_reviews += 1

            # 写入既有计划的历史记录
            after_mastery = calculate_mastery_level(
                review_result.repetitions, review_result.ease_factor
            )
            history = ReviewHistory(
                id=uuid.uuid4(),
                workspace_id=schedule.workspace_id,
                memory_id=memory_id,
                quality=quality,
                ease_factor_before=before_ef,
                interval_before=before_interval,
                repetitions_before=before_reps,
                next_review_before=before_next,
                mastery_level_before=before_mastery,
                ease_factor_after=review_result.ease_factor,
                interval_after=review_result.interval_days,
                repetitions_after=review_result.repetitions,
                next_review_after=review_result.next_review,
                mastery_level_after=after_mastery,
                reviewed_at=now,
            )
            db.add(history)

        await db.flush()

        mastery = calculate_mastery_level(schedule.repetitions, schedule.ease_factor)

        return {
            "memory_id": str(memory_id),
            "ease_factor": schedule.ease_factor,
            "interval_days": schedule.interval_days,
            "repetitions": schedule.repetitions,
            "next_review": schedule.next_review.isoformat(),
            "last_review": now.isoformat(),
            "mastery_level": mastery,
            "total_reviews": schedule.total_reviews,
        }

    async def get_review_stats(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        """获取 workspace 的复习统计。"""
        # 用 naive UTC 对齐 SQLite 存储（存库时已去除 tzinfo）
        now = datetime.now(UTC).replace(tzinfo=None)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_end = now + timedelta(days=1)

        # 用 1 次条件聚合替代 4 次 COUNT 查询，减少数据库往返
        stats_stmt = select(
            func.count(ReviewSchedule.id),
            func.count(case((ReviewSchedule.next_review <= now, ReviewSchedule.id))),
            func.count(
                case(
                    (
                        (ReviewSchedule.next_review >= today_start)
                        & (ReviewSchedule.next_review <= tomorrow_end),
                        ReviewSchedule.id,
                    )
                )
            ),
            func.count(case((ReviewSchedule.last_review >= today_start, ReviewSchedule.id))),
        ).where(ReviewSchedule.workspace_id == workspace_id)
        stats_result = await db.execute(stats_stmt)
        row = stats_result.first()
        total_scheduled, due_count, due_today, reviewed_today = (
            (row[0], row[1], row[2], row[3]) if row else (0, 0, 0, 0)
        )

        # 掌握度分布：SQL CASE WHEN + GROUP BY，口径与 calculate_mastery_level 一致
        mastery_stmt = (
            select(
                case(
                    (ReviewSchedule.repetitions == 0, "new"),
                    (ReviewSchedule.repetitions <= 2, "learning"),
                    (ReviewSchedule.repetitions <= 5, "familiar"),
                    (ReviewSchedule.repetitions <= 10, "proficient"),
                    (ReviewSchedule.ease_factor >= 2.5, "mastered"),
                    else_="proficient",
                ).label("level"),
                func.count(ReviewSchedule.id).label("cnt"),
            )
            .where(ReviewSchedule.workspace_id == workspace_id)
            .group_by("level")
        )
        mastery_result = await db.execute(mastery_stmt)
        mastery_dist = {
            "new": 0,
            "learning": 0,
            "familiar": 0,
            "proficient": 0,
            "mastered": 0,
        }
        for row in mastery_result.all():
            mastery_dist[row.level] = row.cnt

        # 复习趋势：最近 7 天
        seven_days_ago = now - timedelta(days=6)
        seven_days_ago_start = seven_days_ago.replace(hour=0, minute=0, second=0, microsecond=0)
        trend_stmt = (
            select(
                func.date(ReviewSchedule.last_review).label("day"),
                func.count(ReviewSchedule.id).label("cnt"),
            )
            .where(
                ReviewSchedule.workspace_id == workspace_id,
                ReviewSchedule.last_review >= seven_days_ago_start,
            )
            .group_by(func.date(ReviewSchedule.last_review))
        )
        trend_result = await db.execute(trend_stmt)
        trend_map = {str(row.day): row.cnt for row in trend_result.all()}

        review_trend = []
        for i in range(7):
            day = (seven_days_ago_start + timedelta(days=i)).strftime("%Y-%m-%d")
            review_trend.append({"date": day, "count": trend_map.get(day, 0)})

        return {
            "total_scheduled": total_scheduled,
            "due_now": due_count,
            "due_today": due_today,
            "reviewed_today": reviewed_today,
            "mastery_distribution": mastery_dist,
            "review_trend": review_trend,
        }

    async def schedule_memory(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """
        为新批准的记忆创建初始复习计划。

        已有计划时返回 None。
        """
        stmt = select(ReviewSchedule).where(
            ReviewSchedule.memory_id == memory_id,
            ReviewSchedule.workspace_id == workspace_id,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            return None

        initial = get_initial_schedule()

        schedule = ReviewSchedule(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            memory_id=memory_id,
            ease_factor=initial.ease_factor,
            interval_days=initial.interval_days,
            repetitions=initial.repetitions,
            next_review=initial.next_review,
            total_reviews=0,
        )
        db.add(schedule)
        await db.flush()

        return {
            "memory_id": str(memory_id),
            "next_review": initial.next_review.isoformat(),
            "status": "scheduled",
        }

    async def undo_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """
        撤销某条记忆的最近一次复习。

        将计划恢复到上次复习前的状态，并删除对应历史记录。

        Returns:
            撤销结果信息；无历史可撤销时返回 None
        """
        # 找到该记忆最近一条历史记录（按 (reviewed_at, id) 降序）
        stmt = (
            select(ReviewHistory)
            .where(ReviewHistory.memory_id == memory_id)
            .order_by(ReviewHistory.reviewed_at.desc(), ReviewHistory.id.desc())
            .limit(1)
        )
        if workspace_id is not None:
            stmt = stmt.where(ReviewHistory.workspace_id == workspace_id)

        result = await db.execute(stmt)
        history = result.scalar_one_or_none()

        if history is None:
            return None

        schedule_stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory_id)
        if workspace_id is not None:
            schedule_stmt = schedule_stmt.where(ReviewSchedule.workspace_id == workspace_id)

        schedule_result = await db.execute(schedule_stmt)
        schedule = schedule_result.scalar_one_or_none()

        if schedule is None:
            return None

        # 恢复计划到复习前状态
        schedule.ease_factor = history.ease_factor_before
        schedule.interval_days = history.interval_before
        schedule.repetitions = history.repetitions_before
        schedule.next_review = history.next_review_before

        # 依据是否还有更早历史，回推 last_review 与 total_reviews
        earlier_stmt = (
            select(ReviewHistory)
            .where(
                ReviewHistory.memory_id == memory_id,
                ReviewHistory.id != history.id,
            )
            .order_by(ReviewHistory.reviewed_at.desc(), ReviewHistory.id.desc())
            .limit(1)
        )
        if workspace_id is not None:
            earlier_stmt = earlier_stmt.where(ReviewHistory.workspace_id == workspace_id)
        earlier_result = await db.execute(earlier_stmt)
        earlier = earlier_result.scalar_one_or_none()

        if earlier is not None:
            schedule.last_review = earlier.reviewed_at
            schedule.total_reviews = max(0, schedule.total_reviews - 1)
        else:
            schedule.last_review = None
            schedule.total_reviews = 0

        await db.delete(history)
        await db.flush()

        return {
            "memory_id": str(memory_id),
            "undone_quality": history.quality,
            "undone_reviewed_at": history.reviewed_at.isoformat(),
            "restored_mastery_level": history.mastery_level_before,
        }


_review_service: ReviewService | None = None


def get_review_service() -> ReviewService:
    """获取 ReviewService 单例。"""
    global _review_service
    if _review_service is None:
        _review_service = ReviewService()
    return _review_service
