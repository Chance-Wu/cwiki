"""检索报告对比门槛测试（含跨管线守门）。"""

from benchmarks.runners.compare_reports import METRICS, compare


def _report(**overrides):
    base = {metric: 0.8 for metric in METRICS}
    base.update(overrides)
    return base


def _baseline():
    return {
        "hybrid_rrf": _report(),
        "hybrid_rrf_rerank": _report(),
        "full_pipeline": _report(),
    }


class TestCompare:
    def test_all_within_tolerance_passes(self):
        _, failures = compare(_baseline(), _baseline(), tolerance=0.03)
        assert failures == []

    def test_baseline_drop_beyond_tolerance_fails(self):
        current = _baseline()
        current["hybrid_rrf"]["mrr"] = 0.7
        _, failures = compare(_baseline(), current, tolerance=0.03)
        assert any("hybrid_rrf.mrr" in failure for failure in failures)

    def test_rerank_below_rrf_beyond_cross_tolerance_fails(self):
        current = _baseline()
        # 两项都远高于 baseline，但 rerank 相对 RRF 回退 0.02
        current["hybrid_rrf"]["ndcg_at_10"] = 0.90
        current["hybrid_rrf_rerank"]["ndcg_at_10"] = 0.88
        _, failures = compare(_baseline(), current, tolerance=0.03)
        assert any(
            "hybrid_rrf_rerank.ndcg_at_10 below hybrid_rrf" in failure for failure in failures
        )

    def test_rerank_within_cross_tolerance_passes(self):
        current = _baseline()
        current["hybrid_rrf"]["recall_at_10"] = 0.90
        current["hybrid_rrf_rerank"]["recall_at_10"] = 0.897
        _, failures = compare(_baseline(), current, tolerance=0.03)
        assert failures == []

    def test_cross_check_skipped_when_pipeline_missing(self):
        current = _baseline()
        del current["hybrid_rrf"]
        _, failures = compare(_baseline(), current, tolerance=0.03)
        # 缺失管线本身记失败，但不因缺少参照而崩溃
        assert any("基线存在但当前报告缺失" in failure for failure in failures)
