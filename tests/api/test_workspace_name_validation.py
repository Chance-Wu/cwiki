"""resolve_workspace 名称校验回归测试：非法名拒绝自动创建，历史脏名仍可读。

背景：workspace 名直接用作 Markdown 文件的路径组件。修复前 resolve_workspace
自动创建时不校验，`../../evil-dir` 之类的名字可入库；批准转正时 MD 永远写不
出去（file_store 的 validate_path_component 抛错），且经 _meta/_workspaces.json
随重建复活——DB/MD/索引三层永久不对称。
"""

from __future__ import annotations

import time

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


async def test_resolve_creates_valid_names_including_cjk(db_session, monkeypatch):
    from sqlalchemy import select

    from packages.domain.config import settings
    from packages.domain.models import Workspace

    # 默认严格模式（config.yaml auto_create_workspace=false）下需显式开启才自动建区
    monkeypatch.setattr(settings, "auto_create_workspace", True)

    for name in ("alpha-ws", "中文工作区", "a.b_c-d"):
        ws_id = await resolve_workspace(name, db_session)
        row = (
            await db_session.execute(select(Workspace).where(Workspace.id == ws_id))
        ).scalar_one()
        assert row.name == name


async def test_resolve_rejects_unknown_name_when_auto_create_disabled(db_session, monkeypatch):
    """严格模式：拼写错误的工作区名不再静默建区。"""
    from packages.domain.config import settings

    monkeypatch.setattr(settings, "auto_create_workspace", False)

    with pytest.raises(HTTPException) as exc:
        await resolve_workspace("未注册的工作区", db_session)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "unknown_workspace"


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


def test_invalidate_workspace_cache_purges_uuid_keyed_entries(monkeypatch):
    """删除 workspace 后，以 UUID 字符串解析过的缓存条目也必须失效。

    resolve 对可解析的 UUID 直接缓存（无存在校验），invalidate 只按名字
    失效会让 UUID 键条目在删除后永久命中旧值。
    """
    import uuid as uuid_mod

    from apps.api.deps import _WORKSPACE_CACHE_TTL, _workspace_cache
    from apps.api.deps import invalidate_workspace_cache as _invalidate

    name = f"cache-hygiene-{uuid_mod.uuid4().hex[:8]}"
    ws_id = uuid_mod.uuid4()
    # 两种键都进入缓存：名字键 + UUID 字符串键（同值）
    monkeypatch.setattr(
        "apps.api.deps._workspace_cache",
        {name: (ws_id, time.monotonic()), str(ws_id): (ws_id, time.monotonic())},
    )
    _ = _WORKSPACE_CACHE_TTL

    _invalidate(name)

    assert name not in _workspace_cache
    assert str(ws_id) not in _workspace_cache  # UUID 键一并失效


def test_workspace_cache_prunes_expired_entries_when_full(monkeypatch):
    """缓存超阈值时写入侧驱逐过期条目，防止任意名称探测无限增长。"""
    import time as time_mod
    import uuid as uuid_mod

    from apps.api import deps

    monkeypatch.setattr(deps, "_WORKSPACE_CACHE_PRUNE_SIZE", 4)
    monkeypatch.setattr(deps, "_WORKSPACE_CACHE_TTL", 60.0)
    # 预置 4 条全部过期的条目
    stale = time_mod.monotonic() - 120
    monkeypatch.setattr(
        deps, "_workspace_cache", {f"stale-{i}": (uuid_mod.uuid4(), stale) for i in range(4)}
    )

    deps._cache_workspace("fresh", uuid_mod.uuid4())

    assert "fresh" in deps._workspace_cache
    assert len(deps._workspace_cache) == 1  # 过期条目被批量驱逐
