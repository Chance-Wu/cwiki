"""episode_id 回填与规则候选生成测试（W2-T3）。

直接在内存 DB 上运行 task_finalize_episode，验证：
- 时间窗内的 pending 候选被批量回填 episode_id（始终开启，无开关）
- 时间窗外 / 其他 workspace / 已关联 / 非 pending 的候选不受影响
- 规则候选生成开关默认关；开启后仅「失败→修复」信号齐备才生成
- client_write_id 幂等：同一 episode 重复走生成路径不重复建行
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import apps.worker.tasks as tasks_module
from apps.worker.episode_builder import build_episode
from apps.worker.tasks import _generate_episode_candidate, task_finalize_episode
from packages.domain.config import parasitic_evolution_config
from packages.domain.database import Base
from packages.domain.models import (
    Agent,
    CandidateMemory,
    Episode,
    Event,
    Session,
    Workspace,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


def _naive(*args: int) -> datetime:
    """构造 naive 时间戳：SQLite DateTime 列按 naive 存取，
    Event.occurred_at 与 CandidateMemory.created_at 刻意保持一致。"""
    return datetime(*args)  # noqa: DTZ001


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
    embedding_service.is_fallback = True
    return {"embedding_service": embedding_service, "queue": mock_queue}


async def _make_session(db: AsyncSession) -> tuple[Workspace, Session, Agent]:
    """创建 workspace + agent + session 骨架，返回三元组。"""
    ws = Workspace(id=uuid.uuid4(), name=f"ws-{uuid.uuid4().hex[:6]}")
    agent = Agent(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name="agent",
        type="qoder",
        adapter="mcp",
    )
    session = Session(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        agent_id=agent.id,
        external_session_id=f"sess-{uuid.uuid4().hex[:8]}",
    )
    db.add_all([ws, agent, session])
    await db.commit()
    return ws, session, agent


async def _add_debug_events(
    db: AsyncSession,
    session: Session,
    ws: Workspace,
    agent: Agent,
    base: datetime,
) -> list[dict]:
    """写入「失败→修复」事件流，返回与任务内读取格式一致的 dict 列表。

    事件序列会产生 1 条 problem（Bash 失败）与 1 条 solution（Edit 修复）。
    """
    specs = [
        ("prompt.submitted", base, {"content": "修复测试失败的登录逻辑"}),
        (
            "tool.failed",
            base + timedelta(minutes=1),
            {
                "tool_name": "Bash",
                "error": "pytest exited with code 1",
                "input": {"command": "pytest -q"},
            },
        ),
        (
            "tool.completed",
            base + timedelta(minutes=2),
            {"tool_name": "Edit", "input": {"file_path": "src/auth.py"}},
        ),
        ("test.passed", base + timedelta(minutes=3), {"test_name": "test_login"}),
    ]
    events: list[dict] = []
    for seq, (event_type, occurred_at, payload) in enumerate(specs, start=1):
        event_id = uuid.uuid4()
        db.add(
            Event(
                id=event_id,
                workspace_id=ws.id,
                agent_id=agent.id,
                session_id=session.id,
                sequence=seq,
                event_type=event_type,
                occurred_at=occurred_at,
                payload=payload,
            )
        )
        events.append(
            {
                "id": str(event_id),
                "event_type": event_type,
                "sequence": seq,
                "payload": payload,
                "occurred_at": occurred_at.isoformat(),
            }
        )
    await db.commit()
    return events


async def _add_failure_only_events(
    db: AsyncSession,
    session: Session,
    ws: Workspace,
    agent: Agent,
    base: datetime,
) -> None:
    """写入只有失败、没有修复的事件流（problems 有 / solutions 无）。"""
    db.add_all(
        [
            Event(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                agent_id=agent.id,
                session_id=session.id,
                sequence=1,
                event_type="prompt.submitted",
                occurred_at=base,
                payload={"content": "排查构建失败原因"},
            ),
            Event(
                id=uuid.uuid4(),
                workspace_id=ws.id,
                agent_id=agent.id,
                session_id=session.id,
                sequence=2,
                event_type="tool.failed",
                occurred_at=base + timedelta(minutes=1),
                payload={
                    "tool_name": "Bash",
                    "error": "build failed",
                    "input": {"command": "make"},
                },
            ),
        ]
    )
    await db.commit()


async def _make_candidate(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    created_at: datetime,
    episode_id: uuid.UUID | None = None,
    status: str = "pending_review",
) -> CandidateMemory:
    """直接落一行候选；created_at 由参数控制以命中/避开回填时间窗。"""
    cand = CandidateMemory(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        title=f"回填测试候选 {uuid.uuid4().hex[:6]}",
        content="这是一条用于 episode 回填测试的候选记忆内容，满足最小长度要求。",
        type="fact",
        source="mcp",
        status=status,
        episode_id=episode_id,
        created_at=created_at,
    )
    db.add(cand)
    await db.commit()
    return cand


async def _run_finalize(ctx: dict, engine, session: Session, ws: Workspace) -> dict:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    with patch.object(tasks_module, "async_session_maker", maker):
        return await task_finalize_episode(ctx, str(session.id), str(ws.id))


async def _count_episode_candidates(db: AsyncSession, ws_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(CandidateMemory)
        .where(CandidateMemory.workspace_id == ws_id, CandidateMemory.source == "episode")
    )
    return result.scalar_one()


async def _get_candidate(db: AsyncSession, cand_id: uuid.UUID) -> CandidateMemory:
    return (
        await db.execute(select(CandidateMemory).where(CandidateMemory.id == cand_id))
    ).scalar_one()


class TestEpisodeBackfill:
    async def test_backfills_pending_candidates_in_window(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        """时间窗内（含边界 margin）的 pending 候选 100% 回填。"""
        ws, session, agent = await _make_session(db)
        base = _naive(2024, 6, 1, 12, 0, 0)
        await _add_debug_events(db, session, ws, agent, base)
        # episode 窗口 [12:00:00, 12:03:00]，加 margin 后 [11:59:55, 12:03:05]
        in_window = [
            await _make_candidate(db, ws.id, created_at=base + timedelta(minutes=1)),
            await _make_candidate(db, ws.id, created_at=base + timedelta(minutes=3, seconds=4)),
        ]

        result = await _run_finalize(ctx, engine, session, ws)

        assert result["status"] == "completed"
        assert result["candidates_linked"] == 2
        episode_id = uuid.UUID(result["episode_id"])
        # expire 前先取主键，避免 expire_all 后属性懒加载在异步上下文报错
        in_window_ids = [cand.id for cand in in_window]
        db.expire_all()
        for cand_id in in_window_ids:
            row = await _get_candidate(db, cand_id)
            assert row.episode_id == episode_id

    async def test_backfill_scope_excludes_unrelated_candidates(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        """时间窗外 / 其他 workspace / 已关联 / 非 pending 的候选不受影响。"""
        ws, session, agent = await _make_session(db)
        other_ws, _, _ = await _make_session(db)
        base = _naive(2024, 6, 1, 12, 0, 0)
        await _add_debug_events(db, session, ws, agent, base)

        out_of_window = await _make_candidate(db, ws.id, created_at=base - timedelta(hours=1))
        other_workspace = await _make_candidate(
            db, other_ws.id, created_at=base + timedelta(minutes=1)
        )
        existing_episode_id = uuid.uuid4()
        already_linked = await _make_candidate(
            db,
            ws.id,
            created_at=base + timedelta(minutes=1),
            episode_id=existing_episode_id,
        )
        approved = await _make_candidate(
            db, ws.id, created_at=base + timedelta(minutes=1), status="approved"
        )

        result = await _run_finalize(ctx, engine, session, ws)

        assert result["candidates_linked"] == 0
        # expire 前先取主键，避免 expire_all 后属性懒加载在异步上下文报错
        pk_out, pk_other, pk_linked, pk_approved = (
            out_of_window.id,
            other_workspace.id,
            already_linked.id,
            approved.id,
        )
        db.expire_all()
        assert (await _get_candidate(db, pk_out)).episode_id is None
        assert (await _get_candidate(db, pk_other)).episode_id is None
        assert (await _get_candidate(db, pk_linked)).episode_id == existing_episode_id
        assert (await _get_candidate(db, pk_approved)).episode_id is None


class TestEpisodeCandidateExtraction:
    async def test_disabled_by_default_generates_nothing(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """开关关闭（默认）时，即使 problems/solutions 齐备也不生成候选。"""
        monkeypatch.setattr(
            parasitic_evolution_config, "episode_candidate_extraction_enabled", False
        )
        ws, session, agent = await _make_session(db)
        await _add_debug_events(db, session, ws, agent, _naive(2024, 6, 1, 12, 0, 0))

        result = await _run_finalize(ctx, engine, session, ws)

        assert result["status"] == "completed"
        assert result["candidate_generated"] is False
        assert await _count_episode_candidates(db, ws.id) == 0

    async def test_generates_idempotent_lesson_candidate(
        self,
        db: AsyncSession,
        ctx: dict,
        engine,
        mock_queue: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """开关开启且「失败→修复」齐备时生成 1 条 lesson 候选，且同一 episode 幂等。"""
        monkeypatch.setattr(
            parasitic_evolution_config, "episode_candidate_extraction_enabled", True
        )
        ws, session, agent = await _make_session(db)
        base = _naive(2024, 6, 1, 12, 0, 0)
        events = await _add_debug_events(db, session, ws, agent, base)

        result = await _run_finalize(ctx, engine, session, ws)

        assert result["status"] == "completed"
        assert result["candidate_generated"] is True
        episode_id = uuid.UUID(result["episode_id"])

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db2:
            episode_row = (
                await db2.execute(select(Episode).where(Episode.id == episode_id))
            ).scalar_one()
            cand = (
                await db2.execute(
                    select(CandidateMemory).where(
                        CandidateMemory.client_write_id == f"episode-{episode_id}"
                    )
                )
            ).scalar_one()
            assert cand.type == "lesson"
            assert cand.source == "episode"
            assert cand.episode_id == episode_id
            assert cand.title.startswith("调试解决：")
            assert len(cand.title) <= 80
            # 正文使用 problems/solutions 的真实字段值
            assert "Bash" in cand.content
            assert "pytest exited with code 1" in cand.content
            assert "Edit" in cand.content
            cand_id = cand.id

            # 幂等：同一 episode 再走一次生成路径，不重复建行
            created_again = await _generate_episode_candidate(
                db2, ctx, episode_row, build_episode(str(session.id), events)
            )
            assert created_again is False
            assert await _count_episode_candidates(db2, ws.id) == 1

        mock_queue.enqueue.assert_awaited_once_with("generate_candidate_embedding", str(cand_id))

    async def test_no_generation_without_solutions(
        self, db: AsyncSession, ctx: dict, engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """只有 problems 没有 solutions 的失败 episode 不生成候选。"""
        monkeypatch.setattr(
            parasitic_evolution_config, "episode_candidate_extraction_enabled", True
        )
        ws, session, agent = await _make_session(db)
        await _add_failure_only_events(db, session, ws, agent, _naive(2024, 6, 1, 12, 0, 0))

        result = await _run_finalize(ctx, engine, session, ws)

        assert result["status"] == "completed"
        assert result["candidate_generated"] is False
        assert await _count_episode_candidates(db, ws.id) == 0


class TestFinalizeIdempotency:
    async def test_replay_does_not_recreate_episode(
        self, db: AsyncSession, ctx: dict, engine
    ) -> None:
        """at-least-once 重放守卫：同一 session 重复 finalize 返回已有 episode，不重建。"""
        ws, session, agent = await _make_session(db)
        await _add_debug_events(db, session, ws, agent, _naive(2024, 6, 1, 12, 0, 0))

        first = await _run_finalize(ctx, engine, session, ws)
        assert first["status"] == "completed"

        second = await _run_finalize(ctx, engine, session, ws)

        assert second["status"] == "already_finalized"
        assert second["episode_id"] == first["episode_id"]
        count = (
            await db.execute(
                select(func.count()).select_from(Episode).where(Episode.session_id == session.id)
            )
        ).scalar_one()
        assert count == 1

    async def test_replay_does_not_duplicate_candidates(
        self,
        db: AsyncSession,
        ctx: dict,
        engine,
        mock_queue: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """重放 finalize 时回填与规则候选生成都不得重复执行。"""
        monkeypatch.setattr(
            parasitic_evolution_config, "episode_candidate_extraction_enabled", True
        )
        ws, session, agent = await _make_session(db)
        base = _naive(2024, 6, 1, 12, 0, 0)
        await _add_debug_events(db, session, ws, agent, base)
        await _make_candidate(db, ws.id, created_at=base + timedelta(minutes=1))

        first = await _run_finalize(ctx, engine, session, ws)
        assert first["status"] == "completed"

        second = await _run_finalize(ctx, engine, session, ws)
        assert second["status"] == "already_finalized"
        assert await _count_episode_candidates(db, ws.id) == 1
