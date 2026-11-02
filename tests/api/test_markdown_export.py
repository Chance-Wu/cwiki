"""Markdown 导出：完整正文 + frontmatter，可回灌。"""

from __future__ import annotations

import httpx


async def _workspace(client: httpx.AsyncClient, name: str) -> str:
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_export_markdown_includes_full_content_and_frontmatter(client):
    ws_id = await _workspace(client, "export-md")
    content = "完整正文" + ("细节" * 2000)
    created = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws_id,
            "title": "导出测试记忆",
            "content": content,
            "type": "lesson",
            "source": "manual",
            "client_write_id": "export-md-1",
        },
    )
    assert created.status_code == 201, created.text
    candidate_id = created.json()["candidate"]["id"]
    reviewed = await client.post(
        "/v1/reviews",
        json={"candidate_id": candidate_id, "action": "approve", "reviewer_type": "human"},
    )
    assert reviewed.status_code == 201, reviewed.text

    resp = await client.get("/v1/export/markdown", params={"workspace_id": ws_id})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/markdown")
    text = resp.text
    assert "title: 导出测试记忆" in text
    assert "type: lesson" in text
    assert content in text
    assert "id:" in text


async def test_export_markdown_empty_workspace_returns_empty_body(client):
    ws_id = await _workspace(client, "export-empty")
    resp = await client.get("/v1/export/markdown", params={"workspace_id": ws_id})
    assert resp.status_code == 200
    assert resp.text == ""


async def _approve_memory(client: httpx.AsyncClient, ws_id: str, title: str, key: str) -> str:
    created = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws_id,
            "title": title,
            "content": (
                f"{title} 的完整正文内容，包含足够的背景、约束与操作细节，"
                "用于验证按 ID 导出时只包含选中的记忆条目。"
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


async def test_export_markdown_selected_ids_only(client):
    ws_id = await _workspace(client, "export-selected")
    first_id = await _approve_memory(client, ws_id, "选中记忆甲", "export-selected-1")
    await _approve_memory(client, ws_id, "未选记忆乙", "export-selected-2")

    resp = await client.get(
        "/v1/export/markdown",
        params={"workspace_id": ws_id, "memory_ids": first_id},
    )
    assert resp.status_code == 200, resp.text
    assert "选中记忆甲" in resp.text
    assert "未选记忆乙" not in resp.text


async def test_export_markdown_invalid_ids_returns_empty(client):
    ws_id = await _workspace(client, "export-invalid")
    await _approve_memory(client, ws_id, "不应导出的记忆", "export-invalid-1")

    resp = await client.get(
        "/v1/export/markdown",
        params={"workspace_id": ws_id, "memory_ids": "not-a-uuid"},
    )
    assert resp.status_code == 200
    assert resp.text == ""
