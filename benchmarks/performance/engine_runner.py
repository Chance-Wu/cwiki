"""引擎级性能基准：真实 RetrievalEngine + 真实 SQLite（区别于纯内存的 perf_runner）。

perf_runner 只覆盖 BM25/RRF/rerank 等纯计算阶段，从不触碰
``RetrievalEngine.search_ranked``、内容指纹聚合、trace 写路径与 SQLite——
引擎层的结构性成本（指纹扫描、写后全量重建、trace 写放大）此前不可测量。

本运行器在临时 SQLite 库中按目标规模生成合成记忆（复用 perf_runner 语料），
对真实引擎测量四类成本：
  1. fingerprint：内容指纹聚合查询单独耗时（每次请求一次）
  2. cold_build：冷缓存首次查询（含 BM25 全量构建 + jieba 分词）
  3. steady_traced / steady_untraced：连续查询（traced 路径含 usage 回写与 trace 落库）
  4. write_spike：写入 10 条记忆后的首次查询

用法：
    python -m benchmarks.performance.engine_runner [--scale 10000] [--queries 20] \
        [--corpus zh|en|mixed] [--label baseline] [--no-embeddings]

报告输出 benchmarks/reports/performance/engine-report[-label].{json,md}。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchmarks.performance.perf_runner import (
    compute_percentiles,
    generate_queries,
    generate_synthetic_memories,
)
from packages.domain.models import Memory, Workspace
from packages.domain.models.base import Base
from packages.retrieval.engine import get_retrieval_engine

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "reports" / "performance"

# 单独测量的指纹聚合采样次数（其余阶段的查询数由 --queries 控制）
_FINGERPRINT_SAMPLES = 30
# write_spike 阶段每次写入的记忆条数
_WRITE_BATCH = 10


def _percentiles(samples: list[float]) -> dict[str, float]:
    p50, p95, p99 = compute_percentiles(samples)
    return {"p50_ms": round(p50, 2), "p95_ms": round(p95, 2), "p99_ms": round(p99, 2)}


async def _build_fixture(
    db_path: Path,
    scale: int,
    corpus: str,
    with_embeddings: bool,
) -> uuid.UUID:
    """生成临时基准库：1 个工作区 + scale 条 active 记忆，返回 workspace_id。

    with_embeddings 时同时写出生产行为的文件向量索引
    （``vectors.npz``，与 DB 同目录），基准按生产路径装配向量来源。
    """
    from packages.domain.config import settings
    from packages.retrieval.embedding import get_embedding_service
    from packages.storage.vector_index import VectorIndex

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    workspace_id = uuid.uuid5(uuid.NAMESPACE_URL, "engine-bench")
    memories = generate_synthetic_memories(scale, corpus=corpus)
    # 批量生成真实向量（仅影响向量路相关性；计时对向量取值不敏感，
    # 模型不可用时退回 hash 向量同样可测量）
    embeddings: list[list[float] | None] = [None] * scale
    if with_embeddings:
        service = get_embedding_service()
        await service.warm_up()
        logger.info("Generating embeddings for %d memories...", scale)
        texts = [f"{m.title}\n{m.content}" for m in memories]
        for start in range(0, scale, 256):
            chunk = texts[start : start + 256]
            vectors = await service.generate_embeddings_batch(chunk)
            embeddings[start : start + 256] = vectors
            if (start // 256) % 10 == 0:
                logger.info("  embeddings %d / %d", start, scale)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        db.add(Workspace(id=workspace_id, name="engine-bench"))
        for i, m in enumerate(memories):
            db.add(
                Memory(
                    id=uuid.UUID(m.id),
                    workspace_id=workspace_id,
                    title=m.title,
                    content=m.content,
                    type=m.type,
                    status="active",
                    confidence=m.confidence,
                    importance=m.importance,
                    usage_count=m.usage_count,
                    source="benchmark",
                    tags=[],
                    embedding=embeddings[i],
                )
            )
        await db.commit()
        if with_embeddings:
            vector_index = VectorIndex(
                dimensions=settings.embedding_dimensions,
                index_path=str(db_path.with_suffix(".vectors.npz")),
                model=settings.embedding_model,
            )
            for i, m in enumerate(memories):
                if embeddings[i] is not None:
                    vector_index.add(m.id, embeddings[i])
            vector_index.save()
    await engine.dispose()
    logger.info("Fixture ready: %s (%d memories, embeddings=%s)", db_path, scale, with_embeddings)
    return workspace_id


async def _run_benchmark(
    db_path: Path,
    workspace_id: uuid.UUID,
    queries: list[str],
) -> dict[str, Any]:
    from packages.domain.config import settings
    from packages.storage.vector_index import VectorIndex

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    bench = get_retrieval_engine()

    # 生产同款装配：向量取自文件索引（无文件时引擎走 legacy DB 列路径）
    vector_path = db_path.with_suffix(".vectors.npz")
    if vector_path.exists():
        file_index = VectorIndex(
            dimensions=settings.embedding_dimensions,
            index_path=str(vector_path),
            model=settings.embedding_model,
        )
        bench.set_vector_source(lambda: file_index)

    async with maker() as db:
        stages: dict[str, list[float]] = {
            "fingerprint_aggregate": [],
            "cold_build": [],
            "steady_traced": [],
            "steady_untraced": [],
            "write_spike_first": [],
            "write_spike_second": [],
        }

        # 1) 指纹聚合单独耗时
        for _ in range(_FINGERPRINT_SAMPLES):
            t0 = time.perf_counter()
            await bench._content_fingerprint(db, workspace_id, None)
            stages["fingerprint_aggregate"].append((time.perf_counter() - t0) * 1000)

        # 2) 冷缓存首次查询（含全量 BM25 构建）
        t0 = time.perf_counter()
        await bench.search_ranked(
            db=db, query=queries[0], workspace_id=workspace_id, top_k=10, record_trace=True
        )
        await db.commit()
        stages["cold_build"].append((time.perf_counter() - t0) * 1000)

        # 3) 稳态查询：traced（含 usage 回写 + trace 落库）与 untraced 各一轮
        for label, record_trace in (("steady_traced", True), ("steady_untraced", False)):
            for query in queries[1:]:
                t0 = time.perf_counter()
                await bench.search_ranked(
                    db=db,
                    query=query,
                    workspace_id=workspace_id,
                    top_k=10,
                    record_trace=record_trace,
                )
                await db.commit()
                stages[label].append((time.perf_counter() - t0) * 1000)

        # 4) 写入尖峰：插入 10 条后立即查询（记录第一次与随后的第二次）
        for query in queries[:_WRITE_BATCH]:
            db.add(
                Memory(
                    workspace_id=workspace_id,
                    title=f"新增 {query}",
                    content=f"基准写入：{query}。附加说明以增加内容长度。",
                    type="fact",
                    status="active",
                    source="benchmark",
                )
            )
        await db.commit()
        t0 = time.perf_counter()
        await bench.search_ranked(
            db=db, query=queries[1], workspace_id=workspace_id, top_k=10, record_trace=True
        )
        await db.commit()
        stages["write_spike_first"].append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        await bench.search_ranked(
            db=db, query=queries[2], workspace_id=workspace_id, top_k=10, record_trace=True
        )
        await db.commit()
        stages["write_spike_second"].append((time.perf_counter() - t0) * 1000)

    await engine.dispose()

    return {
        "benchmark": "engine",
        "generated_at": datetime.now(UTC).isoformat(),
        "queries": len(queries),
        "fingerprint_aggregate_mean_ms": round(statistics.mean(stages["fingerprint_aggregate"]), 3),
        "stages": {name: _percentiles(samples) for name, samples in stages.items()},
    }


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Engine Benchmark Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- label: {report.get('label', '-')}",
        f"- scale: {report.get('scale', '-')}",
        f"- queries: {report['queries']}",
        f"- fingerprint_aggregate_mean: {report['fingerprint_aggregate_mean_ms']} ms",
        "",
        "| Stage | p50 (ms) | p95 (ms) | p99 (ms) |",
        "|-------|----------|----------|----------|",
    ]
    for name, pct in report["stages"].items():
        lines.append(f"| {name} | {pct['p50_ms']} | {pct['p95_ms']} | {pct['p99_ms']} |")
    return "\n".join(lines)


async def run(scale: int, queries_count: int, corpus: str, label: str, embeddings: bool) -> Path:
    queries = generate_queries(queries_count + _WRITE_BATCH, corpus=corpus)
    with tempfile.TemporaryDirectory(prefix="engine-bench-") as tmp:
        db_path = Path(tmp) / "engine-bench.db"
        workspace_id = await _build_fixture(db_path, scale, corpus, embeddings)
        report = await _run_benchmark(db_path, workspace_id, queries)
    report["scale"] = scale
    report["label"] = label

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"-{label}" if label else ""
    json_path = REPORTS_DIR / f"engine-report{suffix}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (REPORTS_DIR / f"engine-report{suffix}.md").write_text(_format_md(report), encoding="utf-8")
    logger.info("Report saved to %s", json_path)
    return json_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Engine-level performance benchmark")
    parser.add_argument("--scale", type=int, default=10_000, help="Number of synthetic memories")
    parser.add_argument("--queries", type=int, default=20, help="Number of steady-state queries")
    parser.add_argument("--corpus", choices=("en", "zh", "mixed"), default="zh")
    parser.add_argument("--label", default="", help="报告标记（如 baseline / optimized）")
    parser.add_argument(
        "--no-embeddings", action="store_true", help="跳过向量生成（仅测 BM25/指纹/trace 路径）"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run(args.scale, args.queries, args.corpus, args.label, not args.no_embeddings))
