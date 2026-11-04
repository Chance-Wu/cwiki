"""健康摘要分布闭合：total 必须等于各档之和，冲突记忆不能漏计。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from apps.api.routes.memory_status import invalidate_memory_status_caches
from packages.domain.models import (
    Memory,
    MemoryConflict,
    MemoryLifecycleEvent,
    Workspace,
)


async def test_health_summary_distribution_closes_with_conflicted(client, db_session):
    ws = Workspace(name="health-close")
    db_session.add(ws)
    await db_session.flush()
    ok = Memory(workspace_id=ws.id, title="正常记忆", content="知识内容" * 20, type="fact")
    conflicted = Memory(workspace_id=ws.id, title="冲突记忆", content="知识内容" * 20, type="fact")
    db_session.add_all([ok, conflicted])
    await db_session.flush()
    db_session.add(
        MemoryConflict(
            workspace_id=ws.id,
            memory_id=conflicted.id,
            conflict_type="contradiction",
            status="open",
        )
    )
    await db_session.commit()
    invalidate_memory_status_caches()

    resp = await client.get("/v1/health-summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["distribution"]["conflicted"] >= 1
    assert sum(data["distribution"].values()) == data["total"]
    assert isinstance(data["reasons"], list)


async def test_health_summary_filters_by_workspace(client, db_session):
    alpha = Workspace(name="health-alpha")
    beta = Workspace(name="health-beta")
    db_session.add_all([alpha, beta])
    await db_session.flush()
    db_session.add_all(
        [
            Memory(workspace_id=alpha.id, title="A", content="知识内容" * 20, type="fact"),
            Memory(workspace_id=beta.id, title="B1", content="知识内容" * 20, type="fact"),
            Memory(workspace_id=beta.id, title="B2", content="知识内容" * 20, type="fact"),
        ]
    )
    await db_session.commit()
    invalidate_memory_status_caches()

    alpha_resp = await client.get("/v1/health-summary", params={"workspace_id": "health-alpha"})
    beta_resp = await client.get("/v1/health-summary", params={"workspace_id": "health-beta"})
    assert alpha_resp.json()["total"] == 1
    assert beta_resp.json()["total"] == 2


async def test_status_change_writes_lifecycle_event(client, db_session):
    """状态变更写 event_type=status_changed，并记录新旧状态。"""
    ws = Workspace(name="status-ws")
    db_session.add(ws)
    await db_session.flush()
    mem = Memory(workspace_id=ws.id, title="待弃用", content="知识内容" * 20, type="fact")
    db_session.add(mem)
    await db_session.commit()

    resp = await client.patch(f"/v1/memories/{mem.id}", json={"status": "deprecated"})
    assert resp.status_code == 200, resp.text

    events = (
        await db_session.execute(
            select(MemoryLifecycleEvent.event_type, MemoryLifecycleEvent.metadata_json).where(
                MemoryLifecycleEvent.memory_id == mem.id
            )
        )
    ).all()
    status_event = next(
        metadata for event_type, metadata in events if event_type == "status_changed"
    )
    assert json.loads(status_event) == {
        "old_status": "active",
        "new_status": "deprecated",
        "version": mem.version,
        "reason": None,
        "actor_type": "agent",
        "actor_id": "test-agent",
    }


async def test_content_update_records_reason_and_version(client, db_session):
    ws = Workspace(name="edit-audit-ws")
    db_session.add(ws)
    await db_session.flush()
    memory = Memory(workspace_id=ws.id, title="旧结论", content="原始正文" * 20, type="fact")
    db_session.add(memory)
    await db_session.commit()
    response = await client.patch(
        f"/v1/memories/{memory.id}",
        json={
            "content": "修正后的完整正文" * 20,
            "expected_version": memory.version,
            "change_summary": "根据新来源修正",
            "reason": "备用原因",
        },
    )
    assert response.status_code == 200, response.text
    event = (
        await db_session.execute(
            select(MemoryLifecycleEvent).where(
                MemoryLifecycleEvent.memory_id == memory.id,
                MemoryLifecycleEvent.event_type == "updated",
            )
        )
    ).scalar_one()
    assert json.loads(event.metadata_json) == {
        "version": response.json()["version"],
        "reason": "根据新来源修正",
        "actor_type": "agent",
        "actor_id": "test-agent",
    }


async def test_restore_historical_content_creates_new_audited_version(client, db_session):
    ws = Workspace(name="restore-audit-ws")
    db_session.add(ws)
    await db_session.flush()
    memory = Memory(workspace_id=ws.id, title="初始标题", content="初始事实正文" * 20, type="fact")
    db_session.add(memory)
    await db_session.commit()
    original_content = memory.content
    edited = await client.patch(
        f"/v1/memories/{memory.id}",
        json={"content": "新版本正文" * 20, "expected_version": memory.version},
    )
    assert edited.status_code == 200, edited.text
    history = await client.get(f"/v1/memories/{memory.id}/versions")
    assert history.status_code == 200, history.text
    snapshot = next(v for v in history.json() if v["content"] == original_content)
    restored = await client.patch(
        f"/v1/memories/{memory.id}",
        json={
            "content": snapshot["content"],
            "expected_version": edited.json()["version"],
            "change_summary": "人工复核后恢复历史正文",
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["content"].strip() == original_content.strip()
    assert restored.json()["version"] == edited.json()["version"] + 1
    after = await client.get(f"/v1/memories/{memory.id}/versions")
    assert {v["content"].strip() for v in after.json()} >= {
        original_content.strip(),
        edited.json()["content"].strip(),
    }


async def test_lifecycle_returns_latest_events_with_total_count(client, db_session):
    ws = Workspace(name="lifecycle-window-ws")
    db_session.add(ws)
    await db_session.flush()
    memory = Memory(workspace_id=ws.id, title="时间线", content="生命周期内容" * 20, type="fact")
    db_session.add(memory)
    await db_session.flush()
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add_all(
        [
            MemoryLifecycleEvent(
                memory_id=memory.id,
                event_type=f"event_{index}",
                created_at=base_time + timedelta(seconds=index),
            )
            for index in range(105)
        ]
    )
    await db_session.commit()

    resp = await client.get(f"/v1/memories/{memory.id}/lifecycle")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_count"] == 105
    assert len(body["timeline"]) == 100
    assert body["timeline"][0]["event_type"] == "event_5"
    assert body["timeline"][-1]["event_type"] == "event_104"


async def test_conflict_resolution_writes_lifecycle_event(client, db_session):
    ws = Workspace(name="conflict-audit-ws")
    db_session.add(ws)
    await db_session.flush()
    memory = Memory(workspace_id=ws.id, title="事实记忆", content="事实内容" * 20, type="fact")
    db_session.add(memory)
    await db_session.flush()
    conflict = MemoryConflict(
        workspace_id=ws.id,
        memory_id=memory.id,
        conflict_type="contradiction",
        description="新旧事实矛盾",
        status="open",
    )
    db_session.add(conflict)
    await db_session.commit()

    resp = await client.post(
        f"/v1/conflicts/{conflict.id}/resolve",
        json={"resolution": "以有来源的新事实为准"},
    )

    assert resp.status_code == 200, resp.text
    result = await db_session.execute(
        select(MemoryLifecycleEvent.event_type, MemoryLifecycleEvent.metadata_json).where(
            MemoryLifecycleEvent.memory_id == memory.id
        )
    )
    event_type, metadata_json = result.one()
    assert event_type == "conflict_resolved"
    assert json.loads(metadata_json) == {
        "conflict_id": str(conflict.id),
        "resolution": "以有来源的新事实为准",
        "actor_type": "agent",
        "actor_id": "test-agent",
    }
    await db_session.refresh(memory)
    assert memory.status == "active"  # conflict resolution never implicitly changes status
    retry = await client.post(
        f"/v1/conflicts/{conflict.id}/resolve", json={"resolution": "重复处理"}
    )
    assert retry.status_code == 409
    events = (
        (
            await db_session.execute(
                select(MemoryLifecycleEvent).where(
                    MemoryLifecycleEvent.memory_id == memory.id,
                    MemoryLifecycleEvent.event_type == "conflict_resolved",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
