"""Mirror repair intents survive rollback, I/O failure, edits and deletes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.file_sync import replay_file_sync_jobs, sync_memory_to_file
from packages.domain.database import Base
from packages.domain.models import FileSyncJob, Memory, Workspace
from packages.storage.file_store import FileStore


@pytest_asyncio.fixture
async def repair_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


async def seed(db):
    ws = Workspace(name=f"repair-{uuid.uuid4().hex}")
    db.add(ws)
    await db.flush()
    memory = Memory(workspace_id=ws.id, title="mirror", content="durable knowledge", type="fact")
    db.add(memory)
    await db.commit()
    return ws, memory


async def test_intent_is_transactional(repair_db):
    _, memory = await seed(repair_db)
    ids = list(await repair_db.scalars(select(FileSyncJob.id)))
    assert ids
    memory.title = "rolled back"
    await repair_db.flush()
    assert len(list(await repair_db.scalars(select(FileSyncJob.id)))) > len(ids)
    await repair_db.rollback()
    assert list(await repair_db.scalars(select(FileSyncJob.id))) == ids


async def test_replay_failure_retains_intent_then_uses_latest_state(repair_db, monkeypatch):
    _, memory = await seed(repair_db)
    mid = memory.id
    sync = AsyncMock(return_value=False)
    monkeypatch.setattr("apps.api.file_sync.sync_memory_to_file", sync)
    assert await replay_file_sync_jobs(repair_db) == 0
    assert list(await repair_db.scalars(select(FileSyncJob.id)))
    memory = await repair_db.get(Memory, mid)
    memory.content = "latest committed knowledge"
    await repair_db.commit()
    sync.return_value = True
    assert await replay_file_sync_jobs(repair_db) == 1
    assert sync.call_args.args[0].content == "latest committed knowledge"
    assert not list(await repair_db.scalars(select(FileSyncJob.id)))


async def test_bulk_delete_intent_survives_missing_memory(repair_db, monkeypatch):
    _, memory = await seed(repair_db)
    mid = memory.id
    await repair_db.execute(delete(FileSyncJob))
    await repair_db.execute(delete(Memory).where(Memory.id == mid))
    await repair_db.commit()
    assert list(await repair_db.scalars(select(FileSyncJob.memory_id))) == [mid]
    remove = AsyncMock(return_value=False)
    monkeypatch.setattr("apps.api.file_sync.delete_memory_assets", remove)
    assert await replay_file_sync_jobs(repair_db) == 0
    remove.return_value = True
    assert await replay_file_sync_jobs(repair_db) == 1
    assert remove.call_args.args[0] == mid
    assert not list(await repair_db.scalars(select(FileSyncJob.id)))


async def test_type_change_removes_old_mirror_and_meta_failure_reports_failure(
    repair_db, tmp_path, monkeypatch
):
    ws, memory = await seed(repair_db)
    store = FileStore(tmp_path / "memories")
    indexer = AsyncMock()
    indexer.vector_index.remove = lambda mid: None
    monkeypatch.setattr("apps.api.file_sync.get_file_store", lambda: store)
    monkeypatch.setattr("apps.api.file_sync.get_memory_indexer", lambda: indexer)
    meta = AsyncMock()
    monkeypatch.setattr("apps.api.file_sync.export_memory_meta", meta)
    assert await sync_memory_to_file(memory, repair_db, skip_vector_index=True)
    memory.type = "lesson"
    await repair_db.commit()
    await repair_db.refresh(memory)
    assert await sync_memory_to_file(memory, repair_db, skip_vector_index=True)
    files = store.find_all_by_id(str(memory.id))
    assert len(files) == 1
    assert files[0].parent.name == "lesson"
    assert len(store.list(ws.name)) == 1
    meta.side_effect = OSError("disk full")
    assert not await sync_memory_to_file(memory, repair_db, skip_vector_index=True)
    with pytest.raises(OSError):
        await sync_memory_to_file(memory, repair_db, skip_vector_index=True, raise_on_error=True)
