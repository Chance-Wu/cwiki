"""utility_aggregation 共享模块测试：批量聚合计数与 last_used_at 融合口径。

engine 侧的同名行为由 tests/unit/retrieval/test_engine_utility.py 覆盖
（经 _aggregate_utility_scores 薄委托走同一实现）；这里直接测共享函数
本身，锁定列表路由与引擎共用的口径。
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Evidence, Memory, MemoryFeedback, MemoryUsage, Workspace
from packages.memory.utility_aggregation import aggregate_utility_scores, latest_used_at
from packages.memory.utility_score import compute_utility_score


@pytest.fixture
async def agg_env(tmp_path):
    """内存式 SQLite 环境：A 有完整使用/反馈/证据信号，B 无任何信号。"""
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="agg")
        db.add(ws)
        await db.flush()

        # UTC aware：days_since 对 naive/aware 统一按 UTC 处理，档位计算一致
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        a = Memory(
            workspace_id=ws.id,
            title="Aggregate probe alpha",
            content="aggregate probe alpha content",
            type="fact",
            last_used_at=now,
        )
        b = Memory(
            workspace_id=ws.id,
            title="Signal-less beta",
            content="no signals at all",
            type="lesson",
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

        yield SimpleNamespace(db=db, a=a, b=b, a_id=str(a.id), b_id=str(b.id), a_last_used=now)
    await db_engine.dispose()


async def test_aggregate_matches_manual_compute(agg_env):
    """三条批量 SQL 的聚合计数与手算 compute_utility_score 一致。"""
    env = agg_env
    result = await aggregate_utility_scores(env.db, [env.a, env.b])

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


async def test_aggregate_memory_without_signals_gets_floor(agg_env):
    """无任何信号的记忆仍拿先验底分（中性反馈 + 新鲜度底分），而非 0。"""
    env = agg_env
    result = await aggregate_utility_scores(env.db, [env.b])
    # human_feedback 无投票取 0.5（贡献 0.10），freshness 无使用记录取 0.3（贡献 0.045）
    assert result[env.b_id] == pytest.approx(0.145, abs=1e-4)


async def test_aggregate_degrades_to_empty_on_query_error(agg_env):
    """查询异常时降级为空映射（调用方按未计算处理），不抛出。"""
    env = agg_env
    broken_db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db down")))
    assert await aggregate_utility_scores(broken_db, [env.a]) == {}


async def test_aggregate_empty_input_returns_empty(agg_env):
    """空输入直接返回空映射，不发查询。"""
    assert await aggregate_utility_scores(agg_env.db, []) == {}


def test_latest_used_at_picks_newest_and_normalizes_naive():
    """融合多来源取最新者：naive 视为 UTC，返回统一为 naive。"""
    # 以下 naive datetime 均为故意构造，用于验证 naive/aware 混合融合口径
    naive_older = datetime(2025, 1, 1, 0, 0, 0)  # noqa: DTZ001
    aware_newer = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
    naive_newest = datetime(2025, 8, 1, 0, 0, 0)  # noqa: DTZ001

    # aware 来源比 naive_older 新，胜出后去 tzinfo 输出
    result = latest_used_at(naive_older, aware_newer, None)
    assert result == datetime(2025, 6, 1, 0, 0, 0)  # noqa: DTZ001
    assert result.tzinfo is None

    # naive_newest 比 aware_newer 更新，胜出
    assert latest_used_at(naive_older, aware_newer, naive_newest) == naive_newest


def test_latest_used_at_all_none_returns_none():
    """全部来源缺时间（从未使用）时返回 None，不伪造时间。"""
    assert latest_used_at(None, None) is None
    assert latest_used_at() is None


async def test_aggregate_counts_outdated_and_wrong_as_negative(agg_env):
    """outdated / wrong 反馈与 not_useful 一样压低 human_feedback 分量。"""
    env = agg_env
    env.db.add_all(
        [
            MemoryFeedback(
                workspace_id=env.a.workspace_id,
                memory_id=env.a.id,
                feedback_type="outdated",
                source_type="human",
            ),
            MemoryFeedback(
                workspace_id=env.a.workspace_id,
                memory_id=env.a.id,
                feedback_type="wrong",
                source_type="agent",
            ),
        ]
    )
    await env.db.commit()

    result = await aggregate_utility_scores(env.db, [env.a])
    expected = compute_utility_score(
        retrieval_count=5,
        used_count=2,
        cited_count=0,
        useful_votes=2,
        # not_useful(1) + outdated(1) + wrong(1) 全部计入负票
        not_useful_votes=3,
        last_used_at=env.a_last_used,
        evidence_count=2,
    )
    assert result[env.a_id] == round(expected.utility, 4)
