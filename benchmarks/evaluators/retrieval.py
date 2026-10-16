"""检索基准评测器，提供标准 IR 指标。

计算指标：Recall@K、Precision@K、MRR、NDCG@10、Useful@10。

相关性分级（见规格 4.3）：
  0 = 不相关
  1 = 弱相关
  2 = 相关
  3 = 直接有用
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class QueryJudgment:
    query_id: str
    query: str
    judgments: dict[str, int]  # memory_id -> relevance grade (0-3)


@dataclass
class RetrievalResult:
    query_id: str
    ranked_memory_ids: list[str]
    latency_ms: int = 0


@dataclass
class QueryMetrics:
    query_id: str
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_20: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    rr: float = 0.0
    ndcg_at_10: float = 0.0
    useful_at_10: float = 0.0
    relevant_count: int = 0


@dataclass
class BenchmarkReport:
    pipeline: str
    total_queries: int = 0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_20: float = 0.0
    precision_at_5: float = 0.0
    precision_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_10: float = 0.0
    useful_at_10: float = 0.0
    avg_latency_ms: float = 0.0
    per_query: list[QueryMetrics] = field(default_factory=list)


RELEVANCE_THRESHOLD = 2


def _relevant_ids(judgments: dict[str, int], threshold: int = RELEVANCE_THRESHOLD) -> set[str]:
    return {mid for mid, grade in judgments.items() if grade >= threshold}


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = set(ranked[:k])
    hit = top_k & relevant
    return len(hit) / len(relevant)


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    top_k = ranked[:k]
    if not top_k:
        return 0.0
    hit = sum(1 for mid in top_k if mid in relevant)
    return hit / k


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for i, mid in enumerate(ranked):
        if mid in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked: list[str], judgments: dict[str, int], k: int) -> float:
    gains = []
    for mid in ranked[:k]:
        grade = judgments.get(mid, 0)
        gains.append(2**grade - 1)

    dcg = 0.0
    for i, gain in enumerate(gains):
        dcg += gain / math.log2(i + 2)

    ideal_grades = sorted(judgments.values(), reverse=True)[:k]
    idcg = 0.0
    for i, grade in enumerate(ideal_grades):
        idcg += (2**grade - 1) / math.log2(i + 2)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def useful_at_k(
    ranked: list[str], judgments: dict[str, int], k: int, threshold: int = RELEVANCE_THRESHOLD
) -> float:
    top_k = ranked[:k]
    if not top_k:
        return 0.0
    count = sum(1 for mid in top_k if judgments.get(mid, 0) >= threshold)
    return count / k


def evaluate_query(
    result: RetrievalResult,
    judgment: QueryJudgment,
) -> QueryMetrics:
    relevant = _relevant_ids(judgment.judgments)
    qm = QueryMetrics(
        query_id=result.query_id,
        relevant_count=len(relevant),
        recall_at_5=recall_at_k(result.ranked_memory_ids, relevant, 5),
        recall_at_10=recall_at_k(result.ranked_memory_ids, relevant, 10),
        recall_at_20=recall_at_k(result.ranked_memory_ids, relevant, 20),
        precision_at_5=precision_at_k(result.ranked_memory_ids, relevant, 5),
        precision_at_10=precision_at_k(result.ranked_memory_ids, relevant, 10),
        rr=reciprocal_rank(result.ranked_memory_ids, relevant),
        ndcg_at_10=ndcg_at_k(result.ranked_memory_ids, judgment.judgments, 10),
        useful_at_10=useful_at_k(result.ranked_memory_ids, judgment.judgments, 10),
    )
    return qm


def aggregate_report(
    pipeline: str,
    query_metrics: list[QueryMetrics],
    latencies: list[int] | None = None,
) -> BenchmarkReport:
    n = len(query_metrics)
    if n == 0:
        return BenchmarkReport(pipeline=pipeline, total_queries=0)

    report = BenchmarkReport(
        pipeline=pipeline,
        total_queries=n,
        per_query=query_metrics,
    )
    report.recall_at_5 = sum(qm.recall_at_5 for qm in query_metrics) / n
    report.recall_at_10 = sum(qm.recall_at_10 for qm in query_metrics) / n
    report.recall_at_20 = sum(qm.recall_at_20 for qm in query_metrics) / n
    report.precision_at_5 = sum(qm.precision_at_5 for qm in query_metrics) / n
    report.precision_at_10 = sum(qm.precision_at_10 for qm in query_metrics) / n
    report.mrr = sum(qm.rr for qm in query_metrics) / n
    report.ndcg_at_10 = sum(qm.ndcg_at_10 for qm in query_metrics) / n
    report.useful_at_10 = sum(qm.useful_at_10 for qm in query_metrics) / n

    if latencies:
        report.avg_latency_ms = sum(latencies) / len(latencies)

    return report


def format_report_md(report: BenchmarkReport) -> str:
    lines = [
        f"# Retrieval Benchmark Report: {report.pipeline}",
        "",
        f"**Total queries**: {report.total_queries}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Recall@5 | {report.recall_at_5:.4f} |",
        f"| Recall@10 | {report.recall_at_10:.4f} |",
        f"| Recall@20 | {report.recall_at_20:.4f} |",
        f"| Precision@5 | {report.precision_at_5:.4f} |",
        f"| Precision@10 | {report.precision_at_10:.4f} |",
        f"| MRR | {report.mrr:.4f} |",
        f"| NDCG@10 | {report.ndcg_at_10:.4f} |",
        f"| Useful@10 | {report.useful_at_10:.4f} |",
        f"| Avg Latency (ms) | {report.avg_latency_ms:.1f} |",
        "",
    ]
    return "\n".join(lines)
