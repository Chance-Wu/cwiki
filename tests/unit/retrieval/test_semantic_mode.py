"""semantic 检索模式：跳过 BM25，仅向量召回（过滤与重排阶段保持一致）。"""

from __future__ import annotations

import pytest

from packages.retrieval import engine as engine_mod
from packages.retrieval.engine import RetrievalEngine, _SearchParams
from packages.retrieval.query.analyzer import analyze_query


class _CountingIndex:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, query: str, top_k: int = 50) -> list[tuple[str, float]]:
        self.calls += 1
        return []


class _FakeEmbedding:
    is_fallback = False

    async def generate_embedding(self, text: str) -> list[float]:
        return [0.1] * 8


@pytest.fixture
def fake_embedding(monkeypatch):
    monkeypatch.setattr(engine_mod, "get_embedding_service", lambda: _FakeEmbedding())


async def test_semantic_mode_skips_bm25(db_session, fake_embedding, monkeypatch) -> None:
    engine = RetrievalEngine()
    index = _CountingIndex()

    async def _no_vectors(*_args, **_kwargs):
        return []

    monkeypatch.setattr(engine, "_vector_search", _no_vectors)
    params = _SearchParams(db=db_session, query="redis 集群", workspace_id=None, mode="semantic")

    candidates = await engine._dual_recall(
        params,
        index,
        analyze_query("redis 集群"),
        (0, None, 0),  # type: ignore[arg-type]
    )

    assert candidates == {}
    assert index.calls == 0


async def test_hybrid_mode_uses_bm25(db_session, fake_embedding, monkeypatch) -> None:
    engine = RetrievalEngine()
    index = _CountingIndex()

    async def _no_vectors(*_args, **_kwargs):
        return []

    monkeypatch.setattr(engine, "_vector_search", _no_vectors)
    params = _SearchParams(db=db_session, query="redis 集群", workspace_id=None)

    await engine._dual_recall(
        params,
        index,
        analyze_query("redis 集群"),
        (0, None, 0),  # type: ignore[arg-type]
    )

    assert index.calls >= 1
