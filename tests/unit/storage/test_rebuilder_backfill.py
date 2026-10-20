"""rebuild_vector_index 的 embedding 列回填与 vectors.json 计数测试（W7 P2-6）。

- _backfill_memory_embeddings 把重建生成的向量写回 DB memory.embedding
- vector_meta_count 从 vectors.json 读取向量条数，供轻量跳过判定校验
"""

import uuid

from sqlalchemy import select

from packages.domain.models import Base, Memory, Workspace
from packages.storage.rebuilder import DatabaseRebuilder, vector_meta_count


def _make_rebuilder(tmp_path) -> DatabaseRebuilder:
    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    return DatabaseRebuilder(db_url=db_url, data_dir=str(tmp_path / "data"))


async def _create_schema(rebuilder: DatabaseRebuilder) -> None:
    async with rebuilder._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_backfill_writes_embedding_column(tmp_path):
    rebuilder = _make_rebuilder(tmp_path)
    try:
        await _create_schema(rebuilder)
        async with rebuilder._session_factory() as session:
            ws = Workspace(id=uuid.uuid4(), name="ws")
            mem1 = Memory(id=uuid.uuid4(), workspace_id=ws.id, title="a", content="a", type="fact")
            mem2 = Memory(id=uuid.uuid4(), workspace_id=ws.id, title="b", content="b", type="fact")
            orphan_id = uuid.uuid4()  # DB 中不存在的孤儿 MD id
            session.add_all([ws, mem1, mem2])
            await session.commit()
            mem1_id, mem2_id = mem1.id, mem2.id

        updates = [
            (str(mem1_id), [0.1, 0.2, 0.3]),
            (str(orphan_id), [0.4, 0.5, 0.6]),
        ]
        backfilled = await rebuilder._backfill_memory_embeddings(updates)
        assert backfilled == 2  # 语句数（孤儿 UPDATE 影响 0 行但不报错）

        async with rebuilder._session_factory() as session:
            row1 = (await session.execute(select(Memory).where(Memory.id == mem1_id))).scalar_one()
            row2 = (await session.execute(select(Memory).where(Memory.id == mem2_id))).scalar_one()
        assert list(row1.embedding) == [0.1, 0.2, 0.3]
        assert row2.embedding is None
    finally:
        await rebuilder.close()


async def test_backfill_empty_updates_is_noop(tmp_path):
    rebuilder = _make_rebuilder(tmp_path)
    try:
        assert await rebuilder._backfill_memory_embeddings([]) == 0
    finally:
        await rebuilder.close()


def test_vector_meta_count_reads_ids(tmp_path, monkeypatch):
    from packages.storage import config as storage_config

    meta_path = tmp_path / "vectors.json"
    meta_path.write_text('{"ids": ["a", "b"], "metadata": {}, "version": 1}', encoding="utf-8")
    monkeypatch.setattr(storage_config, "vector_meta_path", str(meta_path))
    assert vector_meta_count() == 2


def test_vector_meta_count_missing_or_corrupt_returns_none(tmp_path, monkeypatch):
    from packages.storage import config as storage_config

    missing = tmp_path / "missing.json"
    monkeypatch.setattr(storage_config, "vector_meta_path", str(missing))
    assert vector_meta_count() is None

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not json{", encoding="utf-8")
    monkeypatch.setattr(storage_config, "vector_meta_path", str(corrupt))
    assert vector_meta_count() is None

    no_ids = tmp_path / "no_ids.json"
    no_ids.write_text('{"metadata": {}}', encoding="utf-8")
    monkeypatch.setattr(storage_config, "vector_meta_path", str(no_ids))
    assert vector_meta_count() is None
