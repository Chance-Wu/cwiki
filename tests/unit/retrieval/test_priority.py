"""上下文优先级排序测试。"""

import pytest

from packages.domain.config import settings
from packages.retrieval.context.priority import (
    DEFAULT_PRIORITY,
    get_priority_order,
    rank_by_priority,
)


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

    def test_rank_sorts_by_type_priority(self):
        memories = [
            {"id": "1", "type": "fact", "score": 0.9},
            {"id": "2", "type": "constraint", "score": 0.5},
            {"id": "3", "type": "lesson", "score": 0.7},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "2"
        assert result[1]["id"] == "3"
        assert result[2]["id"] == "1"

    def test_rank_within_same_type_by_score(self):
        memories = [
            {"id": "1", "type": "fact", "score": 0.5},
            {"id": "2", "type": "fact", "score": 0.9},
            {"id": "3", "type": "fact", "score": 0.7},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "2"
        assert result[1]["id"] == "3"
        assert result[2]["id"] == "1"

    def test_intent_adjusts_ordering(self):
        memories = [
            {"id": "1", "type": "constraint", "score": 0.9},
            {"id": "2", "type": "lesson", "score": 0.8},
            {"id": "3", "type": "fact", "score": 0.7},
        ]
        result = rank_by_priority(memories, intent="lesson")
        assert result[0]["id"] == "2"

    def test_empty_list(self):
        assert rank_by_priority([]) == []

    def test_unknown_type_gets_lowest_priority(self):
        memories = [
            {"id": "1", "type": "unknown_type", "score": 0.9},
            {"id": "2", "type": "fact", "score": 0.5},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "2"


@pytest.fixture
def fixed_utility_weight(monkeypatch):
    """固定效用权重，避免外部配置（config.local.yaml 等）影响断言。"""
    monkeypatch.setattr(settings, "utility_weight", 0.15)


class TestUtilityRanking:
    """utility_score 接入排序键后的行为。"""

    def test_same_type_same_score_higher_utility_first(self, fixed_utility_weight):
        memories = [
            {"id": "low", "type": "fact", "score": 0.8, "utility_score": 0.1},
            {"id": "high", "type": "fact", "score": 0.8, "utility_score": 0.9},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "high"

    def test_utility_can_overcome_small_score_gap(self, fixed_utility_weight):
        # 0.8 + 0.15×1.0 = 0.95 > 0.9 + 0.15×0 = 0.9：常用且好用的记忆反超
        memories = [
            {"id": "higher_score", "type": "fact", "score": 0.9},
            {"id": "used_and_useful", "type": "fact", "score": 0.8, "utility_score": 1.0},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "used_and_useful"

    def test_backward_compat_without_utility_key(self, fixed_utility_weight):
        # utility_score 键全部缺省时排序必须与原实现 (priority, -score) 一致
        memories = [
            {"id": "1", "type": "fact", "score": 0.5},
            {"id": "2", "type": "fact", "score": 0.9},
            {"id": "3", "type": "fact", "score": 0.7},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["2", "3", "1"]

    def test_partial_utility_key_defaults_to_zero(self, fixed_utility_weight):
        # 部分记忆带 utility_score=0 时行为必须与完全缺失一致（同步版
        # assemble_context 的调用方不一定注入该键）
        memories = [
            {"id": "1", "type": "fact", "score": 0.5, "utility_score": 0.0},
            {"id": "2", "type": "fact", "score": 0.9},
            {"id": "3", "type": "fact", "score": 0.7, "utility_score": 0.0},
        ]
        result = rank_by_priority(memories)
        assert [m["id"] for m in result] == ["2", "3", "1"]

    def test_type_priority_still_dominates_utility(self, fixed_utility_weight):
        # 效用只影响同优先级内部顺序，不能跨类型抢占 constraint 的位置
        memories = [
            {"id": "fact_high", "type": "fact", "score": 0.5, "utility_score": 1.0},
            {"id": "constraint_low", "type": "constraint", "score": 0.1},
        ]
        result = rank_by_priority(memories)
        assert result[0]["id"] == "constraint_low"
