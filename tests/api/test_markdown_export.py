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
