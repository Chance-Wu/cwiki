"""工作区创建后立即刷新 _meta/_workspaces.json。"""

from __future__ import annotations

import json

from packages.storage.file_store import FileStore


async def test_create_workspace_writes_snapshot(client, tmp_path, monkeypatch):
    store = FileStore(tmp_path / "mirrors")
    monkeypatch.setattr("apps.api.file_sync.get_file_store", lambda: store)

    resp = await client.post("/v1/workspaces", json={"name": "snapshot-ws"})
    assert resp.status_code == 201, resp.text

    path = store.base_path / "_meta" / "_workspaces.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "snapshot-ws" in {item["name"] for item in payload}
