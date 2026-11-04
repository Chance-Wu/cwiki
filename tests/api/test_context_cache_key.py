"""上下文检索缓存键回归：不同 project/session/过滤条件不能命中同一条缓存。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from apps.api.routes.context import _cache_key
from packages.domain.models import Memory, MemoryUsage
from packages.domain.schemas import ContextRequest
from packages.retrieval.context.token_counter import estimate_tokens


def _request(**overrides) -> ContextRequest:
    base = {
        "workspace_id": "ws",
        "agent_id": uuid.UUID(int=1),
        "session_id": uuid.UUID(int=2),
        "keyword": "缓存键",
    }
    base.update(overrides)
    return ContextRequest(**base)


def test_cache_key_separates_projects_and_sessions() -> None:
    base_key = _cache_key(_request())
    assert base_key != _cache_key(_request(project_id=uuid.uuid4()))
    assert base_key != _cache_key(_request(session_id=uuid.uuid4()))
    assert base_key != _cache_key(_request(mode="hybrid"))
    assert base_key != _cache_key(_request(max_tokens=8000))
    assert base_key != _cache_key(_request(event_types=["error"]))


def test_cache_key_stable_for_identical_requests() -> None:
    assert _cache_key(_request()) == _cache_key(_request())


async def test_context_records_only_final_delivery_selection(client, db_session, monkeypatch):
    import apps.api.routes.context as context_module

    ws_id = uuid.UUID((await client.post("/v1/workspaces", json={"name": "delivery"})).json()["id"])
    memories = [
        Memory(workspace_id=ws_id, title=f"item-{i}", content=f"distinct-content-{i}", type="fact")
        for i in range(2)
    ]
    db_session.add_all(memories)
    await db_session.flush()
    engine = SimpleNamespace(
        retrieve=AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(m.id),
                        "title": m.title,
                        "content": m.content,
                        "valid_to": datetime(2000, 1, 1, tzinfo=UTC) if m is memories[0] else None,
                        "type": "fact",
                        "confidence": 0.9,
                        "score": 0.8,
                    }
                    for m in memories
                ],
                "context": "\n".join(m.content for m in memories),
                "sources": [{"memory_id": str(m.id), "title": m.title} for m in memories],
                "total": 2,
            }
        )
    )
    monkeypatch.setattr(context_module, "get_retrieval_engine", lambda: engine)
    monkeypatch.setattr(context_module, "_get_agent_profile_hints", AsyncMock(return_value=None))
    monkeypatch.setattr(
        context_module, "batch_compute_freshness", AsyncMock(return_value=({}, {}, {}))
    )

    async def keep(items, *args, **kwargs):
        return items

    monkeypatch.setattr(context_module, "rerank_context_results", keep)
    monkeypatch.setattr(context_module.settings, "stale_filter_mode", "hard")
    body = {
        "workspace_id": str(ws_id),
        "agent_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "keyword": "delivery",
    }
    response = await client.post("/v1/context", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["memory_id"] for item in data["items"]] == [str(memories[1].id)]
    assert data["sources"] == [f"memory:{memories[1].id}"]
    assert [c["memory_id"] for c in data["citations"]] == [str(memories[1].id)]
    assert memories[0].content not in data["context"]
    assert memories[1].content in data["context"]
    assert data["total"] == 1
    assert f'id="{memories[1].id}"' in data["context"]
    assert "</memory>" in data["context"]
    assert estimate_tokens(data["context"]) <= 2000
    rows = (
        (
            await db_session.execute(
                select(MemoryUsage).where(
                    MemoryUsage.workspace_id == ws_id, MemoryUsage.stage == "used"
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(row.memory_id, row.position) for row in rows] == [(memories[1].id, 0)]
    cached = await client.post("/v1/context", json=body)
    assert cached.status_code == 200
    assert cached.json() == data
    engine.retrieve.assert_awaited_once()
    cached_rows = (
        (
            await db_session.execute(
                select(MemoryUsage).where(
                    MemoryUsage.workspace_id == ws_id, MemoryUsage.stage == "used"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(cached_rows) == 1  # cache reuse does not inflate observations


async def test_context_assembler_preserves_cjk_budget(client, db_session, monkeypatch):
    import apps.api.routes.context as context_module

    ws_id = uuid.UUID(
        (await client.post("/v1/workspaces", json={"name": "cjk-budget"})).json()["id"]
    )
    memory = Memory(
        workspace_id=ws_id, title="中文知识", content="中文知识说明。" * 1000, type="fact"
    )
    db_session.add(memory)
    await db_session.flush()
    engine = SimpleNamespace(
        retrieve=AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(memory.id),
                        "title": memory.title,
                        "content": memory.content,
                        "type": "fact",
                        "confidence": 0.9,
                        "score": 0.9,
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(context_module, "get_retrieval_engine", lambda: engine)
    monkeypatch.setattr(context_module, "_get_agent_profile_hints", AsyncMock(return_value=None))
    monkeypatch.setattr(
        context_module, "batch_compute_freshness", AsyncMock(return_value=({}, {}, {}))
    )

    # Oversized raw content must reach the assembler for compression, rather than
    # being discarded by a len(content)//4 prefilter.
    response = await client.post(
        "/v1/context",
        json={
            "workspace_id": str(ws_id),
            "agent_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "keyword": "中文知识",
            "max_tokens": 1000,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["items"]
    assert estimate_tokens(data["context"]) <= 1000
    assert data["items"][0]["content"] in data["context"]
    assert len(data["items"][0]["content"]) < len(memory.content)
