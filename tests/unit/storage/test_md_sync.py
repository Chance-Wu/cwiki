"""Markdown → DB 单条同步测试：手改 MD 后写回正文/类型/标签/状态。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.storage.file_store import MemoryFile
from packages.storage.md_sync import sync_memory_from_markdown

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def md_engine() -> AsyncGenerator:
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def md_db(md_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(md_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


async def _seed_memory(db: AsyncSession) -> tuple[Workspace, Memory]:
    ws = Workspace(id=uuid.uuid4(), name=f"md-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    memory = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="旧标题",
        content="## 知识\n旧正文。",
        type="fact",
        tags=["old"],
        source="mcp",
        status="active",
        version=1,
        embedding=[0.1, 0.2, 0.3],
    )
    db.add(memory)
    await db.commit()
    return ws, memory


def _file(memory: Memory, **overrides) -> MemoryFile:
    data = {
        "id": str(memory.id),
        "title": "新标题",
        "content": "## 知识\n手改后的新正文。",
        "type": "lesson",
        "tags": ["new", "tags"],
        "status": "active",
        "workspace": "ws",
    }
    data.update(overrides)
    return MemoryFile(**data)


async def test_sync_updates_fields_and_bumps_version(md_db: AsyncSession, tmp_path: Path) -> None:
    _, memory = await _seed_memory(md_db)

    result = await sync_memory_from_markdown(
        md_db,
        _file(memory),
        meta_dir=tmp_path / "_meta",
    )
    assert result.status == "updated"
    assert set(result.changed_fields) == {"title", "content", "type", "tags"}
    assert result.needs_embedding is True
    await md_db.commit()
    await md_db.refresh(memory)

    assert memory.title == "新标题"
    assert memory.content == "## 知识\n手改后的新正文。\n"
    assert memory.type == "lesson"
    assert sorted(memory.tags or []) == ["new", "tags"]
    assert memory.version == 2
    assert memory.embedding is None
    assert (tmp_path / "_meta" / f"{memory.id}.json").is_file()


async def test_unchanged_markdown_is_noop(md_db: AsyncSession, tmp_path: Path) -> None:
    _, memory = await _seed_memory(md_db)
    unchanged = _file(
        memory,
        title=memory.title,
        content=memory.content,
        type=memory.type,
        tags=list(memory.tags or []),
        status=memory.status,
    )

    result = await sync_memory_from_markdown(md_db, unchanged, meta_dir=tmp_path / "_meta")

    assert result.status == "unchanged"
    await md_db.refresh(memory)
    assert memory.version == 1


async def test_missing_memory_returns_missing(md_db: AsyncSession) -> None:
    memory_file = MemoryFile(
        id=str(uuid.uuid4()),
        title="不存在",
        content="## 知识\n孤儿 Markdown。",
        type="fact",
    )

    result = await sync_memory_from_markdown(md_db, memory_file)

    assert result.status == "missing_memory"


async def test_invalid_status_is_rejected(md_db: AsyncSession) -> None:
    _, memory = await _seed_memory(md_db)

    result = await sync_memory_from_markdown(md_db, _file(memory, status="bogus"))

    assert result.status == "invalid"
    await md_db.refresh(memory)
    assert memory.status == "active"
