"""知识图谱接口：TopN 节点、孤立点、来源标记与截断标记。"""

from __future__ import annotations

from datetime import datetime

from packages.domain.models import Memory, MemoryRelation, ReviewSchedule, Workspace


async def test_graph_includes_isolated_nodes_and_relation_source(client, db_session):
    ws = Workspace(name="graph-ws")
    db_session.add(ws)
    await db_session.flush()
    a = Memory(workspace_id=ws.id, title="A", content="知识内容" * 20, type="fact")
    b = Memory(workspace_id=ws.id, title="B", content="知识内容" * 20, type="fact")
    lonely = Memory(workspace_id=ws.id, title="Lonely", content="知识内容" * 20, type="fact")
    db_session.add_all([a, b, lonely])
    await db_session.flush()
    db_session.add(
        MemoryRelation(
            source_memory_id=a.id,
            target_memory_id=b.id,
            relation_type="related",
            confidence=0.9,
            created_by="auto",
            source="similarity:0.90",
        )
    )
    await db_session.commit()

    resp = await client.get("/v1/graph", params={"workspace_id": "graph-ws", "limit": 10})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    by_id = {node["id"]: node for node in data["nodes"]}
    # 孤立记忆也要出现在图里（旧实现只返回边端点）
    assert str(lonely.id) in by_id
    assert by_id[str(lonely.id)]["is_isolated"] is True
    assert by_id[str(a.id)]["degree"] == 1
    assert data["total_active"] == 3
    assert data["truncated"] is False
    assert data["total_edges"] == 1
    assert data["edges"][0]["created_by"] == "auto"


async def test_graph_limit_keeps_highest_degree_nodes_and_marks_truncated(client, db_session):
    ws = Workspace(name="graph-top")
    db_session.add(ws)
    await db_session.flush()
    memories = [
        Memory(workspace_id=ws.id, title=f"M{i}", content="知识内容" * 20, type="fact")
        for i in range(11)
    ]
    db_session.add_all(memories)
    await db_session.flush()
    db_session.add(
        MemoryRelation(
            source_memory_id=memories[0].id,
            target_memory_id=memories[1].id,
            relation_type="related",
            confidence=0.9,
        )
    )
    await db_session.commit()

    resp = await client.get("/v1/graph", params={"workspace_id": "graph-top", "limit": 10})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_active"] == 11
    assert len(data["nodes"]) == 10
    assert data["truncated"] is True
    # 度数最高的两条保留
    ids = {node["id"] for node in data["nodes"]}
    assert str(memories[0].id) in ids
    assert str(memories[1].id) in ids


async def test_graph_without_workspace_aggregates_all(client, db_session):
    alpha = Workspace(name="graph-all-alpha")
    beta = Workspace(name="graph-all-beta")
    db_session.add_all([alpha, beta])
    await db_session.flush()
    a = Memory(workspace_id=alpha.id, title="A", content="知识内容" * 20, type="fact")
    b = Memory(workspace_id=beta.id, title="B", content="知识内容" * 20, type="fact")
    superseded = Memory(
        workspace_id=beta.id,
        title="Superseded",
        content="知识内容" * 20,
        type="fact",
        status="superseded",
    )
    db_session.add_all([a, b, superseded])
    await db_session.commit()

    resp = await client.get("/v1/graph", params={"limit": 10})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    ids = {node["id"] for node in data["nodes"]}
    assert ids == {str(a.id), str(b.id)}
    assert data["total_active"] == 2
    assert data["truncated"] is False


async def test_graph_nodes_include_review_mastery(client, db_session):
    ws = Workspace(name="graph-mastery")
    db_session.add(ws)
    await db_session.flush()
    reviewed = Memory(workspace_id=ws.id, title="Reviewed", content="知识内容" * 20, type="fact")
    leech = Memory(workspace_id=ws.id, title="Leech", content="知识内容" * 20, type="fact")
    db_session.add_all([reviewed, leech])
    await db_session.flush()
    db_session.add_all(
        [
            ReviewSchedule(
                workspace_id=ws.id,
                memory_id=reviewed.id,
                ease_factor=2.5,
                interval_days=6,
                repetitions=3,
                next_review=datetime(2026, 1, 10),
                total_reviews=5,
            ),
            ReviewSchedule(
                workspace_id=ws.id,
                memory_id=leech.id,
                ease_factor=1.3,
                interval_days=1,
                repetitions=0,
                next_review=datetime(2026, 1, 1),
                total_reviews=4,
                lapse_streak=3,
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/v1/graph", params={"workspace_id": "graph-mastery", "limit": 10})
    assert resp.status_code == 200, resp.text
    by_id = {node["id"]: node for node in resp.json()["nodes"]}

    assert by_id[str(reviewed.id)]["mastery_level"] == "familiar"
    assert by_id[str(reviewed.id)]["next_review"] == "2026-01-10T00:00:00"
    assert by_id[str(reviewed.id)]["leech"] is False
    assert by_id[str(leech.id)]["mastery_level"] == "new"
    assert by_id[str(leech.id)]["leech"] is True
    assert by_id[str(leech.id)]["lapse_streak"] == 3
