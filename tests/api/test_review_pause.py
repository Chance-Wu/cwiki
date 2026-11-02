"""复习暂停/恢复/推迟/重置的 API 行为。"""

from __future__ import annotations

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
                f"{title} 的完整正文内容，包含足够的背景、约束与操作细节，用于验证复习暂停与恢复。"
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


async def _due_ids(client: httpx.AsyncClient, ws_id: str) -> set[str]:
    resp = await client.get("/v1/review/due", params={"workspace_id": ws_id, "limit": 100})
    assert resp.status_code == 200, resp.text
    return {item["memory_id"] for item in resp.json()}


async def test_suspend_and_resume_affects_due_queue(client):
    ws_id = await _workspace(client, "review-pause")
    memory_id = await _approve_memory(client, ws_id, "暂停恢复测试", "review-pause-1")

    assert memory_id in await _due_ids(client, ws_id)

    suspended = await client.post(
        f"/v1/review/suspend/{memory_id}", params={"workspace_id": ws_id}
    )
    assert suspended.status_code == 200, suspended.text
    assert memory_id not in await _due_ids(client, ws_id)

    listing = await client.get("/v1/review/suspended", params={"workspace_id": ws_id})
    assert listing.status_code == 200, listing.text
    assert memory_id in {item["memory_id"] for item in listing.json()}

    resumed = await client.post(f"/v1/review/resume/{memory_id}", params={"workspace_id": ws_id})
    assert resumed.status_code == 200, resumed.text
    assert memory_id in await _due_ids(client, ws_id)


async def test_postpone_and_reset(client):
    ws_id = await _workspace(client, "review-postpone")
    memory_id = await _approve_memory(client, ws_id, "推迟重置测试", "review-postpone-1")

    postponed = await client.post(
        f"/v1/review/postpone/{memory_id}",
        params={"workspace_id": ws_id, "days": 5},
    )
    assert postponed.status_code == 200, postponed.text
    assert postponed.json()["postponed_days"] == 5
    assert memory_id not in await _due_ids(client, ws_id)

    reset = await client.post(f"/v1/review/reset/{memory_id}", params={"workspace_id": ws_id})
    assert reset.status_code == 200, reset.text
    assert reset.json()["mastery_level"] == "new"
    assert memory_id in await _due_ids(client, ws_id)
