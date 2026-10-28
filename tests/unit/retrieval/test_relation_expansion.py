"""检索图扩展的关系方向与强度加分测试。"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.retrieval.engine import RetrievalEngine


@pytest.fixture
async def expansion_env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="expansion")
        db.add(ws)
        await db.flush()
        a = Memory(workspace_id=ws.id, title="A", content="alpha", type="fact")
        b = Memory(workspace_id=ws.id, title="B", content="beta", type="fact")
        c = Memory(workspace_id=ws.id, title="C", content="gamma", type="fact")
        d = Memory(workspace_id=ws.id, title="D", content="delta", type="fact")
        db.add_all([a, b, c, d])
        await db.flush()
        db.add_all(
            [
                # B → A：入边，A 被命中时 B 应被扩展
                MemoryRelation(
                    source_memory_id=b.id,
                    target_memory_id=a.id,
                    relation_type="related",
                    confidence=1.0,
                ),
                # A → C：出边，A 被命中时 C 应被扩展
                MemoryRelation(
                    source_memory_id=a.id,
                    target_memory_id=c.id,
                    relation_type="related",
                    confidence=1.0,
                    strength=1.0,
                    last_reinforced_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30),
                ),
                # C → D：与 A 无关，不应进入一跳邻居
                MemoryRelation(
                    source_memory_id=c.id,
                    target_memory_id=d.id,
                    relation_type="related",
                    confidence=1.0,
                ),
            ]
        )
        await db.commit()
        yield SimpleNamespace(
            db=db,
            engine=RetrievalEngine(),
            a=a,
            b=b,
            c=c,
            d=d,
        )
    await engine.dispose()


async def test_neighbors_are_bidirectional(expansion_env) -> None:
    env = expansion_env

    boosts = await env.engine._relation_neighbor_boosts(env.db, [env.a.id])

    assert set(boosts) == {str(env.b.id), str(env.c.id)}
    assert str(env.d.id) not in boosts


async def test_neighbor_boost_includes_decayed_strength(expansion_env) -> None:
    env = expansion_env

    boosts = await env.engine._relation_neighbor_boosts(env.db, [env.a.id])

    # C 的强度 1.0 经过 30 天半衰期后剩 0.5：0.15×1.0 + 0.10×0.5 = 0.20
    assert boosts[str(env.c.id)] == pytest.approx(0.20)
    assert boosts[str(env.b.id)] == pytest.approx(0.15)


async def test_contradicts_relation_does_not_boost(expansion_env) -> None:
    """矛盾关系不能当作正相关给邻居加分。"""
    env = expansion_env
    env.db.add(
        MemoryRelation(
            source_memory_id=env.a.id,
            target_memory_id=env.d.id,
            relation_type="contradicts",
            confidence=1.0,
        )
    )
    await env.db.commit()

    boosts = await env.engine._relation_neighbor_boosts(env.db, [env.a.id])

    assert str(env.d.id) not in boosts


async def test_trace_reinforces_relations_and_usage(expansion_env, monkeypatch) -> None:
    from packages.domain.config import parasitic_evolution_config
    from packages.retrieval.query.analyzer import analyze_query

    env = expansion_env
    relation = (
        await env.db.execute(
            select(MemoryRelation).where(
                MemoryRelation.source_memory_id == env.b.id,
                MemoryRelation.target_memory_id == env.a.id,
            )
        )
    ).scalar_one()
    monkeypatch.setattr(parasitic_evolution_config, "relation_reinforcement_enabled", True)

    await env.engine._record_trace(
        db=env.db,
        workspace_id=env.a.workspace_id,
        session_id=None,
        query="alpha beta",
        analyzed=analyze_query("alpha beta"),
        candidates={},
        final_memories=[
            {"id": str(env.a.id), "rank": 1},
            {"id": str(env.b.id), "rank": 2},
        ],
        latency_ms=1,
    )

    await env.db.refresh(env.a)
    await env.db.refresh(env.b)
    await env.db.refresh(relation)
    assert env.a.usage_count == 1
    assert env.a.last_used_at is not None
    assert relation.strength == pytest.approx(0.2)
