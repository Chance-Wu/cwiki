"""健康摘要分布闭合：total 必须等于各档之和，冲突记忆不能漏计。"""

from __future__ import annotations

from apps.api.routes.memory_status import invalidate_memory_status_caches
from packages.domain.models import Memory, MemoryConflict, Workspace


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
