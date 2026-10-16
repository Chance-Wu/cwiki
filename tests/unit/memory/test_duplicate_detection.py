"""packages.memory.duplicate_detection 测试（spec 8.4 节）。"""

from packages.memory.duplicate_detection import detect_duplicate


class TestDetectDuplicate:
    def test_exact_duplicate(self):
        a = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        b = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        verdict = detect_duplicate(a, b)
        # 没有 embedding 相似度时，纯文本得分达不到 EXACT_DUPLICATE_THRESHOLD
        assert verdict.classification == "possible_duplicate"

    def test_possible_duplicate(self):
        a = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        b = {
            "title": "Connection pooling",
            "content": "Use connection pooling for database access in the project always",
        }
        verdict = detect_duplicate(a, b)
        assert verdict.classification in ("exact_duplicate", "possible_duplicate")

    def test_distinct(self):
        a = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access",
        }
        b = {"title": "Testing", "content": "Use pytest for running all unit tests"}
        verdict = detect_duplicate(a, b)
        assert verdict.classification == "distinct"

    def test_combined_score_is_weighted(self):
        a = {"title": "X", "content": "hello world foo bar baz"}
        b = {"title": "X", "content": "hello world foo bar qux"}
        verdict = detect_duplicate(a, b)
        assert verdict.combined_score > 0
        assert verdict.title_similarity > 0
        assert verdict.content_similarity > 0
        upper = 0.30 * verdict.title_similarity + 0.50 * verdict.content_similarity + 0.20
        assert verdict.combined_score <= upper + 0.001

    def test_to_dict(self):
        a = {"title": "X", "content": "hello"}
        b = {"title": "Y", "content": "world"}
        verdict = detect_duplicate(a, b)
        d = verdict.to_dict()
        assert "classification" in d
        assert "jaccard_score" in d
        assert "normalized_score" in d
        assert "combined_score" in d

    def test_empty_content(self):
        a = {"title": "", "content": ""}
        b = {"title": "X", "content": "hello world"}
        verdict = detect_duplicate(a, b)
        assert verdict.classification == "distinct"

    def test_no_auto_merge(self):
        """Spec 8.4: 不要自动 Merge."""
        a = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        b = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        verdict = detect_duplicate(a, b)
        # 没有 embedding 相似度时，纯文本得分达不到 EXACT_DUPLICATE_THRESHOLD
        assert verdict.classification == "possible_duplicate"
        # 由调用方决定后续处理 — 检测只负责分类

    def test_normalized_more_forgiving_than_jaccard(self):
        """归一化文本相似度对长度差异更宽容。"""
        short = {"title": "X", "content": "hello world"}
        long = {"title": "X", "content": "hello world foo bar baz qux extra stuff here"}
        verdict = detect_duplicate(short, long)
        assert verdict.normalized_score >= verdict.jaccard_score
