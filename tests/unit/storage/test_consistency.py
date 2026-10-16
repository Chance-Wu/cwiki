"""运行时只读对账 run_consistency_check 的行为测试。

在 tmp_path 下构造 DB / MD / index.db / vectors 四份小规模载体，
覆盖完全一致、MD 缺失/孤儿、索引缺行/文件缺失、向量未覆盖、
archived 记忆排除与只读保证等场景。
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import aiosqlite
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.storage.consistency import run_consistency_check
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.vector_index import VectorIndex


@pytest.fixture
async def env(tmp_path):
    """构造四方完全一致的小规模数据，返回各载体路径与记忆 id。"""
    data_dir = tmp_path / "data"
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async with sessions() as db:
        ws = Workspace(name="chat")
        db.add(ws)
        await db.flush()
        mems = [
            Memory(workspace_id=ws.id, title=f"记忆{i}", content=f"内容{i}", type="fact")
            for i in range(3)
        ]
        db.add_all(mems)
        await db.commit()
        ids = [str(m.id) for m in mems]

    file_store = FileStore(data_dir)
    md_paths: dict[str, object] = {}
    for i, mid in enumerate(ids):
        md_paths[mid] = file_store.save(
            MemoryFile(id=mid, title=f"记忆{i}", content=f"内容{i}", type="fact"),
            workspace_name="chat",
        )

    async with aiosqlite.connect(data_dir / "index.db") as conn:
        await conn.execute(
            "CREATE TABLE memory_index (id TEXT PRIMARY KEY, status TEXT DEFAULT 'active')"
        )
        await conn.executemany(
            "INSERT INTO memory_index (id, status) VALUES (?, 'active')",
            [(mid,) for mid in ids],
        )
        await conn.commit()

    vectors = VectorIndex(dimensions=3, index_path=str(data_dir / "vectors.npz"))
    for mid in ids:
        vectors.add(mid, [1.0, 0.0, 0.0])
    vectors.save()

    async def check() -> object:
        async with sessions() as db:
            return await run_consistency_check(
                db,
                memory_dir=data_dir,
                index_db_path=data_dir / "index.db",
                vector_index_path=data_dir / "vectors.npz",
            )

    try:
        yield SimpleNamespace(
            check=check,
            ids=ids,
            md_paths=md_paths,
            data_dir=data_dir,
            file_store=file_store,
            sessions=sessions,
        )
    finally:
        await engine.dispose()


async def test_all_carriers_consistent(env):
    """四方完全一致时 healthy=True 且无任何差异。"""
    report = await env.check()
    assert report.healthy is True
    assert report.errors == {}
    assert report.db_count == report.md_count == report.index_count == report.vector_count == 3
    assert report.md_missing == []
    assert report.md_orphan == []
    assert report.index_missing == []
    assert report.vectors_missing == []
    assert report.vectors_missing_total == 0


async def test_missing_md_file_reported(env):
    """DB 有而 MD 缺失：计入 md_missing 且不健康。"""
    env.md_paths[env.ids[0]].unlink()
    report = await env.check()
    assert report.healthy is False
    assert report.md_missing == [env.ids[0]]
    assert report.md_orphan == []
    assert report.md_count == 2


async def test_orphan_md_file_reported(env):
    """MD 有而 DB 无：计入 md_orphan 且不健康。"""
    orphan_id = str(uuid4())
    env.file_store.save(
        MemoryFile(id=orphan_id, title="孤儿记忆", content="c", type="fact"),
        workspace_name="chat",
    )
    report = await env.check()
    assert report.healthy is False
    assert report.md_orphan == [orphan_id]
    assert report.md_missing == []


async def test_missing_index_row_reported(env):
    """index.db 缺行：计入 index_missing 且不健康。"""
    async with aiosqlite.connect(env.data_dir / "index.db") as conn:
        await conn.execute("DELETE FROM memory_index WHERE id = ?", (env.ids[0],))
        await conn.commit()
    report = await env.check()
    assert report.healthy is False
    assert report.index_missing == [env.ids[0]]
    assert report.index_count == 2


async def test_missing_index_db_file_reports_error(env):
    """index.db 文件不存在：报 error 而不抛异常，healthy=False。"""
    (env.data_dir / "index.db").unlink()
    report = await env.check()
    assert report.healthy is False
    assert "index" in report.errors
    assert "not found" in report.errors["index"]
    assert report.index_count == 0


async def test_uncovered_vector_reported(env):
    """向量未覆盖的 active 记忆：计入 vectors_missing（含总数）且不健康。"""
    vi = VectorIndex(dimensions=3, index_path=str(env.data_dir / "vectors.npz"))
    vi.remove(env.ids[0])
    vi.save()
    report = await env.check()
    assert report.healthy is False
    assert report.vectors_missing == [env.ids[0]]
    assert report.vectors_missing_total == 1


async def test_archived_memory_excluded_from_all_carriers(env):
    """archived 记忆在四方同时退出比对时不计为漂移（active-only 语义）。"""
    archived = env.ids[0]
    async with env.sessions() as db:
        mem = (await db.execute(select(Memory).where(Memory.id == archived))).scalar_one()
        mem.status = "archived"
        await db.commit()
    env.file_store.save(
        MemoryFile(id=archived, title="记忆0", content="内容0", type="fact", status="archived"),
        workspace_name="chat",
    )
    async with aiosqlite.connect(env.data_dir / "index.db") as conn:
        await conn.execute("UPDATE memory_index SET status = 'archived' WHERE id = ?", (archived,))
        await conn.commit()
    vi = VectorIndex(dimensions=3, index_path=str(env.data_dir / "vectors.npz"))
    vi.remove(archived)
    vi.save()

    report = await env.check()
    assert report.healthy is True
    assert report.db_count == report.md_count == report.index_count == report.vector_count == 2


async def test_check_does_not_write_any_file(env):
    """对账全程只读：前后 data_dir 内所有文件路径与 mtime 必须不变。"""

    def snapshot():
        return {
            str(p.relative_to(env.data_dir)): p.stat().st_mtime_ns
            for p in env.data_dir.rglob("*")
            if p.is_file()
        }

    before = snapshot()
    report = await env.check()
    assert report.healthy is True
    assert snapshot() == before
