"""性能基准运行器（规格 10.1-10.2）。

测试检索管线在大规模数据下的延迟：
  - 规模：10K、50K、100K、500K、1M 条记忆
  - 管线：BM25、向量（模拟）、RRF、Rerank、Context、完整 memory_context
  - SLA 目标（规格 10.2，10K 规模）：
      检索 p50 < 150ms、p95 < 500ms、p99 < 1s
      Context p95 < 200ms
      memory_context p95 < 700ms

用法：
    python -m benchmarks.performance.perf_runner [--scale 10000] [--queries 100]
"""

from __future__ import annotations

import json
import logging
import random
import string
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.retrieval.bm25 import BM25Index
from packages.retrieval.context.assembler import assemble_context
from packages.retrieval.query.analyzer import analyze_query
from packages.retrieval.ranking.diversity import apply_diversity
from packages.retrieval.ranking.reranker import RerankInput, rerank
from packages.retrieval.ranking.temporal import temporal_score

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "performance"

SCALES = [10_000, 50_000, 100_000, 500_000, 1_000_000]
PIPELINES = ["bm25", "vector", "rrf", "rerank", "context", "full_memory_context"]

MEMORY_TYPES = ["fact", "decision", "constraint", "lesson", "feedback", "preference"]

SAMPLE_QUERIES = [
    "how to configure database connection",
    "authentication middleware setup",
    "avoid using deprecated API endpoints",
    "project coding style conventions",
    "deployment pipeline configuration",
    "error handling best practices",
    "memory retrieval optimization",
    "test coverage requirements",
    "API rate limiting rules",
    "logging format standards",
]


@dataclass
class SyntheticMemory:
    id: str
    title: str
    content: str
    type: str
    confidence: float
    importance: float
    usage_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "type": self.type,
            "confidence": self.confidence,
            "importance": self.importance,
            "usage_count": self.usage_count,
        }


@dataclass
class StageLatency:
    pipeline: str
    latency_ms: float

    def to_dict(self) -> dict:
        return {"pipeline": self.pipeline, "latency_ms": round(self.latency_ms, 2)}


@dataclass
class ScaleResult:
    scale: int
    total_memories: int
    queries_run: int
    stage_latencies: list[StageLatency] = field(default_factory=list)
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "scale": self.scale,
            "total_memories": self.total_memories,
            "queries_run": self.queries_run,
            "stages": [s.to_dict() for s in self.stage_latencies],
            "full_pipeline": {
                "p50_ms": round(self.p50_ms, 2),
                "p95_ms": round(self.p95_ms, 2),
                "p99_ms": round(self.p99_ms, 2),
            },
        }


def generate_synthetic_memories(count: int, seed: int = 42) -> list[SyntheticMemory]:
    rng = random.Random(seed)
    memories: list[SyntheticMemory] = []

    topics = [
        "database",
        "authentication",
        "API",
        "testing",
        "deployment",
        "configuration",
        "logging",
        "error handling",
        "performance",
        "security",
        "caching",
        "migration",
        "schema",
        "middleware",
        "routing",
        "validation",
        "serialization",
        "monitoring",
    ]
    actions = [
        "configure",
        "setup",
        "implement",
        "avoid",
        "ensure",
        "use",
        "prefer",
        "never",
        "always",
        "require",
    ]
    nouns = [
        "connection pool",
        "token refresh",
        "endpoint",
        "test case",
        "pipeline",
        "environment variable",
        "log level",
        "exception",
        "query plan",
        "access control",
        "cache key",
        "data migration",
        "table schema",
        "request handler",
        "input check",
        "JSON format",
        "health check",
    ]

    for i in range(count):
        mem_id = str(uuid.UUID(int=i))
        topic = rng.choice(topics)
        action = rng.choice(actions)
        noun = rng.choice(nouns)
        title = f"{action} {topic} {noun}"
        words = [rng.choice(string.ascii_lowercase) for _ in range(rng.randint(20, 80))]
        content = f"{topic} {noun} {' '.join(words)}"

        memories.append(
            SyntheticMemory(
                id=mem_id,
                title=title,
                content=content,
                type=rng.choice(MEMORY_TYPES),
                confidence=rng.uniform(0.3, 1.0),
                importance=rng.uniform(0.1, 1.0),
                usage_count=rng.randint(0, 200),
            )
        )

    return memories


def generate_queries(count: int, seed: int = 42) -> list[str]:
    rng = random.Random(seed)
    queries: list[str] = []
    for _ in range(count):
        base = rng.choice(SAMPLE_QUERIES)
        if rng.random() > 0.5:
            suffix = rng.choice(
                ["in production", "for new users", "on staging", "with retry", "v2"]
            )
            queries.append(f"{base} {suffix}")
        else:
            queries.append(base)
    return queries


def benchmark_bm25(index: BM25Index, queries: list[str]) -> list[float]:
    latencies: list[float] = []
    for q in queries:
        t0 = time.monotonic()
        index.search(q, top_k=50)
        latencies.append((time.monotonic() - t0) * 1000)
    return latencies


def benchmark_rrf(
    bm25_results: list[tuple[str, float]],
    random_results: list[tuple[str, float]],
) -> float:
    rrf_k = 60
    t0 = time.monotonic()
    rrf_scores: dict[str, float] = {}
    for rank, (doc_id, _) in enumerate(bm25_results, 1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    for rank, (doc_id, _) in enumerate(random_results, 1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
    sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return (time.monotonic() - t0) * 1000


def benchmark_rerank(
    memories: list[SyntheticMemory],
    query: str,
    top_k: int = 30,
) -> float:
    analyzed = analyze_query(query)
    t0 = time.monotonic()
    inputs: list[RerankInput] = []
    for m in memories[:top_k]:
        inputs.append(
            RerankInput(
                memory_id=m.id,
                title=m.title,
                content=m.content,
                memory_type=m.type,
                bm25_score=0.5,
                vector_score=0.5,
                rrf_score=0.01,
                confidence=m.confidence,
                importance=m.importance,
                freshness=temporal_score(None, None, None, None),
                usage_score=min(m.usage_count / 100.0, 1.0),
            )
        )
    rerank(inputs, query_intent=analyzed.intent, top_k=20)
    return (time.monotonic() - t0) * 1000


def benchmark_context(memories: list[dict], query: str) -> float:
    t0 = time.monotonic()
    assemble_context(memories, query=query, max_tokens=5000)
    return (time.monotonic() - t0) * 1000


def benchmark_full_pipeline(
    index: BM25Index,
    memories: list[SyntheticMemory],
    queries: list[str],
) -> list[float]:
    mem_map = {m.id: m for m in memories}
    latencies: list[float] = []

    for q in queries:
        t0 = time.monotonic()

        bm25_results = index.search(q, top_k=50)
        simulated_vector = [(m.id, random.random()) for m in memories[:50]]

        rrf_scores: dict[str, float] = {}
        for rank, (doc_id, _) in enumerate(bm25_results, 1):
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank)
        for rank, (doc_id, _) in enumerate(simulated_vector, 1):
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (60 + rank)

        sorted_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        top_ids = [doc_id for doc_id, _ in sorted_candidates[:30]]

        analyzed = analyze_query(q)
        rerank_inputs: list[RerankInput] = []
        for doc_id in top_ids:
            m = mem_map.get(doc_id)
            if not m:
                continue
            rerank_inputs.append(
                RerankInput(
                    memory_id=m.id,
                    title=m.title,
                    content=m.content,
                    memory_type=m.type,
                    bm25_score=0.5,
                    vector_score=0.5,
                    rrf_score=rrf_scores.get(doc_id, 0.0),
                    confidence=m.confidence,
                    importance=m.importance,
                    freshness=temporal_score(None, None, None, None),
                    usage_score=min(m.usage_count / 100.0, 1.0),
                )
            )

        reranked = rerank(rerank_inputs, query_intent=analyzed.intent, top_k=20)

        ranked_with_type = [
            (mid, score, mem_map[mid].type) for mid, score in reranked if mid in mem_map
        ]
        diverse = apply_diversity(ranked_with_type, top_k=10, max_per_type=3)

        final_dicts = [mem_map[mid].to_dict() for mid, _, _ in diverse if mid in mem_map]
        assemble_context(final_dicts, query=q, max_tokens=5000)

        latencies.append((time.monotonic() - t0) * 1000)

    return latencies


def compute_percentiles(latencies: list[float]) -> tuple[float, float, float]:
    if not latencies:
        return 0.0, 0.0, 0.0
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    p50 = sorted_lat[int(n * 0.50)]
    p95 = sorted_lat[min(int(n * 0.95), n - 1)]
    p99 = sorted_lat[min(int(n * 0.99), n - 1)]
    return p50, p95, p99


def run_scale_benchmark(
    scale: int,
    num_queries: int = 20,
    seed: int = 42,
) -> ScaleResult:
    logger.info("Generating %d synthetic memories...", scale)
    memories = generate_synthetic_memories(scale, seed=seed)
    queries = generate_queries(num_queries, seed=seed)

    result = ScaleResult(scale=scale, total_memories=len(memories), queries_run=num_queries)

    logger.info("Building BM25 index for %d memories...", scale)
    t0 = time.monotonic()
    index = BM25Index()
    for m in memories:
        index.add(m.id, f"{m.title} {m.content}")
    index.build()
    build_time = (time.monotonic() - t0) * 1000
    result.stage_latencies.append(StageLatency("index_build", build_time))

    logger.info("Benchmarking BM25 search...")
    bm25_lats = benchmark_bm25(index, queries)
    p50, p95, p99 = compute_percentiles(bm25_lats)
    result.stage_latencies.append(StageLatency("bm25_p50", p50))
    result.stage_latencies.append(StageLatency("bm25_p95", p95))
    result.stage_latencies.append(StageLatency("bm25_p99", p99))

    logger.info("Benchmarking RRF fusion...")
    rrf_lats: list[float] = []
    for q in queries:
        bm25_res = index.search(q, top_k=50)
        vec_res = [(m.id, random.random()) for m in memories[:50]]
        rrf_lats.append(benchmark_rrf(bm25_res, vec_res))
    p50, p95, p99 = compute_percentiles(rrf_lats)
    result.stage_latencies.append(StageLatency("rrf_p50", p50))
    result.stage_latencies.append(StageLatency("rrf_p95", p95))
    result.stage_latencies.append(StageLatency("rrf_p99", p99))

    logger.info("Benchmarking rerank...")
    rerank_lats: list[float] = []
    for q in queries:
        top_mems = memories[:30]
        rerank_lats.append(benchmark_rerank(top_mems, q))
    p50, p95, p99 = compute_percentiles(rerank_lats)
    result.stage_latencies.append(StageLatency("rerank_p50", p50))
    result.stage_latencies.append(StageLatency("rerank_p95", p95))
    result.stage_latencies.append(StageLatency("rerank_p99", p99))

    logger.info("Benchmarking context assembly...")
    ctx_lats: list[float] = []
    for q in queries:
        mem_dicts = [m.to_dict() for m in memories[:20]]
        ctx_lats.append(benchmark_context(mem_dicts, q))
    p50, p95, p99 = compute_percentiles(ctx_lats)
    result.stage_latencies.append(StageLatency("context_p50", p50))
    result.stage_latencies.append(StageLatency("context_p95", p95))
    result.stage_latencies.append(StageLatency("context_p99", p99))

    logger.info("Benchmarking full pipeline...")
    full_lats = benchmark_full_pipeline(index, memories, queries)
    result.p50_ms, result.p95_ms, result.p99_ms = compute_percentiles(full_lats)

    return result


def run_all_scales(
    num_queries: int = 20,
    max_scale: int | None = None,
) -> list[ScaleResult]:
    scales = SCALES
    if max_scale:
        scales = [s for s in SCALES if s <= max_scale]

    results: list[ScaleResult] = []
    for scale in scales:
        logger.info("=== Running benchmark at scale %d ===", scale)
        result = run_scale_benchmark(scale, num_queries=num_queries)
        results.append(result)
        logger.info(
            "  Full pipeline: p50=%.2fms p95=%.2fms p99=%.2fms",
            result.p50_ms,
            result.p95_ms,
            result.p99_ms,
        )

    return results


def save_performance_report(results: list[ScaleResult], output_dir: Path | None = None) -> Path:
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "benchmark": "performance",
        "spec": "10.1-10.2",
        "scales_tested": [r.scale for r in results],
        "results": [r.to_dict() for r in results],
    }

    json_path = output_dir / "performance-report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    md_path = output_dir / "performance-report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_format_performance_md(results))

    return json_path


def _format_performance_md(results: list[ScaleResult]) -> str:
    lines = [
        "# Performance Benchmark Report (spec 10.1-10.2)",
        "",
        "## SLA Targets (10K scale)",
        "",
        "| Metric | Target |",
        "|--------|--------|",
        "| Retrieval p50 | < 150ms |",
        "| Retrieval p95 | < 500ms |",
        "| Retrieval p99 | < 1s |",
        "| Context p95 | < 200ms |",
        "| memory_context p95 | < 700ms |",
        "",
        "## Results by Scale",
        "",
    ]

    for r in results:
        lines.append(f"### Scale: {r.scale:,} memories")
        lines.append("")
        lines.append("| Stage | p50 (ms) | p95 (ms) | p99 (ms) |")
        lines.append("|-------|----------|----------|----------|")

        stage_groups: dict[str, dict[str, float]] = {}
        for s in r.stage_latencies:
            parts = s.pipeline.rsplit("_", 1)
            if len(parts) == 2 and parts[1] in ("p50", "p95", "p99"):
                name, pct = parts
                if name not in stage_groups:
                    stage_groups[name] = {}
                stage_groups[name][pct] = s.latency_ms

        for name, pcts in stage_groups.items():
            lines.append(
                f"| {name} | {pcts.get('p50', 0):.2f} | {pcts.get('p95', 0):.2f} | {pcts.get('p99', 0):.2f} |"
            )

        lines.append("")
        lines.append(
            f"**Full pipeline**: p50={r.p50_ms:.2f}ms  p95={r.p95_ms:.2f}ms  p99={r.p99_ms:.2f}ms"
        )
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Performance benchmark runner")
    parser.add_argument("--scale", type=int, default=None, help="Max scale to test")
    parser.add_argument("--queries", type=int, default=20, help="Number of queries per scale")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    results = run_all_scales(num_queries=args.queries, max_scale=args.scale)
    path = save_performance_report(results)
    logger.info("Report saved to %s", path)
