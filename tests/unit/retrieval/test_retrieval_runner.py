"""Reject invalid retrieval judgments before reporting misleading metrics."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from benchmarks.evaluators.retrieval import (
    QueryJudgment,
    RetrievalResult,
    aggregate_report,
    evaluate_query,
)
from benchmarks.runners import retrieval_runner as runner


def test_gold_rejects_inconsistent_query_and_conflicting_grade(tmp_path):
    path = tmp_path / "gold.jsonl"
    base = {"query_id": "q", "query": "中文", "memory_id": "m", "relevance": 2}
    for override, message in [
        ({"query": "different"}, "inconsistent query text"),
        ({"relevance": 3}, "conflicting relevance"),
        ({"relevance": True}, "integer from 0 to 3"),
        ({"relevance": 4}, "integer from 0 to 3"),
    ]:
        path.write_text("\n".join(json.dumps(r) for r in [base, base | override]), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            runner.load_gold_dataset(path)


async def test_missing_positive_fails_but_absent_negative_is_valid(monkeypatch):
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=session)
    monkeypatch.setattr(runner, "_load_memories", AsyncMock(return_value=[]))
    pipeline = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(runner, "run_pipeline", pipeline)
    ws = uuid.uuid4()
    with pytest.raises(ValueError, match="q: relevant memories absent"):
        await runner.run_benchmark(
            "baseline_bm25", [QueryJudgment("q", "query", {"gone": 2})], ws, factory
        )
    pipeline.assert_not_awaited()
    report = await runner.run_benchmark(
        "baseline_bm25", [QueryJudgment("negative", "query", {"other-workspace": 0})], ws, factory
    )
    assert report.negative_probes == 1


def test_report_preserves_ranked_evidence_and_unjudged_hits(tmp_path):
    ranked = ["unjudged", "irrelevant", "weak"]
    metrics = evaluate_query(
        RetrievalResult("q", ranked),
        QueryJudgment("q", "负例查询", {"irrelevant": 0, "weak": 1}),
    )
    ranked.clear()  # evaluation owns its snapshot
    report = aggregate_report("baseline_bm25", [metrics])
    runner.save_report(report, tmp_path)
    data = json.loads(
        (tmp_path / "retrieval-report-baseline_bm25.json").read_text(encoding="utf-8")
    )
    row = data["per_query"][0]
    assert row["query"] == "负例查询"
    assert row["ranked_memory_ids"] == ["unjudged", "irrelevant", "weak"]
    assert row["ranked_relevance"] == [None, 0, 1]
    assert row["negative_fp_at_10"] is True


async def test_empty_dataset_and_unknown_pipeline_fail():
    with pytest.raises(ValueError, match="dataset is empty"):
        await runner.run_benchmark("baseline_bm25", [], uuid.uuid4())
    with pytest.raises(ValueError, match="Unknown retrieval pipeline"):
        await runner.run_benchmark("typo", [], uuid.uuid4())
