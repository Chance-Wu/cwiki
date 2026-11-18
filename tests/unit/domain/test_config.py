"""packages.domain.config 配置加载测试。"""

import pytest

from packages.domain import config as domain_config
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


class TestAutoRecallFlag:
    """召回总闸 retrieval.auto_recall_enabled 的加载语义。"""

    def _retrieval_with(self, monkeypatch, **override):
        retrieval = dict(domain_config._yaml_config.get("retrieval", {}))
        retrieval.update(override)
        monkeypatch.setitem(domain_config._yaml_config, "retrieval", retrieval)
        return retrieval

    def test_defaults_to_true_when_key_absent(self, monkeypatch):
        retrieval = self._retrieval_with(monkeypatch)
        retrieval.pop("auto_recall_enabled", None)
        assert Settings().auto_recall_enabled is True

    def test_reads_false_from_config(self, monkeypatch):
        self._retrieval_with(monkeypatch, auto_recall_enabled=False)
        assert Settings().auto_recall_enabled is False

    def test_reload_picks_up_flag_change(self, monkeypatch):
        self._retrieval_with(monkeypatch, auto_recall_enabled=True)
        s = Settings()
        self._retrieval_with(monkeypatch, auto_recall_enabled=False)
        s.reload()
        assert s.auto_recall_enabled is False


class TestStorageConfigReload:
    """reload_yaml_config 必须同步刷新存储侧模块级配置。"""

    def test_reload_picks_up_memory_dir_change(self, monkeypatch):
        import copy

        from packages.storage import config as storage_config
        from packages.storage.config import reload_storage_config

        saved_yaml = copy.deepcopy(domain_config._yaml_config)
        original_memory_dir = storage_config.memory_dir
        base = copy.deepcopy(saved_yaml)
        base.setdefault("storage", {})["memory_dir"] = "./tmp-reload-test"

        def _fake_load():
            return copy.deepcopy(base)

        monkeypatch.setattr(domain_config, "_load_yaml_config", _fake_load)
        try:
            domain_config.reload_yaml_config()
            assert storage_config.memory_dir == "./tmp-reload-test"
            # 派生路径一并重算
            assert storage_config.index_db_path.endswith("tmp-reload-test/index.db")
            assert storage_config.vector_meta_path.endswith("tmp-reload-test/vectors.json")
        finally:
            # 原地恢复，保持 storage.config 持有的 dict 引用有效
            domain_config._yaml_config.clear()
            domain_config._yaml_config.update(saved_yaml)
            reload_storage_config()
        assert storage_config.memory_dir == original_memory_dir
