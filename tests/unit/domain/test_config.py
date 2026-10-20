"""packages.domain.config 配置加载测试。"""

from packages.domain.config import ParasiticEvolutionConfig, Settings


class TestSettings:
    def test_default_values(self):
        s = Settings()
        assert s.embedding_dimensions == 512

    def test_reranker_weights_loaded(self):
        s = Settings()
        # W6-B 权重重平衡（新增 semantic，元数据信号让位）
        assert s.reranker_rrf_weight == 0.38
        assert s.reranker_semantic_weight == 0.15
        assert s.reranker_confidence_weight == 0.10
        assert s.reranker_importance_weight == 0.12
        assert s.reranker_freshness_weight == 0.10
        assert s.reranker_usage_weight == 0.06
        assert s.reranker_intent_weight == 0.09
        assert s.reranker_key_term_bonus == 0.08

    def test_reranker_weights_sum_to_one(self):
        s = Settings()
        total = (
            s.reranker_rrf_weight
            + s.reranker_semantic_weight
            + s.reranker_confidence_weight
            + s.reranker_importance_weight
            + s.reranker_freshness_weight
            + s.reranker_usage_weight
            + s.reranker_intent_weight
        )
        assert abs(total - 1.0) < 1e-6

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
        assert cfg.auto_consolidate_enabled is True
