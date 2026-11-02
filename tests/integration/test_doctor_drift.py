"""doctor 深度巡检：内容漂移、坏 _meta、向量维度/模型、--fix-drift。"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.config import settings
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.storage.file_store import FileStore, MemoryFile
from scripts import check_integrity


async def _make_layout(
    tmp_path: Path,
    *,
    db_content: str = "## 知识\n旧正文。",
    md_content: str = "## 知识\n手改后的正文。",
) -> tuple[Path, Path, uuid.UUID]:
    memory_dir = tmp_path / "cwiki-data"
    memory_dir.mkdir(parents=True)
    meta_dir = memory_dir / "_meta"
    meta_dir.mkdir(parents=True)
    db_path = memory_dir / "cwiki.db"

    ws_id = uuid.uuid4()
    memory_id = uuid.uuid4()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add(Workspace(id=ws_id, name="ws-one"))
        await db.flush()
        db.add(
            Memory(
                id=memory_id,
                workspace_id=ws_id,
                title="巡检测试记忆",
                content=db_content,
                type="fact",
                tags=["ops"],
                source="mcp",
                status="active",
                version=1,
            )
        )
        await db.commit()
    await engine.dispose()

    store = FileStore(memory_dir)
    store.save(
        MemoryFile(
            id=str(memory_id),
            title="巡检测试记忆",
            content=md_content,
            type="fact",
            tags=["ops"],
            status="active",
            workspace="ws-one",
        ),
        workspace_name="ws-one",
    )
    (meta_dir / f"{memory_id}.json").write_text("{}", encoding="utf-8")
    (meta_dir / "_workspaces.json").write_text(
        json.dumps([{"name": "ws-one", "id": str(ws_id)}]), encoding="utf-8"
    )

    con = sqlite3.connect(memory_dir / "index.db")
    con.execute("create table memory_index (id text, status text)")
    con.execute("insert into memory_index values (?, ?)", (str(memory_id), "active"))
    con.commit()
    con.close()
    np.savez(
        memory_dir / "vectors.npz",
        vectors=np.zeros((1, settings.embedding_dimensions), dtype=np.float32),
    )
    (memory_dir / "vectors.json").write_text(
        json.dumps(
            {
                "ids": [str(memory_id)],
                "dimensions": settings.embedding_dimensions,
                "model": settings.embedding_model,
            }
        ),
        encoding="utf-8",
    )
    return db_path, memory_dir, memory_id


async def test_detects_content_drift(tmp_path: Path) -> None:
    db_path, memory_dir, _ = await _make_layout(tmp_path)

    report = check_integrity.collect(db_path, memory_dir, check_port=False)

    kinds = {issue["kind"] for issue in report["issues"]}
    assert "content_drift" in kinds
    assert report["ok"] is False


async def test_consistent_content_is_ok(tmp_path: Path) -> None:
    db_path, memory_dir, _ = await _make_layout(
        tmp_path,
        db_content="## 知识\n同一正文。",
        md_content="## 知识\n同一正文。",
    )

    report = check_integrity.collect(db_path, memory_dir, check_port=False)

    assert report["ok"] is True, report["issues"]


async def test_detects_bad_meta_and_vector_mismatch(tmp_path: Path) -> None:
    db_path, memory_dir, memory_id = await _make_layout(tmp_path)
    (memory_dir / "_meta" / f"{memory_id}.json").write_text("{bad json", encoding="utf-8")
    (memory_dir / "vectors.json").write_text(
        json.dumps({"ids": [str(memory_id)], "dimensions": 3, "model": "other-model"}),
        encoding="utf-8",
    )
    np.savez(
        memory_dir / "vectors.npz",
        vectors=np.zeros((1, 3), dtype=np.float32),
    )

    report = check_integrity.collect(db_path, memory_dir, check_port=False)

    kinds = {issue["kind"] for issue in report["issues"]}
    assert "bad_meta" in kinds
    assert "vector_index_unhealthy" in kinds


async def test_fix_drift_syncs_markdown_into_db(tmp_path: Path) -> None:
    db_path, memory_dir, memory_id = await _make_layout(tmp_path)
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    fixed = await check_integrity._fix_drift(db_url, memory_dir)

    assert fixed == [str(memory_id)]
    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        memory = (await db.execute(select(Memory).where(Memory.id == memory_id))).scalar_one()
        assert memory.content == "## 知识\n手改后的正文。\n"
        assert memory.version == 2
    await engine.dispose()

    report = check_integrity.collect(db_path, memory_dir, check_port=False)
    kinds = {issue["kind"] for issue in report["issues"]}
    assert "content_drift" not in kinds
