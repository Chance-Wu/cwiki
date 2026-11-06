"""记忆库内重复检测端点测试。"""

from __future__ import annotations

import uuid

from packages.domain.models import Memory

WAL_CONTENT = (
    "SQLite 开启 WAL 模式后读写不再互相阻塞，但需要定期 checkpoint，"
    "否则 -wal 文件会持续增长到影响提交延迟。"
)
NEAR_WAL_CONTENT = (
    "SQLite 开启 WAL 模式后读写不再互相阻塞，但需要定期 checkpoint，"
    "否则 -wal 文件会持续增长，进而影响提交延迟和磁盘占用。"
)


async def _workspace(client, name: str) -> uuid.UUID:
    response = await client.post("/v1/workspaces", json={"name": name})
    return uuid.UUID(response.json()["id"])


def _memory(workspace_id: uuid.UUID, title: str, content: str) -> Memory:
    return Memory(
        workspace_id=workspace_id,
        title=title,
        content=content,
        type="fact",
        status="active",
    )


async def test_duplicates_endpoint_reports_similar_pairs(client, db_session):
    ws_id = await _workspace(client, "dup-scan")
    similar_a = _memory(ws_id, "SQLite WAL 实践", WAL_CONTENT)
    similar_b = _memory(ws_id, "SQLite WAL 实践注意", NEAR_WAL_CONTENT)
    unrelated = _memory(ws_id, "前端虚拟滚动", "列表超过一千行时要改用虚拟滚动，只渲染可见区域。")
    db_session.add_all([similar_a, similar_b, unrelated])
    await db_session.flush()

    response = await client.get(
        "/v1/memories/duplicates", params={"workspace_id": str(ws_id), "min_similarity": 0.5}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scanned"] == 3
    assert {data["pairs"][0]["left"]["id"], data["pairs"][0]["right"]["id"]} == {
        str(similar_a.id),
        str(similar_b.id),
    }
    assert data["pairs"][0]["similarity"] >= 0.5
    assert all(
        {pair["left"]["id"], pair["right"]["id"]} != {str(unrelated.id)} for pair in data["pairs"]
    )


async def test_duplicates_threshold_excludes_dissimilar(client, db_session):
    ws_id = await _workspace(client, "dup-threshold")
    db_session.add_all(
        [
            _memory(ws_id, "SQLite WAL 实践", WAL_CONTENT),
            _memory(ws_id, "前端虚拟滚动", "列表超过一千行时要改用虚拟滚动，只渲染可见区域。"),
        ]
    )
    await db_session.flush()

    response = await client.get(
        "/v1/memories/duplicates", params={"workspace_id": str(ws_id), "min_similarity": 0.95}
    )
    assert response.status_code == 200, response.text
    assert response.json()["pairs"] == []


async def test_duplicates_only_scans_active_and_requested_workspace(client, db_session):
    mine = await _workspace(client, "dup-mine")
    other = await _workspace(client, "dup-other")
    archived = _memory(mine, "SQLite WAL 实践", WAL_CONTENT)
    archived.status = "deprecated"
    db_session.add_all(
        [
            archived,
            _memory(mine, "SQLite WAL 实践注意", NEAR_WAL_CONTENT),
            _memory(other, "SQLite WAL 补充", WAL_CONTENT),
        ]
    )
    await db_session.flush()

    response = await client.get("/v1/memories/duplicates", params={"workspace_id": str(mine)})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["scanned"] == 1
    assert data["pairs"] == []


async def test_duplicates_pair_reported_once_and_limit_applied(client, db_session):
    ws_id = await _workspace(client, "dup-limit")
    db_session.add_all(
        [
            _memory(ws_id, "SQLite WAL 实践", WAL_CONTENT),
            _memory(ws_id, "SQLite WAL 实践注意", NEAR_WAL_CONTENT),
        ]
    )
    await db_session.flush()

    response = await client.get(
        "/v1/memories/duplicates",
        params={"workspace_id": str(ws_id), "min_similarity": 0.0, "limit": 1},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert len(data["pairs"]) == 1
