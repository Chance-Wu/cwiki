"""动态重排权重与多样性限制测试。"""

from packages.retrieval.ranking.reranker import (
    RerankerWeights,
    RerankInput,
    diversity_limit_for_intent,
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


class TestWeightsForIntent:
    def test_unknown_returns_base(self):
        w = RerankerWeights.for_intent("unknown")
        base = RerankerWeights.from_settings()
        assert abs(w.rrf - base.rrf) < 1e-6

    def test_procedure_boosts_freshness(self):
        w = RerankerWeights.for_intent("procedure")
        base = RerankerWeights.from_settings()
        assert w.freshness > base.freshness

    def test_fact_boosts_confidence(self):
        w = RerankerWeights.for_intent("fact")
        base = RerankerWeights.from_settings()
        assert w.confidence > base.confidence

    def test_weights_sum_to_one(self):
        for intent in ["fact", "procedure", "lesson", "project_rule", "constraint", "decision"]:
            w = RerankerWeights.for_intent(intent)
            total = w.rrf + w.confidence + w.importance + w.freshness + w.usage + w.intent
            assert abs(total - 1.0) < 1e-6, f"{intent} weights sum to {total}"

    def test_project_rule_boosts_rrf(self):
        w = RerankerWeights.for_intent("project_rule")
        base = RerankerWeights.from_settings()
        assert w.rrf > base.rrf


class TestDiversityLimit:
    def test_fact_allows_more(self):
        assert diversity_limit_for_intent("fact") == 4

    def test_rule_restricts(self):
        assert diversity_limit_for_intent("project_rule") == 2

    def test_constraint_restricts(self):
        assert diversity_limit_for_intent("constraint") == 2

    def test_unknown_default(self):
        assert diversity_limit_for_intent("unknown") == 3

    def test_unmapped_intent_default(self):
        assert diversity_limit_for_intent("nonexistent") == 3


class TestRerankWithIntentConfidence:
    def test_low_confidence_uses_base_weights(self):
        candidates = [
            _make_input("a", rrf_score=0.9, freshness=0.1),
            _make_input("b", rrf_score=0.1, freshness=0.9),
        ]
        result = rerank(candidates, query_intent="procedure", intent_confidence=0.1)
        assert result[0][0] == "a"

    def test_high_confidence_uses_dynamic_weights(self):
        candidates = [
            _make_input("a", rrf_score=0.5, freshness=0.1, usage_score=0.1),
            _make_input("b", rrf_score=0.5, freshness=0.9, usage_score=0.9),
        ]
        result = rerank(
            candidates,
            query_intent="procedure",
            intent_confidence=0.8,
        )
        assert result[0][0] == "b"

    def test_explicit_weights_override_dynamic(self):
        candidates = [
            _make_input("a", rrf_score=0.9),
            _make_input("b", rrf_score=0.1),
        ]
        w = RerankerWeights(
            rrf=1.0, confidence=0.0, importance=0.0, freshness=0.0, usage=0.0, intent=0.0
        )
        result = rerank(
            candidates,
            query_intent="procedure",
            intent_confidence=0.9,
            weights=w,
        )
        assert result[0][0] == "a"
