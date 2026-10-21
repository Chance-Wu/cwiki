"""标签在 MD 镜像、数据同步、重建与 ZIP 导出中的持久化测试。"""

import uuid

from sqlalchemy import select

from apps.api.file_sync import memory_to_file
from packages.domain.database import Base
from packages.domain.export_import import _memory_to_markdown, _serialize_memory
from packages.domain.models import Memory
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.rebuilder import DatabaseRebuilder, RebuildResult
from scripts.migrate_to_git import _memory_to_file


def _memory(**overrides) -> Memory:
    data = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "title": "标签持久化",
        "content": "标签必须随记忆一起导出。",
        "type": "fact",
        "tags": ["cwiki", "持久化"],
    }
    data.update(overrides)
    return Memory(**data)


def test_file_sync_carries_tags() -> None:
    assert memory_to_file(_memory()).tags == ["cwiki", "持久化"]


def test_migrate_export_carries_tags() -> None:
    assert _memory_to_file(_memory(), "cwiki").tags == ["cwiki", "持久化"]


def test_zip_export_carries_tags() -> None:
    memory = _memory()
    serialized = _serialize_memory(memory)
    markdown = _memory_to_markdown(
        {
            **serialized,
            "title": memory.title,
            "content": memory.content,
            "type": memory.type,
            "source": memory.source,
            "status": memory.status,
            "confidence": memory.confidence,
            "importance": memory.importance,
            "version": memory.version,
            "is_permanent": memory.is_permanent,
        }
    )

    assert serialized["tags"] == ["cwiki", "持久化"]
    assert "tags:" in markdown
    assert "cwiki" in markdown


def test_file_store_roundtrip_keeps_tags(tmp_path) -> None:
    store = FileStore(str(tmp_path))
    memory = _memory()
    path = store.save(memory_to_file(memory), workspace_name="cwiki")

    loaded = store.load_from_path(path)

    assert loaded is not None
    assert loaded.tags == ["cwiki", "持久化"]


async def test_rebuild_restores_tags(tmp_path) -> None:
    rebuilder = DatabaseRebuilder(
        db_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        data_dir=str(tmp_path / "data"),
    )
    try:
        async with rebuilder._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        file_store = FileStore(str(tmp_path / "data"))
        file_store.save(
            MemoryFile(
                id=str(uuid.uuid4()),
                title="重建标签",
                content="重建后的记忆必须保留标签。",
                tags=["cwiki", "重建"],
                workspace="tag-ws",
            ),
            workspace_name="tag-ws",
        )

        async with rebuilder._session_factory() as session:
            ws_map = await rebuilder._build_workspace_map(session)
            await rebuilder._import_memories(session, ws_map, RebuildResult())
            await session.commit()

        async with rebuilder._session_factory() as session:
            restored = (await session.execute(select(Memory))).scalars().one()

        assert restored.tags == ["cwiki", "重建"]
    finally:
        await rebuilder.close()
