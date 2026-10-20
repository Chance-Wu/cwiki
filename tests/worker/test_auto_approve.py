"""三档审核状态机测试：自动生效 / 人工审核 / 隔离留存 / 撤销。

直接在内存 DB 上运行 task_score_candidate，验证：
- 默认开关关闭时高分候选仍走人工审核
- 开关开启且各分项达阈值时自动生效（Review 留痕 + 记忆创建 + 入队向量）
- 任一条件不满足（分数不足 / 重复概率未知 / open 冲突）留在人工审核
- 质量闸门低分候选隔离留存（quarantined，行不删除）
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import apps.worker.tasks as tasks_module
from apps.worker.tasks import task_score_candidate
from packages.domain.config import settings
from packages.domain.database import Base
from packages.domain.models import CandidateMemory, Workspace
from packages.domain.models.memory import Memory, MemoryConflict, MemoryLifecycleEvent, Review

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator:
    eng = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
def mock_queue() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def ctx(mock_queue: AsyncMock) -> dict:
    embedding_service = MagicMock()
    embedding_service.is_fallback = False
    return {"embedding_service": embedding_service, "queue": mock_queue}


async def _make_candidate(
    db: AsyncSession,
    *,
    value_fields: dict | None = None,
    quality_gate_score: float | None = 0.9,
    duplicate_probability: float | None = 0.1,
) -> tuple[CandidateMemory, str]:
    """直接落一行候选，各分项由参数控制。"""
    ws = Workspace(id=uuid.uuid4(), name=f"ws-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()

    fields = {
        "reusability": 0.95,
        "stability": 0.95,
        "confidence": 0.95,
        "importance": 0.95,
        "evidence_strength": 0.95,
        "novelty": 0.9,
    }
    fields.update(value_fields or {})
    cand = CandidateMemory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="自动生效测试候选",
        content=(
            "## 场景\n自动生效状态机测试。\n\n"
            f"## 知识\n唯一校验码 {uuid.uuid4().hex[:12]}。\n\n"
            "## 原因\n验证三档审核行为。"
        ),
        type="fact",
        source="memory_save",
        status="pending_review",
        embedding=[0.1, 0.2, 0.3],
        quality_gate_score=quality_gate_score,
        duplicate_probability=duplicate_probability,
        **fields,
    )
    db.add(cand)
    await db.commit()
    return cand, str(cand.id)


async def _run_score(ctx: dict, engine, candidate_id: str, workspace_id: str) -> dict:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    with (
        patch.object(tasks_module, "async_session_maker", maker),
        patch("apps.api.file_sync.sync_memory_to_file", new=AsyncMock()),
    ):
        return await task_score_candidate(ctx, candidate_id, workspace_id)


def _enable_auto_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auto_approve_enabled", True)


class TestAutoApprove:
    async def test_default_off_keeps_human_review(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        cand, cid = await _make_candidate(db)
        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "completed"
        await db.refresh(cand)
        assert cand.status == "pending_review"

    async def test_auto_approve_all_conditions_met(
        self,
        db: AsyncSession,
        ctx: dict,
        engine,
        mock_queue: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _enable_auto_approve(monkeypatch)
        cand, cid = await _make_candidate(db)

        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))

        assert result["status"] == "auto_approved"
        memory_id = result["memory_id"]
        await db.refresh(cand)
        assert cand.status == "approved"

        memory = (
            await db.execute(select(Memory).where(Memory.id == uuid.UUID(memory_id)))
        ).scalar_one()
        assert memory.status == "active"
        assert memory.title == cand.title

        review = (
            await db.execute(
                select(Review).where(
                    Review.candidate_id == cand.id, Review.action == "auto_approve"
                )
            )
        ).scalar_one()
        assert review.reviewer_type == "system"
        assert review.reviewer_id == "auto_tier_v1"
        reason = json.loads(review.reason)
        assert reason["memory_id"] == memory_id
        assert "thresholds" in reason
        assert reason["value_score"] >= reason["thresholds"]["value"]

        mock_queue.enqueue.assert_awaited_once_with("generate_embedding", memory_id)

    async def test_auto_approve_blocked_by_value_score(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_auto_approve(monkeypatch)
        cand, cid = await _make_candidate(
            db,
            value_fields={"reusability": 0.5, "stability": 0.5, "importance": 0.5},
        )
        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "completed"
        await db.refresh(cand)
        assert cand.status == "pending_review"

    async def test_auto_approve_blocked_by_missing_duplicate_probability(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_auto_approve(monkeypatch)
        cand, cid = await _make_candidate(db, duplicate_probability=None)
        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "completed"
        await db.refresh(cand)
        assert cand.status == "pending_review"

    async def test_auto_approve_blocked_by_low_quality_gate(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_auto_approve(monkeypatch)
        cand, cid = await _make_candidate(db, quality_gate_score=0.5)
        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "completed"
        await db.refresh(cand)
        assert cand.status == "pending_review"

    async def test_auto_approve_blocked_by_open_conflict(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _enable_auto_approve(monkeypatch)
        cand, cid = await _make_candidate(db)
        db.add(
            MemoryConflict(
                workspace_id=cand.workspace_id,
                memory_id=uuid.uuid4(),  # 非记忆侧占位；查询按 candidate_id 过滤
                candidate_id=cand.id,
                conflict_type="contradiction",
                status="open",
            )
        )
        await db.commit()

        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "completed"
        await db.refresh(cand)
        assert cand.status == "pending_review"


class TestQuarantine:
    async def test_needs_enrichment_quarantines_and_retains(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        # MQ-102: discard 改为 needs_enrichment，低分候选隔离留存
        cand, cid = await _make_candidate(
            db,
            value_fields={
                "reusability": 0.1,
                "stability": 0.1,
                "confidence": 0.1,
                "importance": 0.1,
                "evidence_strength": 0.1,
                "novelty": 0.1,
            },
        )
        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))
        assert result["status"] == "needs_enrichment"
        # 行仍在 DB（隔离留存，可恢复）；任务在独立会话提交，需绕过身份映射
        cand_pk = cand.id
        db.expire_all()
        row = (
            await db.execute(select(CandidateMemory).where(CandidateMemory.id == cand_pk))
        ).scalar_one()
        assert row.status == "needs_enrichment"


class TestRevertAutoApprove:
    async def test_revert_archives_memory_and_records_review(
        self, db: AsyncSession, engine
    ) -> None:
        from httpx import ASGITransport, AsyncClient

        from apps.api.deps import get_db
        from apps.api.main import app

        cand, _ = await _make_candidate(db)
        memory = Memory(
            workspace_id=cand.workspace_id,
            title=cand.title,
            content=cand.content,
            type="fact",
            source="memory_save",
            status="active",
            version=1,
        )
        db.add(memory)
        await db.flush()
        db.add(
            Review(
                candidate_id=cand.id,
                reviewer_type="system",
                reviewer_id="auto_tier_v1",
                action="auto_approve",
                reason=json.dumps({"memory_id": str(memory.id), "thresholds": {}}),
            )
        )
        await db.commit()
        memory_id = memory.id
        cand_pk = cand.id

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("apps.api.file_sync.sync_memory_to_file", new=AsyncMock()):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    r = await client.post(f"/v1/candidates/{cand_pk}/revert-auto-approve")
            assert r.status_code == 200, r.text
        finally:
            app.dependency_overrides.clear()

        db.expire_all()
        archived = (await db.execute(select(Memory).where(Memory.id == memory_id))).scalar_one()
        assert archived.status == "archived"

        revert_review = (
            await db.execute(
                select(Review).where(
                    Review.candidate_id == cand_pk, Review.action == "revert_auto_approve"
                )
            )
        ).scalar_one()
        assert revert_review.reviewer_type == "human"

        events = (
            (
                await db.execute(
                    select(MemoryLifecycleEvent).where(
                        MemoryLifecycleEvent.memory_id == memory_id,
                        MemoryLifecycleEvent.event_type == "auto_approve_reverted",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == 1

    async def test_revert_without_auto_review_returns_404(self, db: AsyncSession, engine) -> None:
        from httpx import ASGITransport, AsyncClient

        from apps.api.deps import get_db
        from apps.api.main import app

        cand, _ = await _make_candidate(db)

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.post(f"/v1/candidates/{cand.id}/revert-auto-approve")
            assert r.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestScoreReplayGuard:
    async def test_replay_skips_non_pending_candidate(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        """at-least-once 重放守卫：非 pending_review 候选不再重评，
        auto-approve 不得对同一候选重复创建正式记忆。"""
        cand, cid = await _make_candidate(db)
        cand.status = "approved"
        await db.commit()

        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))

        assert result["status"] == "skipped"
        memory_count = (await db.execute(select(func.count()).select_from(Memory))).scalar_one()
        assert memory_count == 0

    async def test_merged_candidate_not_rescored(self, db: AsyncSession, ctx: dict, engine) -> None:
        """已合并候选重放评分同样跳过。"""
        cand, cid = await _make_candidate(db)
        cand.status = "merged"
        await db.commit()

        result = await _run_score(ctx, engine, cid, str(cand.workspace_id))

        assert result["status"] == "skipped"


class TestApproveStatusGuard:
    async def test_double_approve_raises_candidate_state_error(self, db: AsyncSession) -> None:
        """服务层守卫：终态候选重复批准抛 409，不创建第二条记忆。"""
        from packages.memory.service import CandidateStateError, approve_candidate

        cand, _ = await _make_candidate(db)
        memory = await approve_candidate(db, cand)
        assert memory.status == "active"
        assert cand.status == "approved"

        with pytest.raises(CandidateStateError):
            await approve_candidate(db, cand)

        memory_count = (await db.execute(select(func.count()).select_from(Memory))).scalar_one()
        assert memory_count == 1
