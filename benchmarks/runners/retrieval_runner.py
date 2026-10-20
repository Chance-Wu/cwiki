"""检索基准运行器。

支持对比以下 pipeline：
  - baseline_bm25
  - baseline_vector
  - hybrid_rrf
  - hybrid_rrf_rerank
  - full_pipeline

用法：
    python -m benchmarks.runners.retrieval_runner [--pipeline PIPELINE] [--dataset PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from benchmarks.evaluators.retrieval import (
    BenchmarkReport,
    QueryJudgment,
    QueryMetrics,
    RetrievalResult,
    aggregate_report,
    evaluate_query,
    format_report_md,
)
from packages.domain.config import settings
from packages.domain.database import async_session_maker
from packages.domain.models import Memory
from packages.retrieval.bm25 import BM25Index
from packages.retrieval.embedding import get_embedding_service
from packages.retrieval.engine import RRF_K
from packages.retrieval.query.analyzer import analyze_query
from packages.retrieval.ranking.diversity import apply_diversity
from packages.retrieval.ranking.reranker import RerankInput, rerank
from packages.retrieval.ranking.temporal import temporal_score

logger = logging.getLogger(__name__)


def _quiet_sql_logging() -> None:
    """评测时关闭 SQL 回显日志（config.yaml 的 debug: true 会打开 engine echo）。"""
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def make_session_maker(db_url: str) -> async_sessionmaker[AsyncSession]:
    """按指定数据库 URL 创建独立会话工厂（用于合成评测夹具，不碰全局引擎）。"""
    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


PIPELINES = [
    "baseline_bm25",
    "baseline_vector",
    "hybrid_rrf",
    "hybrid_rrf_rerank",
    "full_pipeline",
]

DATASETS_DIR = Path(__file__).parent.parent / "datasets"
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def load_gold_dataset(path: Path) -> list[QueryJudgment]:
    judgments: dict[str, QueryJudgment] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            qid = record["query_id"]
            if qid not in judgments:
                judgments[qid] = QueryJudgment(
                    query_id=qid,
                    query=record["query"],
                    judgments={},
                )
            judgments[qid].judgments[record["memory_id"]] = record["relevance"]
    return list(judgments.values())


async def _load_memories(db: AsyncSession, workspace_id: uuid.UUID) -> list[Memory]:
    stmt = select(Memory).where(
        Memory.status == "active",
        Memory.workspace_id == workspace_id,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _bm25_search(index: BM25Index, query: str, top_k: int = 50) -> list[tuple[str, float]]:
    return index.search(query, top_k=top_k)


async def _vector_search(
    db: AsyncSession, query: str, workspace_id: uuid.UUID, top_k: int = 50
) -> list[tuple[str, float]]:
    embedding_svc = get_embedding_service()
    query_embedding = await embedding_svc.generate_embedding(query)
    if query_embedding is None:
        return []

    try:
        import numpy as np
        from sqlalchemy import select

        stmt = select(Memory.id, Memory.embedding).where(
            Memory.status == "active",
            Memory.workspace_id == workspace_id,
            Memory.embedding.isnot(None),
        )
        result = await db.execute(stmt)

        scored: list[tuple[str, float]] = []
        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)

        for row in result:
            if row.embedding:
                e = np.array(row.embedding, dtype=np.float32)
                e_norm = np.linalg.norm(e)
                if q_norm > 0 and e_norm > 0:
                    similarity = float(np.dot(q, e) / (q_norm * e_norm))
                    scored.append((str(row.id), similarity))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
    except Exception as e:
        logger.error("Vector search failed: %s", e)
        return []


def _rrf_fusion(
    bm25_results: list[tuple[str, float]],
    vector_results: list[tuple[str, float]],
    bm25_w: float,
    vec_w: float,
) -> dict[str, float]:
    """加权 RRF 融合，与生产 engine 一致（config.yaml 的 bm25_weight/vector_weight）。"""
    rrf_scores: dict[str, float] = {}
    for rank, (doc_id, _) in enumerate(bm25_results, 1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + bm25_w / (RRF_K + rank)
    for rank, (doc_id, _) in enumerate(vector_results, 1):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + vec_w / (RRF_K + rank)
    return rrf_scores


async def run_pipeline(
    pipeline: str,
    query: str,
    workspace_id: uuid.UUID,
    bm25_index: BM25Index,
    memories: list[Memory],
    db: AsyncSession,
    max_items: int = 20,
) -> tuple[list[str], int]:
    start = time.time()
    mem_map = {str(m.id): m for m in memories}

    if pipeline == "baseline_bm25":
        results = await _bm25_search(bm25_index, query, top_k=max_items)
        ranked = [doc_id for doc_id, _ in results[:max_items]]
        latency = int((time.time() - start) * 1000)
        return ranked, latency

    if pipeline == "baseline_vector":
        results = await _vector_search(db, query, workspace_id, top_k=max_items)
        ranked = [doc_id for doc_id, _ in results[:max_items]]
        latency = int((time.time() - start) * 1000)
        return ranked, latency

    bm25_results = await _bm25_search(bm25_index, query, top_k=50)
    vector_results = await _vector_search(db, query, workspace_id, top_k=50)
    rrf_scores = _rrf_fusion(
        bm25_results, vector_results, settings.bm25_weight, settings.vector_weight
    )

    if pipeline == "hybrid_rrf":
        sorted_ids = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        ranked = [doc_id for doc_id, _ in sorted_ids[:max_items]]
        latency = int((time.time() - start) * 1000)
        return ranked, latency

    sorted_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    top_ids = [doc_id for doc_id, _ in sorted_candidates[: max_items * 3]]

    analyzed = analyze_query(query)

    rerank_inputs: list[RerankInput] = []
    for doc_id in top_ids:
        m = mem_map.get(doc_id)
        if not m:
            continue
        freshness = temporal_score(
            valid_from=m.valid_from,
            valid_to=m.valid_to,
            created_at=m.created_at,
            last_used_at=m.last_used_at,
            ignore_expiry=analyzed.is_historical_query,
        )
        usage_score = min(m.usage_count / 100.0, 1.0) if m.usage_count else 0.0

        bm25_score = 0.0
        for rank, (did, s) in enumerate(bm25_results, 1):
            if did == doc_id:
                bm25_score = s
                break

        vector_score = 0.0
        for rank, (did, s) in enumerate(vector_results, 1):
            if did == doc_id:
                vector_score = s
                break

        rerank_inputs.append(
            RerankInput(
                memory_id=doc_id,
                title=m.title,
                content=m.content,
                memory_type=m.type,
                bm25_score=bm25_score,
                vector_score=vector_score,
                rrf_score=rrf_scores.get(doc_id, 0.0),
                confidence=m.confidence,
                importance=m.importance,
                freshness=freshness,
                usage_score=usage_score,
            )
        )

    reranked = rerank(
        rerank_inputs,
        query_intent=analyzed.intent,
        intent_confidence=analyzed.confidence,
        negations=analyzed.negations,
        key_terms=analyzed.key_terms,
        top_k=max_items * 2,
    )

    if pipeline == "hybrid_rrf_rerank":
        ranked = [mem_id for mem_id, _ in reranked[:max_items]]
        latency = int((time.time() - start) * 1000)
        return ranked, latency

    ranked_with_type: list[tuple[str, float, str]] = []
    for mem_id, score in reranked:
        m = mem_map.get(mem_id)
        if m:
            ranked_with_type.append((mem_id, score, m.type))

    diverse = apply_diversity(ranked_with_type, top_k=max_items, max_per_type=3)
    ranked = [item[0] for item in diverse]
    latency = int((time.time() - start) * 1000)
    return ranked, latency


async def run_benchmark(
    pipeline: str,
    judgments: list[QueryJudgment],
    workspace_id: uuid.UUID,
    session_maker: async_sessionmaker[AsyncSession] | None = None,
) -> BenchmarkReport:
    sm = session_maker or async_session_maker
    async with sm() as db:
        memories = await _load_memories(db, workspace_id)

        bm25_index = BM25Index()
        for m in memories:
            bm25_index.add(str(m.id), m.content, title=m.title)
        bm25_index.build()

        query_metrics: list[QueryMetrics] = []
        latencies: list[int] = []

        for judgment in judgments:
            ranked, latency = await run_pipeline(
                pipeline=pipeline,
                query=judgment.query,
                workspace_id=workspace_id,
                bm25_index=bm25_index,
                memories=memories,
                db=db,
            )
            result = RetrievalResult(
                query_id=judgment.query_id,
                ranked_memory_ids=ranked,
                latency_ms=latency,
            )
            qm = evaluate_query(result, judgment)
            query_metrics.append(qm)
            latencies.append(latency)

    return aggregate_report(pipeline, query_metrics, latencies)


def save_report(report: BenchmarkReport, output_dir: Path, prefix: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "pipeline": report.pipeline,
        "total_queries": report.total_queries,
        "recall_at_5": report.recall_at_5,
        "recall_at_10": report.recall_at_10,
        "recall_at_20": report.recall_at_20,
        "precision_at_5": report.precision_at_5,
        "precision_at_10": report.precision_at_10,
        "mrr": report.mrr,
        "ndcg_at_10": report.ndcg_at_10,
        "useful_at_10": report.useful_at_10,
        "avg_latency_ms": report.avg_latency_ms,
        "negative_probes": report.negative_probes,
        "negative_fp_rate_at_10": report.negative_fp_rate_at_10,
        "per_query": [
            {
                "query_id": qm.query_id,
                "recall_at_10": qm.recall_at_10,
                "precision_at_10": qm.precision_at_10,
                "mrr": qm.rr,
                "ndcg_at_10": qm.ndcg_at_10,
                "useful_at_10": qm.useful_at_10,
                "relevant_count": qm.relevant_count,
                "is_negative_probe": qm.is_negative_probe,
                "negative_fp_at_10": qm.negative_fp_at_10,
            }
            for qm in report.per_query
        ],
    }
    json_path = output_dir / f"{prefix}retrieval-report-{report.pipeline}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    md_path = output_dir / f"{prefix}retrieval-report-{report.pipeline}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(format_report_md(report))

    logger.info("Reports saved to %s", output_dir)


async def _get_workspace_by_name(db: AsyncSession, name: str) -> uuid.UUID | None:
    from packages.domain.models import Workspace

    stmt = select(Workspace.id).where(Workspace.name == name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_workspaces_with_memories(
    db: AsyncSession,
) -> list[tuple[uuid.UUID, str, int]]:
    from sqlalchemy import func

    from packages.domain.models import Workspace

    stmt = (
        select(Workspace.id, Workspace.name, func.count(Memory.id))
        .outerjoin(Memory, (Memory.workspace_id == Workspace.id) & (Memory.status == "active"))
        .group_by(Workspace.id, Workspace.name)
        .having(func.count(Memory.id) > 0)
    )
    result = await db.execute(stmt)
    return [(row.id, row.name, row[2]) for row in result]


async def main(
    pipeline: str | None = None,
    dataset_path: Path | None = None,
    workspace_id: str | None = None,
    workspace_name: str | None = None,
    all_workspaces: bool = False,
    db_url: str | None = None,
) -> list[BenchmarkReport]:
    _quiet_sql_logging()
    # 记录调用方是否显式指定数据集（决定报告目录：按数据集分目录避免覆盖默认报告）
    explicit_dataset = dataset_path
    pipelines = [pipeline] if pipeline else PIPELINES
    reports: list[BenchmarkReport] = []
    session_maker = make_session_maker(db_url) if db_url else async_session_maker

    if all_workspaces:
        async with session_maker() as db:
            workspaces = await _get_workspaces_with_memories(db)

        if not workspaces:
            logger.error("No workspaces with memories found")
            return []

        logger.info("Found %d workspaces with memories", len(workspaces))

        for ws_id, ws_name, mem_count in workspaces:
            ws_dataset = DATASETS_DIR / "retrieval" / f"{ws_name}.jsonl"
            if not ws_dataset.exists():
                logger.warning("No dataset for workspace '%s' at %s, skipping", ws_name, ws_dataset)
                continue

            judgments = load_gold_dataset(ws_dataset)
            if not judgments:
                logger.warning("Empty dataset for workspace '%s', skipping", ws_name)
                continue

            logger.info(
                "Workspace '%s': %d memories, %d queries", ws_name, mem_count, len(judgments)
            )

            for pl in pipelines:
                logger.info("  Running pipeline: %s", pl)
                report = await run_benchmark(pl, judgments, ws_id, session_maker=session_maker)
                reports.append(report)
                save_report(report, REPORTS_DIR / ws_name, prefix=f"{ws_name}-")

                logger.info(
                    "    Recall@10=%.4f  MRR=%.4f  NDCG@10=%.4f",
                    report.recall_at_10,
                    report.mrr,
                    report.ndcg_at_10,
                )

        _write_multi_workspace_comparison(reports, REPORTS_DIR / "pipeline-comparison.md")
        return reports

    if workspace_name and not dataset_path:
        dataset_path = DATASETS_DIR / "retrieval" / f"{workspace_name}.jsonl"
        if not dataset_path.exists():
            logger.error("Dataset not found: %s", dataset_path)
            return []

    if dataset_path is None:
        dataset_path = DATASETS_DIR / "retrieval" / "gold.jsonl"

    if not dataset_path.exists():
        logger.error("Gold dataset not found: %s", dataset_path)
        return []

    judgments = load_gold_dataset(dataset_path)
    if not judgments:
        logger.error("No queries in gold dataset")
        return []

    logger.info("Loaded %d queries from %s", len(judgments), dataset_path)

    if workspace_id is None and workspace_name:
        async with session_maker() as db:
            ws_id = await _get_workspace_by_name(db, workspace_name)
            if ws_id is None:
                logger.error("Workspace '%s' not found", workspace_name)
                return []
    elif workspace_id is None:
        async with session_maker() as db:
            from packages.domain.models import Workspace

            result = await db.execute(select(Workspace).limit(1))
            ws = result.scalars().first()
            if ws is None:
                logger.error("No workspace found. Create one first.")
                return []
            ws_id = ws.id
    else:
        ws_id = uuid.UUID(workspace_id)

    for pl in pipelines:
        logger.info("Running pipeline: %s", pl)
        report = await run_benchmark(pl, judgments, ws_id, session_maker=session_maker)
        reports.append(report)
        # 报告目录：显式数据集 → 按数据集名分目录；否则沿用 workspace 目录
        if explicit_dataset is not None:
            stem = explicit_dataset.stem
            save_report(report, REPORTS_DIR / stem, prefix=f"{stem}-")
        elif workspace_name:
            save_report(report, REPORTS_DIR / workspace_name, prefix=f"{workspace_name}-")
        else:
            save_report(report, REPORTS_DIR)

        logger.info(
            "  Recall@10=%.4f  MRR=%.4f  NDCG@10=%.4f  Useful@10=%.4f",
            report.recall_at_10,
            report.mrr,
            report.ndcg_at_10,
            report.useful_at_10,
        )

    if explicit_dataset is not None:
        out_dir = REPORTS_DIR / explicit_dataset.stem
    elif workspace_name:
        out_dir = REPORTS_DIR / workspace_name
    else:
        out_dir = REPORTS_DIR
    comparison_path = out_dir / "pipeline-comparison.md"
    _write_comparison(reports, comparison_path)

    return reports


def _write_comparison(reports: list[BenchmarkReport], path: Path) -> None:
    lines = [
        "# Pipeline Comparison",
        "",
        "| Pipeline | Recall@10 | Precision@10 | MRR | NDCG@10 | Useful@10 | Avg Latency (ms) |",
        "|----------|-----------|--------------|-----|---------|-----------|-------------------|",
    ]
    for r in reports:
        lines.append(
            f"| {r.pipeline} | {r.recall_at_10:.4f} | {r.precision_at_10:.4f} "
            f"| {r.mrr:.4f} | {r.ndcg_at_10:.4f} | {r.useful_at_10:.4f} "
            f"| {r.avg_latency_ms:.1f} |"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _write_multi_workspace_comparison(reports: list[BenchmarkReport], path: Path) -> None:
    """跨 workspace 汇总：按管线宏平均，并列出各 workspace 分项。"""
    by_pipeline: dict[str, list[BenchmarkReport]] = {}
    for r in reports:
        by_pipeline.setdefault(r.pipeline, []).append(r)

    lines = [
        "# Pipeline Comparison (All Workspaces, Macro-Average)",
        "",
        "| Pipeline | Recall@10 | Precision@10 | MRR | NDCG@10 | Useful@10 | Avg Latency (ms) |",
        "|----------|-----------|--------------|-----|---------|-----------|-------------------|",
    ]
    for pl in PIPELINES:
        pl_reports = by_pipeline.get(pl, [])
        if not pl_reports:
            continue
        n = len(pl_reports)
        lines.append(
            f"| {pl} "
            f"| {sum(r.recall_at_10 for r in pl_reports) / n:.4f} "
            f"| {sum(r.precision_at_10 for r in pl_reports) / n:.4f} "
            f"| {sum(r.mrr for r in pl_reports) / n:.4f} "
            f"| {sum(r.ndcg_at_10 for r in pl_reports) / n:.4f} "
            f"| {sum(r.useful_at_10 for r in pl_reports) / n:.4f} "
            f"| {sum(r.avg_latency_ms for r in pl_reports) / n:.1f} |"
        )

    lines.extend(["", "## Per-Workspace", ""])
    if path.parent.exists():
        for ws_dir in sorted(p for p in path.parent.iterdir() if p.is_dir()):
            lines.append(f"### {ws_dir.name}")
            lines.append("")
            lines.append(f"See `{ws_dir.name}/` for detailed reports.")
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval benchmark runner")
    parser.add_argument("--pipeline", choices=PIPELINES, default=None)
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--workspace-id", type=str, default=None)
    parser.add_argument("--workspace-name", type=str, default=None)
    parser.add_argument(
        "--all-workspaces",
        action="store_true",
        help="Run benchmarks for all workspaces with memories, using per-workspace datasets",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        help="Override database URL (e.g. sqlite+aiosqlite:///benchmarks/fixtures/eval_fixture.db)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        main(
            pipeline=args.pipeline,
            dataset_path=args.dataset,
            workspace_id=args.workspace_id,
            workspace_name=args.workspace_name,
            all_workspaces=args.all_workspaces,
            db_url=args.db_url,
        )
    )
