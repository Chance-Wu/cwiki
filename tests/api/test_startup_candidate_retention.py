"""启动流程的候选保留契约：rejected 候选不得被物理清理。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import CandidateMemory, Workspace


@pytest.fixture
async def sessions(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class _FakeScheduler:
    def __init__(self, queue):
        self.queue = queue

    def add(self, *args, **kwargs) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class _FakeIndexer:
    def __init__(self, *args, **kwargs):
        self.vector_index = Mock()

    async def init_db(self) -> None:
        pass

    def start_watching(self) -> None:
        pass

    def stop_watching(self) -> None:
        pass

    async def save_vector_index(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def sync_all(self) -> None:
        pass


async def test_lifespan_preserves_rejected_candidates(sessions, monkeypatch) -> None:
    from apps.api import main

    workspace_id = uuid.uuid4()
    async with sessions() as session:
        session.add(Workspace(id=workspace_id, name=f"startup-{workspace_id}"))
        session.add(
            CandidateMemory(
                workspace_id=workspace_id,
                title="rejected candidate",
                content="保留这段正文，启动后仍应可恢复。" * 4,
                type="fact",
                status="rejected",
            )
        )
        await session.commit()

    monkeypatch.setattr(main, "init_db", AsyncMock())
    monkeypatch.setattr(main, "task_queue_startup", AsyncMock())
    monkeypatch.setattr(main, "task_queue_shutdown", AsyncMock())
    monkeypatch.setattr(main, "close_db", AsyncMock())
    monkeypatch.setattr(main, "PeriodicScheduler", _FakeScheduler)
    monkeypatch.setattr(main, "async_session_maker", sessions)
    monkeypatch.setattr(main, "FileStore", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "MemoryIndexer", _FakeIndexer)
    monkeypatch.setattr(main, "init_storage_components", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "get_retrieval_engine", lambda: Mock(set_vector_source=Mock()))
    monkeypatch.setattr(main, "get_memory_indexer", lambda: _FakeIndexer())
    monkeypatch.setattr(main, "_sync_index_background", AsyncMock())
    monkeypatch.setattr(main, "_warm_up_retrieval_caches", AsyncMock())

    monkeypatch.setattr(main, "_indexer", None)
    monkeypatch.setattr(main, "_scheduler", None)

    async with main.lifespan(main.app):
        pass

    async with sessions() as session:
        count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CandidateMemory)
            .where(CandidateMemory.status == "rejected")
        )
    assert count == 1
