"""上下文组装评测器。

评估组装阶段（assemble_context*）的四个维度：

- Selection Recall：期望入选的记忆是否出现在最终上下文中
- Negative Exclusion Rate：期望排除的记忆（过时/矛盾/无关）是否未入选
- Budget Compliance：最终 token_count 是否符合预算
- Conflict Warning Recall：应告警的矛盾对是否被标记

黄金数据格式（gold.jsonl 每行一条记录）：
    {"query_id": "ctx-001", "query": "...", "intent": "unknown",
     "budget": 2000,
     "pool": [{"memory_id": ..., "score": ...,
               "title"/"content"/"type": 可选（合成条目，内联内容）}, ...],
     "expected_included": ["<memory_id>", ...],
     "expected_excluded": ["<memory_id>", ...],
     "expected_conflict_pairs": [["<id_a>", "<id_b>"], ...]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ContextGold:
    query_id: str
    query: str
    intent: str = "unknown"
    budget: int = 2000
    pool: list[dict] = field(default_factory=list)  # [{"memory_id": ..., "score": ...}]
    expected_included: list[str] = field(default_factory=list)
    expected_excluded: list[str] = field(default_factory=list)
    expected_conflict_pairs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ContextAssemblyOutcome:
    """一次组装的实际结果（由 runner 从 ContextResult 提取）。"""

    query_id: str
    selected_memory_ids: list[str] = field(default_factory=list)
    token_count: int = 0
    conflict_pairs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ContextQueryMetrics:
    query_id: str
    selection_recall: float = 0.0
    negative_exclusion: float = 0.0
    budget_ok: bool = False
    conflict_warning_ok: bool | None = None  # None = 无期望（不计入）
    # 诊断字段：定位失败原因用
    selected_count: int = 0
    expected_included_count: int = 0
    leaked_negative_ids: list[str] = field(default_factory=list)


@dataclass
class ContextBenchmarkReport:
    total_queries: int = 0
    selection_recall: float = 0.0
    negative_exclusion_rate: float = 0.0
    budget_compliance: float = 0.0
    conflict_warning_recall: float = 0.0
    per_query: list[ContextQueryMetrics] = field(default_factory=list)


def load_context_gold(path: Path) -> list[ContextGold]:
    records: list[ContextGold] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            records.append(
                ContextGold(
                    query_id=d["query_id"],
                    query=d["query"],
                    intent=d.get("intent", "unknown"),
                    budget=d.get("budget", 2000),
                    pool=d.get("pool", []),
                    expected_included=d.get("expected_included", []),
                    expected_excluded=d.get("expected_excluded", []),
                    expected_conflict_pairs=[
                        tuple(pair) for pair in d.get("expected_conflict_pairs", [])
                    ],
                )
            )
    return records


def evaluate_context_query(
    gold: ContextGold, outcome: ContextAssemblyOutcome
) -> ContextQueryMetrics:
    selected = set(outcome.selected_memory_ids)

    included = set(gold.expected_included)
    selection_recall = len(included & selected) / len(included) if included else 1.0

    excluded = set(gold.expected_excluded)
    negative_exclusion = len(excluded - selected) / len(excluded) if excluded else 1.0

    budget_ok = outcome.token_count <= gold.budget

    conflict_warning_ok: bool | None = None
    if gold.expected_conflict_pairs:
        warned_pairs = {frozenset(pair) for pair in outcome.conflict_pairs}
        conflict_warning_ok = all(
            frozenset(pair) in warned_pairs for pair in gold.expected_conflict_pairs
        )

    return ContextQueryMetrics(
        query_id=gold.query_id,
        selection_recall=selection_recall,
        negative_exclusion=negative_exclusion,
        budget_ok=budget_ok,
        conflict_warning_ok=conflict_warning_ok,
        selected_count=len(outcome.selected_memory_ids),
        expected_included_count=len(included),
        leaked_negative_ids=sorted(excluded & selected),
    )


def aggregate_context_report(
    metrics: list[ContextQueryMetrics],
) -> ContextBenchmarkReport:
    n = len(metrics)
    if n == 0:
        return ContextBenchmarkReport()

    conflict_cases = [m for m in metrics if m.conflict_warning_ok is not None]
    report = ContextBenchmarkReport(
        total_queries=n,
        per_query=metrics,
        selection_recall=sum(m.selection_recall for m in metrics) / n,
        negative_exclusion_rate=sum(m.negative_exclusion for m in metrics) / n,
        budget_compliance=sum(1 for m in metrics if m.budget_ok) / n,
    )
    if conflict_cases:
        report.conflict_warning_recall = sum(
            1 for m in conflict_cases if m.conflict_warning_ok
        ) / len(conflict_cases)
    return report


def format_context_report_md(report: ContextBenchmarkReport) -> str:
    lines = [
        "# Context Assembly Benchmark Report",
        "",
        f"**Total queries**: {report.total_queries}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Selection Recall | {report.selection_recall:.4f} |",
        f"| Negative Exclusion Rate | {report.negative_exclusion_rate:.4f} |",
        f"| Budget Compliance | {report.budget_compliance:.4f} |",
        f"| Conflict Warning Recall | {report.conflict_warning_recall:.4f} |",
        "",
        "## Per-query",
        "",
        "| Query | Sel Recall | Neg Exclusion | Budget | Conflict | Leaked Negatives |",
        "|-------|-----------|---------------|--------|----------|------------------|",
    ]
    for m in report.per_query:
        conflict = (
            "n/a" if m.conflict_warning_ok is None else ("ok" if m.conflict_warning_ok else "FAIL")
        )
        budget = "ok" if m.budget_ok else "FAIL"
        neg = (
            f"{m.negative_exclusion:.2f}"
            if m.negative_exclusion == 1.0
            else (f"{m.negative_exclusion:.2f} FAIL")
        )
        leaked = ", ".join(m.leaked_negative_ids) if m.leaked_negative_ids else "-"
        lines.append(
            f"| {m.query_id} | {m.selection_recall:.2f} | {neg} "
            f"| {budget} | {conflict} | {leaked} |"
        )
    lines.append("")
    return "\n".join(lines)
