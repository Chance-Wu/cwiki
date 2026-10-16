"""ReviewService 单元测试。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, ReviewHistory, ReviewSchedule, Workspace
from packages.memory.review_service import ReviewService


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
