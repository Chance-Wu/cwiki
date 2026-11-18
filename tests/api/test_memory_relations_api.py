"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestMemoryRelations。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock


class TestMemoryRelations:
    """P4-40：记忆关系图谱。"""

    async def test_memory_relation_model_exists(self):
        from packages.domain.models import MemoryRelation

        assert MemoryRelation.__tablename__ == "memory_relation"
        assert hasattr(MemoryRelation, "source_memory_id")
        assert hasattr(MemoryRelation, "target_memory_id")
        assert hasattr(MemoryRelation, "relation_type")
        assert hasattr(MemoryRelation, "confidence")

    async def test_relation_types(self):
        from packages.domain.models import MemoryRelation

        valid_types = ["related", "contradicts", "supersedes", "depends_on", "extends"]
        rel = MemoryRelation(
            id=uuid.uuid4(),
            source_memory_id=uuid.uuid4(),
            target_memory_id=uuid.uuid4(),
            relation_type="related",
            confidence=0.8,
        )
        assert rel.relation_type in valid_types

    async def test_auto_detect_relations_skips_when_disabled(self):
        from apps.api.routes.reviews import _auto_detect_relations

        db = AsyncMock()
        memory = MagicMock()
        memory.id = uuid.uuid4()
        memory.workspace_id = uuid.uuid4()

        import apps.api.routes.reviews as reviews_module

        original_config = reviews_module.parasitic_evolution_config

        mock_config = MagicMock()
        mock_config.memory_relations_enabled = False
        reviews_module.parasitic_evolution_config = mock_config

        try:
            await _auto_detect_relations(memory, db)
            db.execute.assert_not_called()
        finally:
            reviews_module.parasitic_evolution_config = original_config

    async def test_auto_detect_relations_creates_related(self):
        from apps.api.routes.reviews import _auto_detect_relations
        from packages.domain.models import MemoryRelation

        ws_id = uuid.uuid4()
        mem_id = uuid.uuid4()
        other_id = uuid.uuid4()

        memory = MagicMock()
        memory.id = mem_id
        memory.workspace_id = ws_id
        memory.title = "Python async patterns"
        memory.content = "asyncio and await patterns in Python"

        existing = [
            (other_id, "Python async guide", "asyncio and await patterns guide for Python", None)
        ]

        db = AsyncMock()
        db.add_all = MagicMock()
        rel_result = MagicMock()
        rel_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=rel_result)

        import apps.api.routes.reviews as reviews_module

        original_config = reviews_module.parasitic_evolution_config
        mock_config = MagicMock()
        mock_config.memory_relations_enabled = True
        reviews_module.parasitic_evolution_config = mock_config

        try:
            await _auto_detect_relations(memory, db, existing_memories=existing)
            added = [
                arg
                for call in db.add_all.call_args_list
                for arg in call.args[0]
                if isinstance(arg, MemoryRelation)
            ]
            assert len(added) >= 1
            rel = added[0]
            assert rel.source_memory_id == mem_id
            assert rel.target_memory_id == other_id
            assert rel.relation_type in (
                "related",
                "supersedes",
                "supports",
                "refines",
                "contradicts",
            )
        finally:
            reviews_module.parasitic_evolution_config = original_config

    async def test_auto_detect_relations_dual_signal_fusion(self):
        from unittest.mock import patch

        from apps.api.routes.reviews import _auto_detect_relations
        from packages.domain.models import MemoryRelation

        mem_id = uuid.uuid4()
        other_id = uuid.uuid4()

        memory = MagicMock()
        memory.id = mem_id
        memory.workspace_id = uuid.uuid4()
        memory.title = "Python 异步测试"
        memory.content = "pytest-asyncio 配置方法和最佳实践"

        other_emb = [0.1] * 512
        new_emb = [0.1] * 512
        existing = [
            (other_id, "pytest asyncio 测试指南", "pytest-asyncio 的配置和使用方法", other_emb)
        ]

        db = AsyncMock()
        db.add_all = MagicMock()
        rel_result = MagicMock()
        rel_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=rel_result)

        import apps.api.routes.reviews as reviews_module

        original_config = reviews_module.parasitic_evolution_config
        mock_config = MagicMock()
        mock_config.memory_relations_enabled = True
        reviews_module.parasitic_evolution_config = mock_config

        mock_service = AsyncMock()
        mock_service.generate_embedding = AsyncMock(return_value=new_emb)

        try:
            with (
                patch(
                    "apps.api.routes.reviews.get_embedding_service",
                    return_value=mock_service,
                    create=True,
                ),
                patch(
                    "packages.retrieval.embedding.get_embedding_service", return_value=mock_service
                ),
            ):
                await _auto_detect_relations(memory, db, existing_memories=existing)
            added = [
                arg
                for call in db.add_all.call_args_list
                for arg in call.args[0]
                if isinstance(arg, MemoryRelation)
            ]
            assert len(added) == 1
            assert added[0].target_memory_id == other_id
            assert added[0].confidence > 0
        finally:
            reviews_module.parasitic_evolution_config = original_config

    async def test_auto_detect_relations_jaccard_fallback_no_embedding(self):
        from apps.api.routes.reviews import _auto_detect_relations
        from packages.domain.models import MemoryRelation

        mem_id = uuid.uuid4()
        other_id = uuid.uuid4()

        memory = MagicMock()
        memory.id = mem_id
        memory.workspace_id = uuid.uuid4()
        memory.title = "Python async patterns"
        memory.content = "asyncio and await patterns in Python programming"

        existing = [
            (
                other_id,
                "Python async guide",
                "asyncio and await patterns guide for Python programming",
                None,
            )
        ]

        db = AsyncMock()
        db.add_all = MagicMock()
        rel_result = MagicMock()
        rel_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=rel_result)

        import apps.api.routes.reviews as reviews_module

        original_config = reviews_module.parasitic_evolution_config
        mock_config = MagicMock()
        mock_config.memory_relations_enabled = True
        reviews_module.parasitic_evolution_config = mock_config

        try:
            await _auto_detect_relations(memory, db, existing_memories=existing)
            added = [
                arg
                for call in db.add_all.call_args_list
                for arg in call.args[0]
                if isinstance(arg, MemoryRelation)
            ]
            assert len(added) == 1
            assert added[0].relation_type in (
                "related",
                "supersedes",
                "supports",
                "refines",
                "contradicts",
            )
        finally:
            reviews_module.parasitic_evolution_config = original_config

    async def test_auto_detect_relations_no_match_below_threshold(self):
        from apps.api.routes.reviews import _auto_detect_relations
        from packages.domain.models import MemoryRelation

        mem_id = uuid.uuid4()
        other_id = uuid.uuid4()

        memory = MagicMock()
        memory.id = mem_id
        memory.workspace_id = uuid.uuid4()
        memory.title = "Python 异步编程"
        memory.content = "asyncio 事件循环和协程"

        existing = [(other_id, "React 前端开发", "组件化开发和 hooks 使用指南", None)]

        db = AsyncMock()
        rel_result = MagicMock()
        rel_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=rel_result)

        import apps.api.routes.reviews as reviews_module

        original_config = reviews_module.parasitic_evolution_config
        mock_config = MagicMock()
        mock_config.memory_relations_enabled = True
        reviews_module.parasitic_evolution_config = mock_config

        try:
            await _auto_detect_relations(memory, db, existing_memories=existing)
            added = [
                arg
                for call in db.add_all.call_args_list
                for arg in call.args[0]
                if isinstance(arg, MemoryRelation)
            ]
            assert len(added) == 0
        finally:
            reviews_module.parasitic_evolution_config = original_config

    async def test_feature_flag_exists(self):
        from packages.domain.config import ParasiticEvolutionConfig

        config = ParasiticEvolutionConfig()
        assert hasattr(config, "memory_relations_enabled")
        assert config.memory_relations_enabled is True
