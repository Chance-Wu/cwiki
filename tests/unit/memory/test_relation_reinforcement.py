"""Hebbian 关系强化的纯函数与数据库更新测试。"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.memory.reinforcement import decay_strength, reinforce_relations, reinforce_strength

_NOW = datetime(2026, 10, 20, 12, 0, 0)


def test_decay_strength_halves_over_half_life() -> None:
    last = _NOW - timedelta(days=30)

    assert decay_strength(0.8, last, now=_NOW, half_life_days=30) == pytest.approx(0.4)


def test_reinforce_strength_uses_decayed_base() -> None:
    last = _NOW - timedelta(days=60)

    # 0.8 先衰减到 0.2，再按 0.2 速率逼近 1：0.2 + 0.2 × 0.8 = 0.36
    assert reinforce_strength(0.8, last, now=_NOW, rate=0.2, half_life_days=30) == pytest.approx(
        0.36
    )


@pytest.fixture
async def relation_env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="rel")
        db.add(ws)
        await db.flush()
        a = Memory(workspace_id=ws.id, title="A", content="alpha", type="fact")
        b = Memory(workspace_id=ws.id, title="B", content="beta", type="fact")
        c = Memory(workspace_id=ws.id, title="C", content="gamma", type="fact")
        db.add_all([a, b, c])
        await db.flush()
        relation = MemoryRelation(
            source_memory_id=a.id,
            target_memory_id=b.id,
            relation_type="related",
            confidence=1.0,
        )
        db.add(relation)
        await db.commit()
        yield db, a, b, c, relation
    await engine.dispose()


async def test_reinforce_only_existing_edges(relation_env) -> None:
    db, a, b, c, relation = relation_env

    updated = await reinforce_relations(
        db, [a.id, b.id, c.id], now=_NOW, rate=0.2, half_life_days=30
    )

    assert updated == 1
    await db.refresh(relation)
    assert relation.strength == pytest.approx(0.2)
    rows = (await db.execute(select(MemoryRelation))).scalars().all()
    assert len(rows) == 1


async def test_repeated_co_retrieval_strengthens(relation_env) -> None:
    db, a, b, _c, relation = relation_env

    await reinforce_relations(db, [a.id, b.id], now=_NOW, rate=0.2, half_life_days=30)
    await reinforce_relations(db, [a.id, b.id], now=_NOW, rate=0.2, half_life_days=30)

    await db.refresh(relation)
    assert relation.strength == pytest.approx(0.36)
