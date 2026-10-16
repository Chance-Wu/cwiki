"""检索基准评估器指标测试。"""

from benchmarks.evaluators.retrieval import (
    QueryJudgment,
    RetrievalResult,
    aggregate_report,
    evaluate_query,
    format_report_md,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    useful_at_k,
)


class TestRecallAtK:
    def test_perfect_recall(self):
        ranked = ["a", "b", "c", "d", "e"]
        relevant = {"a", "b", "c"}
        assert recall_at_k(ranked, relevant, 5) == 1.0

    def test_partial_recall(self):
        ranked = ["a", "x", "b", "y", "z"]
        relevant = {"a", "b", "c"}
        assert abs(recall_at_k(ranked, relevant, 5) - 2 / 3) < 1e-6

    def test_no_recall(self):
        ranked = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert recall_at_k(ranked, relevant, 3) == 0.0

    def test_empty_relevant(self):
        assert recall_at_k(["a", "b"], set(), 2) == 0.0

    def test_k_smaller_than_results(self):
        ranked = ["a", "x", "x", "x", "b"]
        relevant = {"a", "b"}
        assert recall_at_k(ranked, relevant, 3) == 0.5


class TestPrecisionAtK:
    def test_perfect_precision(self):
        ranked = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(ranked, relevant, 3) == 1.0

    def test_half_precision(self):
        ranked = ["a", "x", "b", "y"]
        relevant = {"a", "b"}
        assert precision_at_k(ranked, relevant, 4) == 0.5

    def test_empty_results(self):
        assert precision_at_k([], {"a"}, 5) == 0.0


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0

    def test_second_position(self):
        assert reciprocal_rank(["x", "a", "b"], {"a"}) == 0.5

    def test_not_found(self):
        assert reciprocal_rank(["x", "y", "z"], {"a"}) == 0.0


class TestNDCGAtK:
    def test_perfect_ordering(self):
        ranked = ["a", "b", "c"]
        judgments = {"a": 3, "b": 2, "c": 1}
        score = ndcg_at_k(ranked, judgments, 3)
        assert score == 1.0

    def test_reversed_ordering(self):
        ranked = ["c", "b", "a"]
        judgments = {"a": 3, "b": 2, "c": 0}
        perfect = ndcg_at_k(["a", "b", "c"], judgments, 3)
        reversed_score = ndcg_at_k(ranked, judgments, 3)
        assert reversed_score < perfect

    def test_no_relevant(self):
        ranked = ["a", "b"]
        judgments = {"a": 0, "b": 0}
        assert ndcg_at_k(ranked, judgments, 2) == 0.0


class TestUsefulAtK:
    def test_all_useful(self):
        ranked = ["a", "b", "c"]
        judgments = {"a": 3, "b": 2, "c": 2}
        assert useful_at_k(ranked, judgments, 3) == 1.0

    def test_none_useful(self):
        ranked = ["a", "b", "c"]
        judgments = {"a": 1, "b": 0, "c": 1}
        assert useful_at_k(ranked, judgments, 3) == 0.0

    def test_mixed(self):
        ranked = ["a", "b", "c", "d", "e"]
        judgments = {"a": 3, "b": 1, "c": 2, "d": 0, "e": 3}
        assert abs(useful_at_k(ranked, judgments, 5) - 3 / 5) < 1e-6


class TestEvaluateQuery:
    def test_full_evaluation(self):
        judgment = QueryJudgment(
            query_id="q1",
            query="test query",
            judgments={"m1": 3, "m2": 2, "m3": 1, "m4": 0},
        )
        result = RetrievalResult(
            query_id="q1",
            ranked_memory_ids=["m1", "m5", "m2", "m6", "m3"],
            latency_ms=50,
        )
        qm = evaluate_query(result, judgment)
        assert qm.query_id == "q1"
        assert qm.relevant_count == 2
        assert qm.recall_at_5 == 1.0
        assert qm.rr == 1.0
        assert qm.useful_at_10 > 0


class TestAggregateReport:
    def test_aggregate(self):
        judgments_list = [
            QueryJudgment("q1", "q1", {"m1": 3, "m2": 2}),
            QueryJudgment("q2", "q2", {"m3": 3}),
        ]
        results = [
            RetrievalResult("q1", ["m1", "m2"], 10),
            RetrievalResult("q2", ["m4", "m3"], 20),
        ]
        qms = [evaluate_query(r, j) for r, j in zip(results, judgments_list)]
        report = aggregate_report("test_pipeline", qms, [10, 20])
        assert report.pipeline == "test_pipeline"
        assert report.total_queries == 2
        assert report.avg_latency_ms == 15.0
        assert report.recall_at_10 > 0

    def test_empty_report(self):
        report = aggregate_report("empty", [])
        assert report.total_queries == 0


class TestFormatReport:
    def test_markdown_output(self):
        judgment = QueryJudgment("q1", "test", {"m1": 3})
        result = RetrievalResult("q1", ["m1"], 10)
        qm = evaluate_query(result, judgment)
        report = aggregate_report("test", [qm])
        md = format_report_md(report)
        assert "test" in md
        assert "Recall@10" in md
        assert "MRR" in md
