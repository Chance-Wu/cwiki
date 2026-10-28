"""健康摘要分布闭合：total 必须等于各档之和，冲突记忆不能漏计。"""

from __future__ import annotations

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


async def test_archive_status_writes_archived_lifecycle_event(client, db_session):
    """归档动作要写 event_type=archived，演化指标才能统计到。"""
    ws = Workspace(name="archive-ws")
    db_session.add(ws)
    await db_session.flush()
    mem = Memory(workspace_id=ws.id, title="待归档", content="知识内容" * 20, type="fact")
    db_session.add(mem)
    await db_session.commit()

    resp = await client.patch(f"/v1/memories/{mem.id}", json={"status": "archived"})
    assert resp.status_code == 200, resp.text

    event_types = (
        (
            await db_session.execute(
                select(MemoryLifecycleEvent.event_type).where(
                    MemoryLifecycleEvent.memory_id == mem.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert "archived" in event_types

