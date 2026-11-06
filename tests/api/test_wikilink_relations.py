"""PATCH 记忆正文时同步 [[标题]] 关系边。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from packages.domain.models import Memory, MemoryRelation


async def test_patch_content_creates_and_removes_wikilink_edge(client, db_session):
    ws = await client.post("/v1/workspaces", json={"name": "wikilink-api"})
    ws_id = uuid.UUID(ws.json()["id"])
    target_id, source_id = uuid.uuid4(), uuid.uuid4()
    db_session.add_all(
        [
            Memory(
                id=target_id,
                workspace_id=ws_id,
                title="连接池配置",
                content="max_connections=20",
                type="fact",
                status="active",
            ),
            Memory(
                id=source_id,
                workspace_id=ws_id,
                title="排查手册",
                content="先看日志",
                type="fact",
                status="active",
            ),
        ]
    )
    await db_session.flush()

    patched = await client.patch(
        f"/v1/memories/{source_id}",
        json={
            "content": "排查时先读 [[连接池配置]] 再动手调整参数，避免走弯路",
            "change_summary": "补双链",
        },
    )
    assert patched.status_code == 200, patched.text

    rows = (
        (
            await db_session.execute(
                select(MemoryRelation).where(MemoryRelation.source_memory_id == source_id)
            )
        )
        .scalars()
        .all()
    )
    assert [(rel.target_memory_id, rel.created_by) for rel in rows] == [(target_id, "wikilink")]

    cleared = await client.patch(
        f"/v1/memories/{source_id}",
        json={
            "content": "排查时先读日志再动手调整参数，避免走弯路和误判",
            "change_summary": "去掉双链",
        },
    )
    assert cleared.status_code == 200, cleared.text
    rows = (
        (
            await db_session.execute(
                select(MemoryRelation).where(MemoryRelation.source_memory_id == source_id)
            )
        )
        .scalars()
        .all()
    )
    assert rows == []
