"""正式记忆合并端点测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from packages.domain.models import Evidence, Memory, MemoryRelation, ReviewSchedule

SOURCE_CONTENT = "SQLite WAL 模式读写不互相阻塞，但需要定期 checkpoint，否则 -wal 会持续增长。"
TARGET_CONTENT = "SQLite 开启 WAL 后读写不再互相阻塞，务必定期 checkpoint 控制 -wal 体积。"


async def _workspace(client, name: str) -> uuid.UUID:
    response = await client.post("/v1/workspaces", json={"name": name})
    return uuid.UUID(response.json()["id"])


def _memory(
    workspace_id: uuid.UUID,
    title: str,
    content: str,
    *,
    tags: list[str] | None = None,
    status: str = "active",
) -> Memory:
    return Memory(
        workspace_id=workspace_id,
        title=title,
        content=content,
        type="fact",
        status=status,
        tags=tags,
    )


async def _merge(client, source_id, target_id, merge_content: bool = False):
    return await client.post(
        "/v1/memories/merge",
        json={
            "source_id": str(source_id),
            "target_id": str(target_id),
            "merge_content": merge_content,
        },
    )


async def test_merge_supersedes_source_and_unions_tags(client, db_session):
    ws_id = await _workspace(client, "merge-basic")
    source = _memory(ws_id, "WAL checkpoint", SOURCE_CONTENT, tags=["sqlite", "pinned"])
    target = _memory(ws_id, "WAL 实践", TARGET_CONTENT, tags=["sqlite", "wal"])
    db_session.add_all([source, target])
    await db_session.flush()

    response = await _merge(client, source.id, target.id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["merged"] is True
    assert set(data["tags"]) == {"sqlite", "pinned", "wal"}

    await db_session.refresh(source)
    await db_session.refresh(target)
    assert source.status == "superseded"
    assert set(target.tags or []) == {"sqlite", "pinned", "wal"}
    # 默认不改写目标正文
    assert target.content == TARGET_CONTENT


async def test_merge_moves_relations_and_drops_self_loops(client, db_session):
    ws_id = await _workspace(client, "merge-relations")
    source = _memory(ws_id, "来源", SOURCE_CONTENT)
    target = _memory(ws_id, "目标", TARGET_CONTENT)
    other = _memory(ws_id, "第三方", "另一个与合并无关的记忆正文，用来验证入边迁移。")
    db_session.add_all([source, target, other])
    await db_session.flush()
    db_session.add_all(
        [
            MemoryRelation(
                id=uuid.uuid4(),
                source_memory_id=source.id,
                target_memory_id=other.id,
                relation_type="related",
                created_by="manual",
            ),
            # 来源 → 目标：合并后变成自环，应被丢弃
            MemoryRelation(
                id=uuid.uuid4(),
                source_memory_id=source.id,
                target_memory_id=target.id,
                relation_type="related",
                created_by="manual",
            ),
        ]
    )
    await db_session.flush()

    response = await _merge(client, source.id, target.id)
    assert response.status_code == 200, response.text
    assert response.json()["relations_dropped"] == 1

    rows = (
        (
            await db_session.execute(
                select(MemoryRelation).where(
                    MemoryRelation.target_memory_id == other.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [row.source_memory_id for row in rows] == [target.id]


async def test_merge_migrates_evidence_and_drops_review_schedule(client, db_session):
    ws_id = await _workspace(client, "merge-evidence")
    source = _memory(ws_id, "带证据", SOURCE_CONTENT)
    target = _memory(ws_id, "接收方", TARGET_CONTENT)
    db_session.add_all([source, target])
    await db_session.flush()
    evidence = Evidence(
        id=uuid.uuid4(),
        memory_id=source.id,
        source_type="conversation",
        content="来自某次会话的原始记录",
    )
    db_session.add(evidence)
    db_session.add(
        ReviewSchedule(
            id=uuid.uuid4(),
            memory_id=source.id,
            workspace_id=ws_id,
            next_review=datetime.now(UTC),
            interval_days=1,
            ease_factor=2.5,
            repetitions=0,
        )
    )
    await db_session.flush()

    response = await _merge(client, source.id, target.id)
    assert response.status_code == 200, response.text
    assert response.json()["evidences_moved"] == 1

    await db_session.refresh(evidence)
    assert evidence.memory_id == target.id
    schedules = (
        (
            await db_session.execute(
                select(ReviewSchedule).where(ReviewSchedule.memory_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert schedules == []


async def test_merge_content_appends_source_section(client, db_session):
    ws_id = await _workspace(client, "merge-content")
    source = _memory(ws_id, "旧结论", SOURCE_CONTENT)
    target = _memory(ws_id, "新结论", TARGET_CONTENT)
    db_session.add_all([source, target])
    await db_session.flush()

    response = await _merge(client, source.id, target.id, merge_content=True)
    assert response.status_code == 200, response.text
    assert response.json()["needs_reembedding"] is True

    await db_session.refresh(target)
    assert target.content.startswith(TARGET_CONTENT)
    assert "## 合并自《旧结论》" in target.content
    assert SOURCE_CONTENT in target.content
    # 正文变了，向量置空等待重建
    assert target.embedding is None


async def test_merge_rejects_self_and_cross_workspace(client, db_session):
    ws_a = await _workspace(client, "merge-ws-a")
    ws_b = await _workspace(client, "merge-ws-b")
    source = _memory(ws_a, "A 区记忆", SOURCE_CONTENT)
    target = _memory(ws_b, "B 区记忆", TARGET_CONTENT)
    db_session.add_all([source, target])
    await db_session.flush()

    same = await _merge(client, source.id, source.id)
    assert same.status_code == 400
    assert "不能把记忆合并到自身" in same.json()["detail"]

    cross = await _merge(client, source.id, target.id)
    assert cross.status_code == 400
    assert "只能合并同一工作区内的记忆" in cross.json()["detail"]


async def test_merge_rejects_missing_and_inactive(client, db_session):
    ws_id = await _workspace(client, "merge-invalid")
    active = _memory(ws_id, "活跃记忆", SOURCE_CONTENT)
    archived = _memory(ws_id, "已归档", TARGET_CONTENT, status="archived")
    db_session.add_all([active, archived])
    await db_session.flush()

    missing = await _merge(client, uuid.uuid4(), active.id)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "记忆不存在"

    inactive = await _merge(client, archived.id, active.id)
    assert inactive.status_code == 400
    assert inactive.json()["detail"] == "只有 active 记忆可以合并"
