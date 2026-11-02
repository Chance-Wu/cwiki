"""ReviewService 单元测试。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, ReviewHistory, ReviewSchedule, Workspace
from packages.memory.review_service import ReviewService


def _make_memory(workspace: Workspace, title: str) -> Memory:
    """构造一条测试记忆。"""
    return Memory(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        title=title,
        content=f"{title} content for review stats testing.",
        type="fact",
        source="test",
        status="active",
        version=1,
    )


def _make_history(
    workspace_id: uuid.UUID,
    memory_id: uuid.UUID,
    reviewed_at: datetime,
    quality: int = 4,
) -> ReviewHistory:
    """构造一条复习历史，用于统计口径测试。"""
    return ReviewHistory(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        memory_id=memory_id,
        quality=quality,
        ease_factor_before=2.5,
        interval_before=1,
        repetitions_before=0,
        next_review_before=reviewed_at,
        mastery_level_before="new",
        ease_factor_after=2.5,
        interval_after=1,
        repetitions_after=1,
        next_review_after=reviewed_at + timedelta(days=1),
        mastery_level_after="learning",
        reviewed_at=reviewed_at,
    )


def _freeze_now(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """把 review_service 内的 datetime.now 冻结到指定时刻（当作 UTC 墙钟）。"""

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return moment.replace(tzinfo=tz)

    monkeypatch.setattr("packages.memory.review_service.datetime", _FrozenDatetime)


@pytest.fixture
async def workspace(db_session: AsyncSession) -> Workspace:
    """创建测试工作区。"""
    ws = Workspace(id=uuid.uuid4(), name="test-review-ws")
    db_session.add(ws)
    await db_session.flush()
    return ws


@pytest.fixture
async def memory(db_session: AsyncSession, workspace: Workspace) -> Memory:
    """创建测试记忆。"""
    mem = Memory(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        title="Test Memory",
        content="This is test content for review service testing.",
        type="fact",
        source="test",
        status="active",
        version=1,
    )
    db_session.add(mem)
    await db_session.flush()
    return mem


@pytest.fixture
def service() -> ReviewService:
    """创建 ReviewService 实例。"""
    return ReviewService()


class TestScheduleMemory:
    """schedule_memory 方法测试。"""

    async def test_schedule_creates_new_schedule(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """schedule_memory 应创建新的复习排期。"""
        result = await service.schedule_memory(db_session, memory.id, workspace.id)

        assert result is not None
        assert result["memory_id"] == str(memory.id)
        assert result["status"] == "scheduled"
        assert "next_review" in result

        # 验证排期已创建
        schedule = await db_session.get(ReviewSchedule, result.get("memory_id"))
        # 实际需要按 memory_id 查询
        from sqlalchemy import select

        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        result_row = await db_session.execute(stmt)
        schedule = result_row.scalar_one_or_none()

        assert schedule is not None
        assert schedule.ease_factor == 2.5
        assert schedule.interval_days == 1
        assert schedule.repetitions == 0
        assert schedule.total_reviews == 0

    async def test_schedule_returns_none_if_already_scheduled(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """已排期时 schedule_memory 应返回 None。"""
        # 第一次排期
        result1 = await service.schedule_memory(db_session, memory.id, workspace.id)
        assert result1 is not None

        # 第二次排期应返回 None
        result2 = await service.schedule_memory(db_session, memory.id, workspace.id)
        assert result2 is None


class TestSubmitReview:
    """submit_review 方法测试。"""

    async def test_submit_review_creates_schedule_if_none_exists(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """无排期时 submit_review 应创建排期。"""
        result = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )

        assert result["memory_id"] == str(memory.id)
        assert result["total_reviews"] == 1
        assert "mastery_level" in result
        assert "ease_factor" in result

    async def test_submit_review_updates_existing_schedule(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """submit_review 应更新已有排期。"""
        # 第一次复习
        await service.submit_review(db_session, memory.id, quality=4, workspace_id=workspace.id)

        # 第二次复习
        result = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )

        assert result["total_reviews"] == 2
        assert result["repetitions"] == 2  # 0 -> 1 -> 2

    async def test_submit_review_records_history(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """submit_review 应记录历史条目。"""
        await service.submit_review(db_session, memory.id, quality=4, workspace_id=workspace.id)

        # 检查历史已记录
        from sqlalchemy import select

        stmt = select(ReviewHistory).where(ReviewHistory.memory_id == memory.id)
        result = await db_session.execute(stmt)
        history = result.scalar_one_or_none()

        assert history is not None
        assert history.quality == 4
        assert history.ease_factor_before == 2.5
        assert history.mastery_level_before == "new"
        assert history.mastery_level_after == "learning"

    async def test_submit_review_low_quality_resets_progress(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """低质量（0-2）应重置重复次数。"""
        # 先积累进度
        await service.submit_review(db_session, memory.id, quality=4, workspace_id=workspace.id)
        await service.submit_review(db_session, memory.id, quality=4, workspace_id=workspace.id)

        # 然后失败一次
        result = await service.submit_review(
            db_session, memory.id, quality=1, workspace_id=workspace.id
        )

        assert result["repetitions"] == 0
        assert result["interval_days"] == 1

    async def test_submit_review_invalid_quality(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """submit_review 应拒绝非法 quality。"""
        with pytest.raises(ValueError, match="Quality must be between 0 and 5"):
            await service.submit_review(db_session, memory.id, quality=6, workspace_id=workspace.id)

        with pytest.raises(ValueError, match="Quality must be between 0 and 5"):
            await service.submit_review(
                db_session, memory.id, quality=-1, workspace_id=workspace.id
            )


class TestUndoReview:
    """undo_review 方法测试。"""

    async def test_undo_restores_previous_state(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """undo_review 应将排期恢复到之前的状态。"""
        # 第一次复习
        result1 = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )
        assert result1["repetitions"] == 1

        # 第二次复习
        result2 = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )
        assert result2["repetitions"] == 2

        # 撤销第二次复习
        undo_result = await service.undo_review(db_session, memory.id, workspace.id)

        assert undo_result is not None
        assert undo_result["undone_quality"] == 4
        assert undo_result["restored_mastery_level"] == "learning"

        # 验证排期已恢复
        from sqlalchemy import select

        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule_result = await db_session.execute(stmt)
        schedule = schedule_result.scalar_one_or_none()

        assert schedule.repetitions == 1

    async def test_undo_is_deterministic_with_identical_clock_readings(
        self,
        db_session: AsyncSession,
        service: ReviewService,
        memory: Memory,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """冻结时钟（模拟 Windows 毫秒粒度）：两次提交读到相同时间，undo 仍须恢复第一次的状态。

        回归背景：reviewed_at 相同时，undo 的 (reviewed_at DESC, id DESC) 排序因 id 为随机
        UUID 而随机选中错误记录。修复后 submit_review 写入端保证 reviewed_at 严格单调（+1μs）。
        """

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return cls(2026, 10, 14, 5, 0, 0, tzinfo=tz)

        monkeypatch.setattr("packages.memory.review_service.datetime", _FrozenDatetime)

        result1 = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )
        result2 = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )
        assert result1["repetitions"] == 1
        assert result2["repetitions"] == 2

        # 两次 reviewed_at 必须严格单调，undo 才能稳定定位最近一条
        from sqlalchemy import select

        hist_stmt = (
            select(ReviewHistory)
            .where(ReviewHistory.memory_id == memory.id)
            .order_by(ReviewHistory.reviewed_at)
        )
        hist_rows = (await db_session.execute(hist_stmt)).scalars().all()
        assert len(hist_rows) == 2
        assert hist_rows[0].reviewed_at < hist_rows[1].reviewed_at

        undo_result = await service.undo_review(db_session, memory.id, workspace.id)

        assert undo_result is not None
        assert undo_result["restored_mastery_level"] == "learning"
        assert undo_result["undone_reviewed_at"] == hist_rows[1].reviewed_at.isoformat()

    async def test_undo_returns_none_if_no_history(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """无历史时 undo_review 应返回 None。"""
        # 排期但没有任何复习
        await service.schedule_memory(db_session, memory.id, workspace.id)

        result = await service.undo_review(db_session, memory.id, workspace.id)
        assert result is None

    async def test_undo_clears_last_review_when_all_undone(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """全部撤销后 undo_review 应清空 last_review。"""
        # 仅一次复习
        await service.submit_review(db_session, memory.id, quality=4, workspace_id=workspace.id)

        # 撤销它
        await service.undo_review(db_session, memory.id, workspace.id)

        # 验证排期状态
        from sqlalchemy import select

        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule_result = await db_session.execute(stmt)
        schedule = schedule_result.scalar_one_or_none()

        assert schedule.last_review is None
        assert schedule.total_reviews == 0


class TestGetDueReviews:
    """get_due_reviews 方法测试。"""

    async def test_get_due_reviews_empty(
        self, db_session: AsyncSession, service: ReviewService, workspace: Workspace
    ):
        """没有到期项时 get_due_reviews 应返回空列表。"""
        result = await service.get_due_reviews(db_session, workspace.id)
        assert result == []

    async def test_get_due_reviews_returns_due_items(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """get_due_reviews 应返回到期项。"""
        # 创建一个过期日期的排期
        from sqlalchemy import select

        await service.schedule_memory(db_session, memory.id, workspace.id)

        # 手动把 next_review 设为过去（用 naive datetime 匹配 SQLite 存储）
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule_result = await db_session.execute(stmt)
        schedule = schedule_result.scalar_one()
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        await db_session.flush()

        result = await service.get_due_reviews(db_session, workspace.id)

        assert len(result) == 1
        assert result[0]["memory_id"] == str(memory.id)
        assert result[0]["days_overdue"] >= 1

    async def test_get_due_reviews_respects_limit(
        self, db_session: AsyncSession, service: ReviewService, workspace: Workspace
    ):
        """get_due_reviews 应遵守 limit 参数。"""
        # 创建多条已到期的记忆
        for i in range(5):
            mem = Memory(
                id=uuid.uuid4(),
                workspace_id=workspace.id,
                title=f"Test Memory {i}",
                content=f"Test content {i} for review service testing purposes.",
                type="fact",
                source="test",
                status="active",
                version=1,
            )
            db_session.add(mem)
            await db_session.flush()
            await service.schedule_memory(db_session, mem.id, workspace.id)

            # 设为到期（用 naive datetime 匹配 SQLite 存储）
            from sqlalchemy import select

            stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == mem.id)
            schedule_result = await db_session.execute(stmt)
            schedule = schedule_result.scalar_one()
            schedule.next_review = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
            await db_session.flush()

        result = await service.get_due_reviews(db_session, workspace.id, limit=3)
        assert len(result) == 3


class TestGetReviewStats:
    """get_review_stats 方法测试。"""

    async def test_get_review_stats_empty(
        self, db_session: AsyncSession, service: ReviewService, workspace: Workspace
    ):
        """空工作区时 get_review_stats 应返回全零。"""
        result = await service.get_review_stats(db_session, workspace.id)

        assert result["total_scheduled"] == 0
        assert result["due_now"] == 0
        assert result["due_today"] == 0
        assert result["reviewed_today"] == 0
        assert result["mastery_distribution"]["new"] == 0
        assert len(result["review_trend"]) == 7

    async def test_get_review_stats_counts_scheduled(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """get_review_stats 应统计已排期记忆。"""
        await service.schedule_memory(db_session, memory.id, workspace.id)

        result = await service.get_review_stats(db_session, workspace.id)

        assert result["total_scheduled"] == 1

    async def test_stats_counts_history_today(
        self,
        db_session: AsyncSession,
        service: ReviewService,
        memory: Memory,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """同一天多次复习：reviewed_today 去重，review_count_today 计事件。"""
        _freeze_now(monkeypatch, datetime(2026, 10, 15, 12, 0, 0))
        mem2 = _make_memory(workspace, "Second")
        db_session.add(mem2)
        await db_session.flush()
        db_session.add_all(
            [
                _make_history(workspace.id, memory.id, datetime(2026, 10, 15, 9, 0, 0), quality=4),
                _make_history(workspace.id, memory.id, datetime(2026, 10, 15, 10, 0, 0), quality=5),
                _make_history(workspace.id, mem2.id, datetime(2026, 10, 15, 11, 0, 0), quality=4),
            ]
        )
        await db_session.flush()

        result = await service.get_review_stats(db_session, workspace.id)

        assert result["reviewed_today"] == 2
        assert result["review_count_today"] == 3

    async def test_stats_trend_keeps_yesterday(
        self,
        db_session: AsyncSession,
        service: ReviewService,
        memory: Memory,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """昨天的复习不应被今天的复习覆盖。"""
        _freeze_now(monkeypatch, datetime(2026, 10, 15, 12, 0, 0))
        mem2 = _make_memory(workspace, "Second")
        db_session.add(mem2)
        await db_session.flush()
        db_session.add_all(
            [
                _make_history(workspace.id, memory.id, datetime(2026, 10, 14, 9, 0, 0)),
                _make_history(workspace.id, mem2.id, datetime(2026, 10, 15, 9, 0, 0)),
            ]
        )
        await db_session.flush()

        result = await service.get_review_stats(db_session, workspace.id)
        trend = {row["date"]: row["count"] for row in result["review_trend"]}

        assert trend["2026-10-14"] == 1
        assert trend["2026-10-15"] == 1

    async def test_stats_uses_local_day_boundary(
        self,
        db_session: AsyncSession,
        service: ReviewService,
        memory: Memory,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """UTC 16:20 在东八区属于次日 00:20，应计入今天。"""
        _freeze_now(monkeypatch, datetime(2026, 10, 30, 16, 30, 0))
        mem2 = _make_memory(workspace, "Second")
        db_session.add(mem2)
        await db_session.flush()
        db_session.add_all(
            [
                _make_history(workspace.id, memory.id, datetime(2026, 10, 30, 16, 20, 0)),
                _make_history(workspace.id, mem2.id, datetime(2026, 10, 30, 15, 50, 0)),
            ]
        )
        await db_session.flush()

        result = await service.get_review_stats(db_session, workspace.id, tz_offset_minutes=480)

        assert result["reviewed_today"] == 1
        assert result["review_count_today"] == 1

    async def test_stats_streak_counts_consecutive_days(
        self,
        db_session: AsyncSession,
        service: ReviewService,
        memory: Memory,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """连续 3 天有记录应返回 streak_days=3。"""
        _freeze_now(monkeypatch, datetime(2026, 10, 15, 12, 0, 0))
        db_session.add_all(
            [
                _make_history(workspace.id, memory.id, datetime(2026, 10, 13, 9, 0, 0)),
                _make_history(workspace.id, memory.id, datetime(2026, 10, 14, 9, 0, 0)),
                _make_history(workspace.id, memory.id, datetime(2026, 10, 15, 9, 0, 0)),
            ]
        )
        await db_session.flush()

        result = await service.get_review_stats(db_session, workspace.id)

        assert result["streak_days"] == 3


class TestLeechAndPause:
    """顽固记忆识别与暂停/恢复/推迟/重置。"""

    async def test_lapse_streak_marks_leech(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """连续 3 次 quality<3 应标记为 leech。"""
        result = None
        for _ in range(3):
            result = await service.submit_review(
                db_session, memory.id, quality=2, workspace_id=workspace.id
            )

        assert result is not None
        assert result["lapse_streak"] == 3
        assert result["leech"] is True

    async def test_success_resets_lapse_streak(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """答对一次即清零遗忘记账。"""
        await service.submit_review(db_session, memory.id, quality=2, workspace_id=workspace.id)
        result = await service.submit_review(
            db_session, memory.id, quality=4, workspace_id=workspace.id
        )

        assert result["lapse_streak"] == 0
        assert result["leech"] is False

    async def test_suspended_item_leaves_due_queue(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """暂停后不再出现在到期队列，恢复后立即回到队列。"""
        from sqlalchemy import select

        await service.schedule_memory(db_session, memory.id, workspace.id)
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule = (await db_session.execute(stmt)).scalar_one()
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        await db_session.flush()

        assert len(await service.get_due_reviews(db_session, workspace.id)) == 1

        await service.suspend_review(db_session, memory.id, workspace.id)
        assert await service.get_due_reviews(db_session, workspace.id) == []

        suspended = await service.list_suspended(db_session, workspace.id)
        assert len(suspended) == 1
        assert suspended[0]["memory_id"] == str(memory.id)

        await service.unsuspend_review(db_session, memory.id, workspace.id)
        assert len(await service.get_due_reviews(db_session, workspace.id)) == 1

    async def test_stats_excludes_suspended_from_due(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """暂停的记忆不计入 due_now，但仍计入 total_scheduled。"""
        from sqlalchemy import select

        await service.schedule_memory(db_session, memory.id, workspace.id)
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule = (await db_session.execute(stmt)).scalar_one()
        schedule.next_review = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        await db_session.flush()
        await service.suspend_review(db_session, memory.id, workspace.id)

        result = await service.get_review_stats(db_session, workspace.id)

        assert result["due_now"] == 0
        assert result["total_scheduled"] == 1

    async def test_resume_without_suspend_keeps_schedule(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """未暂停时恢复不应把未来的 next_review 提前到当前。"""
        from sqlalchemy import select

        await service.schedule_memory(db_session, memory.id, workspace.id)
        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule = (await db_session.execute(stmt)).scalar_one()
        future = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=3)
        schedule.next_review = future
        await db_session.flush()

        result = await service.unsuspend_review(db_session, memory.id, workspace.id)

        assert result is not None
        assert result["status"] == "not_suspended"
        await db_session.refresh(schedule)
        assert schedule.next_review == future

    async def test_postpone_and_reset(
        self, db_session: AsyncSession, service: ReviewService, memory: Memory, workspace: Workspace
    ):
        """推迟更新下次时间；重置回到初始参数。"""
        from sqlalchemy import select

        await service.submit_review(db_session, memory.id, quality=5, workspace_id=workspace.id)
        await service.submit_review(db_session, memory.id, quality=5, workspace_id=workspace.id)

        postponed = await service.postpone_review(db_session, memory.id, 5, workspace.id)
        assert postponed is not None
        assert postponed["postponed_days"] == 5

        reset = await service.reset_review(db_session, memory.id, workspace.id)
        assert reset is not None
        assert reset["mastery_level"] == "new"

        stmt = select(ReviewSchedule).where(ReviewSchedule.memory_id == memory.id)
        schedule = (await db_session.execute(stmt)).scalar_one()
        assert schedule.ease_factor == 2.5
        assert schedule.interval_days == 1
        assert schedule.repetitions == 0
        assert schedule.lapse_streak == 0
