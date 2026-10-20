"""resolve_workspace 名称校验回归测试：非法名拒绝自动创建，历史脏名仍可读。

背景：workspace 名直接用作 Markdown 文件的路径组件。修复前 resolve_workspace
自动创建时不校验，`../../evil-dir` 之类的名字可入库；批准转正时 MD 永远写不
出去（file_store 的 validate_path_component 抛错），且经 _meta/_workspaces.json
随重建复活——DB/MD/索引三层永久不对称。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from apps.api.deps import invalidate_workspace_cache, resolve_workspace

LONG_CONTENT = (
    "回归验证内容：本条长度超过质量门硬性下限，描述明确的场景与结论，用于覆盖候选创建链路。"
)


@pytest.fixture(autouse=True)
def _clear_ws_cache():
    invalidate_workspace_cache()
    yield
    invalidate_workspace_cache()


async def test_resolve_rejects_path_traversal(db_session):
    with pytest.raises(HTTPException) as exc:
        await resolve_workspace("../../evil-dir", db_session)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_workspace_name"


async def test_resolve_rejects_windows_reserved_and_separators(db_session):
    for evil in ("CON", "a/b", "trailing.", "nul.md"):
        with pytest.raises(HTTPException) as exc:
            await resolve_workspace(evil, db_session)
        assert exc.value.status_code == 400, evil


async def test_resolve_creates_valid_names_including_cjk(db_session):
    from sqlalchemy import select

    from packages.domain.models import Workspace

    for name in ("alpha-ws", "中文工作区", "a.b_c-d"):
        ws_id = await resolve_workspace(name, db_session)
        row = (
            await db_session.execute(select(Workspace).where(Workspace.id == ws_id))
        ).scalar_one()
        assert row.name == name


async def test_resolve_existing_dirty_name_still_reads(db_session):
    """历史脏名行不被拒绝：由 /workspaces/hygiene 治理，读写保持可用。"""
    from packages.domain.models import Workspace

    dirty = Workspace(name="legacy--dirty")
    db_session.add(dirty)
    await db_session.flush()
    resolved = await resolve_workspace(str(dirty.id), db_session)
    assert resolved == dirty.id


async def test_candidates_endpoint_rejects_invalid_workspace_name(client):
    """经由 POST /v1/candidates 的端到端 HTTP 行为：400 而非创建垃圾工作区。"""
    resp = await client.post(
        "/v1/candidates",
        json={
            "title": "注入名回归",
            "content": LONG_CONTENT,
            "type": "fact",
            "workspace_id": "../escape-ws",
        },
    )
    assert resp.status_code == 400, resp.text
    listed = await client.get("/v1/workspaces?limit=100")
    names = {w["name"] for w in listed.json()["items"]}
    assert "../escape-ws" not in names
