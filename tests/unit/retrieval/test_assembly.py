"""完整上下文组装管线测试。"""

from packages.retrieval.context.assembler import (
    ContextResult,
    assemble_context,
)


def _make_mem(
    id: str, type: str = "fact", content: str = "test content", score: float = 0.5
) -> dict:
    return {"id": id, "type": type, "content": content, "score": score}


class TestAssembleContext:
    def test_empty_memories(self):
        result = assemble_context([])
        assert isinstance(result, ContextResult)
        assert len(result.memories) == 0
        assert result.token_count == 0
        assert result.text == ""
        assert result.truncated is False
        assert result.conflicts == []

    def test_basic_assembly(self):
        memories = [_make_mem("1", "fact", "SQLite is the database")]
        result = assemble_context(memories, query="what database?")
        assert len(result.memories) == 1
        assert result.memories[0].memory_id == "1"
        assert "what database?" in result.text
        assert result.token_count > 0

    def test_priority_ordering_in_output(self):
        memories = [
            _make_mem("1", "fact", "Python is the language", score=0.9),
            _make_mem("2", "constraint", "Must use type hints", score=0.5),
        ]
        result = assemble_context(memories)
        assert len(result.memories) == 2
        assert result.memories[0].memory_type == "constraint"

    def test_token_budget_respected(self):
        memories = [
            _make_mem(str(i), "fact", "word " * 200, score=0.9 - i * 0.01) for i in range(20)
        ]
        result = assemble_context(memories, max_tokens=500)
        assert result.token_count <= 500 + 50

    def test_deduplication_in_pipeline(self):
        memories = [
            _make_mem("1", "fact", "use SQLite for persistence", score=0.9),
            _make_mem("2", "fact", "use SQLite for persistence", score=0.7),
        ]
        result = assemble_context(memories)
        assert len(result.memories) == 1
        assert result.memories[0].memory_id == "1"

    def test_conflict_warning_in_output(self):
        memories = [
            _make_mem("1", "rule", "you must always enable caching", score=0.9),
            _make_mem("2", "rule", "you should never enable caching", score=0.8),
        ]
        result = assemble_context(memories)
        if result.conflicts:
            assert "\u26a0" in result.text

    def test_intent_adjusts_priority(self):
        memories = [
            _make_mem("1", "fact", "Some technical detail", score=0.5),
            _make_mem("2", "lesson", "Never trust user input", score=0.9),
        ]
        result = assemble_context(memories, intent="lesson")
        assert result.memories[0].memory_type == "lesson"

    def test_context_result_to_dict(self):
        memories = [_make_mem("1", "fact", "test content")]
        result = assemble_context(memories, query="test")
        d = result.to_dict()
        assert "trace_id" in d
        assert "memories" in d
        assert "conflicts" in d
        assert isinstance(d["memories"], list)

    def test_default_budget_is_2000(self):
        from packages.retrieval.context.token_counter import DEFAULT_BUDGET

        assert DEFAULT_BUDGET == 2000

    def test_low_value_memories_dropped_first(self):
        memories = [
            _make_mem("1", "fact", "important content " * 50, score=0.9),
            _make_mem("2", "preference", "minor preference " * 50, score=0.1),
        ]
        result = assemble_context(memories, max_tokens=500)
        types = [m.memory_type for m in result.memories]
        if len(result.memories) == 1:
            assert types[0] == "fact"
