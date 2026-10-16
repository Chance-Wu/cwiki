"""apps.worker.dedup 冲突检测与向量检索测试。"""

import numpy as np

from apps.worker.dedup import _cosine_similarity


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-5

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-5

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) - (-1.0)) < 1e-5

    def test_empty_vectors(self):
        assert _cosine_similarity([], [1.0]) == 0.0

    def test_mismatched_lengths(self):
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


class TestNegationIndicators:
    @staticmethod
    def _make_vecs_with_similarity(target_sim: float) -> tuple[list[float], list[float]]:
        a = [1.0, 0.0, 0.0]
        b = [target_sim, (1 - target_sim**2) ** 0.5, 0.0]
        return a, b

    def test_chinese_negation_detected(self):
        from apps.worker.dedup import classify_relation

        a, b = self._make_vecs_with_similarity(0.70)
        result = classify_relation(a, b, "不使用连接池", "使用连接池")
        # MQ-302: 移除基于否定词的 CONFLICT 判定，改为保守的 similar
        assert result == "similar"

    def test_chinese_baomi(self):
        from apps.worker.dedup import classify_relation

        a, b = self._make_vecs_with_similarity(0.70)
        result = classify_relation(a, b, "避免使用 ORM", "使用 ORM")
        # MQ-302: 移除基于否定词的 CONFLICT 判定，改为保守的 similar
        assert result == "similar"

    def test_english_negation_detected(self):
        from apps.worker.dedup import classify_relation

        a, b = self._make_vecs_with_similarity(0.70)
        result = classify_relation(a, b, "Do not use connection pooling", "Use connection pooling")
        # MQ-302: 移除基于否定词的 CONFLICT 判定，改为保守的 similar
        assert result == "similar"

    def test_no_negation_is_similar(self):
        from apps.worker.dedup import classify_relation

        a, b = self._make_vecs_with_similarity(0.70)
        result = classify_relation(
            a,
            b,
            "Use connection pooling for databases",
            "Use connection pooling for database access",
        )
        # MQ-302: 相似度在 conflict 阈值之上时返回 similar，需人工判断
        assert result == "similar"


class TestClassifyRelationHighSimilarity:
    """merge 阈值之上的保守关系判定（MQ-302）。"""

    @staticmethod
    def _make_vecs_with_similarity(target_sim: float) -> tuple[list[float], list[float]]:
        a = [1.0, 0.0, 0.0]
        b = [target_sim, (1 - target_sim**2) ** 0.5, 0.0]
        return a, b

    def _classify(
        self,
        candidate_content: str,
        existing_content: str,
        candidate_title: str = "",
        existing_title: str = "",
    ) -> str:
        from apps.worker.dedup import classify_relation

        a, b = self._make_vecs_with_similarity(0.98)
        return classify_relation(
            a, b, candidate_content, existing_content, candidate_title, existing_title
        )

    def test_new_version_number_marks_update_candidate(self):
        # 候选带新版本号 → 建议更新（强信号）
        assert (
            self._classify(
                "部署流程使用 v2.1.0，包含蓝绿发布",
                "部署流程使用 v2.0.0，包含滚动发布",
            )
            == "update_candidate"
        )

    def test_new_date_marks_update_candidate(self):
        # 候选带新日期 → 建议更新（强信号）
        assert (
            self._classify(
                "2026-10-15 会议决定采用方案 B",
                "2026-09-01 会议讨论了方案 A/B",
            )
            == "update_candidate"
        )

    def test_superset_content_marks_similar(self):
        # MQ-302: 即使既有内容是候选子集，也返回 similar 需人工判断
        existing = "连接池大小 20，超时 30 秒，PostgreSQL 专用"
        candidate = existing + "，新增只读副本路由与失败重试 3 次"
        assert self._classify(candidate, existing, "数据库连接池", "数据库连接池") == "similar"

    def test_complementary_content_marks_similar(self):
        # MQ-302: 互补内容返回 similar 需人工判断
        assert (
            self._classify(
                "前端 Vite 构建配置要点与缓存策略",
                "后端 FastAPI 部署配置要点与端口规划",
                "前端构建",
                "后端部署",
            )
            == "similar"
        )

    def test_near_identical_content_marks_similar(self):
        # MQ-302: 近乎重复也返回 similar 需人工判断
        assert (
            self._classify(
                "使用 SQLAlchemy async 会话工厂",
                "使用 SQLAlchemy async 会话工厂。",
            )
            == "similar"
        )

    def test_title_similarity_returns_similar(self):
        # MQ-302: 标题相似度不再影响判定，统一返回 similar
        existing = "评审关注错误处理"
        candidate = existing + "并发"
        # 不带标题：similar
        assert self._classify(candidate, existing) == "similar"
        # 同一标题：仍然 similar（移除标题分层逻辑）
        assert self._classify(candidate, existing, "代码评审", "代码评审") == "similar"

    def test_dissimilar_title_returns_similar(self):
        # MQ-302: 标题差异大也返回 similar
        existing = "连接池大小 20，超时 30 秒"
        candidate = existing + "，新增只读副本路由"
        assert self._classify(candidate, existing, "读扩展方案", "写连接配置") == "similar"

    def test_missing_content_returns_similar(self):
        # MQ-302: 缺失内容也返回 similar
        assert self._classify("", "已有内容") == "similar"


class TestBatchVectorSearch:
    def test_numpy_batch_cosine(self):
        query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        matrix = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.707, 0.707, 0.0],
            ],
            dtype=np.float32,
        )

        norms = np.linalg.norm(matrix, axis=1)
        query_norm = np.linalg.norm(query)
        safe_norms = np.where(norms == 0, 1.0, norms)
        similarities = matrix @ query / (safe_norms * query_norm)

        assert abs(similarities[0] - 1.0) < 1e-4
        assert abs(similarities[1] - 0.0) < 1e-4
        assert similarities[0] > similarities[2] > similarities[1]
