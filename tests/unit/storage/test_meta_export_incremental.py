"""增量 _meta 导出：单条记忆整份重写、工作区快照含空工作区。"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base, Memory, MemoryRelation, Workspace
from packages.storage.meta_export import export_memory_meta, export_workspaces_meta


async def _session_factory(tmp_path):
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'sidecar.db').as_posix()}"
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_export_memory_meta_rewrites_full_relation_set(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    meta_dir = tmp_path / "_meta"
    ws_id, mem_id, other_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async with session_factory() as session:
        session.add(Workspace(id=ws_id, name="meta-ws"))
        session.add_all(
            [
                Memory(id=mem_id, workspace_id=ws_id, title="A", content="内容", type="fact"),
                Memory(id=other_id, workspace_id=ws_id, title="B", content="内容", type="fact"),
            ]
        )
        await session.flush()
        session.add(
            MemoryRelation(
                source_memory_id=mem_id,
                target_memory_id=other_id,
                relation_type="related",
                confidence=0.9,
            )
        )
        await session.commit()

        path = await export_memory_meta(session, mem_id, meta_dir)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data["relation"]) == 1
        assert data["relation"][0]["relation_type"] == "related"

        # 再建一条反向关系后重新导出：整份重写，不能只剩新增边
        session.add(
            MemoryRelation(
                source_memory_id=other_id,
                target_memory_id=mem_id,
                relation_type="supports",
                confidence=0.8,
            )
        )
        await session.commit()
        await export_memory_meta(session, mem_id, meta_dir)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert {row["relation_type"] for row in data["relation"]} == {"related", "supports"}
    assert set(data) >= {
        "feedback",
        "usage",
        "conflict",
        "review_schedule",
        "relation",
        "lifecycle_event",
        "evidence",
        "versions",
        "review_history",
    }
    await engine.dispose()


async def test_export_workspaces_meta_includes_empty_workspace(tmp_path):
    engine, session_factory = await _session_factory(tmp_path)
    meta_dir = tmp_path / "_meta"

    async with session_factory() as session:
        session.add_all([Workspace(name="ws-b"), Workspace(name="ws-a-empty")])
        await session.commit()
        count = await export_workspaces_meta(session, meta_dir)

    payload = json.loads((meta_dir / "_workspaces.json").read_text(encoding="utf-8"))
    assert count == 2
    assert [item["name"] for item in payload] == ["ws-a-empty", "ws-b"]
    await engine.dispose()
