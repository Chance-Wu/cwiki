"""性能基准合成语料：英文/中文/混合的可复现性与基本结构。"""

from __future__ import annotations

import pytest

from benchmarks.performance.perf_runner import (
    generate_queries,
    generate_synthetic_memories,
    run_scale_benchmark,
)

CJK_START, CJK_END = "\u4e00", "\u9fff"


def _has_cjk(text: str) -> bool:
    return any(CJK_START <= ch <= CJK_END for ch in text)


def test_en_corpus_is_reproducible_and_ascii() -> None:
    first = generate_synthetic_memories(5, seed=7, corpus="en")
    second = generate_synthetic_memories(5, seed=7, corpus="en")

    assert [m.title for m in first] == [m.title for m in second]
    assert all(m.title.isascii() for m in first)


def test_zh_corpus_contains_cjk_titles_and_queries() -> None:
    memories = generate_synthetic_memories(20, seed=7, corpus="zh")
    queries = generate_queries(10, seed=7, corpus="zh")

    assert all(_has_cjk(m.title) for m in memories)
    assert all(_has_cjk(q) for q in queries)


def test_mixed_corpus_contains_both_languages() -> None:
    memories = generate_synthetic_memories(40, seed=7, corpus="mixed")
    zh_count = sum(_has_cjk(m.title) for m in memories)

    assert 0 < zh_count < len(memories)


def test_unknown_corpus_rejected() -> None:
    with pytest.raises(ValueError):
        generate_synthetic_memories(1, corpus="fr")


def test_zh_scale_benchmark_produces_all_stages() -> None:
    result = run_scale_benchmark(200, num_queries=3, corpus="zh")

    assert result.total_memories == 200
    stages = {stage.pipeline for stage in result.stage_latencies}
    assert {"index_build", "bm25_p95", "rrf_p95", "rerank_p95", "context_p95"} <= stages
