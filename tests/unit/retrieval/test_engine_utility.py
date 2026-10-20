"""utility_score 批量聚合与检索管线注入测试。

覆盖两条路径：
1. ``_aggregate_utility_scores`` 的三条 GROUP BY 批量 SQL 计数正确、
   异常时降级为空映射；
2. ``retrieve()`` 完整管线把非 0 utility_score 注入 final_memories。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.config import settings
from packages.domain.database import Base
from packages.domain.models import Evidence, Memory, MemoryFeedback, MemoryUsage, Workspace
from packages.memory.utility_score import compute_utility_score
from packages.retrieval.engine import RetrievalEngine


class _StubEmbedding:
    """零模型调用的 embedding 桩：固定二维向量，让 retrieve() 走纯内存路径。"""

    async def generate_embedding(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
async def utility_env(tmp_path):
    """内存式 SQLite 环境：A 有完整使用/反馈/证据信号，B 无任何信号。"""
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="util")
        db.add(ws)
        await db.flush()

        # UTC aware：days_since 对 naive/aware 统一按 UTC 处理，档位计算一致
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        a = Memory(
            workspace_id=ws.id,
            title="Utility probe alpha",
            content="utility probe alpha content",
            type="fact",
            embedding=[1.0, 0.0],
            last_used_at=now,
        )
        b = Memory(
            workspace_id=ws.id,
            title="Unrelated beta",
            content="different topic entirely",
            type="lesson",
            embedding=[0.0, 1.0],
        )
        db.add_all([a, b])
        await db.flush()

        # A：5 条使用流水（2 条 used）+ 3 条反馈（2 useful / 1 not_useful）+ 2 条证据
        for stage in ("used", "used", "retrieved", "retrieved", "retrieved"):
            db.add(MemoryUsage(workspace_id=ws.id, memory_id=a.id, stage=stage))
        db.add_all(
            [
                MemoryFeedback(
                    workspace_id=ws.id, memory_id=a.id, feedback_type="useful", source_type="human"
                ),
                MemoryFeedback(
                    workspace_id=ws.id, memory_id=a.id, feedback_type="useful", source_type="agent"
                ),
                MemoryFeedback(
                    workspace_id=ws.id,
                    memory_id=a.id,
                    feedback_type="not_useful",
                    source_type="human",
                ),
            ]
        )
        db.add_all(
            [
                Evidence(memory_id=a.id, source_type="event"),
                Evidence(memory_id=a.id, source_type="event"),
            ]
        )
        await db.commit()

        yield SimpleNamespace(
            db=db,
            engine=RetrievalEngine(),
            workspace=ws,
            a=a,
            b=b,
            a_id=str(a.id),
            b_id=str(b.id),
            a_last_used=now,
        )
    await db_engine.dispose()


async def test_aggregate_counts_match_expected(utility_env):
    """三条批量 SQL 的聚合计数与手算 compute_utility_score 一致。"""
    env = utility_env
    mem_map = {env.a_id: env.a, env.b_id: env.b}
    result = await env.engine._aggregate_utility_scores(env.db, [env.a_id, env.b_id], mem_map)

    expected = compute_utility_score(
        retrieval_count=5,
        used_count=2,
        cited_count=0,
        useful_votes=2,
        not_useful_votes=1,
        last_used_at=env.a_last_used,
        evidence_count=2,
    )
    assert result[env.a_id] == round(expected.utility, 4)
    assert result[env.a_id] > 0


async def test_aggregate_memory_without_signals_gets_nonzero_floor(utility_env):
    """无任何信号的记忆仍拿到底分：中性反馈先验 + 新鲜度底分，而非 0。"""
    env = utility_env
    result = await env.engine._aggregate_utility_scores(env.db, [env.b_id], {env.b_id: env.b})
    # human_feedback 无投票取 0.5（贡献 0.10），freshness 无使用记录取 0.3（贡献 0.045）
    assert result[env.b_id] == pytest.approx(0.145, abs=1e-4)


async def test_aggregate_degrades_to_empty_on_query_error(utility_env):
    """查询异常时降级为空映射（调用方按 utility_score=0 处理），不抛出。"""
    env = utility_env
    broken_db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down")))
    result = await env.engine._aggregate_utility_scores(broken_db, [env.a_id], {})
    assert result == {}


async def test_retrieve_injects_nonzero_utility_into_final_memories(utility_env, monkeypatch):
    """完整检索管线：final_memories dict 携带与批量聚合一致的非 0 utility_score。"""
    env = utility_env
    # 桩掉 engine 与 assembler 两处 embedding 服务，避免触发本地模型加载
    monkeypatch.setattr("packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding())
    monkeypatch.setattr(
        "packages.retrieval.context.assembler.get_embedding_service", lambda: _StubEmbedding()
    )
    # 本测试关注 utility 注入；关闭 relevance_floor，避免双条目小夹具的
    # 低 composite 分被 hard 档清场（过滤行为在 test_candidate_filters 覆盖）
    monkeypatch.setattr(settings, "relevance_floor_mode", "none")

    result = await env.engine.retrieve("utility probe alpha", env.workspace.id, env.db, max_items=5)

    assert result["total"] >= 1
    by_id = {m["id"]: m for m in result["memories"]}
    assert env.a_id in by_id
    expected = round(
        compute_utility_score(
            retrieval_count=5,
            used_count=2,
            cited_count=0,
            useful_votes=2,
            not_useful_votes=1,
            last_used_at=env.a_last_used,
            evidence_count=2,
        ).utility,
        4,
    )
    assert by_id[env.a_id]["utility_score"] == expected
    assert by_id[env.a_id]["utility_score"] > 0


async def test_normal_retrieval_not_marked_fallback(utility_env, monkeypatch):
    """W5-D：有候选的正常路径 fallback=False，分数保持真实信号。"""
    monkeypatch.setattr("packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding())
    monkeypatch.setattr(
        "packages.retrieval.context.assembler.get_embedding_service", lambda: _StubEmbedding()
    )
    monkeypatch.setattr(settings, "relevance_floor_mode", "none")

    result = await utility_env.engine.retrieve(
        "utility probe alpha", utility_env.workspace.id, utility_env.db, max_items=5
    )

    assert result["fallback"] is False
    assert result["total"] >= 1
    assert any(m["score"] > 0 for m in result["memories"])
