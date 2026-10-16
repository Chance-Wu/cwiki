"""上下文组装评估器指标测试。"""

import json
from pathlib import Path

from benchmarks.evaluators.context import (
    ContextAssemblyOutcome,
    ContextGold,
    aggregate_context_report,
    evaluate_context_query,
    format_context_report_md,
    load_context_gold,
)


def _gold(**overrides) -> ContextGold:
    base: dict = {
        "query_id": "q1",
        "query": "测试查询",
        "intent": "unknown",
        "budget": 1000,
        "pool": [{"memory_id": "m1", "score": 0.9}],
        "expected_included": ["m1"],
        "expected_excluded": ["m2"],
        "expected_conflict_pairs": [],
    }
    base.update(overrides)
    return ContextGold(**base)


def _outcome(**overrides) -> ContextAssemblyOutcome:
    base: dict = {
        "query_id": "q1",
        "selected_memory_ids": ["m1"],
        "token_count": 500,
        "conflict_pairs": [],
    }
    base.update(overrides)
    return ContextAssemblyOutcome(**base)


class TestEvaluateContextQuery:
    def test_perfect_case(self):
        m = evaluate_context_query(
            _gold(),
            _outcome(selected_memory_ids=["m1"], token_count=900),
        )
        assert m.selection_recall == 1.0
        assert m.negative_exclusion == 1.0
        assert m.budget_ok
        assert m.conflict_warning_ok is None
        assert m.leaked_negative_ids == []
        assert m.selected_count == 1
        assert m.expected_included_count == 1

    def test_partial_selection_recall(self):
        m = evaluate_context_query(
            _gold(expected_included=["m1", "m2", "m3"]),
            _outcome(selected_memory_ids=["m1", "m3"]),
        )
        assert abs(m.selection_recall - 2 / 3) < 1e-6

    def test_no_included_expectation(self):
        m = evaluate_context_query(
            _gold(expected_included=[]),
            _outcome(selected_memory_ids=[]),
        )
        assert m.selection_recall == 1.0

    def test_negative_leak(self):
        m = evaluate_context_query(
            _gold(expected_excluded=["m2", "m3"]),
            _outcome(selected_memory_ids=["m1", "m2"]),
        )
        assert m.negative_exclusion == 0.5
        assert m.leaked_negative_ids == ["m2"]

    def test_no_excluded_expectation(self):
        m = evaluate_context_query(
            _gold(expected_excluded=[]),
            _outcome(selected_memory_ids=[]),
        )
        assert m.negative_exclusion == 1.0

    def test_budget_violation(self):
        m = evaluate_context_query(_gold(), _outcome(token_count=1500))
        assert not m.budget_ok

    def test_conflict_pair_warned(self):
        m = evaluate_context_query(
            _gold(expected_conflict_pairs=[("a", "b")]),
            _outcome(conflict_pairs=[("b", "a")]),
        )
        assert m.conflict_warning_ok is True

    def test_conflict_pair_missing(self):
        m = evaluate_context_query(
            _gold(expected_conflict_pairs=[("a", "b")]),
            _outcome(conflict_pairs=[]),
        )
        assert m.conflict_warning_ok is False

    def test_conflict_pair_partial(self):
        m = evaluate_context_query(
            _gold(expected_conflict_pairs=[("a", "b"), ("c", "d")]),
            _outcome(conflict_pairs=[("a", "b")]),
        )
        assert m.conflict_warning_ok is False


class TestAggregateReport:
    def test_aggregate(self):
        metrics = [
            evaluate_context_query(_gold(query_id="q1"), _outcome()),
            evaluate_context_query(
                _gold(query_id="q2", expected_excluded=[]),
                _outcome(token_count=1500),
            ),
        ]
        report = aggregate_context_report(metrics)
        assert report.total_queries == 2
        assert report.selection_recall == 1.0
        assert report.negative_exclusion_rate == 1.0
        assert report.budget_compliance == 0.5
        assert report.conflict_warning_recall == 0.0

    def test_conflict_recall_excludes_none(self):
        metrics = [
            evaluate_context_query(_gold(query_id="q1"), _outcome()),
            evaluate_context_query(
                _gold(query_id="q2", expected_conflict_pairs=[("a", "b")]),
                _outcome(conflict_pairs=[("a", "b")]),
            ),
        ]
        report = aggregate_context_report(metrics)
        # 仅 q2 有矛盾期望且成功
        assert report.conflict_warning_recall == 1.0

    def test_empty_metrics(self):
        report = aggregate_context_report([])
        assert report.total_queries == 0
        assert report.selection_recall == 0.0


class TestLoadGold:
    def test_load_jsonl(self, tmp_path: Path):
        path = tmp_path / "gold.jsonl"
        record = {
            "query_id": "ctx-001",
            "query": "查询",
            "intent": "fact",
            "budget": 500,
            "pool": [
                {"memory_id": "m1", "score": 0.9},
                {
                    "memory_id": "s1",
                    "score": 0.8,
                    "title": "合成",
                    "content": "内联",
                    "type": "fact",
                },
            ],
            "expected_included": ["m1"],
            "expected_excluded": ["m2"],
            "expected_conflict_pairs": [["m1", "m2"]],
        }
        path.write_text(json.dumps(record, ensure_ascii=False) + "\n")
        golds = load_context_gold(path)
        assert len(golds) == 1
        g = golds[0]
        assert g.query_id == "ctx-001"
        assert g.intent == "fact"
        assert g.budget == 500
        assert len(g.pool) == 2
        assert g.expected_conflict_pairs == [("m1", "m2")]

    def test_defaults(self, tmp_path: Path):
        path = tmp_path / "gold.jsonl"
        path.write_text(json.dumps({"query_id": "q", "query": "查询"}) + "\n")
        g = load_context_gold(path)[0]
        assert g.intent == "unknown"
        assert g.budget == 2000
        assert g.expected_conflict_pairs == []


class TestFormatReport:
    def test_md_contains_rows(self):
        metrics = [
            evaluate_context_query(
                _gold(query_id="q1", expected_excluded=["m2", "m3"]),
                _outcome(selected_memory_ids=["m1", "m2"]),
            ),
        ]
        report = aggregate_context_report(metrics)
        md = format_context_report_md(report)
        assert "Selection Recall" in md
        assert "| q1 |" in md
        assert "m2" in md
        assert "FAIL" in md  # 负例泄漏在表中可见
