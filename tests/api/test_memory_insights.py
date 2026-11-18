"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestMemoryStatusInsights、TestMemoryGapDetection、TestEvolutionMetrics、TestPermanentMemory、TestMemoryVersionTracking、TestAgentProfile。
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from apps.api.routes.context import compute_freshness


class TestMemoryStatusInsights:
    async def test_insights_structure(self):
        from unittest.mock import AsyncMock, MagicMock

        from apps.api.routes.memory_status import _compute_insights

        db = AsyncMock()
        workspace_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.all.return_value = []
        mock_result.first.return_value = (0, 0)
        mock_result.one_or_none.return_value = (0, 0)
        db.execute = AsyncMock(return_value=mock_result)

        insights = await _compute_insights(db, workspace_id)
        assert "submission_trend" in insights
        assert "recent_submissions_7d" in insights
        assert "type_distribution" in insights
        assert "low_confidence_count" in insights
        assert "suggestions" in insights
        assert insights["submission_trend"] in ["rising", "stable", "declining", "new"]

    async def test_low_confidence_suggestion_generated(self):
        from unittest.mock import AsyncMock, MagicMock

        from apps.api.routes.memory_status import _compute_insights

        db = AsyncMock()
        workspace_id = uuid.uuid4()

        results = []

        # 第 1 次查询：submission_stats（合并 COUNT）— 使用 .one_or_none()
        r1 = MagicMock()
        r1.one_or_none.return_value = (10, 10)
        results.append(r1)

        # 第 2 次查询：type_distribution（active），合并 low_confidence
        # 每行为：(type, count, low_conf_count)
        r2 = MagicMock()
        r2.all.return_value = [("fact", 3, 5)]
        results.append(r2)

        # 第 3 次查询：type_distribution（candidates）— 使用 .all()
        r2b = MagicMock()
        r2b.all.return_value = []
        results.append(r2b)

        db.execute = AsyncMock(side_effect=results)

        insights = await _compute_insights(db, workspace_id)
        assert insights["low_confidence_count"] == 5
        assert any("低置信度" in s for s in insights["suggestions"])

    async def test_pending_review_suggestion_when_many(self):
        from unittest.mock import AsyncMock, MagicMock

        from apps.api.routes.memory_status import _compute_insights

        db = AsyncMock()
        workspace_id = uuid.uuid4()

        results = []

        # 第 1 次查询：submission_stats（合并 COUNT）— 使用 .one_or_none()
        r1 = MagicMock()
        r1.one_or_none.return_value = (5, 5)
        results.append(r1)

        # 第 2 次查询：type_distribution（active），合并 low_confidence
        r2 = MagicMock()
        r2.all.return_value = []
        results.append(r2)

        # 第 3 次查询：type_distribution（candidates）— 使用 .all()
        r2b = MagicMock()
        r2b.all.return_value = []
        results.append(r2b)

        db.execute = AsyncMock(side_effect=results)

        insights = await _compute_insights(db, workspace_id, candidate_count=15)
        assert any("待审核" in s for s in insights["suggestions"])


class TestMemoryGapDetection:
    def test_extract_technical_terms_camelcase(self):
        from packages.memory.memory_gap import extract_technical_terms

        text = "如何使用 UserService 和 UserManager"
        terms = extract_technical_terms(text)
        assert "UserService" in terms
        assert "UserManager" in terms

    def test_extract_technical_terms_snake_case(self):
        from packages.memory.memory_gap import extract_technical_terms

        text = "配置 database_connection 和 api_endpoint"
        terms = extract_technical_terms(text)
        assert "database_connection" in terms
        assert "api_endpoint" in terms

    def test_extract_technical_terms_constant_case(self):
        from packages.memory.memory_gap import extract_technical_terms

        text = "设置 MAX_RETRY_COUNT 和 TIMEOUT_MS"
        terms = extract_technical_terms(text)
        assert "MAX_RETRY_COUNT" in terms
        assert "TIMEOUT_MS" in terms

    def test_is_question_english(self):
        from packages.memory.memory_gap import is_question

        assert is_question("How to configure the database?")
        assert is_question("What is the best practice?")
        assert is_question("Can you explain this?")
        assert not is_question("This is a statement")

    def test_is_question_chinese(self):
        from packages.memory.memory_gap import is_question

        assert is_question("如何配置数据库？")
        assert is_question("为什么会出现这个错误？")
        assert is_question("什么是最佳实践？")
        assert not is_question("这是一个陈述句")

    def test_detect_gap_low_confidence(self):
        from packages.memory.memory_gap import detect_memory_gap

        items = [
            {"score": 0.2, "content": "result 1"},
            {"score": 0.15, "content": "result 2"},
        ]
        gap = detect_memory_gap("test query", items)
        assert gap is not None
        assert gap["type"] == "low_confidence_retrieval"
        assert "置信度较低" in gap["message"]

    def test_detect_gap_memory_gap_with_terms(self):
        from packages.memory.memory_gap import detect_memory_gap

        gap = detect_memory_gap("如何配置 UserService 和 DatabaseManager", [])
        assert gap is not None
        assert gap["type"] == "memory_gap"
        assert "technical_terms" in gap
        assert len(gap["technical_terms"]) >= 2

    def test_detect_gap_question(self):
        from packages.memory.memory_gap import detect_memory_gap

        gap = detect_memory_gap("如何配置数据库？", [])
        assert gap is not None
        assert gap["type"] == "question_gap"
        assert "无匹配记忆" in gap["message"]

    def test_detect_gap_no_gap_with_good_results(self):
        from packages.memory.memory_gap import detect_memory_gap

        items = [
            {"score": 0.8, "content": "result 1"},
            {"score": 0.6, "content": "result 2"},
        ]
        gap = detect_memory_gap("test query", items)
        assert gap is None

    def test_detect_gap_no_gap_with_simple_query(self):
        from packages.memory.memory_gap import detect_memory_gap

        gap = detect_memory_gap("简单查询", [])
        assert gap is None


class TestEvolutionMetrics:
    async def test_empty_workspace_returns_zeros(self):
        import uuid

        from packages.memory.evolution_metrics import compute_evolution_metrics

        db = AsyncMock()

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.one.return_value = (0, 0)
            elif call_count == 2:
                r.scalar_one.return_value = 0
            elif call_count == 3:
                r.one.return_value = (0, 0)
            elif call_count == 4:
                r.one.return_value = (0, None)
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)

        metrics = await compute_evolution_metrics(db, uuid.uuid4(), days=30)

        assert metrics["period_days"] == 30
        assert metrics["notes"]["created"] == 0
        assert metrics["notes"]["formalized"] == 0
        assert metrics["notes"]["formalization_rate"] == 0.0
        assert metrics["submissions"]["total"] == 0
        assert metrics["submissions"]["approval_rate"] == 0.0
        assert metrics["memory_health"]["active"] == 0
        assert metrics["memory_health"]["avg_confidence"] == 0.0

    async def test_metrics_with_data(self):
        import uuid

        from packages.memory.evolution_metrics import compute_evolution_metrics

        db = AsyncMock()
        ws_id = uuid.uuid4()

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.one.return_value = (10, 6)
            elif call_count == 2:
                r.scalar_one.return_value = 8
            elif call_count == 3:
                r.one.return_value = (5, 1)
            elif call_count == 4:
                r.one.return_value = (20, 0.75)
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)

        metrics = await compute_evolution_metrics(db, ws_id, days=7)

        assert metrics["notes"]["created"] == 10
        assert metrics["notes"]["formalized"] == 6
        assert metrics["notes"]["formalization_rate"] == 0.6
        assert metrics["submissions"]["total"] == 8
        assert metrics["submissions"]["approved"] == 5
        assert metrics["submissions"]["rejected"] == 1
        assert metrics["memory_health"]["active"] == 20
        assert metrics["memory_health"]["avg_confidence"] == 0.75

    async def test_formalization_rate_zero_when_no_notes(self):
        import uuid

        from packages.memory.evolution_metrics import compute_evolution_metrics

        db = AsyncMock()

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            if call_count == 1:
                r.one.return_value = (0, 0)
            elif call_count == 2:
                r.scalar_one.return_value = 0
            elif call_count == 3:
                r.one.return_value = (0, 0)
            elif call_count == 4:
                r.one.return_value = (0, None)
            return r

        db.execute = AsyncMock(side_effect=execute_side_effect)

        metrics = await compute_evolution_metrics(db, uuid.uuid4(), days=30)
        assert metrics["notes"]["formalization_rate"] == 0.0
        assert metrics["submissions"]["approval_rate"] == 0.0


class TestPermanentMemory:
    """永久记忆标记与新鲜度豁免测试。"""

    async def test_compute_freshness_returns_permanent_for_permanent_memory(self):
        import uuid
        from unittest.mock import AsyncMock, MagicMock

        db = AsyncMock()
        mem_id = uuid.uuid4()

        mem_result = MagicMock()
        mem_result.one_or_none.return_value = (True, "Core architecture decision")

        db.execute = AsyncMock(return_value=mem_result)

        result = await compute_freshness(mem_id, db)

        assert result["status"] == "permanent"
        assert result["reason"] == "Core architecture decision"
        assert result["days_unused"] is None

    async def test_compute_freshness_normal_for_non_permanent(self):
        import uuid
        from unittest.mock import AsyncMock, MagicMock

        from apps.api.routes.context import compute_freshness

        db = AsyncMock()
        mem_id = uuid.uuid4()

        mem_result = MagicMock()
        mem_result.one_or_none.return_value = (False, None)

        usage_result = MagicMock()
        usage_result.scalar_one_or_none.return_value = datetime.now(UTC) - timedelta(days=5)

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mem_result
            return usage_result

        db.execute = AsyncMock(side_effect=execute_side_effect)

        result = await compute_freshness(mem_id, db)

        assert result["days_unused"] == 5

    async def test_compute_freshness_permanent_without_reason(self):
        import uuid
        from unittest.mock import AsyncMock, MagicMock

        db = AsyncMock()
        mem_id = uuid.uuid4()

        mem_result = MagicMock()
        mem_result.one_or_none.return_value = (True, None)

        db.execute = AsyncMock(return_value=mem_result)

        result = await compute_freshness(mem_id, db)

        assert result["status"] == "permanent"
        assert result["reason"] is None

    async def test_reranking_includes_permanent_boost(self):
        import uuid
        from unittest.mock import AsyncMock, MagicMock

        from apps.api.routes.context import rerank_context_results
        from packages.domain.schemas import ContextItem

        db = AsyncMock()
        ws_id = uuid.uuid4()
        mem_id = uuid.uuid4()

        item = ContextItem(
            memory_id=mem_id,
            id=mem_id,
            title="Test",
            content="Test content",
            type="fact",
            score=0.5,
            source="memory",
        )

        merged_result = MagicMock()
        merged_result.all.return_value = [(mem_id, 0, "fact")]

        approval_result = MagicMock()
        approval_result.all.return_value = []

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return merged_result
            elif call_count in (2, 3):
                return approval_result
            return MagicMock()

        db.execute = AsyncMock(side_effect=execute_side_effect)

        import apps.api.routes.context as ctx_module

        original_batch = ctx_module.batch_compute_freshness

        async def mock_batch(ids, db_sess, type_map=None):
            return (
                {mem_id: {"status": "permanent", "reason": "core", "days_unused": None}},
                {mem_id: "fact"},
                {mem_id: 5},
            )

        ctx_module.batch_compute_freshness = mock_batch

        try:
            result = await rerank_context_results([item], ws_id, db)
            assert len(result) == 1
            assert result[0].score > 0.5
        finally:
            ctx_module.batch_compute_freshness = original_batch


class TestMemoryVersionTracking:
    """P4-43：记忆版本历史追踪。"""

    async def test_model_exists(self):
        from packages.domain.models import MemoryVersion

        assert MemoryVersion.__tablename__ == "memory_version"

    async def test_model_fields(self):
        import uuid

        from packages.domain.models import MemoryVersion

        mv = MemoryVersion(
            memory_id=uuid.uuid4(),
            version=1,
            title="Original Title",
            content="Original content here",
            change_type="edit",
            changed_by_type="agent",
            changed_by_id="agent-1",
            reason="Updated for accuracy",
        )
        assert mv.version == 1
        assert mv.title == "Original Title"
        assert mv.change_type == "edit"
        assert mv.changed_by_type == "agent"
        assert mv.reason == "Updated for accuracy"

    async def test_schema_read(self):
        import uuid

        from packages.domain.schemas import MemoryVersionRead

        class MockVersion:
            id = uuid.uuid4()
            memory_id = uuid.uuid4()
            version = 2
            title = "Updated Title"
            content = "Updated content"
            change_type = "edit"
            changed_by_type = "agent"
            changed_by_id = "agent-1"
            reason = "fix"
            created_at = datetime.now(UTC)

        schema = MemoryVersionRead.model_validate(MockVersion())
        assert schema.version == 2
        assert schema.change_type == "edit"
        assert schema.title == "Updated Title"

    async def test_feature_flag(self):
        from packages.domain.config import ParasiticEvolutionConfig

        config = ParasiticEvolutionConfig()
        assert hasattr(config, "memory_version_tracking_enabled")
        assert config.memory_version_tracking_enabled is True

    async def test_client_get_memory_versions(self):
        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        versions = [
            {
                "id": str(uuid.uuid4()),
                "memory_id": str(uuid.uuid4()),
                "version": 1,
                "title": "V1",
                "content": "Content V1",
                "change_type": "edit",
                "changed_by_type": "agent",
                "changed_by_id": None,
                "reason": "initial",
                "created_at": "2026-09-01T00:00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "memory_id": str(uuid.uuid4()),
                "version": 2,
                "title": "V2",
                "content": "Content V2",
                "change_type": "edit",
                "changed_by_type": "agent",
                "changed_by_id": None,
                "reason": "update",
                "created_at": "2026-09-10T00:00:00",
            },
        ]
        client._request = AsyncMock(return_value=versions)

        result = await client.get_memory_versions("test-mem-id", limit=5)

        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "GET"
        assert "/v1/memories/test-mem-id/versions" in call_args[0][1]
        assert call_args[1].get("params") == {"limit": 5}
        assert len(result) == 2
        assert result[0]["version"] == 1
        assert result[1]["version"] == 2

    async def test_client_get_memory_versions_default_limit(self):
        from adapters.mcp.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value=[])

        await client.get_memory_versions("test-mem-id")

        call_args = client._request.call_args
        assert call_args[1].get("params") == {"limit": 10}


class TestAgentProfile:
    async def test_model_exists(self):
        from packages.domain.models import AgentProfile

        assert AgentProfile.__tablename__ == "agent_profile"

    async def test_model_fields(self):

        from packages.domain.models import AgentProfile

        profile = AgentProfile(
            workspace_id="test-ws",
            agent_id="agent-1",
            total_sessions=5,
            total_memories_submitted=10,
            note_formalization_rate=0.8,
            nudge_response_rate=0.6,
        )
        assert profile.workspace_id == "test-ws"
        assert profile.agent_id == "agent-1"
        assert profile.total_sessions == 5
        assert profile.total_memories_submitted == 10
        assert profile.note_formalization_rate == 0.8
        assert profile.nudge_response_rate == 0.6

    async def test_schema_read(self):
        import uuid

        from packages.domain.schemas import AgentProfileRead

        class MockProfile:
            id = uuid.uuid4()
            workspace_id = "test-ws"
            agent_id = "agent-1"
            total_sessions = 5
            total_memories_submitted = 10
            total_notes_created = 3
            note_formalization_rate = 0.6
            preferred_signal_types = '["correction", "decision"]'
            preferred_memory_types = '["fact", "convention"]'
            nudge_response_rate = 0.7
            preferred_nudge_types = None
            updated_at = datetime.now(UTC)

        profile = AgentProfileRead.from_orm_with_json(MockProfile())
        assert profile.workspace_id == "test-ws"
        assert profile.preferred_signal_types == ["correction", "decision"]
        assert profile.preferred_memory_types == ["fact", "convention"]
        assert profile.nudge_response_rate == 0.7

    async def test_schema_update(self):
        from packages.domain.schemas import AgentProfileUpdate

        update = AgentProfileUpdate(
            total_sessions=10,
            preferred_memory_types=["fact", "pattern"],
        )
        data = update.model_dump(exclude_unset=True)
        assert data["total_sessions"] == 10
        assert data["preferred_memory_types"] == ["fact", "pattern"]
        assert "nudge_response_rate" not in data

    async def test_feature_flag(self):
        from packages.domain.config import ParasiticEvolutionConfig

        config = ParasiticEvolutionConfig()
        assert hasattr(config, "agent_profile_enabled")
        assert config.agent_profile_enabled is True

    async def test_profile_hints_returns_none_when_disabled(self):
        import uuid
        from unittest.mock import MagicMock

        from apps.api.routes.context import _get_agent_profile_hints

        db = MagicMock()
        import apps.api.routes.context as context_module

        original_config = context_module.parasitic_evolution_config

        mock_config = MagicMock()
        mock_config.agent_profile_enabled = False
        context_module.parasitic_evolution_config = mock_config

        try:
            result = await _get_agent_profile_hints(uuid.uuid4(), uuid.uuid4(), db)
            assert result is None
        finally:
            context_module.parasitic_evolution_config = original_config
