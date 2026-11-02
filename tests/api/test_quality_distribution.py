"""质量分布接口：单工作区口径与跨工作区汇总口径。"""

from __future__ import annotations

from apps.api.routes.memory_status import invalidate_memory_status_caches
from packages.domain.models import Memory, Workspace


async def test_stats_type_distribution_follows_status(client, db_session, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "apps.api.routes.file_memories.get_memory_indexer",
        lambda: SimpleNamespace(
            vector_index=SimpleNamespace(size=lambda: 0, index_path="vectors.npz")
        ),
    )
    ws = Workspace(name="stats-status-ws")
    db_session.add(ws)
    await db_session.flush()
    db_session.add_all(
        [
            Memory(workspace_id=ws.id, title="A", content="知识内容" * 20, type="fact"),
            Memory(
                workspace_id=ws.id,
                title="B",
                content="知识内容" * 20,
                type="decision",
                status="superseded",
            ),
        ]
    )
    await db_session.commit()

    all_resp = await client.get("/v1/file-memories/stats")
    assert all_resp.status_code == 200, all_resp.text
    assert all_resp.json()["file_count"] == 2
    assert all_resp.json()["type_distribution"] == {"fact": 1, "decision": 1}

    superseded_resp = await client.get("/v1/file-memories/stats", params={"status": "superseded"})
    assert superseded_resp.status_code == 200, superseded_resp.text
    assert superseded_resp.json()["file_count"] == 1
    assert superseded_resp.json()["type_distribution"] == {"decision": 1}


async def test_quality_distribution_all_workspaces(client, db_session):
    alpha = Workspace(name="quality-alpha")
    beta = Workspace(name="quality-beta")
    db_session.add_all([alpha, beta])
    await db_session.flush()
    db_session.add_all(
        [
            Memory(workspace_id=alpha.id, title="A1", content="知识内容" * 20, type="fact"),
            Memory(workspace_id=alpha.id, title="A2", content="知识内容" * 20, type="fact"),
            Memory(workspace_id=beta.id, title="B1", content="知识内容" * 20, type="fact"),
            Memory(
                workspace_id=beta.id,
                title="B2",
                content="知识内容" * 20,
                type="fact",
                status="superseded",
            ),
        ]
    )
    await db_session.commit()
    invalidate_memory_status_caches()

    all_resp = await client.get("/v1/quality-distribution")
    assert all_resp.status_code == 200, all_resp.text
    all_data = all_resp.json()
    assert all_data["total"] == 3
    assert all_data["truncated"] is False
    assert sum(all_data["confidence_distribution"].values()) == 3

    alpha_resp = await client.get(
        "/v1/quality-distribution", params={"workspace_id": "quality-alpha"}
    )
    assert alpha_resp.status_code == 200, alpha_resp.text
    alpha_data = alpha_resp.json()
    assert alpha_data["total"] == 2
    assert sum(alpha_data["importance_distribution"].values()) == 2
