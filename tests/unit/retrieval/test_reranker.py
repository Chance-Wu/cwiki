"""packages.retrieval.ranking.reranker 排序语义测试。"""

import pytest

from packages.retrieval.ranking.reranker import (
    RerankerWeights,
    RerankInput,
    _intent_bonus,
    rerank,
)


def _make_input(memory_id: str, **kwargs) -> RerankInput:
    defaults = {
        "title": "test",
        "content": "test content",
        "memory_type": "fact",
    }
    defaults.update(kwargs)
    return RerankInput(memory_id=memory_id, **defaults)


def _weights(**overrides) -> RerankerWeights:
    """构造完全可控的权重：未指定的相关性/元数据权重一律归零。"""
    base = {
        "rrf": 0.0,
        "semantic": 0.0,
        "bm25": 0.0,
        "intent": 0.0,
        "confidence": 0.0,
        "importance": 0.0,
        "freshness": 0.0,
        "usage": 0.0,
        "band": 0.05,
        "key_term_bonus": 0.0,
    }
    base.update(overrides)
    return RerankerWeights(**base)


class TestRerank:
    def test_basic_ranking(self):
        candidates = [
            _make_input("a", rrf_score=0.0164, confidence=0.9, importance=0.9),
            _make_input("b", rrf_score=0.0082, confidence=0.1, importance=0.1),
        ]
        result = rerank(candidates)
        assert result[0][0] == "a"
        assert result[1][0] == "b"

    def test_top_k(self):
        candidates = [_make_input(f"m{i}", rrf_score=0.0164 - i * 0.001) for i in range(10)]
        result = rerank(candidates, top_k=3)
        assert len(result) == 3

    def test_empty_candidates(self):
        assert rerank([]) == []

    def test_high_rrf_score_wins(self):
        candidates = [
            _make_input("a", rrf_score=0.0164),
            _make_input("b", rrf_score=0.0020),
        ]
        result = rerank(candidates)
        assert result[0][0] == "a"

    def test_configurable_weights(self):
        candidates = [
            _make_input("a", rrf_score=0.0, usage_score=0.0),
            _make_input("b", rrf_score=0.0, usage_score=1.0),
        ]
        w = _weights(usage=1.0)
        result = rerank(candidates, weights=w)
        assert result[0][0] == "b"


class TestIntentBonus:
    def test_unknown_intent(self):
        assert _intent_bonus("fact", "unknown") == 0.5

    def test_matching_type(self):
        assert _intent_bonus("procedure", "procedure") == 1.0

    def test_no_match_is_neutral(self):
        """类型不匹配给中性 0.5 而非惩罚基线：意图来自查询关键词分析，
        可靠性有限，重罚会让低置信信号产生高置信影响。"""
        assert _intent_bonus("fact", "procedure") == 0.5
        assert _intent_bonus("reference", "fact") == 0.5

    def test_partial_match(self):
        assert _intent_bonus("rule", "project_rule") == 1.0
        assert _intent_bonus("constraint", "project_rule") == 0.8

    def test_secondary_type_uses_real_memory_type_names(self):
        """次匹配项必须是真实记忆类型：`project_rule` 是查询意图而非记忆类型，
        用它作键会让 procedure/constraint 意图的 rule 加成永远不生效。"""
        assert _intent_bonus("rule", "procedure") == 0.5
        assert _intent_bonus("rule", "constraint") == 0.8


class TestRelevanceSignals:
    """相关性主导：RRF 锚定、元数据为池内最小不被压扁。"""

    def test_metadata_pool_min_not_crushed(self):
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                confidence=0.85,
                importance=0.85,
                freshness=0.85,
                usage_score=0.85,
            ),
            _make_input(
                "noise1",
                rrf_score=0.0161,
                confidence=0.90,
                importance=0.90,
                freshness=0.90,
                usage_score=0.90,
            ),
            _make_input(
                "noise2",
                rrf_score=0.0158,
                confidence=0.88,
                importance=0.88,
                freshness=0.88,
                usage_score=0.88,
            ),
            _make_input(
                "floor",
                rrf_score=0.0141,
                confidence=0.86,
                importance=0.86,
                freshness=0.86,
                usage_score=0.86,
            ),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_rrf_absolute_anchor_monotonic(self):
        """RRF 按理论满分锚定后仍单调，且不依赖池内极值。"""
        candidates = [
            _make_input("a", rrf_score=0.0164),
            _make_input("b", rrf_score=0.0080),
            _make_input("c", rrf_score=0.0020),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert [mid for mid, _ in result] == ["a", "b", "c"]

    def test_rrf_head_gap_survives_metadata_gap(self):
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                confidence=0.68,
                importance=0.83,
                freshness=1.0,
                usage_score=0.28,
            ),
            _make_input(
                "noise",
                rrf_score=0.0141,
                confidence=0.91,
                importance=0.92,
                freshness=1.0,
                usage_score=0.37,
            ),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_intent_misjudgment_neutral_for_unmatched_types(self):
        candidates = [
            _make_input("gold", rrf_score=0.0164, memory_type="fact"),
            _make_input("noise", rrf_score=0.0161, memory_type="reference"),
        ]
        result = rerank(candidates, query_intent="procedure")
        assert result[0][0] == "gold"

    def test_small_and_large_pools_get_same_relevance_score(self):
        """同一 RRF 名次在 2 条与 60 条候选池里得分一致。"""
        top = _make_input("top", rrf_score=0.0164)
        small = rerank([top, _make_input("low", rrf_score=0.0020)])[0][1]
        large = rerank(
            [top] + [_make_input(f"f{i}", rrf_score=0.0020 - i * 0.00001) for i in range(59)]
        )[0][1]
        assert small == pytest.approx(large)

    def test_all_relevance_weights_zero_uses_metadata(self):
        candidates = [
            _make_input("a", confidence=0.9),
            _make_input("b", confidence=0.1),
        ]
        result = rerank(candidates, weights=_weights(confidence=1.0, band=1.0))
        assert result[0][0] == "a"

    def test_deterministic_tiebreak(self):
        candidates = [
            _make_input("b", rrf_score=0.0164),
            _make_input("a", rrf_score=0.0164),
        ]
        result = rerank(candidates)
        assert [mid for mid, _ in result] == ["a", "b"]


class TestRelevanceBand:
    """元数据只在 band 内微调，不能跨带压过相关性。"""

    def test_metadata_scaled_by_band(self):
        a = _make_input("a", confidence=0.9)
        b = _make_input("b", confidence=0.4)
        result = rerank([a, b], weights=_weights(confidence=1.0))
        delta = result[0][1] - result[1][1]
        assert delta == pytest.approx(0.05 * 0.5)

    def test_band_bounds_metadata_share(self):
        candidates = [
            _make_input("gold", rrf_score=0.0164, confidence=0.3),
            _make_input("metadata_favored", rrf_score=0.0141, confidence=0.9),
        ]
        result = rerank(candidates, weights=_weights(rrf=1.0, confidence=1.0))
        assert result[0][0] == "gold"

    def test_band_allows_within_band_flip(self):
        candidates = [
            _make_input("gold", rrf_score=0.0163, confidence=0.1),
            _make_input("metadata_favored", rrf_score=0.0162, confidence=0.9),
        ]
        result = rerank(candidates, weights=_weights(rrf=1.0, confidence=1.0))
        assert result[0][0] == "metadata_favored"

    def test_band_zero_is_pure_relevance(self):
        candidates = [
            _make_input("gold", rrf_score=0.0164, confidence=0.1),
            _make_input("metadata_favored", rrf_score=0.0141, confidence=0.9),
        ]
        result = rerank(
            candidates,
            weights=_weights(rrf=1.0, confidence=1.0, band=0.0),
        )
        assert result[0][0] == "gold"

    def test_band_above_one_is_clamped(self):
        candidates = [
            _make_input("a", rrf_score=0.0164, confidence=0.1),
            _make_input("b", rrf_score=0.0020, confidence=0.9),
        ]
        # band=2 被 clamp 到 1：最终分等于元数据
        result = rerank(candidates, weights=_weights(rrf=1.0, confidence=1.0, band=2.0))
        assert result[0][0] == "b"

    def test_band_does_not_mutate_caller_weights(self):
        w = _weights(rrf=1.0, confidence=0.3, band=2.0)
        candidates = [_make_input("a"), _make_input("b")]
        rerank(candidates, weights=w)
        assert w.band == 2.0
        assert w.confidence == 0.3

    def test_negative_weights_clamped(self):
        candidates = [
            _make_input("a", confidence=0.9),
            _make_input("b", confidence=0.1),
        ]
        result = rerank(candidates, weights=_weights(rrf=-1.0, confidence=1.0))
        assert result[0][0] == "a"


class TestBM25Signal:
    """bm25_score 从死字段变为相关性组信号。"""

    def test_bm25_signal_used(self):
        candidates = [
            _make_input("a", bm25_score=2.0),
            _make_input("b", bm25_score=1.0),
        ]
        result = rerank(candidates, weights=_weights(bm25=1.0, band=0.0))
        assert result[0][0] == "a"

    def test_bm25_missing_route_is_zero(self):
        candidates = [
            _make_input("a", bm25_score=0.0),
            _make_input("b", bm25_score=1.0),
        ]
        result = rerank(candidates, weights=_weights(bm25=1.0, band=0.0))
        assert result[0][0] == "b"


class TestVectorSignal:
    def test_semantic_signal_breaks_metadata_advantage(self):
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                vector_score=0.806,
                confidence=0.68,
                importance=0.83,
                freshness=0.87,
                usage_score=0.57,
            ),
            _make_input(
                "noise",
                rrf_score=0.01635,
                vector_score=0.617,
                confidence=0.83,
                importance=0.93,
                freshness=0.87,
                usage_score=0.57,
            ),
            _make_input("floor", rrf_score=0.0141, vector_score=0.0),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_without_vector_signal_metadata_wins(self):
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                vector_score=0.806,
                confidence=0.68,
                importance=0.83,
                freshness=0.87,
                usage_score=0.57,
            ),
            _make_input(
                "noise",
                rrf_score=0.01635,
                vector_score=0.617,
                confidence=0.83,
                importance=0.93,
                freshness=0.87,
                usage_score=0.57,
            ),
            _make_input("floor", rrf_score=0.0141, vector_score=0.0),
        ]
        w = RerankerWeights(
            rrf=0.5,
            semantic=0.0,
            confidence=0.35,
            importance=0.30,
            freshness=0.20,
            usage=0.15,
            intent=0.10,
            bm25=0.15,
            band=0.05,
        )
        result = rerank(candidates, query_intent="unknown", weights=w)
        assert result[0][0] == "noise"

    def test_vector_uses_raw_value_with_band(self):
        a = _make_input("a", vector_score=0.8)
        b = _make_input("b", vector_score=0.3)
        result = rerank([a, b], weights=_weights(semantic=1.0))
        delta = result[0][1] - result[1][1]
        assert delta == pytest.approx(0.95 * 0.5)


class TestNegationAndKeyTerms:
    def test_negation_attenuates_relevance(self):
        candidates = [
            _make_input("gold", title="alpha", content="must not use redis", rrf_score=0.0164),
            _make_input("plain", title="alpha", content="use redis", rrf_score=0.0160),
        ]
        result = rerank(candidates, negations=["not"])
        assert result[0][0] == "plain"

    def test_key_term_bonus_is_additive(self):
        candidates = [
            _make_input("hit", title="alpha beta", content=""),
            _make_input("miss", title="alpha", content=""),
        ]
        result = rerank(
            candidates,
            weights=_weights(rrf=1.0, key_term_bonus=0.08),
            key_terms=["beta"],
        )
        # rrf 相同，key term 命中者胜出
        assert result[0][0] == "hit"
