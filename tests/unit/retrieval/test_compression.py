"""L1–L5 上下文压缩测试。"""

from packages.retrieval.context.compression import (
    DEFAULT_RESERVE_TYPES,
    apply_per_memory_cap,
    degrade_to_fit,
    merge_similar_memories,
    per_memory_cap,
    reserve_priority,
    trim_content_to_cap,
)
from packages.retrieval.context.token_counter import estimate_tokens


class TestPerMemoryCap:
    def test_default_ratio(self):
        assert per_memory_cap(2000) == 500

    def test_custom_ratio(self):
        assert per_memory_cap(2000, ratio=0.5) == 1000

    def test_minimum_cap(self):
        assert per_memory_cap(100, ratio=0.1) == 50

    def test_small_budget(self):
        assert per_memory_cap(500, ratio=0.25) == 125


class TestTrimContentToCap:
    def test_short_content_unchanged(self):
        content = "Short content that fits."
        result = trim_content_to_cap(content, cap_tokens=100)
        assert result == content

    def test_empty_content(self):
        assert trim_content_to_cap("", cap_tokens=100) == ""

    def test_single_paragraph_truncated(self):
        content = "First sentence. " * 50
        cap = estimate_tokens(content) // 2
        result = trim_content_to_cap(content, cap_tokens=cap)
        assert result.endswith("...")
        assert estimate_tokens(result) <= cap + 5

    def test_multi_paragraph_keeps_first(self):
        first = "Core conclusion: always do X."
        middle = "Supporting detail that is very long. " * 20
        last = "Exception: unless Y."
        content = f"{first}\n\n{middle}\n\n{last}"

        cap = estimate_tokens(first) + 20
        result = trim_content_to_cap(content, cap_tokens=cap)

        assert first in result
        assert "... [已压缩]" in result

    def test_multi_paragraph_keeps_first_and_last(self):
        first = "Rule: use Python."
        middle = "Details about Python that go on for a while. " * 10
        last = "Exception: unless performance critical."
        content = f"{first}\n\n{middle}\n\n{last}"

        cap = estimate_tokens(first) + estimate_tokens(last) + 15
        result = trim_content_to_cap(content, cap_tokens=cap)

        assert first in result
        assert last in result
        assert "... [已压缩]" in result

    def test_cjk_content(self):
        first = "核心结论：必须使用 Python。"
        middle = "详细说明" * 50
        last = "例外情况：性能关键路径可用 Rust。"
        content = f"{first}\n\n{middle}\n\n{last}"

        cap = estimate_tokens(first) + 10
        result = trim_content_to_cap(content, cap_tokens=cap)

        assert "核心结论" in result
        assert result.endswith("...") or "... [已压缩]" in result
        assert estimate_tokens(result) <= cap + 10


class TestApplyPerMemoryCap:
    def test_no_compression_needed(self):
        memories = [
            {"id": "1", "content": "short content", "title": "Test"},
        ]
        result, trimmed = apply_per_memory_cap(memories, budget=2000)
        assert len(result) == 1
        assert trimmed == 0
        assert result[0]["content"] == "short content"

    def test_compression_applied(self):
        long_content = "This is a very long memory content. " * 100
        memories = [
            {"id": "1", "content": long_content, "title": "Long Memory"},
        ]
        result, trimmed = apply_per_memory_cap(memories, budget=2000, ratio=0.25)

        assert trimmed == 1
        assert result[0]["_compressed"] is True
        assert estimate_tokens(result[0]["content"]) <= 500 + 20

    def test_mixed_compression(self):
        long_content = "Long content. " * 200
        short_content = "Short."
        memories = [
            {"id": "1", "content": long_content, "title": "Long"},
            {"id": "2", "content": short_content, "title": "Short"},
        ]
        result, trimmed = apply_per_memory_cap(memories, budget=2000, ratio=0.25)

        assert trimmed == 1
        assert result[0]["_compressed"] is True
        assert "_compressed" not in result[1]
        assert result[1]["content"] == short_content

    def test_empty_list(self):
        result, trimmed = apply_per_memory_cap([], budget=2000)
        assert result == []
        assert trimmed == 0

    def test_custom_ratio(self):
        content = "Word. " * 500
        memories = [{"id": "1", "content": content, "title": "Test"}]

        _, trimmed_narrow = apply_per_memory_cap(memories, budget=2000, ratio=0.1)
        _, trimmed_wide = apply_per_memory_cap(memories, budget=2000, ratio=0.8)

        assert trimmed_narrow == 1
        assert trimmed_wide == 0


class TestMergeSimilarMemories:
    def test_skips_when_under_trigger(self):
        memories = [
            {"id": "1", "content": "short", "score": 0.9},
            {"id": "2", "content": "also short", "score": 0.8},
        ]
        result, merged = merge_similar_memories(memories, budget=2000)
        assert len(result) == 2
        assert merged == 0

    def test_merges_similar_with_embedding(self):
        emb = [1.0, 0.0, 0.0]
        memories = [
            {"id": "1", "content": "Python is great", "score": 0.9, "embedding": emb},
            {"id": "2", "content": "Python is awesome", "score": 0.8, "embedding": emb},
            {"id": "3", "content": "Python rocks", "score": 0.7, "embedding": emb},
        ]
        long_content = "word " * 500
        for m in memories:
            m["content"] = long_content

        result, merged = merge_similar_memories(memories, budget=2000, threshold=0.85)
        assert merged == 2
        assert len(result) == 1
        assert "等 3 条相关记忆已合并" in result[0]["content"]
        assert result[0]["id"] == "1"

    def test_preserves_dissimilar(self):
        emb1 = [1.0, 0.0, 0.0]
        emb2 = [0.0, 1.0, 0.0]
        long_content = "word " * 500
        memories = [
            {"id": "1", "content": long_content, "score": 0.9, "embedding": emb1},
            {"id": "2", "content": long_content, "score": 0.8, "embedding": emb2},
        ]

        result, merged = merge_similar_memories(memories, budget=2000, threshold=0.85)
        assert merged == 0
        assert len(result) == 2

    def test_fallback_to_hash_grouping(self):
        long_content = "word " * 500
        memories = [
            {"id": "1", "content": long_content, "score": 0.9},
            {"id": "2", "content": long_content, "score": 0.8},
        ]

        result, merged = merge_similar_memories(memories, budget=2000, threshold=0.85)
        assert merged == 1
        assert len(result) == 1

    def test_empty_list(self):
        result, merged = merge_similar_memories([], budget=2000)
        assert result == []
        assert merged == 0

    def test_custom_trigger_ratio(self):
        emb = [1.0, 0.0, 0.0]
        long_content = "word " * 500
        memories = [
            {"id": "1", "content": long_content, "score": 0.9, "embedding": emb},
            {"id": "2", "content": long_content, "score": 0.8, "embedding": emb},
        ]

        _, merged_low = merge_similar_memories(memories, budget=2000, trigger_ratio=0.3)
        _, merged_high = merge_similar_memories(memories, budget=2000, trigger_ratio=0.9)

        assert merged_low > 0
        assert merged_high == 0


class TestDegradeToFit:
    def test_fits_within_budget(self):
        memories = [
            {"id": "1", "content": "short", "title": "A"},
            {"id": "2", "content": "also short", "title": "B"},
        ]
        result, degraded = degrade_to_fit(memories, budget=2000)
        assert len(result) == 2
        assert degraded == 0

    def test_degrades_to_summary(self):
        long_content = "First sentence. " + "More details. " * 50
        memories = [
            {"id": "1", "content": "short", "title": "High priority"},
            {"id": "2", "content": long_content, "title": "Low priority"},
        ]
        budget = estimate_tokens("short") + estimate_tokens("First sentence.") + 5
        result, degraded = degrade_to_fit(memories, budget=budget)
        assert degraded >= 1
        assert result[-1]["content"].startswith("First sentence.")
        assert result[-1]["_degraded_level"] == 1

    def test_degrades_to_title_only(self):
        long1 = "word " * 200
        long2 = "word " * 200
        memories = [
            {"id": "1", "content": long1, "title": "First"},
            {"id": "2", "content": long2, "title": "Second"},
        ]
        budget = estimate_tokens(long1) + 5
        result, degraded = degrade_to_fit(memories, budget=budget)
        assert degraded >= 1
        title_only = [m for m in result if m.get("_degraded_level") == 2]
        assert len(title_only) >= 1
        assert title_only[0]["content"] == ""

    def test_degrades_all_to_title_when_tight_budget(self):
        memories = [
            {"id": "1", "content": "word " * 100, "title": "First"},
            {"id": "2", "content": "word " * 100, "title": "Second"},
            {"id": "3", "content": "word " * 100, "title": "Third"},
        ]
        budget = 10
        result, degraded = degrade_to_fit(memories, budget=budget)
        assert degraded == 3
        assert all(m.get("_degraded_level") == 2 for m in result)
        assert all(m["content"] == "" for m in result)

    def test_empty_list(self):
        result, degraded = degrade_to_fit([], budget=2000)
        assert result == []
        assert degraded == 0

    def test_preserves_high_priority(self):
        long_content = "word " * 200
        memories = [
            {"id": "1", "content": long_content, "title": "High"},
            {"id": "2", "content": long_content, "title": "Low"},
        ]
        budget = estimate_tokens(long_content) + 5
        result, _ = degrade_to_fit(memories, budget=budget)
        assert result[0]["id"] == "1"
        assert result[0].get("_degraded_level", 0) == 0


class TestReservePriority:
    def test_reserved_types_placed_first(self):
        memories = [
            {"id": "1", "type": "fact", "content": "some fact", "score": 0.9},
            {"id": "2", "type": "constraint", "content": "must do X", "score": 0.8},
            {"id": "3", "type": "rule", "content": "always Y", "score": 0.7},
        ]
        result, reserved_tokens = reserve_priority(memories, budget=2000)
        assert result[0]["type"] == "constraint"
        assert result[1]["type"] == "rule"
        assert result[2]["type"] == "fact"
        assert reserved_tokens > 0

    def test_reserved_tokens_counted(self):
        constraint_content = "This is a constraint."
        memories = [
            {"id": "1", "type": "constraint", "content": constraint_content, "score": 0.9},
            {"id": "2", "type": "fact", "content": "some fact", "score": 0.8},
        ]
        _, reserved_tokens = reserve_priority(memories, budget=2000)
        assert reserved_tokens == estimate_tokens(constraint_content)

    def test_no_reserved_types(self):
        memories = [
            {"id": "1", "type": "fact", "content": "fact one", "score": 0.9},
            {"id": "2", "type": "lesson", "content": "lesson one", "score": 0.8},
        ]
        result, reserved_tokens = reserve_priority(memories, budget=2000)
        assert len(result) == 2
        assert reserved_tokens == 0
        assert result[0]["id"] == "1"

    def test_empty_list(self):
        result, reserved_tokens = reserve_priority([], budget=2000)
        assert result == []
        assert reserved_tokens == 0

    def test_custom_reserve_types(self):
        memories = [
            {"id": "1", "type": "fact", "content": "fact", "score": 0.9},
            {"id": "2", "type": "decision", "content": "we decided X", "score": 0.8},
        ]
        custom_types = frozenset({"decision"})
        result, reserved_tokens = reserve_priority(
            memories, budget=2000, reserve_types=custom_types
        )
        assert result[0]["type"] == "decision"
        assert reserved_tokens > 0

    def test_reserved_memories_keep_full_content(self):
        long_constraint = "Important constraint. " * 50
        long_fact = "Some fact detail. " * 50
        memories = [
            {"id": "1", "type": "constraint", "content": long_constraint, "score": 0.9},
            {"id": "2", "type": "fact", "content": long_fact, "score": 0.8},
        ]
        result, _ = reserve_priority(memories, budget=2000)
        assert result[0]["content"] == long_constraint
        assert "_degraded_level" not in result[0]

    def test_default_reserve_types(self):
        assert "constraint" in DEFAULT_RESERVE_TYPES
        assert "rule" in DEFAULT_RESERVE_TYPES
        assert "fact" not in DEFAULT_RESERVE_TYPES
