"""宿主无关的 Agent 捕获 API 测试。"""

from __future__ import annotations

import httpx

CAPTURE = "/v1/integrations/agent/capture"


async def _capture(client: httpx.AsyncClient, records: list[dict], host: str = "qoder"):
    return await client.post(CAPTURE, json={"host": host, "records": records})


async def test_capture_creates_full_note_and_session(client):
    long_content = "完整摘要 " + ("重要细节 " * 1000)
    resp = await _capture(
        client,
        [
            {
                "record_id": "rec-1",
                "kind": "compact_summary",
                "session_id": "host-session-1",
                "workspace": "capture-test",
                "cwd": "/tmp/capture-test",
                "content": long_content,
                "signal_type": "session_snapshot",
            }
        ],
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["accepted"] == 1
    assert data["duplicates"] == 0
    assert data["session_id"]
    note_id = data["note_ids"][0]

    detail = await client.get(f"/v1/session-notes/{note_id}")
    assert detail.status_code == 200, detail.text
    note = detail.json()
    assert note["content"] == long_content.strip()
    assert note["content_length"] == len(long_content.strip())
    assert note["host"] == "qoder"
    assert note["workspace_name"] == "capture-test"
    assert note["signal_type"] == "session_snapshot"


async def test_list_returns_preview_not_full_content(client):
    content = "x" * 5000
    resp = await _capture(
        client,
        [
            {
                "record_id": "rec-preview",
                "kind": "tool_failure",
                "session_id": "host-session-preview",
                "workspace": "preview-test",
                "content": content,
                "signal_type": "issue",
            }
        ],
    )
    note_id = resp.json()["note_ids"][0]

    listing = await client.get(
        "/v1/session-notes", params={"workspace_id": "preview-test", "limit": 10}
    )
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["id"] == note_id)
    assert item["content"] is None
    assert item["content_preview"]
    assert item["content_length"] == 5000

    full = await client.get(
        "/v1/session-notes",
        params={"workspace_id": "preview-test", "view": "full", "limit": 10},
    )
    full_item = next(i for i in full.json()["items"] if i["id"] == note_id)
    assert full_item["content"] == content


async def test_capture_is_idempotent_by_record_id(client):
    record = {
        "record_id": "same-record",
        "kind": "compact_summary",
        "session_id": "host-session-idem",
        "workspace": "idem-test",
        "content": "same content",
    }
    first = await _capture(client, [record])
    second = await _capture(client, [record])
    assert first.json()["accepted"] == 1
    assert second.json()["accepted"] == 0
    assert second.json()["duplicates"] == 1


async def test_invalid_workspace_is_rejected_without_creating_workspace(client):
    resp = await _capture(
        client,
        [
            {
                "record_id": "bad-ws",
                "kind": "tool_failure",
                "session_id": "s",
                "workspace": "C--Users-Administrator--qoder",
                "content": "error",
            }
        ],
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["accepted"] == 0
    assert data["rejected"][0]["record_id"] == "bad-ws"


async def test_session_end_updates_session_without_note(client):
    start = await _capture(
        client,
        [
            {
                "record_id": "start",
                "kind": "compact_summary",
                "session_id": "end-session",
                "workspace": "end-test",
                "content": "start content",
            }
        ],
    )
    session_id = start.json()["session_id"]
    end = await _capture(
        client,
        [
            {
                "record_id": "end",
                "kind": "session_end",
                "session_id": "end-session",
                "workspace": "end-test",
                "content": "completed",
            }
        ],
    )
    assert end.status_code == 201
    assert end.json()["note_ids"] == []
    assert end.json()["session_id"] == session_id

    stats = await client.get(
        "/v1/integrations/agent/stats", params={"host": "qoder", "workspace_id": "end-test"}
    )
    assert stats.status_code == 200
    assert stats.json()["sessions"] == 1
    assert stats.json()["notes_total"] == 1
    assert stats.json()["notes_formalized"] == 0
    assert stats.json()["formalization_rate"] == 0.0


async def test_formalize_links_candidate_and_keeps_full_content(client):
    resp = await _capture(
        client,
        [
            {
                "record_id": "formalize",
                "kind": "compact_summary",
                "session_id": "formalize-session",
                "workspace": "formalize-test",
                "content": "a complete note",
            }
        ],
    )
    note_id = resp.json()["note_ids"][0]
    candidate_id = "00000000-0000-0000-0000-000000000123"

    formalized = await client.patch(
        f"/v1/session-notes/{note_id}/formalize",
        json={"candidate_id": candidate_id},
    )
    assert formalized.status_code == 200, formalized.text
    data = formalized.json()
    assert data["formalized"] is True
    assert data["candidate_id"] == candidate_id
    assert data["content"] == "a complete note"

    stats = await client.get(
        "/v1/integrations/agent/stats",
        params={"host": "qoder", "workspace_id": "formalize-test"},
    )
    assert stats.json()["notes_formalized"] == 1
    assert stats.json()["formalization_rate"] == 1.0
