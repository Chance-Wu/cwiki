"""PATCH 状态流转需保证向量与文件镜像和数据库保持一致。"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api import file_sync
from apps.api.deps import get_db
from apps.api.routes import memories
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.indexer import MemoryIndexer
from packages.storage.vector_index import VectorIndex

DIMS = 3


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    file_store = FileStore(tmp_path / "mirrors")
    indexer = MemoryIndexer(
        str(tmp_path / "index.sqlite"),
        file_store,
        vector_index_path=str(tmp_path / "vectors.npz"),
        embedding_dimensions=DIMS,
    )
    await indexer.init_db()
    indexer._embedding_service = SimpleNamespace(
        generate_embedding=AsyncMock(return_value=[0.5] * DIMS)
    )

    monkeypatch.setattr(file_sync, "get_file_store", lambda: file_store)
    monkeypatch.setattr(file_sync, "get_memory_indexer", lambda: indexer)
    enqueue = AsyncMock()
    monkeypatch.setattr(memories.task_queue, "enqueue", enqueue)

    async def test_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(memories.router)
    app.dependency_overrides[get_db] = test_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield SimpleNamespace(
                http=http,
                indexer=indexer,
                file_store=file_store,
                sessions=sessions,
                enqueue=enqueue,
            )
    finally:
        await indexer.close()
        await engine.dispose()


async def seed(env, *, status="active", embedding=None, vector=None):
    async with env.sessions() as db:
        ws = Workspace(name=f"ws-{uuid.uuid4()}")
        db.add(ws)
        await db.flush()
        memory = Memory(
            workspace_id=ws.id,
            title="Lifecycle",
            content="Lifecycle body",
            type="fact",
            status=status,
            embedding=embedding,
        )
        db.add(memory)
        await db.commit()
        memory_id = str(memory.id)
        workspace = ws.name

    mirror = MemoryFile(
        id=memory_id,
        title="Lifecycle",
        content="Lifecycle body",
        type="fact",
        status=status,
    )
    env.file_store.save(mirror, workspace_name=workspace)
    await env.indexer.index_memory(mirror, update_vector=False)
    if vector is not None:
        env.indexer.vector_index.add(memory_id, vector)
        await env.indexer.save_vector_index()
    return memory_id, workspace


def reloaded_vectors(env):
    index = VectorIndex(dimensions=DIMS, index_path=str(env.indexer.vector_index.index_path))
    return set(index.vectors)


async def test_patch_archive_removes_vector_from_memory_and_disk(env):
    mid, workspace = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "archived"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "archived"
    assert mid not in env.indexer.vector_index.vectors
    assert mid not in reloaded_vectors(env)
    assert (await env.indexer.get_memory(mid))["status"] == "archived"
    mirror = env.file_store.load(workspace, "fact", "Lifecycle", mid)
    assert mirror.status == "archived"
    env.enqueue.assert_not_awaited()


async def test_patch_restore_reinjects_embedding_and_persists(env):
    mid, _ = await seed(env, status="archived", embedding=[0.4, 0.5, 0.6])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "active"})

    assert resp.status_code == 200, resp.text
    assert mid in env.indexer.vector_index.vectors
    assert env.indexer.vector_index.get_vector(mid).tolist() == pytest.approx([0.4, 0.5, 0.6])
    assert mid in reloaded_vectors(env)
    assert (await env.indexer.get_memory(mid))["status"] == "active"
    env.enqueue.assert_not_awaited()


async def test_patch_restore_without_embedding_enqueues_regeneration(env):
    mid, _ = await seed(env, status="archived", embedding=None)

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "active"})

    assert resp.status_code == 200, resp.text
    assert (await env.indexer.get_memory(mid))["status"] == "active"
    assert mid not in env.indexer.vector_index.vectors
    env.enqueue.assert_awaited_once_with("generate_embedding", mid)


async def test_patch_edit_drops_stale_vector_and_enqueues(env):
    mid, _ = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"content": "Rewritten lifecycle body"})

    assert resp.status_code == 200, resp.text
    assert mid not in env.indexer.vector_index.vectors
    env.enqueue.assert_awaited_once_with("generate_embedding", mid)
