"""合并建议忽略闭环：记录后不再出现在建议列表。"""

from __future__ import annotations

import uuid

from packages.domain.models import Memory, Workspace

LONG = "相似内容验证" * 12


async def test_dismiss_filters_suggestion(client, db_session, monkeypatch, tmp_path):
    # 状态文件隔离到临时目录，避免污染真实 ~/.cwiki/state
    monkeypatch.setenv("CWIKI_STATE_DIR", str(tmp_path))
    ws_name = f"merge-dismiss-{uuid.uuid4().hex[:8]}"
    ws = Workspace(name=ws_name)
    db_session.add(ws)
    await db_session.flush()
    first = Memory(
        workspace_id=ws.id,
        title="合并建议来源",
        content=LONG,
        type="fact",
        embedding=[1.0, 0.0, 0.0],
    )
    second = Memory(
        workspace_id=ws.id,
        title="合并建议目标",
        content=LONG + "补充",
        type="fact",
        embedding=[0.999, 0.001, 0.0],
    )
    db_session.add_all([first, second])
    await db_session.commit()

    listing = await client.get("/v1/memories/merge-suggestions", params={"workspace_id": ws_name})
    assert listing.status_code == 200, listing.text
    pairs = {(item["source_id"], item["target_id"]) for item in listing.json()["items"]}
    key = (str(first.id), str(second.id))
    reverse = (str(second.id), str(first.id))
    assert key in pairs or reverse in pairs
    src, tgt = key if key in pairs else reverse

    dismissed = await client.post(
        "/v1/memories/merge-suggestions/dismiss",
        json={"source_id": src, "target_id": tgt, "workspace_id": ws_name},
    )
    assert dismissed.status_code == 200, dismissed.text

    again = await client.get("/v1/memories/merge-suggestions", params={"workspace_id": ws_name})
    remaining = {(item["source_id"], item["target_id"]) for item in again.json()["items"]}
    assert key not in remaining and reverse not in remaining
