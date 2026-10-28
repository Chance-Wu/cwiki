"""自动关系发现：来源标记与总配额语义。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.memory.auto_relation import discover_relations


@pytest.fixture
async def relation_env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="auto-relations")
        db.add(ws)
        await db.flush()
        # A 与 B 向量相同（相似度 1.0），C 正交
        a = Memory(
            workspace_id=ws.id,
            title="A",
            content="内容 A",
            type="fact",
            embedding=[1.0, 0.0, 0.0],
        )
        b = Memory(
            workspace_id=ws.id,
            title="B",
            content="内容 B",
            type="fact",
            embedding=[1.0, 0.0, 0.0],
        )
        c = Memory(
            workspace_id=ws.id,
            title="C",
            content="内容 C",
            type="fact",
            embedding=[0.0, 1.0, 0.0],
        )
        db.add_all([a, b, c])
        await db.commit()
        yield db, ws, a, b, c
    await engine.dispose()


async def test_creates_edges_with_auto_source(relation_env) -> None:
    db, ws, a, b, _c = relation_env

    created = await discover_relations(db, ws.id, threshold=0.5, max_relations_per_memory=10)

    assert created == 1
    edge = (await db.execute(select(MemoryRelation))).scalars().one()
    assert {edge.source_memory_id, edge.target_memory_id} == {a.id, b.id}
    assert edge.created_by == "auto"
    assert edge.source is not None
    assert edge.source.startswith("similarity:")


async def test_quota_counts_existing_edges(relation_env) -> None:
    """配额是总度数上限：已有关系占额度，单轮不再无限加边。"""
    db, ws, a, b, _c = relation_env
    db.add(
        MemoryRelation(
            source_memory_id=a.id,
            target_memory_id=b.id,
            relation_type="related",
            confidence=1.0,
            created_by="manual",
        )
    )
    await db.commit()

    created = await discover_relations(db, ws.id, threshold=0.5, max_relations_per_memory=1)

    assert created == 0
