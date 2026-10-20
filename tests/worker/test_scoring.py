"""apps/worker/scoring.py 测试 — 价值评分、新颖度、优先级分类。"""

import pytest

from apps.worker.scoring import (
    calculate_novelty,
    calculate_value_score,
    classify_priority,
    score_candidate,
)


class TestCalculateValueScore:
    def test_all_defaults(self):
        # MQ-102: 缺失维度返回 None（需补充）而非默认分
        candidate = {}
        score = calculate_value_score(candidate)
        assert score is None

    def test_all_none_values(self):
        # MQ-102: 所有维度为 None 时返回 None
        candidate = {
            "novelty": None,
            "reusability": None,
            "stability": None,
            "confidence": None,
            "importance": None,
            "evidence_strength": None,
        }
        score = calculate_value_score(candidate)
        assert score is None

    def test_partial_none_values(self):
        # MQ-102: 部分维度为 None 时返回 None（需补充完整）
        candidate = {
            "novelty": 0.9,
            "reusability": None,
            "stability": 0.8,
            "confidence": None,
            "importance": 0.7,
            "evidence_strength": None,
        }
        score = calculate_value_score(candidate)
        assert score is None

    def test_all_high_values(self):
        candidate = {
            "novelty": 0.9,
            "reusability": 0.95,
            "stability": 0.85,
            "confidence": 0.9,
            "importance": 0.88,
            "evidence_strength": 0.92,
        }
        score = calculate_value_score(candidate)
        assert score >= 0.85

    def test_all_low_values(self):
        candidate = {
            "novelty": 0.1,
            "reusability": 0.05,
            "stability": 0.15,
            "confidence": 0.1,
            "importance": 0.12,
            "evidence_strength": 0.08,
        }
        score = calculate_value_score(candidate)
        assert score < 0.35

    def test_weights_sum_to_one(self):
        candidate = {
            "novelty": 1.0,
            "reusability": 1.0,
            "stability": 1.0,
            "confidence": 1.0,
            "importance": 1.0,
            "evidence_strength": 1.0,
        }
        score = calculate_value_score(candidate)
        assert score == pytest.approx(1.0)

    def test_zero_inputs(self):
        candidate = {
            "novelty": 0.0,
            "reusability": 0.0,
            "stability": 0.0,
            "confidence": 0.0,
            "importance": 0.0,
            "evidence_strength": 0.0,
        }
        score = calculate_value_score(candidate)
        assert score == pytest.approx(0.0)

    def test_clamps_above_one(self):
        # MQ-102: 新公式不含 novelty，权重为 reusability(0.25) + stability(0.20) + confidence(0.20) + importance(0.20) + evidence_strength(0.15)
        candidate = {
            "reusability": 100.0,
            "stability": 100.0,
            "confidence": 100.0,
            "importance": 100.0,
            "evidence_strength": 100.0,
        }
        score = calculate_value_score(candidate)
        assert score <= 1.0

    def test_clamps_below_zero(self):
        # MQ-102: 新公式不含 novelty
        candidate = {
            "reusability": -1.0,
            "stability": -0.5,
            "confidence": -0.5,
            "importance": -0.5,
            "evidence_strength": -0.5,
        }
        score = calculate_value_score(candidate)
        assert score >= 0.0

    def test_reusability_has_highest_weight(self):
        # MQ-102: reusability 权重最高（0.25），novelty 不参与价值分计算
        base = {
            "stability": 0.5,
            "confidence": 0.5,
            "importance": 0.5,
            "evidence_strength": 0.5,
        }
        low = calculate_value_score({**base, "reusability": 0.2})
        high = calculate_value_score({**base, "reusability": 0.9})
        assert high > low
        assert (high - low) > 0.13

    def test_string_numeric_values(self):
        candidate = {
            "novelty": "0.8",
            "reusability": "0.7",
            "stability": 0.6,
            "confidence": 0.5,
            "importance": 0.9,
            "evidence_strength": 0.4,
        }
        score = calculate_value_score(candidate)
        assert 0.0 <= score <= 1.0


class TestClassifyPriority:
    def test_needs_enrichment_boundary(self):
        # MQ-102: None 和低分都归入 needs_enrichment（需补充维度）
        assert classify_priority(None) == "needs_enrichment"
        assert classify_priority(0.0) == "needs_enrichment"
        assert classify_priority(0.34) == "needs_enrichment"
        assert classify_priority(0.349) == "needs_enrichment"

    def test_low_priority_boundary(self):
        assert classify_priority(0.35) == "low_priority"
        assert classify_priority(0.50) == "low_priority"
        assert classify_priority(0.64) == "low_priority"
        assert classify_priority(0.649) == "low_priority"

    def test_normal_boundary(self):
        assert classify_priority(0.65) == "normal"
        assert classify_priority(0.75) == "normal"
        assert classify_priority(0.84) == "normal"
        assert classify_priority(0.849) == "normal"

    def test_high_value_boundary(self):
        assert classify_priority(0.85) == "high_value"
        assert classify_priority(0.95) == "high_value"
        assert classify_priority(1.0) == "high_value"

    def test_all_tiers_covered(self):
        # MQ-102: discard 改为 needs_enrichment
        scores = [None, 0.35, 0.65, 0.85]
        tiers = {classify_priority(s) for s in scores}
        assert tiers == {"needs_enrichment", "low_priority", "normal", "high_value"}


class TestCalculateNovelty:
    def test_no_existing_embeddings(self):
        novelty, idx = calculate_novelty([1.0, 0.0, 0.0], [])
        assert novelty == 1.0
        assert idx is None

    def test_empty_candidate_embedding(self):
        novelty, idx = calculate_novelty([], [[1.0, 0.0]])
        assert novelty == 0.5
        assert idx is None

    def test_identical_embeddings_low_novelty(self):
        vec = [1.0, 0.0, 0.0]
        novelty, idx = calculate_novelty(vec, [vec])
        assert novelty == pytest.approx(0.0, abs=0.01)
        assert idx == 0

    def test_orthogonal_embeddings_high_novelty(self):
        candidate = [1.0, 0.0]
        existing = [[0.0, 1.0]]
        novelty, _idx = calculate_novelty(candidate, existing)
        assert novelty == pytest.approx(1.0, abs=0.01)

    def test_opposite_direction(self):
        candidate = [1.0, 0.0]
        existing = [[-1.0, 0.0]]
        novelty, _idx = calculate_novelty(candidate, existing)
        assert novelty == pytest.approx(1.0, abs=0.01)

    def test_most_similar_index(self):
        candidate = [1.0, 0.0, 0.0]
        existing = [
            [0.0, 1.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 0.0, 1.0],
        ]
        _novelty, idx = calculate_novelty(candidate, existing)
        assert idx == 1

    def test_zero_vector_candidate(self):
        novelty, idx = calculate_novelty([0.0, 0.0, 0.0], [[1.0, 0.0, 0.0]])
        assert novelty == 0.5
        assert idx is None

    def test_zero_vector_existing(self):
        candidate = [1.0, 0.0]
        existing = [[0.0, 0.0], [0.0, 1.0]]
        novelty, _idx = calculate_novelty(candidate, existing)
        assert 0.0 <= novelty <= 1.0

    def test_multiple_existing_returns_max_similarity(self):
        candidate = [1.0, 0.0, 0.0]
        existing = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        novelty, idx = calculate_novelty(candidate, existing)
        assert novelty == pytest.approx(0.0, abs=0.01)
        assert idx == 0

    def test_novelty_clamped_to_zero_one(self):
        candidate = [1.0, 0.0]
        existing = [[-1.0, 0.0]]
        novelty, _ = calculate_novelty(candidate, existing)
        assert 0.0 <= novelty <= 1.0

    def test_dimension_mismatch_returns_fallback(self):
        candidate = [1.0, 0.0]
        existing = [[1.0, 0.0, 0.0]]
        novelty, idx = calculate_novelty(candidate, existing)
        assert novelty == 0.5
        assert idx is None

    def test_ragged_existing_embeddings_returns_fallback(self):
        candidate = [1.0, 0.0, 0.0]
        existing = [[1.0, 0.0, 0.0], [0.0, 1.0]]
        novelty, idx = calculate_novelty(candidate, existing)
        assert novelty == 0.5
        assert idx is None


class TestScoreCandidate:
    def test_minimal_candidate_all_defaults(self):
        # MQ-102: 缺失维度时 value_score 为 None，priority 为 needs_enrichment
        candidate = {"title": "test", "content": "raw content"}
        result = score_candidate(candidate)
        assert result["value_score"] is None
        assert result["novelty"] == pytest.approx(0.5)
        assert result["priority"] == "needs_enrichment"

    def test_none_fields_return_none_score(self):
        # MQ-102: None 字段不再默认为 0.5，返回 None 表示需补充
        candidate = {
            "title": "test",
            "content": "content",
            "novelty": None,
            "reusability": None,
            "stability": None,
            "confidence": None,
            "importance": None,
            "evidence_strength": None,
        }
        result = score_candidate(candidate)
        assert result["value_score"] is None
        assert result["novelty"] == pytest.approx(0.5)
        assert result["priority"] == "needs_enrichment"

    def test_high_quality_candidate(self):
        candidate = {
            "title": "关键架构决策",
            "content": "选择了事件溯源模式而非传统CRUD，因为需要完整的审计追踪",
            "novelty": 0.9,
            "reusability": 0.85,
            "stability": 0.9,
            "confidence": 0.95,
            "importance": 0.88,
            "evidence_strength": 0.92,
        }
        result = score_candidate(candidate)
        assert result["value_score"] >= 0.85
        assert result["priority"] == "high_value"

    def test_low_quality_candidate(self):
        # MQ-102: 低分候选归入 needs_enrichment 而非 discard
        candidate = {
            "title": "test",
            "content": "随便写的",
            "novelty": 0.1,
            "reusability": 0.05,
            "stability": 0.1,
            "confidence": 0.15,
            "importance": 0.1,
            "evidence_strength": 0.05,
        }
        result = score_candidate(candidate)
        assert result["value_score"] < 0.35
        assert result["priority"] == "needs_enrichment"

    def test_medium_quality_candidate(self):
        candidate = {
            "title": "项目约定",
            "content": "统一使用 ruff 进行代码格式化",
            "novelty": 0.5,
            "reusability": 0.6,
            "stability": 0.7,
            "confidence": 0.6,
            "importance": 0.5,
            "evidence_strength": 0.6,
        }
        result = score_candidate(candidate)
        assert 0.35 <= result["value_score"] < 0.85
        assert result["priority"] in ("low_priority", "normal")

    def test_with_embedding_novelty_computed(self):
        candidate = {
            "title": "test",
            "content": "content",
            "embedding": [1.0, 0.0, 0.0],
        }
        existing = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        result = score_candidate(candidate, existing_embeddings=existing)
        assert result["novelty"] == pytest.approx(1.0, abs=0.01)
        assert result["similar_index"] is not None

    def test_with_similar_embedding_low_novelty(self):
        candidate = {
            "title": "test",
            "content": "content",
            "embedding": [1.0, 0.0, 0.0],
        }
        existing = [[0.99, 0.01, 0.0]]
        result = score_candidate(candidate, existing_embeddings=existing)
        assert result["novelty"] < 0.1
        assert result["similar_index"] == 0

    def test_no_embedding_uses_default_novelty(self):
        candidate = {
            "title": "test",
            "content": "content",
            "novelty": 0.7,
        }
        result = score_candidate(candidate, existing_embeddings=[[1.0, 0.0]])
        assert result["novelty"] == pytest.approx(0.7)
        assert result["similar_index"] is None

    def test_preserves_original_fields(self):
        candidate = {
            "title": "原始标题",
            "content": "原始内容",
            "reusability": 0.8,
            "confidence": 0.9,
        }
        result = score_candidate(candidate)
        assert result["title"] == "原始标题"
        assert result["content"] == "原始内容"
        assert result["reusability"] == 0.8
        assert result["confidence"] == 0.9

    def test_does_not_mutate_input(self):
        candidate = {"title": "test", "novelty": 0.8}
        original_novelty = candidate["novelty"]
        score_candidate(candidate)
        assert candidate["novelty"] == original_novelty
        assert "value_score" not in candidate

    def test_empty_title_and_content(self):
        # MQ-102: 空内容时 value_score 为 None
        candidate = {"title": "", "content": ""}
        result = score_candidate(candidate)
        assert result["value_score"] is None
        assert result["priority"] == "needs_enrichment"

    def test_long_detailed_content(self):
        candidate = {
            "title": "性能优化经验",
            "content": "在大规模数据管道中，批量 embedding 比逐条调用快 10 倍。"
            "关键是将文本分批，每批不超过 API 限制。"
            "同时需要注意超时设置和重试逻辑。",
            "novelty": 0.8,
            "reusability": 0.9,
            "stability": 0.7,
            "confidence": 0.85,
            "importance": 0.75,
            "evidence_strength": 0.88,
        }
        result = score_candidate(candidate)
        assert result["value_score"] >= 0.75
        assert result["priority"] in ("normal", "high_value")

    def test_vague_low_effort_content(self):
        # MQ-102: 低质量内容归入 needs_enrichment
        candidate = {
            "title": "笔记",
            "content": "一些想法",
            "novelty": 0.3,
            "reusability": 0.2,
            "stability": 0.2,
            "confidence": 0.1,
            "importance": 0.1,
            "evidence_strength": 0.1,
        }
        result = score_candidate(candidate)
        assert result["priority"] == "needs_enrichment"

    def test_mixed_none_and_values(self):
        # MQ-102: 部分维度为 None 时返回 None
        candidate = {
            "title": "混合测试",
            "content": "部分字段为 None",
            "novelty": 0.8,
            "reusability": None,
            "stability": 0.6,
            "confidence": None,
            "importance": 0.7,
            "evidence_strength": None,
        }
        result = score_candidate(candidate)
        assert result["value_score"] is None
        assert result["novelty"] == pytest.approx(0.8)
        assert result["priority"] == "needs_enrichment"
