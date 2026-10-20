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

from benchmarks.evaluators.context import (
    ContextAssemblyOutcome,
    ContextBenchmarkReport,
    ContextGold,
    aggregate_context_report,
    evaluate_context_query,
    format_context_report_md,
)
from benchmarks.fixtures.generate_fixture import WORKSPACE_NAME
from benchmarks.runners.retrieval_runner import make_session_maker
from packages.domain.config import settings
from packages.retrieval.context.assembler import assemble_context_with_embedding

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

    session_maker = make_session_maker(f"sqlite+aiosqlite:///{FIXTURE_DB}")
    async with session_maker() as db:
        ws = (
            await db.execute(select(Workspace).where(Workspace.name == WORKSPACE_NAME))
        ).scalar_one()
        rows = (
            (
                await db.execute(
                    select(Memory).where(Memory.workspace_id == ws.id, Memory.status == "active")
                )
            )
            .scalars()
            .all()
        )

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
            logger.warning("Pool entry %s not found in fixture DB, skipping", mid)
            continue
        pool.append(mem)
    return pool


async def run_context_benchmark() -> ContextBenchmarkReport:
    _quiet_sql()
    # gold 池的 score 为手造语义（0.3-0.55 模拟弱相关、0.58+ 模拟相关），
    # 与生产 rerank composite 分布无关，适合开启 relevance floor 验证
    # ctx-002 的负例排除修复；生产链路默认 none（config.yaml 注释见定值依据）
    settings.relevance_floor_mode = "hard"
    settings.relevance_floor = 0.5
    fixture_memories = await _load_fixture_memories()

    gold_raws = [json.loads(line) for line in GOLD_PATH.read_text().splitlines() if line.strip()]
    outcomes: list[ContextAssemblyOutcome] = []
    golds: list[ContextGold] = []

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
    return aggregate_context_report(metrics)


def save_report(report: ContextBenchmarkReport) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "total_queries": report.total_queries,
        "selection_recall": report.selection_recall,
        "negative_exclusion_rate": report.negative_exclusion_rate,
        "budget_compliance": report.budget_compliance,
        "conflict_warning_recall": report.conflict_warning_recall,
        "per_query": [m.__dict__ for m in report.per_query],
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
