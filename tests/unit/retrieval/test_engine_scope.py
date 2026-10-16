"""RetrievalEngine 的工作区作用域：省略 workspace 时覆盖全部 active 记忆。

BM25 与向量检索必须接受 ``workspace_id=None`` 以跨全部工作区检索；
显式指定工作区时结果保持限定在该工作区。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.retrieval.engine import RetrievalEngine


@pytest.fixture
async def scope_env(tmp_path):
    db_engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        alpha, beta = Workspace(name="alpha"), Workspace(name="beta")
        db.add_all([alpha, beta])
        await db.flush()
        alpha_memory = Memory(
            workspace_id=alpha.id,
            title="Alpha scope probe",
            content="alpha scope probe content",
            type="fact",
            embedding=[1.0, 0.0],
        )
        beta_memory = Memory(
            workspace_id=beta.id,
            title="Beta scope probe",
            content="beta scope probe content",
            type="fact",
            embedding=[0.8, 0.6],
        )
        db.add_all([alpha_memory, beta_memory])
        await db.commit()
        yield SimpleNamespace(
            db=db,
            engine=RetrievalEngine(),
            alpha=alpha.id,
            alpha_id=str(alpha_memory.id),
            beta_id=str(beta_memory.id),
        )
    await db_engine.dispose()


async def test_vector_search_without_workspace_spans_all(scope_env):
    env = scope_env
    hits = await env.engine.vector_search(env.db, [1.0, 0.0], None, top_k=10)
    assert {doc_id for doc_id, _ in hits} == {env.alpha_id, env.beta_id}


async def test_vector_search_with_workspace_stays_scoped(scope_env):
    env = scope_env
    hits = await env.engine.vector_search(env.db, [1.0, 0.0], env.alpha, top_k=10)
    assert {doc_id for doc_id, _ in hits} == {env.alpha_id}


async def test_bm25_index_without_workspace_spans_all(scope_env):
    env = scope_env
    index = await env.engine.get_bm25_index(env.db, None)
    assert {doc_id for doc_id, _ in index.search("probe", top_k=10)} == {
        env.alpha_id,
        env.beta_id,
    }


async def test_bm25_index_with_workspace_stays_scoped(scope_env):
    env = scope_env
    index = await env.engine.get_bm25_index(env.db, env.alpha)
    assert {doc_id for doc_id, _ in index.search("probe", top_k=10)} == {env.alpha_id}
