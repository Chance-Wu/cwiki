"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestParasiticEvolutionConfig、TestFeatureFlagIntegration。
"""


class TestParasiticEvolutionConfig:
    def test_default_values_from_config_yaml(self):
        from packages.domain.config import parasitic_evolution_config

        assert parasitic_evolution_config.memory_gap_detection_enabled is True
        assert parasitic_evolution_config.memory_relations_enabled is True
        assert parasitic_evolution_config.agent_profile_enabled is True
        assert parasitic_evolution_config.proactive_push_enabled is True
        assert parasitic_evolution_config.memory_version_tracking_enabled is True

    def test_config_reads_from_yaml(self):
        from packages.domain.config import ParasiticEvolutionConfig, _yaml_config

        original = _yaml_config.get("parasitic_evolution")
        try:
            import packages.domain.config as config_module

            config_module._yaml_config["parasitic_evolution"] = {
                "memory_gap_detection_enabled": True,
                "memory_relations_enabled": True,
            }
            cfg = ParasiticEvolutionConfig()
            assert cfg.memory_gap_detection_enabled is True
            assert cfg.memory_relations_enabled is True
        finally:
            if original is not None:
                config_module._yaml_config["parasitic_evolution"] = original
            else:
                config_module._yaml_config.pop("parasitic_evolution", None)

    def test_missing_section_uses_defaults(self):
        import packages.domain.config as config_module
        from packages.domain.config import ParasiticEvolutionConfig

        original = config_module._yaml_config.get("parasitic_evolution")
        try:
            config_module._yaml_config.pop("parasitic_evolution", None)
            cfg = ParasiticEvolutionConfig()
            assert cfg.memory_gap_detection_enabled is False
        finally:
            if original is not None:
                config_module._yaml_config["parasitic_evolution"] = original


class TestFeatureFlagIntegration:
    """验证特性开关能真正拦截对应功能。"""
