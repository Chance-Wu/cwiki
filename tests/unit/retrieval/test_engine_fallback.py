"""无候选 fallback 的显式不足标记测试（W5-D）。

无候选时 engine 仍返回 importance Top-N 兜底，但必须显式标记 fallback、
score 归零——不再伪造 1.0 高分误导按分数过滤的消费方（如主动推送）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.config import settings
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.retrieval.engine import RetrievalEngine
from tests.unit.retrieval.test_engine_utility import _StubEmbedding


@pytest.fixture
async def fallback_env(tmp_path):
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        ws = Workspace(name="fallback")
        db.add(ws)
        await db.flush()
        # 无 embedding 且与查询零词面重叠：BM25 与向量两路均无候选
        m = Memory(
            workspace_id=ws.id,
            title="Redis 大 key 渐进删除",
            content="HSCAN 分批删除大集合成员，UNLINK 异步释放内存",
            type="lesson",
        )
        db.add(m)
        await db.commit()
        yield SimpleNamespace(db=db, engine=RetrievalEngine(), workspace=ws)
    await db_engine.dispose()


async def test_no_candidate_fallback_marks_insufficient(fallback_env, monkeypatch):
    env = fallback_env
    monkeypatch.setattr("packages.retrieval.engine.get_embedding_service", lambda: _StubEmbedding())
    monkeypatch.setattr(
        "packages.retrieval.context.assembler.get_embedding_service", lambda: _StubEmbedding()
    )
    monkeypatch.setattr(settings, "relevance_floor_mode", "none")

    result = await env.engine.retrieve(
        "qqzz 完全无关的字符串组合查询", env.workspace.id, env.db, max_items=5
    )

    assert result["fallback"] is True
    assert result["total"] >= 1  # 仍返回 importance Top-N 兜底
    for m in result["memories"]:
        assert m["score"] == 0.0
        assert m["fallback"] is True
