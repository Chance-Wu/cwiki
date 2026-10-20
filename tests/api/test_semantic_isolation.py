"""作用域化语义召回必须使用已提交的数据库身份，而非过期的镜像元数据。"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from adapters.mcp.client import CwikiClient
from apps.api.deps import get_db, invalidate_workspace_cache
from apps.api.routes import file_memories
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.indexer import MemoryIndexer


@pytest.fixture
async def semantic_env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    indexer = MemoryIndexer(
        str(tmp_path / "index.sqlite"),
        FileStore(tmp_path / "mirrors"),
        vector_index_path=str(tmp_path / "vectors.npz"),
        embedding_dimensions=2,
    )
    await indexer.init_db()
    indexer._embedding_service = SimpleNamespace(
        generate_embedding=AsyncMock(return_value=[1.0, 0.0])
    )
    monkeypatch.setattr(file_memories, "get_memory_indexer", lambda: indexer)
    async with sessions() as db:
        local, foreign = Workspace(name="local-name"), Workspace(name="foreign-name")
        db.add_all([local, foreign])
        await db.flush()
        memories = [
            Memory(workspace_id=local.id, title="Local", content="Current local body", type="fact"),
            Memory(workspace_id=foreign.id, title="Foreign", content="Foreign body", type="fact"),
            Memory(
                workspace_id=local.id,
                title="Archived",
                content="Archived body",
                type="fact",
                status="archived",
            ),
        ]
        db.add_all(memories)
        await db.commit()
        workspace_id = str(local.id)
        ids = [str(memory.id) for memory in memories]
        for i, memory in enumerate(memories):
            # 归档 DB 行故意保留一份过期的 active 镜像/向量。
            await indexer.index_memory(
                MemoryFile(
                    id=str(memory.id),
                    title="Stale mirror",
                    content="Old mirror body",
                    workspace="foreign-name" if i == 1 else "local-name",
                    status="active",
                ),
                embedding=[0.8, 0.2] if i == 0 else [1.0, 0.0],
            )

    async def test_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(file_memories.router)
    app.dependency_overrides[get_db] = test_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield SimpleNamespace(
                http=http, indexer=indexer, sessions=sessions, workspace=workspace_id, ids=ids
            )
    finally:
        await engine.dispose()


async def search(env, **overrides):
    return await env.http.post(
        "/v1/file-memories/search/semantic",
        json={
            "keyword": "memory",
            "workspace_id": env.workspace,
            "limit": 1,
            **overrides,
        },
    )


async def test_client_passes_workspace_and_filters_before_top_k(semantic_env):
    env = semantic_env
    client = CwikiClient("http://test")
    client._http = env.http
    result = await client.recall("memory", env.workspace, limit=1)
    assert result["total"] == 1
    assert result["results"][0]["id"] == env.ids[0]
    assert result["results"][0]["title"] == "Local"
    assert result["results"][0]["content"] == "Current local body"
    assert result["results"][0]["workspace"] == "local-name"


async def test_recall_request_contains_workspace_uuid():
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "total": 0})

    client = CwikiClient("http://test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client.recall("memory", "workspace-uuid", 2)
    finally:
        await client.close()
    assert observed == [{"keyword": "memory", "workspace_id": "workspace-uuid", "limit": 2}]


async def test_unknown_workspace_and_empty_allowlist_never_fall_back(semantic_env):
    env = semantic_env
    response = await search(env, workspace_id=str(uuid.uuid4()))
    assert response.status_code == 200
    assert response.json() == {"results": [], "total": 0}
    env.indexer._embedding_service.generate_embedding.assert_not_awaited()
    assert await env.indexer.semantic_search([1.0, 0.0], allowed_ids=set()) == []


async def test_archived_files_and_orphan_vectors_do_not_consume_top_k(semantic_env):
    env = semantic_env
    # 允许列表只包含本地 active 文件与一个得分更高的归档镜像。
    await env.indexer.index_memory(
        MemoryFile(id=env.ids[2], title="Archived mirror", content="Archived", status="archived"),
        embedding=[1.0, 0.0],
    )
    env.indexer.vector_index.add("orphan-vector", [1.0, 0.0])
    result = await env.indexer.semantic_search(
        [1.0, 0.0], limit=1, allowed_ids={env.ids[0], env.ids[2], "orphan-vector"}
    )
    assert [row["id"] for row in result] == [env.ids[0]]


@pytest.mark.parametrize("change", ["archive", "delete", "move"])
async def test_db_scope_rechecked_after_embedding_await(semantic_env, change):
    env = semantic_env

    async def modify_while_embedding(_query):
        async with env.sessions() as db:
            memory = await db.get(Memory, uuid.UUID(env.ids[0]))
            if change == "delete":
                await db.delete(memory)
            elif change == "move":
                foreign = await db.get(Memory, uuid.UUID(env.ids[1]))
                memory.workspace_id = foreign.workspace_id
            else:
                memory.status = "archived"
            await db.commit()
        return [1.0, 0.0]

    env.indexer._embedding_service.generate_embedding.side_effect = modify_while_embedding
    response = await search(env)
    assert response.status_code == 200
    assert response.json() == {"results": [], "total": 0}


async def test_global_file_search_remains_available_without_workspace(semantic_env):
    response = await semantic_env.http.post(
        "/v1/file-memories/search/semantic", json={"keyword": "memory", "limit": 3}
    )
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["results"]} == set(semantic_env.ids)


@pytest.mark.parametrize("extra", [{"limit": 0}, {"limit": 101}])
async def test_semantic_request_rejects_invalid_bounds(semantic_env, extra):
    assert (await search(semantic_env, **extra)).status_code == 422


async def test_workspace_name_scopes_like_uuid(semantic_env):
    env = semantic_env
    invalidate_workspace_cache("local-name")
    by_uuid = await search(env)
    by_name = await search(env, workspace_id="local-name")
    assert by_name.status_code == 200
    assert by_name.json() == by_uuid.json()
    invalidate_workspace_cache("local-name")
