"""packages.domain.config 配置加载测试。"""

import pytest

from packages.domain.config import ParasiticEvolutionConfig, Settings


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.embedding_dimensions == 512

    def test_reranker_weights_loaded(self):
        s = Settings()
        # 相关性组（组内归一）+ 元数据组（组内归一，仅 band 内生效）
        assert s.reranker_rrf_weight == 0.40
        assert s.reranker_semantic_weight == 0.30
        assert s.reranker_bm25_weight == 0.30
        assert s.reranker_intent_weight == 0.15
        assert s.reranker_confidence_weight == 0.35
        assert s.reranker_importance_weight == 0.30
        assert s.reranker_freshness_weight == 0.20
        assert s.reranker_usage_weight == 0.15
        assert s.reranker_key_term_bonus == 0.08
        assert s.reranker_relevance_band == 0.05

    def test_reranker_group_weights_sum_to_one(self):
        s = Settings()
        relevance = s.reranker_rrf_weight + s.reranker_semantic_weight + s.reranker_bm25_weight
        meta = (
            s.reranker_confidence_weight
            + s.reranker_importance_weight
            + s.reranker_freshness_weight
            + s.reranker_usage_weight
        )
        assert abs(relevance - 1.0) < 1e-6
        assert abs(meta - 1.0) < 1e-6
        assert s.reranker_intent_weight == pytest.approx(0.15)

    def test_is_sqlite(self):
        s = Settings()
        assert s.is_sqlite is True


class TestParasiticEvolutionConfig:
    def test_remaining_flags_exist(self):
        cfg = ParasiticEvolutionConfig()
        # 这些值来自 config.yaml，而非类默认值
        assert cfg.memory_gap_detection_enabled is True
        assert cfg.proactive_push_enabled is True
        assert cfg.memory_relations_enabled is True
        assert cfg.agent_profile_enabled is True
        assert cfg.memory_version_tracking_enabled is True
