"""混合检索端点 /v1/search 的跨工作区召回。

省略 workspace_id 时不区分工作区检索（覆盖全部 active 记忆）；
传入工作区名称或 UUID 时结果保持限定在该工作区内。
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from adapters.qoder.client import CwikiClient
from apps.api.deps import get_db, invalidate_workspace_cache
from apps.api.routes import search as search_route
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.retrieval.engine import RetrievalEngine

KEYWORD = "跨库召回验证"


@pytest.fixture
async def search_env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        alpha, beta = Workspace(name="alpha-name"), Workspace(name="beta-name")
        db.add_all([alpha, beta])
        await db.flush()
        alpha_memory = Memory(
            workspace_id=alpha.id,
            title="Alpha 约定",
            content="跨库召回验证 alpha 专属内容",
            type="fact",
            embedding=[1.0, 0.0],
        )
        beta_memory = Memory(
            workspace_id=beta.id,
            title="Beta 经验",
            content="跨库召回验证 beta 专属内容",
            type="lesson",
            embedding=[0.9, 0.1],
        )
        db.add_all([alpha_memory, beta_memory])
        await db.commit()
        alpha_id, beta_id = str(alpha_memory.id), str(beta_memory.id)

    retrieval = RetrievalEngine()
    monkeypatch.setattr(search_route, "get_retrieval_engine", lambda: retrieval)
    fake_embedding = SimpleNamespace(generate_embedding=AsyncMock(return_value=[1.0, 0.0]))
    monkeypatch.setattr(search_route, "get_embedding_service", lambda: fake_embedding)
    invalidate_workspace_cache("alpha-name")
    search_route.invalidate_search_cache()

    async def _db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(search_route.router)
    app.dependency_overrides[get_db] = _db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield SimpleNamespace(http=http, alpha=alpha_id, beta=beta_id)
    finally:
        search_route.invalidate_search_cache()
        await engine.dispose()


async def test_search_without_workspace_spans_all_workspaces(search_env):
    env = search_env
    response = await env.http.post("/v1/search", json={"keyword": KEYWORD, "limit": 10})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.alpha, env.beta}


async def test_search_with_workspace_name_stays_scoped(search_env):
    env = search_env
    response = await env.http.post(
        "/v1/search", json={"keyword": KEYWORD, "workspace_id": "alpha-name", "limit": 10}
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.alpha}


async def test_search_with_workspace_uuid_stays_scoped(search_env):
    env = search_env
    workspace_uuid = str(uuid.uuid4())
    response = await env.http.post(
        "/v1/search", json={"keyword": KEYWORD, "workspace_id": workspace_uuid, "limit": 10}
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


async def test_client_search_omits_workspace_when_none():
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "total": 0})

    client = CwikiClient("http://test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client.search(KEYWORD, None, limit=3)
    finally:
        await client.close()
    assert observed == [{"keyword": KEYWORD, "limit": 3}]


async def test_client_search_includes_workspace_when_set():
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "total": 0})

    client = CwikiClient("http://test")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        await client.search(KEYWORD, "proj-ws", limit=3)
    finally:
        await client.close()
    assert observed == [{"keyword": KEYWORD, "workspace_id": "proj-ws", "limit": 3}]
