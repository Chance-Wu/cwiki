"""状态流转与物理删除需保证向量、文件镜像和数据库保持一致。"""

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
from apps.api.routes import file_memories, memories
from packages.domain.database import Base
from packages.domain.models import Memory, MemoryVersion, Workspace
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
    monkeypatch.setattr(file_memories, "get_file_store", lambda: file_store)
    monkeypatch.setattr(file_memories, "get_memory_indexer", lambda: indexer)
    enqueue = AsyncMock()
    monkeypatch.setattr(memories.task_queue, "enqueue", enqueue)

    async def test_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(memories.router)
    app.include_router(file_memories.router)
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
    mirror.workspace = workspace
    mirror.file_path = env.file_store.save(mirror, workspace_name=workspace)
    await env.indexer.index_memory(mirror, update_vector=False)
    if vector is not None:
        env.indexer.vector_index.add(memory_id, vector)
        await env.indexer.save_vector_index()
    return memory_id, workspace


def reloaded_vectors(env):
    index = VectorIndex(dimensions=DIMS, index_path=str(env.indexer.vector_index.index_path))
    return set(index.vectors)


async def test_patch_superseded_removes_vector_from_memory_and_disk(env):
    mid, workspace = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "superseded"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "superseded"
    assert mid not in env.indexer.vector_index.vectors
    assert mid not in reloaded_vectors(env)
    assert (await env.indexer.get_memory(mid))["status"] == "superseded"
    mirror = env.file_store.load(workspace, "fact", "Lifecycle", mid)
    assert mirror.status == "superseded"
    env.enqueue.assert_not_awaited()


async def test_patch_restore_reinjects_embedding_and_persists(env):
    mid, _ = await seed(env, status="superseded", embedding=[0.4, 0.5, 0.6])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "active"})

    assert resp.status_code == 200, resp.text
    assert mid in env.indexer.vector_index.vectors
    assert env.indexer.vector_index.get_vector(mid).tolist() == pytest.approx([0.4, 0.5, 0.6])
    assert mid in reloaded_vectors(env)
    assert (await env.indexer.get_memory(mid))["status"] == "active"
    env.enqueue.assert_not_awaited()


async def test_patch_restore_without_embedding_enqueues_regeneration(env):
    mid, _ = await seed(env, status="superseded", embedding=None)

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"status": "active"})

    assert resp.status_code == 200, resp.text
    assert (await env.indexer.get_memory(mid))["status"] == "active"
    assert mid not in env.indexer.vector_index.vectors
    env.enqueue.assert_awaited_once_with("generate_embedding", mid)


async def test_delete_removes_db_files_index_and_vector(env):
    mid, workspace = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])
    async with env.sessions() as db:
        db.add(
            MemoryVersion(
                memory_id=uuid.UUID(mid),
                version=1,
                title="Lifecycle",
                content="snapshot",
                change_type="edit",
                changed_by_type="human",
            )
        )
        await db.commit()

    resp = await env.http.delete(f"/v1/memories/{mid}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] is True
    assert resp.json()["assets_removed"] is True
    async with env.sessions() as db:
        assert await db.get(Memory, uuid.UUID(mid)) is None
    assert await env.indexer.get_memory(mid) is None
    assert mid not in env.indexer.vector_index.vectors
    assert mid not in reloaded_vectors(env)
    assert env.file_store.load(workspace, "fact", "Lifecycle", mid) is None
    env.enqueue.assert_not_awaited()


async def test_file_route_delete_commits_db_before_cleaning_assets(env):
    mid, workspace = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])

    resp = await env.http.delete(f"/v1/file-memories/{mid}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["db_cleaned"] is True
    assert resp.json()["assets_removed"] is True
    async with env.sessions() as db:
        assert await db.get(Memory, uuid.UUID(mid)) is None
    assert await env.indexer.get_memory(mid) is None
    assert mid not in env.indexer.vector_index.vectors
    assert mid not in reloaded_vectors(env)
    assert env.file_store.load(workspace, "fact", "Lifecycle", mid) is None


async def test_delete_missing_memory_returns_404(env):
    resp = await env.http.delete(f"/v1/memories/{uuid.uuid4()}")

    assert resp.status_code == 404, resp.text


async def test_delete_invalid_uuid_returns_422(env):
    resp = await env.http.delete("/v1/memories/not-a-uuid")

    assert resp.status_code == 422, resp.text


async def test_delete_rejects_overlong_reason_without_deleting(env):
    mid, _ = await seed(env)

    resp = await env.http.delete(
        f"/v1/memories/{mid}", params={"reason": "x" * 501}
    )

    assert resp.status_code == 422, resp.text
    async with env.sessions() as db:
        assert await db.get(Memory, uuid.UUID(mid)) is not None


async def test_file_route_delete_falls_back_when_index_is_missing(env):
    mid, workspace = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])
    await env.indexer.remove_from_index(mid)

    resp = await env.http.delete(f"/v1/file-memories/{mid}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["db_cleaned"] is True
    async with env.sessions() as db:
        assert await db.get(Memory, uuid.UUID(mid)) is None
    assert env.file_store.load(workspace, "fact", "Lifecycle", mid) is None


async def test_file_route_batch_delete_cleans_all_assets(env):
    mid_a, workspace_a = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])
    mid_b, workspace_b = await seed(env, embedding=[0.3, 0.2, 0.1], vector=[0.3, 0.2, 0.1])

    resp = await env.http.post("/v1/file-memories/batch-delete", json={"ids": [mid_a, mid_b]})

    assert resp.status_code == 200, resp.text
    assert set(resp.json()["deleted"]) == {mid_a, mid_b}
    async with env.sessions() as db:
        assert await db.get(Memory, uuid.UUID(mid_a)) is None
        assert await db.get(Memory, uuid.UUID(mid_b)) is None
    for mid, workspace in ((mid_a, workspace_a), (mid_b, workspace_b)):
        assert await env.indexer.get_memory(mid) is None
        assert mid not in env.indexer.vector_index.vectors
        assert env.file_store.load(workspace, "fact", "Lifecycle", mid) is None
    assert reloaded_vectors(env) == set()


async def test_patch_edit_drops_stale_vector_and_enqueues(env):
    mid, _ = await seed(env, embedding=[0.1, 0.2, 0.3], vector=[0.1, 0.2, 0.3])

    resp = await env.http.patch(f"/v1/memories/{mid}", json={"content": "Rewritten lifecycle body"})

    assert resp.status_code == 200, resp.text
    assert mid not in env.indexer.vector_index.vectors
    env.enqueue.assert_awaited_once_with("generate_embedding", mid)
