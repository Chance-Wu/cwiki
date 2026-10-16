"""token 计数与预算约束测试。"""

from packages.retrieval.context.token_counter import (
    DEFAULT_BUDGET,
    estimate_tokens,
    normalize_budget,
    within_budget,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_english_text(self):
        text = "hello world this is a test"
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert tokens < len(text)

    def test_cjk_text(self):
        text = "这是一段中文测试文本"
        tokens = estimate_tokens(text)
        assert tokens > 0
        cjk_chars = len(text)
        assert tokens <= cjk_chars

    def test_cjk_higher_density(self):
        english = "a" * 100
        chinese = "中" * 100
        eng_tokens = estimate_tokens(english)
        cjk_tokens = estimate_tokens(chinese)
        assert cjk_tokens > eng_tokens


class TestNormalizeBudget:
    def test_none_returns_default(self):
        assert normalize_budget(None) == DEFAULT_BUDGET

    def test_exact_supported_value(self):
        assert normalize_budget(2000) == 2000

    def test_rounds_up_to_nearest(self):
        assert normalize_budget(1500) == 2000

    def test_below_minimum(self):
        assert normalize_budget(100) == 500

    def test_above_maximum(self):
        assert normalize_budget(10000) == 8000


class TestWithinBudget:
    def test_empty_list(self):
        assert within_budget([], 2000) == []

    def test_all_fit(self):
        memories = [
            {"id": "1", "content": "short"},
            {"id": "2", "content": "also short"},
        ]
        result = within_budget(memories, 2000)
        assert len(result) == 2

    def test_exceeds_budget(self):
        memories = [
            {"id": "1", "content": "word " * 500},
            {"id": "2", "content": "word " * 500},
        ]
        result = within_budget(memories, 100)
        assert len(result) < 2

    def test_respects_order(self):
        memories = [
            {"id": "1", "content": "first priority content"},
            {"id": "2", "content": "second priority content"},
            {"id": "3", "content": "third priority content"},
        ]
        result = within_budget(memories, 500)
        assert len(result) >= 1
        assert result[0]["id"] == "1"
