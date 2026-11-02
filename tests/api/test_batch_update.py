"""批量编辑记忆：字段应用与逐条失败上报。"""

from __future__ import annotations

import uuid

import httpx


async def _workspace(client: httpx.AsyncClient, name: str) -> str:
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _approve_memory(client: httpx.AsyncClient, ws_id: str, title: str, key: str) -> str:
    created = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws_id,
            "title": title,
            "content": (
                f"{title} 的完整正文内容，包含足够的背景、约束与操作细节，用于验证批量编辑字段写入。"
            ),
            "type": "fact",
            "source": "manual",
            "client_write_id": key,
        },
    )
    assert created.status_code == 201, created.text
    candidate_id = created.json()["candidate"]["id"]
    reviewed = await client.post(
        "/v1/reviews",
        json={"candidate_id": candidate_id, "action": "approve", "reviewer_type": "human"},
    )
    assert reviewed.status_code == 201, reviewed.text

    listing = await client.get("/v1/memories", params={"workspace_id": ws_id})
    assert listing.status_code == 200, listing.text
    for item in listing.json()["items"]:
        if item["title"] == title:
            return item["id"]
    raise AssertionError(f"memory {title} not found")


async def test_batch_update_applies_fields(client):
    ws_id = await _workspace(client, "batch-update")
    first = await _approve_memory(client, ws_id, "批量更新甲", "batch-1")
    second = await _approve_memory(client, ws_id, "批量更新乙", "batch-2")

    resp = await client.post(
        "/v1/memories/batch-update",
        json={
            "ids": [first, second],
            "patch": {
                "type": "lesson",
                "confidence": 0.9,
                "importance": 0.8,
                "tags": ["Batch", "Test", "batch"],
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["succeeded"] == 2
    assert body["failed"] == 0

    detail = await client.get(f"/v1/memories/{first}")
    assert detail.status_code == 200, detail.text
    memory = detail.json()["memory"]
    assert memory["type"] == "lesson"
    assert abs(memory["confidence"] - 0.9) < 1e-6
    assert abs(memory["importance"] - 0.8) < 1e-6
    assert set(memory["tags"] or []) == {"batch", "test"}


async def test_batch_update_rejects_empty_patch(client):
    ws_id = await _workspace(client, "batch-update-empty")
    memory_id = await _approve_memory(client, ws_id, "空补丁批量更新", "batch-empty-1")

    resp = await client.post(
        "/v1/memories/batch-update",
        json={"ids": [memory_id], "patch": {}},
    )
    assert resp.status_code == 400, resp.text


async def test_batch_update_reports_partial_failure(client):
    ws_id = await _workspace(client, "batch-update-partial")
    memory_id = await _approve_memory(client, ws_id, "批量更新部分失败", "batch-partial-1")
    missing = str(uuid.uuid4())

    resp = await client.post(
        "/v1/memories/batch-update",
        json={"ids": [memory_id, missing], "patch": {"confidence": 0.7}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    failed = [item for item in body["results"] if not item["success"]]
    assert len(failed) == 1
    assert failed[0]["memory_id"] == missing
    assert failed[0]["error"]
