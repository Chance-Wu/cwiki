"""上下文优先级排序测试：相关性主导，类型与效用只在带内微调。"""

import pytest

from packages.domain.config import settings
from packages.retrieval.context.priority import (
    DEFAULT_PRIORITY,
    get_priority_order,
    rank_by_priority,
)


@pytest.fixture
def fixed_band(monkeypatch):
    """固定 band 与效用占比，避免 config.local.yaml 影响断言。"""
    monkeypatch.setattr(settings, "reranker_relevance_band", 0.05)
    monkeypatch.setattr(settings, "utility_weight", 0.15)


class TestPriority:
    def test_default_priority_order(self):
        order = get_priority_order()
        assert order[0] == "constraint"
        assert order[1] == "decision"
        assert order[2] == "rule"

    def test_constraint_intent_promotes_constraint(self):
        order = get_priority_order("constraint")
        assert order[0] == "constraint"
        assert order[1] == "rule"

    def test_unknown_intent_uses_default(self):
        order = get_priority_order("unknown")
        assert order == DEFAULT_PRIORITY

    def test_relevance_dominates_type_priority(self, fixed_band):
        """低相关 constraint 不能跨带压过高相关 fact。"""
        memories = [
            {"id": "fact_high", "type": "fact", "score": 0.9},
            {"id": "constraint_low", "type": "constraint", "score": 0.5},
            {"id": "lesson_mid", "type": "lesson", "score": 0.7},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["fact_high", "lesson_mid", "constraint_low"]

    def test_type_priority_breaks_score_ties(self, fixed_band):
        memories = [
            {"id": "fact", "type": "fact", "score": 0.5},
            {"id": "constraint", "type": "constraint", "score": 0.5},
            {"id": "reference", "type": "reference", "score": 0.5},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "constraint"
        assert result[-1]["id"] == "reference"

    def test_intent_adjusts_ordering_within_band(self, fixed_band):
        """意图只在近邻分数内调整类型顺序，不整体重排。"""
        memories = [
            {"id": "constraint", "type": "constraint", "score": 0.782},
            {"id": "lesson", "type": "lesson", "score": 0.780},
            {"id": "fact", "type": "fact", "score": 0.600},
        ]
        result = rank_by_priority(memories, intent="lesson")
        assert result[0]["id"] == "lesson"

    def test_empty_list(self):
        assert rank_by_priority([]) == []

    def test_unknown_type_gets_lowest_priority(self, fixed_band):
        memories = [
            {"id": "unknown", "type": "unknown_type", "score": 0.5},
            {"id": "fact", "type": "fact", "score": 0.5},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "fact"

    def test_band_zero_disables_type_priority(self, monkeypatch):
        monkeypatch.setattr(settings, "reranker_relevance_band", 0.0)
        memories = [
            {"id": "low", "type": "constraint", "score": 0.4},
            {"id": "high", "type": "reference", "score": 0.9},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["high", "low"]


class TestUtilityRanking:
    """utility_score 只在 band 内参与排序。"""

    def test_higher_utility_flips_within_band(self, fixed_band):
        memories = [
            {"id": "higher_score", "type": "fact", "score": 0.900},
            {"id": "used_and_useful", "type": "fact", "score": 0.895, "utility_score": 1.0},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "used_and_useful"

    def test_utility_cannot_cross_band(self, fixed_band):
        memories = [
            {"id": "higher_score", "type": "fact", "score": 0.9},
            {"id": "used_and_useful", "type": "fact", "score": 0.8, "utility_score": 1.0},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "higher_score"

    def test_backward_compat_without_utility_key(self, fixed_band):
        memories = [
            {"id": "1", "type": "fact", "score": 0.5},
            {"id": "2", "type": "fact", "score": 0.9},
            {"id": "3", "type": "fact", "score": 0.7},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["2", "3", "1"]

    def test_partial_utility_key_defaults_to_zero(self, fixed_band):
        memories = [
            {"id": "1", "type": "fact", "score": 0.5, "utility_score": 0.0},
            {"id": "2", "type": "fact", "score": 0.9},
            {"id": "3", "type": "fact", "score": 0.7, "utility_score": 0.0},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["2", "3", "1"]

    def test_relevance_survives_utility_advantage(self, fixed_band):
        """效用不能跨带抢占高相关记忆的位置。"""
        memories = [
            {"id": "fact_high", "type": "fact", "score": 0.5, "utility_score": 1.0},
            {"id": "constraint_low", "type": "constraint", "score": 0.1},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "fact_high"
