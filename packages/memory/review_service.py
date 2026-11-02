"""间隔重复复习服务。"""

from __future__ import annotations

import json
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


def _quiz_history_fields(quiz: dict[str, Any] | None) -> dict[str, Any]:
    """把判分记录转为 ReviewHistory 列；列表/字典序列化为 JSON 文本。"""
    if not quiz:
        return {}
    expected = quiz.get("expected")
    response = quiz.get("response")
    return {
        "quiz_type": quiz.get("type"),
        "quiz_correct": quiz.get("correct"),
        "quiz_prompt": quiz.get("prompt"),
        "quiz_expected": (
            json.dumps(expected, ensure_ascii=False)
            if isinstance(expected, (list, dict))
            else expected
        ),
        "quiz_response": (
            json.dumps(response, ensure_ascii=False)
            if isinstance(response, (list, dict))
            else response
        ),
    }


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
                ReviewSchedule.suspended_at.is_(None),
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
                    "source": memory.source,
                    "confidence": memory.confidence,
                    "tags": memory.tags or [],
                    "importance": memory.importance,
                    "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
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
                    "lapse_streak": schedule.lapse_streak,
                    "leech": schedule.lapse_streak >= 3,
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
        quiz: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        提交某条记忆的复习结果。

        Args:
            memory_id: 被复习的记忆
            quality: 质量评分（0-5）
            workspace_id: 可选 workspace，用于隔离校验
            quiz: 可选的填空/选择判分记录（type/correct/prompt/expected/response）

        Returns:
            更新后的计划信息
        """
        if not 0 <= quality <= 5:
            raise ValueError("Quality must be between 0 and 5")

        quiz_fields = _quiz_history_fields(quiz)

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
                lapse_streak=1 if quality < 3 else 0,
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
                **quiz_fields,
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
            # 连续遗忘累加，答对即清零；达到 3 次由前端标为顽固记忆
            schedule.lapse_streak = schedule.lapse_streak + 1 if quality < 3 else 0

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
                **quiz_fields,
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
            "lapse_streak": schedule.lapse_streak,
            "leech": schedule.lapse_streak >= 3,
        }

    async def get_review_stats(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        tz_offset_minutes: int = 0,
    ) -> dict[str, Any]:
        """获取 workspace 的复习统计。

        时间口径：数据库存 naive UTC；tz_offset_minutes 为客户端相对 UTC 的分钟偏移
        （东八区 +480），仅用于划分「本地自然日」边界，不改变存储值。

        reviewed_today / review_count_today / review_trend / streak_days 以
        ReviewHistory 为唯一事实源：ReviewSchedule.last_review 每张卡只保留最后一次，
        会把同一天多次复习折叠为一次，也会让昨天的记录被今天的复习覆盖。
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        offset = timedelta(minutes=tz_offset_minutes)

        # 本地自然日边界，换算回 UTC 供查询
        local_now = now + offset
        local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_today_date = local_today_start.date()
        today_start_utc = local_today_start - offset
        tomorrow_start_utc = today_start_utc + timedelta(days=1)

        # 计划侧统计：已排期总量、当前到期、今日到期
        stats_stmt = select(
            func.count(ReviewSchedule.id),
            func.count(
                case(
                    (
                        (ReviewSchedule.next_review <= now)
                        & (ReviewSchedule.suspended_at.is_(None)),
                        ReviewSchedule.id,
                    )
                )
            ),
            func.count(
                case(
                    (
                        (ReviewSchedule.next_review >= today_start_utc)
                        & (ReviewSchedule.next_review < tomorrow_start_utc)
                        & (ReviewSchedule.suspended_at.is_(None)),
                        ReviewSchedule.id,
                    )
                )
            ),
        ).where(ReviewSchedule.workspace_id == workspace_id)
        stats_result = await db.execute(stats_stmt)
        row = stats_result.first()
        total_scheduled, due_count, due_today = (row[0], row[1], row[2]) if row else (0, 0, 0)

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

        # 历史侧：取最近 365 天事件，按本地日分组（单用户数据量小，Python 聚合）
        history_start_utc = today_start_utc - timedelta(days=364)
        history_stmt = select(ReviewHistory.memory_id, ReviewHistory.reviewed_at).where(
            ReviewHistory.workspace_id == workspace_id,
            ReviewHistory.reviewed_at >= history_start_utc,
        )
        history_result = await db.execute(history_stmt)

        day_memory_ids: dict[str, set[uuid.UUID]] = {}
        day_counts: dict[str, int] = {}
        for memory_id, reviewed_at in history_result.all():
            key = (reviewed_at + offset).date().isoformat()
            day_memory_ids.setdefault(key, set()).add(memory_id)
            day_counts[key] = day_counts.get(key, 0) + 1

        today_key = local_today_date.isoformat()
        reviewed_today = len(day_memory_ids.get(today_key, set()))
        review_count_today = day_counts.get(today_key, 0)

        # 连续学习天数：今天还没复习时从昨天起算，避免一天未开始就显示断签
        streak_days = 0
        cursor = local_today_date
        if today_key not in day_memory_ids:
            cursor -= timedelta(days=1)
        while cursor.isoformat() in day_memory_ids:
            streak_days += 1
            cursor -= timedelta(days=1)

        # 复习趋势：最近 7 天，每天的去重记忆数
        review_trend = []
        for i in range(7):
            day = (local_today_date - timedelta(days=6 - i)).isoformat()
            review_trend.append({"date": day, "count": len(day_memory_ids.get(day, set()))})

        # 填空判分准确率：最近 30 天，workspace 内所有判分事件
        quiz_start_utc = today_start_utc - timedelta(days=29)
        quiz_stmt = select(
            func.count(ReviewHistory.id),
            func.count(case((ReviewHistory.quiz_correct.is_(True), ReviewHistory.id))),
        ).where(
            ReviewHistory.workspace_id == workspace_id,
            ReviewHistory.quiz_type.isnot(None),
            ReviewHistory.reviewed_at >= quiz_start_utc,
        )
        quiz_row = (await db.execute(quiz_stmt)).first()
        quiz_attempts = int(quiz_row[0]) if quiz_row else 0
        quiz_correct = int(quiz_row[1]) if quiz_row else 0
        quiz_accuracy = round(quiz_correct / quiz_attempts, 4) if quiz_attempts else None

        return {
            "total_scheduled": total_scheduled,
            "due_now": due_count,
            "due_today": due_today,
            "reviewed_today": reviewed_today,
            "review_count_today": review_count_today,
            "streak_days": streak_days,
            "mastery_distribution": mastery_dist,
            "review_trend": review_trend,
            "quiz_attempts": quiz_attempts,
            "quiz_correct": quiz_correct,
            "quiz_accuracy": quiz_accuracy,
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

    async def _get_schedule(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> ReviewSchedule | None:
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory_id)
        if workspace_id is not None:
            stmt = stmt.where(ReviewSchedule.workspace_id == workspace_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def suspend_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """暂停某条记忆的复习：移出到期队列，保留排期与历史。"""
        schedule = await self._get_schedule(db, memory_id, workspace_id)
        if schedule is None:
            return None
        schedule.suspended_at = datetime.now(UTC).replace(tzinfo=None)
        await db.flush()
        return {
            "memory_id": str(memory_id),
            "suspended_at": schedule.suspended_at.isoformat(),
        }

    async def unsuspend_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """恢复复习：立即排入到期队列，避免以逾期多天的状态涌入。"""
        schedule = await self._get_schedule(db, memory_id, workspace_id)
        if schedule is None:
            return None
        if schedule.suspended_at is None:
            # 未暂停时不改动排期，避免误调用把未来复习提前到当前
            return {"memory_id": str(memory_id), "status": "not_suspended"}
        schedule.suspended_at = None
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None)
        await db.flush()
        return {"memory_id": str(memory_id), "status": "resumed"}

    async def postpone_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        days: int,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """把下次复习推迟指定天数。"""
        if not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        schedule = await self._get_schedule(db, memory_id, workspace_id)
        if schedule is None:
            return None
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=days)
        await db.flush()
        return {
            "memory_id": str(memory_id),
            "next_review": schedule.next_review.isoformat(),
            "postponed_days": days,
        }

    async def reset_review(
        self,
        db: AsyncSession,
        memory_id: uuid.UUID,
        workspace_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """重置进度：回到初始参数并立即进入复习队列。"""
        schedule = await self._get_schedule(db, memory_id, workspace_id)
        if schedule is None:
            return None
        schedule.ease_factor = 2.5
        schedule.interval_days = 1
        schedule.repetitions = 0
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None)
        schedule.lapse_streak = 0
        schedule.suspended_at = None
        await db.flush()
        return {
            "memory_id": str(memory_id),
            "next_review": schedule.next_review.isoformat(),
            "mastery_level": "new",
        }

    async def list_suspended(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出已暂停复习的记忆。"""
        stmt = (
            select(ReviewSchedule, Memory)
            .join(Memory, ReviewSchedule.memory_id == Memory.id)
            .where(
                ReviewSchedule.workspace_id == workspace_id,
                ReviewSchedule.suspended_at.is_not(None),
                Memory.status == "active",
            )
            .order_by(ReviewSchedule.suspended_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [
            {
                "memory_id": str(memory.id),
                "title": memory.title,
                "memory_type": memory.type,
                "suspended_at": schedule.suspended_at.isoformat()
                if schedule.suspended_at
                else None,
                "lapse_streak": schedule.lapse_streak,
            }
            for schedule, memory in result.all()
        ]


_review_service: ReviewService | None = None


def get_review_service() -> ReviewService:
    """获取 ReviewService 单例。"""
    global _review_service
    if _review_service is None:
        _review_service = ReviewService()
    return _review_service
