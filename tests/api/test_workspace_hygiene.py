"""工作区治理 API 测试：脏名预览 + 归并迁移。"""

from __future__ import annotations

import uuid

import httpx


async def _mk_workspace(client: httpx.AsyncClient, name: str) -> str:
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_hygiene_preview_lists_only_dirty_names(client, db_session):
    from packages.domain.models import AgentSession, Memory, SessionNote

    dirty_hash = await _mk_workspace(client, "179cf7e8")
    await _mk_workspace(client, "C--Users-Administrator--qoder")
    await _mk_workspace(client, "cwiki")

    memory_id = uuid.uuid4()
    db_session.add(
        Memory(
            id=memory_id,
            workspace_id=uuid.UUID(dirty_hash),
            title="哈希工作区里的记忆",
            content="正文",
            type="fact",
        )
    )
    session_id = uuid.uuid4()
    db_session.add(AgentSession(id=session_id, workspace_id=uuid.UUID(dirty_hash), agent="qoder"))
    db_session.add(
        SessionNote(
            id=uuid.uuid4(),
            session_id=session_id,
            workspace_id=uuid.UUID(dirty_hash),
            content="note",
            signal_type="issue",
        )
    )
    await db_session.flush()

    resp = await client.get("/v1/workspaces/hygiene/preview")
    assert resp.status_code == 200
    data = resp.json()
    names = [w["name"] for w in data["workspaces"]]
    assert "179cf7e8" in names
    assert "C--Users-Administrator--qoder" in names
    assert "cwiki" not in names
    entry = next(w for w in data["workspaces"] if w["name"] == "179cf7e8")
    assert entry["memories"] == 1
    assert entry["notes"] == 1


async def test_hygiene_merge_moves_memories_and_deletes_source(client, db_session):
    from sqlalchemy import select

    from packages.domain.models import Memory

    source = await _mk_workspace(client, "5bf205f7")
    target = await _mk_workspace(client, "msp-caa")

    memory_id = uuid.uuid4()
    db_session.add(
        Memory(
            id=memory_id,
            workspace_id=uuid.UUID(source),
            title="待迁移",
            content="正文",
            type="lesson",
            status="active",
        )
    )
    await db_session.flush()

    resp = await client.post(
        "/v1/workspaces/hygiene/merge",
        json={"source_workspace_id": source, "target_workspace_id": target},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["memories_moved"] == 1
    assert data["target_workspace_id"] == target

    moved = (await db_session.execute(select(Memory).where(Memory.id == memory_id))).scalar_one()
    assert str(moved.workspace_id) == target

    gone = await client.get(f"/v1/workspaces/{source}")
    assert gone.status_code == 404


async def test_hygiene_merge_rejects_same_workspace(client):
    ws = await _mk_workspace(client, "87c03549")
    resp = await client.post(
        "/v1/workspaces/hygiene/merge",
        json={"source_workspace_id": ws, "target_workspace_id": ws},
    )
    assert resp.status_code == 400
