"""/v1/search 端点的过滤行为。

memory_type、min_confidence 与 filters 字典必须真正过滤结果
（此前这些参数会被静默忽略）。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.deps import get_db, invalidate_workspace_cache
from apps.api.routes import search as search_route
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.retrieval import engine as retrieval_engine
from packages.retrieval.engine import RetrievalEngine

KEYWORD = "过滤验证"


@pytest.fixture
async def filter_env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        workspace = Workspace(name="filter-ws")
        db.add(workspace)
        await db.flush()
        # 三条记忆：不同 type 与 confidence 组合
        mem_lesson = Memory(
            workspace_id=workspace.id,
            title="踩坑经验",
            content="过滤验证 踩坑经验 下次注意",
            type="lesson",
            confidence=0.9,
            embedding=[1.0, 0.0],
        )
        mem_decision = Memory(
            workspace_id=workspace.id,
            title="架构决策",
            content="过滤验证 架构决策 选型取舍",
            type="decision",
            confidence=0.7,
            embedding=[0.9, 0.1],
        )
        mem_fact = Memory(
            workspace_id=workspace.id,
            title="技术事实",
            content="过滤验证 技术事实 客观描述",
            type="fact",
            confidence=0.3,
            embedding=[0.8, 0.2],
        )
        db.add_all([mem_lesson, mem_decision, mem_fact])
        await db.commit()
        lesson_id, decision_id, fact_id = (
            str(mem_lesson.id),
            str(mem_decision.id),
            str(mem_fact.id),
        )

    retrieval = RetrievalEngine()
    monkeypatch.setattr(search_route, "get_retrieval_engine", lambda: retrieval)
    fake_embedding = SimpleNamespace(generate_embedding=AsyncMock(return_value=[1.0, 0.0]))
    # embedding 由检索引擎管线内部调用，patch 引擎模块而非路由模块
    monkeypatch.setattr(retrieval_engine, "get_embedding_service", lambda: fake_embedding)
    invalidate_workspace_cache("filter-ws")
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
            yield SimpleNamespace(
                http=http,
                lesson=lesson_id,
                decision=decision_id,
                fact=fact_id,
            )
    finally:
        search_route.invalidate_search_cache()
        await engine.dispose()


async def test_search_filters_by_memory_type(filter_env):
    """memory_type 过滤只返回匹配类型。"""
    env = filter_env
    response = await env.http.post(
        "/v1/search", json={"keyword": KEYWORD, "memory_type": "lesson", "limit": 10}
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.lesson}


async def test_search_filters_by_min_confidence(filter_env):
    """min_confidence 过滤只返回 >= 阈值的记忆。"""
    env = filter_env
    response = await env.http.post(
        "/v1/search", json={"keyword": KEYWORD, "min_confidence": 0.7, "limit": 10}
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.lesson, env.decision}


async def test_search_filters_by_filters_dict_type(filter_env):
    """filters 字典的 type 键作为 memory_type 的别名生效。"""
    env = filter_env
    response = await env.http.post(
        "/v1/search",
        json={"keyword": KEYWORD, "filters": {"type": "decision"}, "limit": 10},
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.decision}


async def test_search_filters_combined(filter_env):
    """filters 字典同时含 type 与 min_confidence 时两者都生效。"""
    env = filter_env
    response = await env.http.post(
        "/v1/search",
        json={
            "keyword": KEYWORD,
            "filters": {"type": "lesson", "min_confidence": 0.5},
            "limit": 10,
        },
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.lesson}


async def test_search_filters_cache_key_distinct(filter_env):
    """不同过滤条件产生不同缓存条目（不共享）。"""
    env = filter_env
    # 第一次调用 type=lesson
    response1 = await env.http.post(
        "/v1/search",
        json={"keyword": KEYWORD, "filters": {"type": "lesson"}, "limit": 10},
    )
    assert response1.status_code == 200
    ids1 = {row["id"] for row in response1.json()["results"]}
    assert ids1 == {env.lesson}

    # 第二次调用 type=decision（不应命中 lesson 缓存）
    response2 = await env.http.post(
        "/v1/search",
        json={"keyword": KEYWORD, "filters": {"type": "decision"}, "limit": 10},
    )
    assert response2.status_code == 200
    ids2 = {row["id"] for row in response2.json()["results"]}
    assert ids2 == {env.decision}
    assert ids1 != ids2


async def test_search_threshold_filters_low_similarity(filter_env):
    """threshold 只保留向量相似度达标的候选。

    查询向量 [1,0]：lesson cos=1.0、decision≈0.994、fact≈0.970，
    threshold=0.995 时仅 lesson 存活。
    """
    env = filter_env
    response = await env.http.post(
        "/v1/search", json={"keyword": KEYWORD, "threshold": 0.995, "limit": 10}
    )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.lesson}


async def test_search_threshold_blocks_gibberish(filter_env, monkeypatch):
    """乱码查询在向量路同样无命中时返回空结果，不再返回凑数条目。"""
    monkeypatch.setattr(
        retrieval_engine,
        "get_embedding_service",
        lambda: SimpleNamespace(generate_embedding=AsyncMock(return_value=[0.0, 1.0])),
    )
    env = filter_env
    response = await env.http.post(
        "/v1/search", json={"keyword": "zzzz qqqqq wkwk", "threshold": 0.5, "limit": 10}
    )
    assert response.status_code == 200
    assert response.json()["results"] == []


async def test_search_no_candidates_marks_insufficient(filter_env, monkeypatch):
    """两路均无候选时返回按重要度兜底的列表并显式标记不足。"""
    monkeypatch.setattr(
        retrieval_engine,
        "get_embedding_service",
        lambda: SimpleNamespace(generate_embedding=AsyncMock(return_value=None)),
    )
    env = filter_env
    response = await env.http.post("/v1/search", json={"keyword": "zzzz qqqqq wkwk", "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["insufficient"] is True
    assert body["insufficient_reason"]
    assert body["results"]
    assert all(row["score"] == 0.0 for row in body["results"])


async def test_semantic_mode_applies_filters(filter_env):
    """semantic 模式与 hybrid 共用过滤链（仅向量路召回）。"""
    env = filter_env
    response = await env.http.post(
        "/v1/search",
        json={"keyword": KEYWORD, "mode": "semantic", "memory_type": "lesson", "limit": 10},
    )
    assert response.status_code == 200, response.text
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {env.lesson}


async def test_invalid_mode_rejected(filter_env):
    env = filter_env
    response = await env.http.post("/v1/search", json={"keyword": KEYWORD, "mode": "vector"})
    assert response.status_code == 422
