"""packages.memory.duplicate_detection 测试（spec 8.4 节）。"""

from typing import ClassVar

from packages.memory.duplicate_detection import (
    batch_detect_duplicates,
    detect_duplicate,
    precompute_combined,
)


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
        verdict = detect_duplicate(a, b, embedding_similarity=1.0)
        assert verdict.classification == "exact_duplicate"

    def test_exact_unreachable_without_embedding(self):
        """不提供 embedding 时词面满分约 0.70，达不到 exact 阈值（明确记录而非缺陷）。"""
        a = {
            "title": "Use connection pooling",
            "content": "Always use connection pooling for database access in this project",
        }
        b = dict(a)
        verdict = detect_duplicate(a, b)
        assert verdict.classification == "possible_duplicate"
        assert verdict.combined_score < 0.85

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
        verdict = detect_duplicate(a, b, embedding_similarity=1.0)
        assert verdict.classification == "exact_duplicate"
        # 由调用方决定后续处理 — 检测只负责分类

    def test_normalized_more_forgiving_than_jaccard(self):
        """归一化文本相似度对长度差异更宽容。"""
        short = {"title": "X", "content": "hello world"}
        long = {"title": "X", "content": "hello world foo bar baz qux extra stuff here"}
        verdict = detect_duplicate(short, long)
        assert verdict.normalized_score >= verdict.jaccard_score


class TestBatchDetectDuplicate:
    def test_batch_reuses_precomputed_tokens_and_embedding(self):
        candidate = {
            "title": "Connection pooling",
            "content": "Always use connection pooling for database access",
        }
        items = [
            {
                "title": "Connection pooling",
                "content": "Always use connection pooling for database access",
            },
            {"title": "Testing", "content": "Use pytest for running unit tests"},
        ]
        verdicts = batch_detect_duplicates(
            candidate,
            precompute_combined(items),
            embedding_similarities=[0.99, 0.0],
        )
        assert verdicts[0].classification == "exact_duplicate"
        assert verdicts[1].classification == "distinct"


class TestConfiguredStrategyAndWeights:
    """memory.similarity_strategy / similarity_hybrid_weights 在生产判定路径生效。

    回归背景：_build_verdict 此前从不读取配置，两个配置项只在文档里存在，
    生产查重始终用模块常量权重。
    """

    _A: ClassVar[dict[str, str]] = {
        "title": "Redis 连接池",
        "content": "使用 connection pooling 避免句柄耗尽",
    }
    _B: ClassVar[dict[str, str]] = {
        "title": "Redis 连接池",
        "content": "使用 connection pool 避免耗尽句柄",
    }

    def test_embedding_strategy_ignores_lexical_overlap(self, monkeypatch) -> None:
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "similarity_strategy", "embedding", raising=False)
        monkeypatch.setattr(settings, "similarity_hybrid_weights", {}, raising=False)

        no_vec = detect_duplicate(self._A, self._B, embedding_similarity=0.0)
        assert no_vec.combined_score == 0.0

        with_vec = detect_duplicate(self._A, self._B, embedding_similarity=0.9)
        assert with_vec.combined_score == 0.9

    def test_jaccard_strategy_drops_embedding_channel(self, monkeypatch) -> None:
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "similarity_strategy", "jaccard", raising=False)

        low = detect_duplicate(self._A, self._B, embedding_similarity=0.0)
        high = detect_duplicate(self._A, self._B, embedding_similarity=1.0)
        assert low.combined_score == high.combined_score
        assert high.combined_score > 0.0

    def test_hybrid_weights_are_normalized_and_applied(self, monkeypatch) -> None:
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "similarity_strategy", "hybrid", raising=False)
        monkeypatch.setattr(
            settings,
            "similarity_hybrid_weights",
            {"title": 0.0, "content": 0.0, "keyword": 0.0, "embedding": 5.0},
            raising=False,
        )

        # 权重全部落在 embedding 通道：词面分被完全忽略
        verdict = detect_duplicate(self._A, self._B, embedding_similarity=0.42)
        assert verdict.combined_score == 0.42

    def test_unknown_strategy_falls_back_to_hybrid(self, monkeypatch) -> None:
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "similarity_strategy", "nonsense", raising=False)
        monkeypatch.setattr(
            settings,
            "similarity_hybrid_weights",
            {"title": 0.2, "content": 0.35, "keyword": 0.15, "embedding": 0.3},
            raising=False,
        )

        verdict = detect_duplicate(self._A, self._B, embedding_similarity=0.5)
        assert 0.0 < verdict.combined_score < 1.0
