"""本周学习回顾聚合测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from packages.domain.models import (
    AgentSession,
    Memory,
    MemoryConflict,
    MemoryUsage,
    RetrievalTrace,
    ReviewHistory,
    SessionNote,
)


async def test_weekly_review_aggregates_learning_signals(client, db_session):
    ws = await client.post("/v1/workspaces", json={"name": "weekly-test"})
    ws_id = ws.json()["id"]
    memory_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)

    db_session.add(
        Memory(
            id=memory_id,
            workspace_id=uuid.UUID(ws_id),
            title="本周新增记忆",
            content="完整正文",
            type="lesson",
            status="active",
        )
    )
    db_session.add(
        AgentSession(
            id=session_id,
            workspace_id=uuid.UUID(ws_id),
            agent="qoder",
            started_at=now,
        )
    )
    db_session.add(
        ReviewHistory(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(ws_id),
            memory_id=memory_id,
            quality=4,
            ease_factor_before=2.5,
            interval_before=1,
            repetitions_before=0,
            next_review_before=now,
            mastery_level_before="new",
            ease_factor_after=2.6,
            interval_after=3,
            repetitions_after=1,
            next_review_after=now + timedelta(days=3),
            mastery_level_after="proficient",
            reviewed_at=now,
        )
    )
    db_session.add(
        MemoryUsage(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(ws_id),
            memory_id=memory_id,
            stage="used",
            created_at=now,
        )
    )
    db_session.add(
        SessionNote(
            id=uuid.uuid4(),
            session_id=session_id,
            workspace_id=uuid.UUID(ws_id),
            content="待整理",
            signal_type="issue",
        )
    )
    stale_id = uuid.uuid4()
    db_session.add(
        Memory(
            id=stale_id,
            workspace_id=uuid.UUID(ws_id),
            title="过期记忆",
            content="已过时内容",
            type="fact",
            status="active",
            valid_to=now - timedelta(days=1),
        )
    )
    db_session.add(
        MemoryConflict(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(ws_id),
            memory_id=stale_id,
            conflict_type="contradiction",
            description="两条记忆结论相反",
            status="open",
        )
    )
    db_session.add(
        RetrievalTrace(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(ws_id),
            keyword="部署步骤",
            returned_count=0,
            candidate_count=0,
        )
    )
    db_session.add(
        RetrievalTrace(
            id=uuid.uuid4(),
            workspace_id=uuid.UUID(ws_id),
            keyword="部署步骤",
            returned_count=2,
            candidate_count=5,
        )
    )
    await db_session.flush()

    resp = await client.get("/v1/review/weekly", params={"workspace_id": ws_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["new_memories"] == 2  # 本周新增 1 条 + 过期测试记忆 1 条
    assert data["reviewed"] == 1
    assert data["avg_quality"] == 4.0
    assert data["mastered_up"] == 1
    assert data["pending_notes"] == 1
    assert data["most_used"][0]["memory_id"] == str(memory_id)
    assert data["most_used"][0]["uses"] == 1
    assert data["most_used"][0]["retrievals"] == 0
    assert data["most_used"][0]["context_uses"] == 1
    assert data["most_used"][0]["citations"] == 0
    assert "success_rate" not in data["most_used"][0]
    # 行动项：未决冲突、过期记忆、知识缺口（无果检索只计一次）
    actions = data["actions"]
    assert len(actions["conflicts"]) == 1
    assert actions["conflicts"][0]["description"] == "两条记忆结论相反"
    assert len(actions["stale_memories"]) == 1
    assert actions["stale_memories"][0]["memory_id"] == str(stale_id)
    assert actions["knowledge_gaps"] == [{"query": "部署步骤", "attempts": 1}]


async def test_weekly_reuse_counts_independent_stages_and_excludes_ineligible_rows(
    client, db_session
):
    ws_id = uuid.UUID((await client.post("/v1/workspaces", json={"name": "reuse"})).json()["id"])
    other_ws = uuid.UUID((await client.post("/v1/workspaces", json={"name": "other"})).json()["id"])
    now = datetime.now(UTC).replace(tzinfo=None)
    ids = {name: uuid.uuid4() for name in ("reuse", "retrieved_only", "inactive", "other")}
    for name, mid in ids.items():
        db_session.add(
            Memory(
                id=mid,
                workspace_id=other_ws if name == "other" else ws_id,
                title=name,
                content="完整记忆正文",
                type="fact",
                status="deprecated" if name == "inactive" else "active",
            )
        )
    await db_session.flush()

    def usage(name, stage, *, days=0, workspace=ws_id):
        db_session.add(
            MemoryUsage(
                id=uuid.uuid4(),
                workspace_id=workspace,
                memory_id=ids[name],
                stage=stage,
                created_at=now + timedelta(days=days),
            )
        )

    for stage in ("retrieved", "retrieved", "used", "cited"):
        usage("reuse", stage)
    usage("reuse", "used", days=-8)
    usage("reuse", "used", days=1)
    usage("reuse", "used", workspace=other_ws)
    for _ in range(10):
        usage("retrieved_only", "retrieved")
    usage("inactive", "used")
    usage("other", "used", workspace=other_ws)
    session_id = uuid.uuid4()
    db_session.add(AgentSession(id=session_id, workspace_id=ws_id, agent="qoder"))
    await db_session.flush()
    db_session.add(
        SessionNote(
            id=uuid.uuid4(),
            session_id=session_id,
            workspace_id=ws_id,
            content="已丢弃笔记",
            signal_type="issue",
            discarded_at=now,
        )
    )
    await db_session.flush()
    response = await client.get("/v1/review/weekly", params={"workspace_id": str(ws_id)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pending_notes"] == 0
    assert data["most_used"] == [
        {
            "memory_id": str(ids["reuse"]),
            "title": "reuse",
            "uses": 2,
            "retrievals": 2,
            "context_uses": 1,
            "citations": 1,
        }
    ]


async def test_weekly_retrieval_gaps_flag_hits_with_zero_delivery(client, db_session):
    """命中多次却零交付的记忆进入召回缺口；命中不足门槛或已有交付的不进。"""
    ws_id = uuid.UUID((await client.post("/v1/workspaces", json={"name": "gaps"})).json()["id"])
    now = datetime.now(UTC).replace(tzinfo=None)
    ids = {name: uuid.uuid4() for name in ("never_used", "used_once", "rare_hit")}
    for name, mid in ids.items():
        db_session.add(
            Memory(
                id=mid,
                workspace_id=ws_id,
                title=name,
                content="完整记忆正文",
                type="fact",
                status="active",
            )
        )
    await db_session.flush()

    def usage(name, stage, *, days=0):
        db_session.add(
            MemoryUsage(
                id=uuid.uuid4(),
                workspace_id=ws_id,
                memory_id=ids[name],
                stage=stage,
                created_at=now - timedelta(days=days),
            )
        )

    for _ in range(5):
        usage("never_used", "retrieved")
    for _ in range(4):
        usage("used_once", "retrieved")
    usage("used_once", "used")
    for _ in range(2):
        usage("rare_hit", "retrieved")
    # 窗口外的命中不计入
    for _ in range(6):
        usage("rare_hit", "retrieved", days=30)
    await db_session.flush()

    response = await client.get("/v1/review/weekly", params={"workspace_id": str(ws_id)})
    assert response.status_code == 200, response.text
    gaps = response.json()["actions"]["retrieval_gaps"]
    assert gaps == [
        {
            "memory_id": str(ids["never_used"]),
            "title": "never_used",
            "retrievals": 5,
            "deliveries": 0,
        }
    ]
