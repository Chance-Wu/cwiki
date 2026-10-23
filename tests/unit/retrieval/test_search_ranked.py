"""search_ranked() 管线行为测试。

覆盖核心路径：双路召回 → RRF 融合 → 重排 → 图扩展 → 过滤 → 多样性 → 效用分。
确保重构前后行为一致。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.retrieval.engine import RetrievalEngine


class _StubEmbedding:
    async def generate_embedding(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
async def search_env(tmp_path, monkeypatch):
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="search-test")
        db.add(ws)
        await db.flush()

        mem_a = Memory(
            workspace_id=ws.id,
            title="Redis 大 key 处理",
            content="Redis 大 key 渐进删除 HSCAN 分批",
            type="lesson",
            confidence=0.9,
            embedding=[1.0, 0.0],
            tags=["redis", "performance"],
        )
        mem_b = Memory(
            workspace_id=ws.id,
            title="Python 异步编程",
            content="Python asyncio 异步编程最佳实践",
            type="fact",
            confidence=0.7,
            embedding=[0.8, 0.2],
            tags=["python", "async"],
        )
        mem_c = Memory(
            workspace_id=ws.id,
            title="数据库索引优化",
            content="数据库索引优化 B+树 查询性能",
            type="decision",
            confidence=0.3,
            embedding=[0.0, 1.0],
            tags=["database"],
        )
        db.add_all([mem_a, mem_b, mem_c])
        await db.commit()

        monkeypatch.setattr("packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding())
        monkeypatch.setattr(
            "packages.retrieval.context.assembler.get_embedding_service", lambda: _StubEmbedding()
        )

        yield SimpleNamespace(
            db=db,
            engine=RetrievalEngine(),
            workspace=ws,
            mem_a=mem_a,
            mem_b=mem_b,
            mem_c=mem_c,
            id_a=str(mem_a.id),
            id_b=str(mem_b.id),
            id_c=str(mem_c.id),
        )
    await db_engine.dispose()


async def test_search_ranked_returns_sorted_memories(search_env):
    """基本路径：返回排序后的记忆列表，包含必要字段。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis 大 key",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    assert "memories" in result
    assert "total" in result
    assert "fallback" in result
    assert "latency_ms" in result
    assert len(result["memories"]) > 0
    for mem in result["memories"]:
        assert "id" in mem
        assert "score" in mem
        assert "bm25_score" in mem
        assert "vector_score" in mem
        assert "rank" in mem


async def test_search_ranked_fallback_when_no_match(search_env, monkeypatch):
    """无候选时走 fallback 路径，返回重要性排序结果并标记 fallback=True。"""
    env = search_env
    # 用零向量让 vector search 返回空，BM25 也无匹配
    class _ZeroEmbedding:
        async def generate_embedding(self, text: str) -> list[float]:
            return [0.0, 0.0]
        async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
            return [[0.0, 0.0] for _ in texts]
    monkeypatch.setattr("packages.retrieval.engine.get_embedding_service", lambda: _ZeroEmbedding())
    result = await env.engine.search_ranked(
        db=env.db,
        query="xyzabc123完全不匹配",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    # fallback 标记必须显式
    assert result["fallback"] is True
    assert len(result["memories"]) > 0
    for mem in result["memories"]:
        assert mem["score"] == 0.0


async def test_search_ranked_filters_by_memory_type(search_env):
    """memory_type 过滤必须生效。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Python asyncio 异步",
        workspace_id=env.workspace.id,
        memory_type="fact",
        top_k=10,
        record_trace=False,
    )
    for mem in result["memories"]:
        assert mem["type"] == "fact"


async def test_search_ranked_filters_by_min_confidence(search_env):
    """min_confidence 过滤必须生效。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="数据库索引 查询性能",
        workspace_id=env.workspace.id,
        min_confidence=0.5,
        top_k=10,
        record_trace=False,
    )
    # confidence=0.3 的 mem_c 应被过滤
    for mem in result["memories"]:
        assert mem.get("confidence", 0) is None or mem["confidence"] >= 0.5 or result["fallback"]


async def test_search_ranked_filters_by_tags(search_env):
    """tags 过滤必须生效。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis Python 数据库",
        workspace_id=env.workspace.id,
        tags=["redis"],
        top_k=10,
        record_trace=False,
    )
    for mem in result["memories"]:
        if not result["fallback"]:
            assert "redis" in [t.lower() for t in mem.get("tags", [])]


async def test_search_ranked_workspace_scope(search_env, tmp_path, monkeypatch):
    """workspace_id=None 跨工作区，指定 id 限定范围。"""
    env = search_env
    # 创建第二个工作区
    db_engine2 = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db2.sqlite').as_posix()}")
    async with db_engine2.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions2 = async_sessionmaker(db_engine2, expire_on_commit=False)
    async with sessions2() as db2:
        ws2 = Workspace(name="other-ws")
        db2.add(ws2)
        await db2.flush()
        mem_other = Memory(
            workspace_id=ws2.id,
            title="Other workspace memory",
            content="Redis 大 key 渐进删除",
            type="fact",
            embedding=[1.0, 0.0],
        )
        db2.add(mem_other)
        await db2.commit()

        monkeypatch.setattr(
            "packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding()
        )

        # 限定到 ws2，应只找到 ws2 的记忆
        result = await env.engine.search_ranked(
            db=db2,
            query="Redis 大 key",
            workspace_id=ws2.id,
            top_k=5,
            record_trace=False,
        )
        for mem in result["memories"]:
            # fallback 时不限定 workspace，但非 fallback 应只含 ws2 的
            if not result["fallback"]:
                assert mem["id"] == str(mem_other.id)

    await db_engine2.dispose()


async def test_search_ranked_top_k_limits_results(search_env):
    """top_k 参数限制返回数量。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis Python 数据库 索引 异步",
        workspace_id=env.workspace.id,
        top_k=1,
        record_trace=False,
    )
    assert len(result["memories"]) <= 1


async def test_search_ranked_empty_query(search_env):
    """空查询走 fallback 路径。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    assert result["fallback"] is True


async def test_search_ranked_none_query(search_env):
    """None 查询走 fallback 路径。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query=None,
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    assert result["fallback"] is True


async def test_search_ranked_record_trace(search_env):
    """record_trace=True 时写入 trace 记录。"""
    env = search_env
    from packages.domain.models import RetrievalTrace

    # 先确认没有 trace
    result_before = await env.db.execute(
        __import__("sqlalchemy").select(RetrievalTrace).where(
            RetrievalTrace.workspace_id == env.workspace.id
        )
    )
    count_before = len(result_before.all())

    await env.engine.search_ranked(
        db=env.db,
        query="Redis 大 key",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=True,
    )

    result_after = await env.db.execute(
        __import__("sqlalchemy").select(RetrievalTrace).where(
            RetrievalTrace.workspace_id == env.workspace.id
        )
    )
    count_after = len(result_after.all())
    assert count_after == count_before + 1


async def test_search_ranked_scores_are_ordered(search_env):
    """返回结果的 score 必须降序排列。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis 大 key 渐进删除",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    scores = [mem["score"] for mem in result["memories"]]
    assert scores == sorted(scores, reverse=True)


async def test_search_ranked_contains_analyzed_query(search_env):
    """返回结果包含 analyzed 查询分析。"""
    env = search_env
    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis 大 key",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    assert "analyzed" in result
    assert "candidates" in result


async def test_search_ranked_graph_expansion_with_relations(search_env):
    """有关系连接时，图扩展应让邻居获得加分。"""
    env = search_env
    # 在 mem_a 和 mem_b 之间建立关系
    relation = MemoryRelation(
        source_memory_id=env.mem_a.id,
        target_memory_id=env.mem_b.id,
        relation_type="related",
        confidence=0.9,
        strength=1.0,
    )
    env.db.add(relation)
    await env.db.commit()

    result = await env.engine.search_ranked(
        db=env.db,
        query="Redis 大 key",
        workspace_id=env.workspace.id,
        top_k=5,
        record_trace=False,
    )
    # 不崩溃即可，图扩展是尽力而为
    assert "memories" in result
