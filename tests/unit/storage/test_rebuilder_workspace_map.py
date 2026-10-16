"""DatabaseRebuilder 工作区恢复（_build_workspace_map）测试。

覆盖数据保真修复：重建到空数据库时必须保留每条记忆的工作区归属，
从 ``_meta/_workspaces.json`` 恢复工作区（包括没有 MD 文件的空工作区）。
"""

import uuid
from datetime import datetime

from sqlalchemy import select

from packages.domain.models import Base, Workspace
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.meta_store import MetaStore
from packages.storage.rebuilder import DatabaseRebuilder

_CREATED = "2026-01-01T00:00:00"
_UPDATED = "2026-01-02T03:04:05"


def _make_rebuilder(tmp_path) -> DatabaseRebuilder:
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    return DatabaseRebuilder(db_url=db_url, data_dir=str(tmp_path / "data"))


async def _create_schema(rebuilder: DatabaseRebuilder) -> None:
    async with rebuilder._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _save_memory(data_dir, workspace: str) -> None:
    file_store = FileStore(str(data_dir))
    file_store.save(
        MemoryFile(id=str(uuid.uuid4()), title="t", content="c", workspace=workspace),
        workspace_name=workspace,
    )


async def _workspace_rows(rebuilder: DatabaseRebuilder) -> dict[str, Workspace]:
    async with rebuilder._session_factory() as session:
        rows = (await session.execute(select(Workspace))).scalars().all()
        return {ws.name: ws for ws in rows}


async def test_build_workspace_map_restores_from_workspaces_json(tmp_path):
    """_workspaces.json 精确恢复 id/时间戳，包括空工作区。"""
    rebuilder = _make_rebuilder(tmp_path)
    data_dir = tmp_path / "data"
    try:
        await _create_schema(rebuilder)
        empty_id = str(uuid.uuid4())
        MetaStore(data_dir / "_meta").export_workspaces(
            [
                {
                    "name": "empty-ws",
                    "id": empty_id,
                    "created_at": _CREATED,
                    "updated_at": _UPDATED,
                }
            ]
        )
        _save_memory(data_dir, "md-ws")

        async with rebuilder._session_factory() as session:
            ws_map = await rebuilder._build_workspace_map(session)
            await session.commit()

        assert ws_map["empty-ws"] == empty_id
        assert ws_map["md-ws"] != empty_id

        rows = await _workspace_rows(rebuilder)
        assert str(rows["empty-ws"].id) == empty_id
        assert rows["empty-ws"].created_at == datetime.fromisoformat(_CREATED)
        assert rows["empty-ws"].updated_at == datetime.fromisoformat(_UPDATED)
        # 文件中缺失的 MD 引用工作区会被创建（兜底安全网）。
        assert "md-ws" in rows
    finally:
        await rebuilder.close()


async def test_build_workspace_map_fallback_from_md_frontmatter(tmp_path):
    """没有 _workspaces.json 时，MD 引用的 workspace 被重建。"""
    rebuilder = _make_rebuilder(tmp_path)
    data_dir = tmp_path / "data"
    try:
        await _create_schema(rebuilder)
        _save_memory(data_dir, "alpha")
        _save_memory(data_dir, "beta")

        async with rebuilder._session_factory() as session:
            ws_map = await rebuilder._build_workspace_map(session)

        assert set(ws_map) == {"alpha", "beta"}
        assert ws_map["alpha"] != ws_map["beta"]
        # 全新生成 UUID（无原始 id 可用）。
        for value in ws_map.values():
            uuid.UUID(value)
    finally:
        await rebuilder.close()


async def test_build_workspace_map_merges_with_existing_rows(tmp_path):
    """既有行优先于文件：同名或同 id 的条目被跳过。"""
    rebuilder = _make_rebuilder(tmp_path)
    data_dir = tmp_path / "data"
    try:
        await _create_schema(rebuilder)
        existing_id = uuid.uuid4()
        fresh_id = str(uuid.uuid4())
        async with rebuilder._session_factory() as session:
            session.add(Workspace(id=existing_id, name="cwiki"))
            await session.commit()

        MetaStore(data_dir / "_meta").export_workspaces(
            [
                # 同名 — 以既有行为准，保留原始 id。
                {"name": "cwiki", "id": str(uuid.uuid4()), "created_at": None, "updated_at": None},
                # 同 id 换了名字 — 跳过。
                {"name": "dup-id", "id": str(existing_id), "created_at": None, "updated_at": None},
                # 新条目 — 以保留的 id 创建。
                {"name": "fresh", "id": fresh_id, "created_at": None, "updated_at": None},
            ]
        )

        async with rebuilder._session_factory() as session:
            ws_map = await rebuilder._build_workspace_map(session)

        assert ws_map["cwiki"] == str(existing_id)
        assert "dup-id" not in ws_map
        assert ws_map["fresh"] == fresh_id
    finally:
        await rebuilder.close()
