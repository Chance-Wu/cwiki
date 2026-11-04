"""上下文组装基准运行器。

在合成评测夹具（eval_fixture.db）上运行 assemble_context_with_embedding，
对照 datasets/context/gold.jsonl 评估选择质量、负例排除、预算符合与冲突告警。

用法：
    python -m benchmarks.runners.context_runner
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchmarks.evaluators.context import (
    ContextAssemblyOutcome,
    ContextBenchmarkReport,
    ContextGold,
    aggregate_context_report,
    evaluate_context_query,
    format_context_report_md,
)
from benchmarks.fixtures.generate_fixture import WORKSPACE_NAME
from packages.domain.config import settings
from packages.retrieval.context.assembler import ContextResult, assemble_context_with_embedding
from packages.retrieval.context.token_counter import estimate_tokens

logger = logging.getLogger(__name__)

FIXTURE_DB = Path(__file__).parent.parent / "fixtures" / "eval_fixture.db"
GOLD_PATH = Path(__file__).parent.parent / "datasets" / "context" / "gold.jsonl"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "eval-fixture"


def _quiet_sql() -> None:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def _load_fixture_memories() -> dict[str, dict[str, Any]]:
    """从夹具 DB 加载全部 active 记忆为组装器可用的字典。"""
    from sqlalchemy import select

    from packages.domain.models import Memory, Workspace

    if not FIXTURE_DB.is_file():
        raise FileNotFoundError(f"Context fixture database not found: {FIXTURE_DB}")
    # SQLite URI read-only mode prevents accidental writes to the fixture itself.
    url = URL.create(
        "sqlite+aiosqlite",
        database=f"file:{FIXTURE_DB.resolve().as_posix()}",
        query={"mode": "ro", "uri": "true"},
    )
    engine = create_async_engine(url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as db:
            ws = (
                await db.execute(select(Workspace).where(Workspace.name == WORKSPACE_NAME))
            ).scalar_one()
            rows = (
                (
                    await db.execute(
                        select(Memory).where(
                            Memory.workspace_id == ws.id, Memory.status == "active"
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    return {
        str(m.id): {
            "id": str(m.id),
            "title": m.title,
            "content": m.content,
            "type": m.type,
            "score": 0.0,
            "version": m.version,
            "updated_at": str(m.updated_at),
            "embedding": list(m.embedding) if m.embedding else None,
            "confidence": m.confidence,
            "importance": m.importance,
            "valid_from": m.valid_from,
            "valid_to": m.valid_to,
            "evidence_count": 0,
        }
        for m in rows
    }


def delivery_snapshot(result: ContextResult) -> dict[str, Any]:
    """Preserve observable delivery evidence without inferring relevance labels.

    Filter events can include demotion as well as removal. Keep them separate
    from the authoritative delivered IDs; do not label every event 'excluded'.
    """
    return {
        "selected_memory_ids": [m.memory_id for m in result.memories],
        "context": result.text,
        "token_count": result.token_count,
        "rendered_token_estimate": estimate_tokens(result.text),
        "truncated": result.truncated,
        "filter_events": [
            {"memory_id": event.memory_id, "stage": event.stage, "reason": event.reason}
            for event in result.filter_reasons
        ],
    }


def _build_pool(
    gold_raw: dict[str, Any],
    fixture_memories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """按黄金记录的池定义构造记忆字典。

    条目含 content 字段时为合成条目（内联内容，不查夹具 DB），
    用于字面重复/改写重复/矛盾对注入；否则按 memory_id 查夹具。
    """
    pool: list[dict[str, Any]] = []
    for entry in gold_raw["pool"]:
        mid, score = entry["memory_id"], entry["score"]
        if "content" in entry:
            mem = {
                "id": mid,
                "title": entry.get("title", "合成条目"),
                "content": entry["content"],
                "type": entry.get("type", "fact"),
                "score": score,
                "version": 1,
                "updated_at": "",
                "embedding": None,
                "evidence_count": 0,
            }
        elif mid in fixture_memories:
            mem = dict(fixture_memories[mid])
            mem["score"] = score
        else:
            raise ValueError(f"{gold_raw['query_id']}: pool memory {mid} not found in fixture DB")
        pool.append(mem)
    return pool


async def run_context_benchmark() -> ContextBenchmarkReport:
    """Run sequentially; restore temporary benchmark settings even on failure.

    This standalone runner must not run concurrently with production requests in
    the same process, because the assembler currently reads shared settings.
    """
    _quiet_sql()
    old_mode, old_floor = settings.relevance_floor_mode, settings.relevance_floor
    try:
        # Hand-scored gold pools use a different score distribution from production.
        settings.relevance_floor_mode = "hard"
        settings.relevance_floor = 0.5
        return await _run_context_benchmark()
    finally:
        settings.relevance_floor_mode = old_mode
        settings.relevance_floor = old_floor


async def _run_context_benchmark() -> ContextBenchmarkReport:
    fixture_memories = await _load_fixture_memories()
    gold_raws = [
        json.loads(line)
        for line in GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not gold_raws:
        raise ValueError(f"Context gold dataset is empty: {GOLD_PATH}")
    outcomes: list[ContextAssemblyOutcome] = []
    golds: list[ContextGold] = []
    diagnostics: list[dict[str, Any]] = []

    for gold_raw in gold_raws:
        gold = ContextGold(
            query_id=gold_raw["query_id"],
            query=gold_raw["query"],
            intent=gold_raw.get("intent", "unknown"),
            budget=gold_raw.get("budget", 2000),
            pool=gold_raw.get("pool", []),
            expected_included=gold_raw.get("expected_included", []),
            expected_excluded=gold_raw.get("expected_excluded", []),
            expected_conflict_pairs=[
                tuple(pair) for pair in gold_raw.get("expected_conflict_pairs", [])
            ],
        )
        pool = _build_pool(gold_raw, fixture_memories)

        result = await assemble_context_with_embedding(
            pool,
            query=gold.query,
            intent=gold.intent,
            max_tokens=gold.budget,
        )
        diagnostics.append({"query_id": gold.query_id, **delivery_snapshot(result)})
        outcomes.append(
            ContextAssemblyOutcome(
                query_id=gold.query_id,
                selected_memory_ids=[m.memory_id for m in result.memories],
                token_count=result.token_count,
                conflict_pairs=[(c.memory_id_a, c.memory_id_b) for c in result.conflicts],
            )
        )
        golds.append(gold)
        logger.info(
            "  %s: selected=%d tokens=%d conflicts=%d",
            gold.query_id,
            len(result.memories),
            result.token_count,
            len(result.conflicts),
        )

    metrics = [evaluate_context_query(g, o) for g, o in zip(golds, outcomes, strict=True)]
    report = aggregate_context_report(metrics)
    report.delivery_diagnostics = diagnostics
    return report


def save_report(report: ContextBenchmarkReport) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "total_queries": report.total_queries,
        "selection_recall": report.selection_recall,
        "negative_exclusion_rate": report.negative_exclusion_rate,
        "budget_compliance": report.budget_compliance,
        "conflict_warning_recall": report.conflict_warning_recall,
        "per_query": [m.__dict__ for m in report.per_query],
        "delivery_diagnostics": report.delivery_diagnostics,
    }
    with open(REPORTS_DIR / "context-report.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(REPORTS_DIR / "context-report.md", "w", encoding="utf-8") as f:
        f.write(format_context_report_md(report))


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    report = await run_context_benchmark()
    save_report(report)
    print(format_context_report_md(report))


if __name__ == "__main__":
    argparse.ArgumentParser(description="Context assembly benchmark runner").parse_args()
    asyncio.run(main())
