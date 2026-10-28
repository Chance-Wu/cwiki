"""useful 反馈应写入 cited 使用流水，为 utility 的 agent_usage 提供信号。"""

from __future__ import annotations

from sqlalchemy import select

from packages.domain.models import Memory, MemoryUsage, Workspace


async def _make_memory(db_session, name: str) -> Memory:
    ws = Workspace(name=name)
    db_session.add(ws)
    await db_session.flush()
    mem = Memory(workspace_id=ws.id, title="反馈信号", content="知识内容" * 20, type="fact")
    db_session.add(mem)
    await db_session.commit()
    return mem


async def test_useful_feedback_records_cited_usage(client, db_session):
    mem = await _make_memory(db_session, "feedback-signal")

    resp = await client.post(
        "/v1/feedback",
        json={
            "memory_id": str(mem.id),
            "workspace_id": "feedback-signal",
            "feedback_type": "useful",
            "source_type": "agent",
        },
    )
    assert resp.status_code == 201, resp.text

    stages = (
        (await db_session.execute(select(MemoryUsage.stage).where(MemoryUsage.memory_id == mem.id)))
        .scalars()
        .all()
    )
    assert "cited" in stages


async def test_not_useful_feedback_does_not_record_cited(client, db_session):
    mem = await _make_memory(db_session, "feedback-negative")

    resp = await client.post(
        "/v1/feedback",
        json={
            "memory_id": str(mem.id),
            "workspace_id": "feedback-negative",
            "feedback_type": "not_useful",
            "source_type": "agent",
        },
    )
    assert resp.status_code == 201, resp.text

    stages = (
        (await db_session.execute(select(MemoryUsage.stage).where(MemoryUsage.memory_id == mem.id)))
        .scalars()
        .all()
    )
    assert "cited" not in stages
