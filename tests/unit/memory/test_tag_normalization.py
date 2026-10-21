"""标签规范化测试。

验证标签在所有写入路径被统一处理：去空格、转小写、去重、过滤空串。
"""

from packages.memory.service import normalize_tags


class TestNormalizeTags:
    def test_strips_whitespace(self):
        assert normalize_tags(["  foo  ", "bar\t", "\nbaz"]) == ["foo", "bar", "baz"]

    def test_lowercases(self):
        assert normalize_tags(["Python", "FASTAPI", "ReAct"]) == ["python", "fastapi", "react"]

    def test_deduplicates(self):
        assert normalize_tags(["python", "Python", "PYTHON"]) == ["python"]

    def test_filters_empty_strings(self):
        assert normalize_tags(["foo", "", "  ", "bar"]) == ["foo", "bar"]

    def test_handles_none_input(self):
        assert normalize_tags(None) == []

    def test_handles_empty_list(self):
        assert normalize_tags([]) == []

    def test_combined_normalization(self):
        result = normalize_tags(["  Python ", "fastapi", "Python", "", "  ", "ReAct"])
        assert result == ["python", "fastapi", "react"]

    def test_preserves_order(self):
        result = normalize_tags(["zebra", "apple", "mango"])
        assert result == ["zebra", "apple", "mango"]

    def test_dedup_keeps_first_occurrence(self):
        result = normalize_tags(["Python", "python", "PYTHON"])
        assert result == ["python"]
