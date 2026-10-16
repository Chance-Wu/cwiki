"""性能基准框架测试（spec 10.1-10.2）。"""

import pytest

from benchmarks.performance.perf_runner import (
    PIPELINES,
    SCALES,
    ScaleResult,
    StageLatency,
    benchmark_bm25,
    benchmark_context,
    benchmark_full_pipeline,
    benchmark_rerank,
    benchmark_rrf,
    compute_percentiles,
    generate_queries,
    generate_synthetic_memories,
)
from packages.retrieval.bm25 import BM25Index


class TestSpecConstants:
    def test_scales_defined(self):
        assert 10_000 in SCALES
        assert 50_000 in SCALES
        assert 100_000 in SCALES
        assert 500_000 in SCALES
        assert 1_000_000 in SCALES

    def test_pipelines_defined(self):
        assert "bm25" in PIPELINES
        assert "vector" in PIPELINES
        assert "rrf" in PIPELINES
        assert "rerank" in PIPELINES
        assert "context" in PIPELINES
        assert "full_memory_context" in PIPELINES


class TestSyntheticData:
    def test_generate_memories_count(self):
        memories = generate_synthetic_memories(100)
        assert len(memories) == 100

    def test_generate_memories_unique_ids(self):
        memories = generate_synthetic_memories(50)
        ids = [m.id for m in memories]
        assert len(set(ids)) == 50

    def test_generate_memories_valid_types(self):
        memories = generate_synthetic_memories(50)
        valid_types = {"fact", "decision", "constraint", "lesson", "feedback", "preference"}
        for m in memories:
            assert m.type in valid_types

    def test_generate_memories_to_dict(self):
        memories = generate_synthetic_memories(5)
        d = memories[0].to_dict()
        assert "id" in d
        assert "title" in d
        assert "content" in d
        assert "type" in d

    def test_generate_queries_count(self):
        queries = generate_queries(30)
        assert len(queries) == 30

    def test_generate_queries_non_empty(self):
        queries = generate_queries(10)
        for q in queries:
            assert len(q.strip()) > 0

    def test_deterministic_with_seed(self):
        m1 = generate_synthetic_memories(20, seed=123)
        m2 = generate_synthetic_memories(20, seed=123)
        assert [m.id for m in m1] == [m.id for m in m2]
        assert [m.title for m in m1] == [m.title for m in m2]


class TestBenchmarkStages:
    @pytest.fixture
    def small_index(self):
        memories = generate_synthetic_memories(100)
        index = BM25Index()
        for m in memories:
            index.add(m.id, f"{m.title} {m.content}")
        index.build()
        return index, memories

    def test_benchmark_bm25_returns_latencies(self, small_index):
        index, _ = small_index
        queries = ["database", "testing"]
        latencies = benchmark_bm25(index, queries)
        assert len(latencies) == 2
        assert all(lat >= 0 for lat in latencies)

    def test_benchmark_rrf_returns_latency(self, small_index):
        index, memories = small_index
        bm25_res = index.search("database", top_k=50)
        vec_res = [(m.id, 0.5) for m in memories[:50]]
        latency = benchmark_rrf(bm25_res, vec_res)
        assert latency >= 0

    def test_benchmark_rerank_returns_latency(self, small_index):
        _, memories = small_index
        latency = benchmark_rerank(memories[:30], "database connection")
        assert latency >= 0

    def test_benchmark_context_returns_latency(self, small_index):
        _, memories = small_index
        mem_dicts = [m.to_dict() for m in memories[:10]]
        latency = benchmark_context(mem_dicts, "test query")
        assert latency >= 0

    def test_benchmark_full_pipeline(self, small_index):
        index, memories = small_index
        queries = ["database", "testing"]
        latencies = benchmark_full_pipeline(index, memories, queries)
        assert len(latencies) == 2
        assert all(lat >= 0 for lat in latencies)


class TestPercentiles:
    def test_compute_percentiles(self):
        latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        p50, p95, p99 = compute_percentiles(latencies)
        assert p50 == 60
        assert p95 == 100
        assert p99 == 100

    def test_empty_latencies(self):
        p50, p95, p99 = compute_percentiles([])
        assert p50 == 0.0
        assert p95 == 0.0
        assert p99 == 0.0

    def test_single_value(self):
        p50, p95, p99 = compute_percentiles([42.0])
        assert p50 == 42.0
        assert p95 == 42.0
        assert p99 == 42.0


class TestScaleResult:
    def test_to_dict(self):
        result = ScaleResult(
            scale=10000,
            total_memories=10000,
            queries_run=20,
            stage_latencies=[
                StageLatency("bm25_p50", 5.0),
                StageLatency("bm25_p95", 15.0),
            ],
            p50_ms=50.0,
            p95_ms=120.0,
            p99_ms=200.0,
        )
        d = result.to_dict()
        assert d["scale"] == 10000
        assert d["total_memories"] == 10000
        assert d["queries_run"] == 20
        assert len(d["stages"]) == 2
        assert d["full_pipeline"]["p50_ms"] == 50.0
        assert d["full_pipeline"]["p95_ms"] == 120.0
        assert d["full_pipeline"]["p99_ms"] == 200.0
