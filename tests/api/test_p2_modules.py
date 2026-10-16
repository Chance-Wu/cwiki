"""P2 模块测试：新鲜度计算。"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.routes.context import compute_freshness


class TestComputeFreshness:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db

    def _setup_mock_db(self, mock_db, usage_result):
        mem_result = MagicMock()
        mem_result.one_or_none.return_value = (False, None)
        usage_mock = MagicMock()
        usage_mock.scalar_one_or_none.return_value = usage_result
        mock_db.execute = AsyncMock(side_effect=[mem_result, usage_mock])

    async def test_unknown_when_no_usage(self, mock_db):
        self._setup_mock_db(mock_db, None)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] is None

    async def test_fresh_when_used_recently(self, mock_db):
        recent_time = datetime.now(UTC) - timedelta(days=3)
        self._setup_mock_db(mock_db, recent_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 3

    async def test_aging_when_used_week_ago(self, mock_db):
        aging_time = datetime.now(UTC) - timedelta(days=20)
        self._setup_mock_db(mock_db, aging_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 20

    async def test_stale_when_used_month_ago(self, mock_db):
        stale_time = datetime.now(UTC) - timedelta(days=150)
        self._setup_mock_db(mock_db, stale_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 150

    async def test_boundary_seven_days(self, mock_db):
        boundary_time = datetime.now(UTC) - timedelta(days=7)
        self._setup_mock_db(mock_db, boundary_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 7

    async def test_boundary_fifteen_days(self, mock_db):
        boundary_time = datetime.now(UTC) - timedelta(days=15)
        self._setup_mock_db(mock_db, boundary_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 15

    async def test_boundary_sixty_days(self, mock_db):
        boundary_time = datetime.now(UTC) - timedelta(days=60)
        self._setup_mock_db(mock_db, boundary_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 60

    async def test_boundary_sixtyone_days(self, mock_db):
        boundary_time = datetime.now(UTC) - timedelta(days=121)
        self._setup_mock_db(mock_db, boundary_time)

        freshness = await compute_freshness(uuid.uuid4(), mock_db)
        assert freshness["days_unused"] == 121


class TestRerankContextResults:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    async def test_empty_items_returns_empty(self, mock_db):
        from apps.api.routes.context import rerank_context_results

        result = await rerank_context_results([], uuid.uuid4(), mock_db)
        assert result == []

    async def test_usage_count_boosts_score(self, mock_db):
        from unittest.mock import patch

        from apps.api.routes.context import rerank_context_results
        from packages.domain.schemas import ContextItem

        mem_id1 = uuid.uuid4()
        mem_id2 = uuid.uuid4()
        items = [
            ContextItem(
                memory_id=mem_id1,
                id=mem_id1,
                title="A",
                content="a",
                type="fact",
                score=0.5,
                source="memory",
            ),
            ContextItem(
                memory_id=mem_id2,
                id=mem_id2,
                title="B",
                content="b",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]

        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[("fact", 10, 8)])),
            ]
        )

        with patch(
            "apps.api.routes.context.batch_compute_freshness",
            new_callable=lambda: AsyncMock(
                return_value=(
                    {
                        mem_id1: {"days_unused": 2},
                        mem_id2: {"days_unused": 2},
                    },
                    {mem_id1: "fact", mem_id2: "fact"},
                    {mem_id1: 10, mem_id2: 0},
                )
            ),
        ):
            result = await rerank_context_results(items, uuid.uuid4(), mock_db)
        assert result[0].memory_id == mem_id1
        assert result[0].score > result[1].score

    async def test_fresh_memory_gets_boost(self, mock_db):
        from unittest.mock import patch

        from apps.api.routes.context import rerank_context_results
        from packages.domain.schemas import ContextItem

        mem_id1 = uuid.uuid4()
        mem_id2 = uuid.uuid4()
        items = [
            ContextItem(
                memory_id=mem_id1,
                id=mem_id1,
                title="A",
                content="a",
                type="fact",
                score=0.5,
                source="memory",
            ),
            ContextItem(
                memory_id=mem_id2,
                id=mem_id2,
                title="B",
                content="b",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]

        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[("fact", 0, 0)])),
            ]
        )

        with patch(
            "apps.api.routes.context.batch_compute_freshness",
            new_callable=lambda: AsyncMock(
                return_value=(
                    {
                        mem_id1: {"days_unused": 2},
                        mem_id2: {"days_unused": 100},
                    },
                    {mem_id1: "fact", mem_id2: "fact"},
                    {mem_id1: 5, mem_id2: 0},
                )
            ),
        ):
            result = await rerank_context_results(items, uuid.uuid4(), mock_db)
        assert result[0].memory_id == mem_id1

    async def test_high_approval_rate_boosts_score(self, mock_db):
        from unittest.mock import patch

        from apps.api.routes.context import rerank_context_results
        from packages.domain.schemas import ContextItem

        mem_id = uuid.uuid4()
        items = [
            ContextItem(
                memory_id=mem_id,
                id=mem_id,
                title="A",
                content="a",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]

        mock_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[("fact", 100, 80)])),
            ]
        )

        with patch(
            "apps.api.routes.context.batch_compute_freshness",
            new_callable=lambda: AsyncMock(
                return_value=(
                    {mem_id: {"days_unused": None}},
                    {mem_id: "fact"},
                    {mem_id: 0},
                )
            ),
        ):
            result = await rerank_context_results(items, uuid.uuid4(), mock_db)
        assert result[0].score > 0.5


class TestFitToTokenBudget:
    async def test_empty_items_returns_empty(self):
        from apps.api.routes.context import fit_to_token_budget

        result = await fit_to_token_budget([], budget=1000)
        assert result == []

    async def test_items_within_budget_all_selected(self):
        from apps.api.routes.context import fit_to_token_budget
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="a" * 40,
                type="fact",
                score=0.5,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="B",
                content="b" * 40,
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]
        result = await fit_to_token_budget(items, budget=1000)
        assert len(result) == 2

    async def test_items_exceeding_budget_truncated(self):
        from apps.api.routes.context import fit_to_token_budget
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="a" * 400,
                type="fact",
                score=0.9,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="B",
                content="b" * 400,
                type="fact",
                score=0.8,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="C",
                content="c" * 400,
                type="fact",
                score=0.7,
                source="memory",
            ),
        ]
        result = await fit_to_token_budget(items, budget=150)
        assert len(result) == 1
        assert result[0].title == "A"

    async def test_estimated_tokens_in_metadata(self):
        from apps.api.routes.context import fit_to_token_budget
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="a" * 100,
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]
        result = await fit_to_token_budget(items, budget=1000)
        assert result[0].metadata["estimated_tokens"] == 25

    async def test_higher_score_items_selected_first(self):
        from apps.api.routes.context import fit_to_token_budget
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="Low",
                content="a" * 200,
                type="fact",
                score=0.3,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="High",
                content="b" * 200,
                type="fact",
                score=0.9,
                source="memory",
            ),
        ]
        items_sorted = sorted(items, key=lambda x: x.score, reverse=True)
        result = await fit_to_token_budget(items_sorted, budget=60)
        assert len(result) == 1
        assert result[0].title == "High"


class TestDeduplicateResults:
    async def test_empty_items_returns_empty(self):
        from apps.api.routes.context import deduplicate_results

        result = await deduplicate_results([])
        assert result == []

    async def test_single_item_returns_same(self):
        from apps.api.routes.context import deduplicate_results
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="unique content",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]
        result = await deduplicate_results(items)
        assert len(result) == 1

    async def test_dissimilar_items_all_kept(self):
        from apps.api.routes.context import deduplicate_results
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="completely different text",
                type="fact",
                score=0.5,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="B",
                content="another unique sentence here",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]
        result = await deduplicate_results(items)
        assert len(result) == 2

    async def test_similar_items_deduplicated(self):
        from apps.api.routes.context import deduplicate_results
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="A",
                content="the quick brown fox jumps over the lazy dog",
                type="fact",
                score=0.5,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="B",
                content="the quick brown fox jumps over the lazy cat",
                type="fact",
                score=0.5,
                source="memory",
            ),
        ]
        result = await deduplicate_results(items, similarity_threshold=0.7)
        assert len(result) == 1

    async def test_higher_score_kept_on_duplicate(self):
        from apps.api.routes.context import deduplicate_results
        from packages.domain.schemas import ContextItem

        items = [
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="Low",
                content="the quick brown fox jumps over the lazy dog",
                type="fact",
                score=0.3,
                source="memory",
            ),
            ContextItem(
                memory_id=uuid.uuid4(),
                id=uuid.uuid4(),
                title="High",
                content="the quick brown fox jumps over the lazy cat",
                type="fact",
                score=0.9,
                source="memory",
            ),
        ]
        result = await deduplicate_results(items, similarity_threshold=0.7)
        assert len(result) == 1
        assert result[0].title == "High"

    async def test_jaccard_similarity_identical_strings(self):
        from packages.memory.similarity import jaccard_similarity

        assert jaccard_similarity("hello world", "hello world") == 1.0

    async def test_jaccard_similarity_completely_different(self):
        from packages.memory.similarity import jaccard_similarity

        assert jaccard_similarity("hello world", "foo bar baz") == 0.0

    async def test_jaccard_similarity_empty_string(self):
        from packages.memory.similarity import jaccard_similarity

        assert jaccard_similarity("", "hello") == 0.0
        assert jaccard_similarity("hello", "") == 0.0


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


class TestMemoryUpdate:
    async def test_update_confidence_only(self):
        from unittest.mock import AsyncMock

        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id", "confidence": 0.9})

        result = await client.update_memory(
            memory_id="test-id",
            confidence=0.9,
        )

        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "PATCH"
        assert call_args[0][1] == "/v1/memories/test-id"
        assert call_args[1]["json_body"] == {"confidence": 0.9}
        assert result["confidence"] == 0.9

    async def test_update_multiple_fields(self):
        from unittest.mock import AsyncMock

        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id"})

        await client.update_memory(
            memory_id="test-id",
            title="新标题",
            content="新内容",
            confidence=0.8,
            importance=0.9,
        )

        call_args = client._request.call_args
        assert call_args[1]["json_body"] == {
            "title": "新标题",
            "content": "新内容",
            "confidence": 0.8,
            "importance": 0.9,
        }

    async def test_update_with_none_fields_excluded(self):
        from unittest.mock import AsyncMock

        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value={"id": "test-id"})

        await client.update_memory(
            memory_id="test-id",
            confidence=0.7,
            title=None,
            content=None,
        )

        call_args = client._request.call_args
        assert "title" not in call_args[1]["json_body"]
        assert "content" not in call_args[1]["json_body"]
        assert call_args[1]["json_body"] == {"confidence": 0.7}


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


class TestMemoryTitleConfig:
    @pytest.mark.parametrize("config", [{}, {"memory": {}}], ids=["no-section", "no-key"])
    def test_default_title_limit_is_eighty(self, monkeypatch, config):
        import packages.domain.config as config_module

        monkeypatch.setattr(config_module, "_yaml_config", config)
        assert config_module.Settings().memory_title_max_length == 80

    @pytest.mark.parametrize("max_length", [12, 32])
    def test_settings_reads_title_limit_from_memory_section(self, monkeypatch, max_length):
        import packages.domain.config as config_module

        monkeypatch.setattr(
            config_module, "_yaml_config", {"memory": {"title_max_length": max_length}}
        )
        assert config_module.Settings().memory_title_max_length == max_length

    @pytest.mark.parametrize(
        "config, expected",
        [
            ({"memory": {"title_max_length": 12}}, 12),
            ({"memory": {"title_max_length": 32}}, 32),
            ({"memory": {}}, 80),
            ({}, 80),
        ],
        ids=["lower-limit", "higher-limit", "removed-key", "removed-section"],
    )
    def test_reload_refreshes_title_limit_without_replacing_settings(
        self, monkeypatch, config, expected
    ):
        import packages.domain.config as config_module

        monkeypatch.setattr(config_module, "_yaml_config", {"memory": {"title_max_length": 27}})
        settings = config_module.Settings()
        assert settings.memory_title_max_length == 27
        # 只 mock 磁盘加载；实际执行缓存与 Settings 的 reload 方法。
        monkeypatch.setattr(config_module, "_load_yaml_config", lambda: config)
        config_module.reload_yaml_config()
        settings.reload()
        assert settings.memory_title_max_length == expected


class TestParasiticEvolutionConfig:
    def test_default_values_from_config_yaml(self):
        from packages.domain.config import parasitic_evolution_config

        assert parasitic_evolution_config.memory_gap_detection_enabled is True
        assert parasitic_evolution_config.memory_relations_enabled is True
        assert parasitic_evolution_config.agent_profile_enabled is True
        assert parasitic_evolution_config.proactive_push_enabled is True
        assert parasitic_evolution_config.memory_version_tracking_enabled is True
        assert parasitic_evolution_config.auto_consolidate_enabled is True

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

        from apps.api.routes.context import compute_freshness

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
        from datetime import datetime, timedelta
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

        from apps.api.routes.context import compute_freshness

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


class TestMemoryLifecycle:
    """记忆生命周期管理测试（P4-37）。"""

    async def test_client_get_lifecycle(self):
        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        expected = {
            "memory_id": "test-id",
            "current_status": "updated",
            "timeline": [
                {"event_type": "created", "timestamp": "2026-09-01T00:00:00", "metadata": None},
                {"event_type": "updated", "timestamp": "2026-09-10T00:00:00", "metadata": None},
            ],
            "age_days": 14,
            "event_count": 2,
        }
        client._request = AsyncMock(return_value=expected)

        result = await client.get_memory_lifecycle("test-id")

        client._request.assert_called_once()
        call_args = client._request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/v1/memories/test-id/lifecycle"
        assert result["current_status"] == "updated"
        assert result["event_count"] == 2
        assert len(result["timeline"]) == 2

    async def test_client_get_lifecycle_empty(self):
        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(
            return_value={
                "memory_id": "test-id",
                "current_status": "unknown",
                "timeline": [],
                "age_days": None,
                "event_count": 0,
            }
        )

        result = await client.get_memory_lifecycle("test-id")

        assert result["current_status"] == "unknown"
        assert result["event_count"] == 0
        assert result["age_days"] is None

    def test_lifecycle_model_exists(self):
        from packages.domain.models import MemoryLifecycleEvent

        assert hasattr(MemoryLifecycleEvent, "__tablename__")
        assert MemoryLifecycleEvent.__tablename__ == "memory_lifecycle_event"
        assert hasattr(MemoryLifecycleEvent, "memory_id")
        assert hasattr(MemoryLifecycleEvent, "event_type")
        assert hasattr(MemoryLifecycleEvent, "metadata_json")
        assert hasattr(MemoryLifecycleEvent, "created_at")

    async def test_lifecycle_returns_unknown_status_for_unknown_memory(self):
        from apps.api.routes.memories import get_memory_lifecycle

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = await get_memory_lifecycle(memory_id=str(uuid.uuid4()), db=db)
        assert result["current_status"] == "unknown"
        assert result["event_count"] == 0

    async def test_relations_returns_empty_for_unknown_memory(self):
        from apps.api.routes.memories import get_memory_relations

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = await get_memory_relations(memory_id=str(uuid.uuid4()), db=db)
        assert result["relations"] == []
        assert result["total_relations"] == 0


class TestMemoryContentValidation:
    @pytest.mark.parametrize(
        "content",
        [
            (
                "先验证再提交：离线导出保留正文和附件的对应关系，恢复时应核对文件数量、"
                "编码和原始时间戳。本轮只验证当前工作区，其他工作区尚未确认。"
            ),
            (
                "## 排查证据\n连接超时仍未定位，不编造根因。已保留完整错误响应和请求时间，"
                "下一步核对连接池设置与服务日志，当前没有可验证的修复结论。"
            ),
            (
                "### 适用边界\n仅隔离环境需要离线依赖包。部署前应准备对应平台的依赖版本和"
                "校验值，安装后核对包清单；联网环境暂不采用这套离线分发流程。"
            ),
            (
                "- 导出时保存完整正文、附件路径和原始时间戳。\n"
                "- 恢复时核对文件数量与校验值，确认来源完整后重建索引，不使用摘要替代原文。"
            ),
            (
                "| 方案 | 取舍 |\n| --- | --- |\n| 离线安装 | 需要准备依赖包 |\n"
                "| 联网安装 | 依赖下载服务可用 |\n\n当前环境网络受限，选择预先准备离线依赖包。"
            ),
            (
                "```markdown\n## 这是示例中的标题，不应被删除\n"
                "代码块中的标题和缩进都属于原始材料。\n```\n"
                "接收端只校验长度，不因分类变化而修改围栏或重排示例。"
            ),
            (
                "## 场景\n原来的结构仍然可用，已有记录由人工核实。\n"
                "## 知识\n保留已有内容及其原始证据和适用条件。\n"
                "## 原因\n正文结构不影响分类，无需迁移或强制转换为其他格式。"
            ),
        ],
    )
    def test_free_content_is_valid(self, content):
        from packages.domain.types import validate_memory_content
        from packages.memory.service import _validate_mcp_content

        assert len(content.strip()) >= 50
        _validate_mcp_content(content)
        assert validate_memory_content(content) == content

    @pytest.mark.parametrize(
        "content",
        [
            "",
            " \n\t ",
            "短",
            "1234",
            "  1234  ",
            "Too short content!",
            " \t\nToo short content!  \n",
        ],
    )
    def test_empty_or_too_short_content_is_rejected(self, content):
        from packages.memory.service import ContentFormatError, _validate_mcp_content

        with pytest.raises(ContentFormatError, match="至少 20 个字符"):
            _validate_mcp_content(content)

    def test_types_provide_type_definitions(self):
        from packages.domain.types import TYPE_DEFINITIONS

        assert len(TYPE_DEFINITIONS) == 11
        for t in TYPE_DEFINITIONS.values():
            assert t["name"]
            assert t["description"]


class TestSharedMemoryWriteValidation:
    @pytest.fixture(autouse=True)
    def default_title_limit(self, monkeypatch):
        from packages.domain.config import settings

        monkeypatch.setattr(settings, "memory_title_max_length", 20)

    @pytest.fixture(params=["memory", "candidate", "patch", "file-create", "file-update", "review"])
    def schema_payload(self, request):
        from apps.api.routes.file_memories import MemoryCreateRequest, MemoryUpdateRequest
        from packages.domain.schemas.memory import (
            CandidateMemoryCreate,
            MemoryCreate,
            MemoryUpdate,
            ReviewCreate,
        )

        schemas = {
            "memory": MemoryCreate,
            "candidate": CandidateMemoryCreate,
            "patch": MemoryUpdate,
            "file-create": MemoryCreateRequest,
            "file-update": MemoryUpdateRequest,
            "review": ReviewCreate,
        }
        if request.param == "review":
            payload = {"candidate_id": uuid.uuid4(), "reviewer_type": "human", "action": "edit"}
            title_field, content_field = "edited_title", "edited_content"
        else:
            payload = (
                {"workspace_id": str(uuid.uuid4()), "type": "fact"}
                if request.param in ("memory", "candidate")
                else {}
            )
            title_field, content_field = "title", "content"
        payload[title_field] = "Offline export notes"
        payload[content_field] = "Offline export keeps source text for later review."
        return schemas[request.param], payload, title_field, content_field

    @pytest.mark.parametrize(
        "field, value",
        [
            ("title", ""),
            ("title", " \n\t "),
            ("title", "Offline export notes!"),
            ("title", " Offline export notes"),
            ("content", "Too short content!"),
            ("content", " \t\nToo short content!  \n"),
        ],
        ids=[
            "empty-title",
            "blank-title",
            "title-21",
            "padded-title-21",
            "content-18",
            "padded-18",
        ],
    )
    def test_schemas_share_title_and_stripped_content_validation(
        self, schema_payload, field, value
    ):
        from pydantic import ValidationError

        schema, payload, title_field, content_field = schema_payload
        target = title_field if field == "title" else content_field
        with pytest.raises(ValidationError) as exc:
            schema.model_validate({**payload, target: value})
        assert any(error["loc"] == (target,) for error in exc.value.errors())

    @pytest.mark.parametrize("padded", [False, True])
    def test_schema_accepts_exact_boundary_without_normalizing(self, schema_payload, padded):
        schema, payload, title_field, content_field = schema_payload
        assert len(payload[title_field]) == 20
        assert len(payload[content_field]) == 50
        if padded:
            payload[title_field] = "  离线导出标题  "
            payload[content_field] = " \t\n" + payload[content_field] + "  \n"
        result = schema.model_validate(payload)
        assert getattr(result, title_field) == payload[title_field]
        assert getattr(result, content_field) == payload[content_field]

    def test_schema_uses_runtime_title_limit_after_settings_reload(
        self, schema_payload, monkeypatch
    ):
        from pydantic import ValidationError

        import packages.domain.config as config_module

        schema, payload, title_field, _ = schema_payload
        runtime_settings = config_module.Settings()
        monkeypatch.setattr("packages.domain.types.settings", runtime_settings)
        # 模型已导入完毕；校验不得沿用导入时刻冻结的上限。
        for max_length in (12, 32):
            monkeypatch.setattr(
                config_module, "_yaml_config", {"memory": {"title_max_length": max_length}}
            )
            runtime_settings.reload()
            title = "标" * max_length
            result = schema.model_validate({**payload, title_field: title})
            assert getattr(result, title_field) == title
            with pytest.raises(ValidationError) as exc:
                schema.model_validate({**payload, title_field: title + "题"})
            assert any(error["loc"] == (title_field,) for error in exc.value.errors())

    @pytest.mark.parametrize("with_nulls", [False, True])
    def test_update_schemas_allow_omitted_or_null_text(self, with_nulls):
        from apps.api.routes.file_memories import MemoryUpdateRequest
        from packages.domain.schemas.memory import MemoryUpdate

        payload = {"title": None, "content": None} if with_nulls else {}
        for schema in (MemoryUpdate, MemoryUpdateRequest):
            result = schema.model_validate(payload)
            assert result.title is None
            assert result.content is None
            assert result.model_dump(exclude_unset=True) == payload

    @pytest.mark.parametrize("padded", [False, True])
    def test_review_merged_content_uses_same_boundary(self, padded):
        from pydantic import ValidationError

        from packages.domain.schemas.memory import ReviewCreate

        payload = {"candidate_id": uuid.uuid4(), "reviewer_type": "human", "action": "merge"}
        valid = "A" * 20
        invalid = "A" * 19
        if padded:
            valid, invalid = " \t\n" + valid + "  \n", " \t\n" + invalid + "  \n"
        result = ReviewCreate(**payload, merged_content=valid)
        assert result.merged_content == valid
        with pytest.raises(ValidationError) as exc:
            ReviewCreate(**payload, merged_content=invalid)
        assert any(error["loc"] == ("merged_content",) for error in exc.value.errors())
        assert ReviewCreate(**payload, merged_content=None).merged_content is None

    def test_shared_validators_return_original_strings(self):
        from packages.domain.types import (
            MIN_CONTENT_LENGTH,
            validate_memory_content,
            validate_memory_title,
        )

        assert MIN_CONTENT_LENGTH == 20
        title = "  离线导出说明  "
        content = " \t\nOffline export keeps source text for later review.  \n"
        assert validate_memory_title(title) == title
        assert validate_memory_content(content) == content
        with pytest.raises(ValueError):
            validate_memory_title(" \n\t ")
        with pytest.raises(ValueError):
            validate_memory_title("Offline export notes!")
        with pytest.raises(ValueError):
            validate_memory_content(" \t\nToo short  \n")

    @pytest.mark.parametrize(
        "updates",
        [
            {"title": ""},
            {"title": " \n\t "},
            {"title": "Offline export notes!"},
            {"content": "Too short"},
            {"content": " \t\nToo short  \n"},
        ],
    )
    async def test_service_direct_calls_raise_content_format_error_before_writing(self, updates):
        from packages.memory.service import ContentFormatError, create_candidate

        db = AsyncMock()
        payload = {
            "workspace_id": uuid.uuid4(),
            "title": "Offline export notes",
            "content": "Offline export keeps source text for later review.",
            "type": "fact",
            **updates,
        }
        with pytest.raises(ContentFormatError):
            await create_candidate(db=db, **payload)
        db.execute.assert_not_awaited()
        db.flush.assert_not_awaited()
        db.add.assert_not_called()


class TestNoteSummarization:
    """笔记智能摘要测试（P4-39）。"""

    def test_extract_keywords_chinese(self):
        from adapters.qoder.content_processing import extract_keywords

        texts = [
            "配置 database_connection 参数",
            "database_connection 超时问题",
            "优化 database_connection 连接池",
        ]
        keywords = extract_keywords(texts)
        assert "database_connection" in keywords

    def test_extract_keywords_english(self):
        from adapters.qoder.content_processing import extract_keywords

        texts = [
            "AuthService handles authentication",
            "AuthService token refresh logic",
        ]
        keywords = extract_keywords(texts)
        assert "authservice" in keywords

    def test_extract_keywords_filters_stopwords(self):
        from adapters.qoder.content_processing import extract_keywords

        texts = ["这是一个关于配置数据库的测试"]
        keywords = extract_keywords(texts)
        for sw in ["的", "是", "一个", "关于"]:
            assert sw not in keywords

    def test_extract_keywords_empty_input(self):
        from adapters.qoder.content_processing import extract_keywords

        assert extract_keywords([]) == []
        assert extract_keywords([""]) == []

    def test_summarize_notes_by_type_groups(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "auth token fix", "signal_type": "issue", "formalized": False},
            {"content": "auth middleware update", "signal_type": "issue", "formalized": False},
            {"content": "use snake_case naming", "signal_type": "convention", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert len(summaries) == 2
        issue_summary = next(s for s in summaries if s["signal_type"] == "issue")
        assert issue_summary["count"] == 2
        assert "auth" in issue_summary["keywords"]

    def test_summarize_notes_excludes_formalized(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "already done", "signal_type": "fact", "formalized": True},
            {"content": "pending item", "signal_type": "fact", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert len(summaries) == 1
        assert summaries[0]["count"] == 1

    def test_summarize_notes_empty(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        assert _summarize_notes_by_type([]) == []

    def test_summarize_notes_sorted_by_count_desc(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "one", "signal_type": "fact", "formalized": False},
            {"content": "two", "signal_type": "issue", "formalized": False},
            {"content": "three", "signal_type": "issue", "formalized": False},
            {"content": "four", "signal_type": "issue", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert summaries[0]["signal_type"] == "issue"
        assert summaries[0]["count"] == 3
        assert summaries[1]["signal_type"] == "fact"
        assert summaries[1]["count"] == 1


class TestProactivePush:
    """P3-32：基于会话关键词的主动记忆推送。"""

    async def test_empty_keywords_returns_empty(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        result = await proactive_memory_push(
            conversation_keywords=[],
            workspace_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            db=db,
        )
        assert result == []
        db.execute.assert_not_called()

    async def test_filters_already_pushed(self):
        from apps.api.routes.context import proactive_memory_push

        ws_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        mem_id = uuid.uuid4()

        db = AsyncMock()

        pushed_result = MagicMock()
        pushed_result.all.return_value = [(mem_id,)]

        search_result_mock = MagicMock()
        search_result_mock.all.return_value = []

        db.execute = AsyncMock(side_effect=[pushed_result, search_result_mock])

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(mem_id),
                        "title": "Already pushed",
                        "content": "This was already pushed",
                        "score": 0.8,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=ws_id,
                session_id=sess_id,
                db=db,
            )
            assert result == []
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_pushes_new_memories(self):
        from apps.api.routes.context import proactive_memory_push

        ws_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        mem_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.add_all = MagicMock()

        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(mem_id),
                        "title": "Test Memory",
                        "content": "Some relevant content here for testing",
                        "score": 0.75,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test", "keyword"],
                workspace_id=ws_id,
                session_id=sess_id,
                db=db,
            )
            assert len(result) == 1
            assert result[0].memory_id == mem_id
            assert result[0].title == "Test Memory"
            assert result[0].relevance == 0.75
            assert "test" in result[0].push_reason
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_filters_low_score(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(uuid.uuid4()),
                        "title": "Low Score",
                        "content": "Not relevant enough",
                        "score": 0.3,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                db=db,
            )
            assert result == []
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_respects_max_items(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        db.add = MagicMock()
        db.add_all = MagicMock()
        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        memories = [
            {
                "id": str(uuid.uuid4()),
                "title": f"Memory {i}",
                "content": f"Content {i} for testing",
                "score": 0.8 - i * 0.05,
                "status": "active",
            }
            for i in range(5)
        ]

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(return_value={"memories": memories})

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                db=db,
                max_items=2,
            )
            assert len(result) == 2
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_proactive_push_record_model_exists(self):
        from packages.domain.models import ProactivePushRecord

        assert ProactivePushRecord.__tablename__ == "proactive_push_record"
        assert hasattr(ProactivePushRecord, "session_id")
        assert hasattr(ProactivePushRecord, "memory_id")
        assert hasattr(ProactivePushRecord, "relevance_score")
        assert hasattr(ProactivePushRecord, "keywords")

    async def test_proactive_push_schema_exists(self):
        from packages.domain.schemas import (
            ProactivePushItem,
            ProactivePushRequest,
            ProactivePushResponse,
        )

        req = ProactivePushRequest(
            workspace_id=str(uuid.uuid4()),
            session_id=uuid.uuid4(),
            keywords=["test"],
        )
        assert req.keywords == ["test"]
        assert req.max_items == 3

        item = ProactivePushItem(
            memory_id=uuid.uuid4(),
            title="Test",
            snippet="snippet",
            relevance=0.8,
            push_reason="reason",
        )
        assert item.relevance == 0.8

        resp = ProactivePushResponse(items=[item], total=1)
        assert resp.total == 1

    async def test_feature_flag_gates_endpoint(self):
        from packages.domain.config import ParasiticEvolutionConfig

        config = ParasiticEvolutionConfig()
        assert hasattr(config, "proactive_push_enabled")
        assert config.proactive_push_enabled is True


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
        from datetime import datetime

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
        from datetime import datetime

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
        from adapters.qoder.client import CwikiClient

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
        from adapters.qoder.client import CwikiClient

        client = CwikiClient("http://test:5172")
        client._request = AsyncMock(return_value=[])

        await client.get_memory_versions("test-mem-id")

        call_args = client._request.call_args
        assert call_args[1].get("params") == {"limit": 10}


class TestAutoConsolidateSimilar:
    """P4-44：自动合并相似记忆。"""

    async def test_disabled_when_flag_off(self):
        import packages.domain.config as config_module

        original = config_module.parasitic_evolution_config.auto_consolidate_enabled
        config_module.parasitic_evolution_config.auto_consolidate_enabled = False
        try:
            from apps.worker.tasks import task_auto_consolidate_similar

            result = await task_auto_consolidate_similar({})
            assert result["status"] == "disabled"
        finally:
            config_module.parasitic_evolution_config.auto_consolidate_enabled = original

    async def test_finds_similar_group(self):
        from unittest.mock import MagicMock, patch

        import packages.domain.config as config_module
        from apps.worker.tasks import task_auto_consolidate_similar

        original = config_module.parasitic_evolution_config.auto_consolidate_enabled
        config_module.parasitic_evolution_config.auto_consolidate_enabled = True
        try:
            mem1 = MagicMock()
            mem1.id = uuid.uuid4()
            mem1.title = "Title A"
            mem1.content = "项目使用Python作为主要开发语言并且采用FastAPI框架进行后端系统的开发工作"
            mem1.confidence = 0.8
            mem1.importance = 0.7

            mem2 = MagicMock()
            mem2.id = uuid.uuid4()
            mem2.title = "Title B"
            mem2.content = "项目使用Python作为主要开发语言并且采用FastAPI框架进行后端系统的开发任务"
            mem2.confidence = 0.6
            mem2.importance = 0.5

            mem3 = MagicMock()
            mem3.id = uuid.uuid4()
            mem3.title = "Title C"
            mem3.content = "这是完全不同的内容关于另一个主题的知识"
            mem3.confidence = 0.7
            mem3.importance = 0.6

            mock_result = MagicMock()
            mock_result.all.return_value = [mem1, mem2, mem3]

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch("apps.worker.tasks.async_session_maker", return_value=mock_session_ctx):
                result = await task_auto_consolidate_similar({})

            assert result["status"] == "completed"
            assert result["total_memories"] == 3
            suggestions = result["suggestions"]
            assert len(suggestions) >= 1
            group_ids = suggestions[0]["memory_ids"]
            assert str(mem1.id) in group_ids
            assert str(mem2.id) in group_ids
        finally:
            config_module.parasitic_evolution_config.auto_consolidate_enabled = original

    async def test_no_similar_memories_returns_empty(self):
        from unittest.mock import MagicMock, patch

        import packages.domain.config as config_module
        from apps.worker.tasks import task_auto_consolidate_similar

        original = config_module.parasitic_evolution_config.auto_consolidate_enabled
        config_module.parasitic_evolution_config.auto_consolidate_enabled = True
        try:
            mem1 = MagicMock()
            mem1.id = uuid.uuid4()
            mem1.title = "数据库配置"
            mem1.content = "完全不同的主题A关于数据库配置"
            mem1.confidence = 0.5
            mem1.importance = 0.5

            mem2 = MagicMock()
            mem2.id = uuid.uuid4()
            mem2.title = "前端框架"
            mem2.content = "另一个主题B关于前端框架选择"
            mem2.confidence = 0.5
            mem2.importance = 0.5

            mock_result = MagicMock()
            mock_result.all.return_value = [mem1, mem2]

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch("apps.worker.tasks.async_session_maker", return_value=mock_session_ctx):
                result = await task_auto_consolidate_similar({})

            assert result["groups_found"] == 0
            assert result["suggestions"] == []
        finally:
            config_module.parasitic_evolution_config.auto_consolidate_enabled = original

    async def test_single_memory_returns_no_groups(self):
        from unittest.mock import MagicMock, patch

        import packages.domain.config as config_module
        from apps.worker.tasks import task_auto_consolidate_similar

        original = config_module.parasitic_evolution_config.auto_consolidate_enabled
        config_module.parasitic_evolution_config.auto_consolidate_enabled = True
        try:
            mem1 = MagicMock()
            mem1.id = uuid.uuid4()
            mem1.title = "单条记忆"
            mem1.content = "只有一条记忆"
            mem1.confidence = 0.5
            mem1.importance = 0.5

            mock_result = MagicMock()
            mock_result.all.return_value = [mem1]

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch("apps.worker.tasks.async_session_maker", return_value=mock_session_ctx):
                result = await task_auto_consolidate_similar({})

            assert result["groups_found"] == 0
        finally:
            config_module.parasitic_evolution_config.auto_consolidate_enabled = original

    async def test_recommends_highest_quality_keeper(self):
        from unittest.mock import MagicMock, patch

        import packages.domain.config as config_module
        from apps.worker.tasks import task_auto_consolidate_similar

        original = config_module.parasitic_evolution_config.auto_consolidate_enabled
        config_module.parasitic_evolution_config.auto_consolidate_enabled = True
        try:
            mem_low = MagicMock()
            mem_low.id = uuid.uuid4()
            mem_low.title = "Low quality"
            mem_low.content = (
                "项目使用Python作为主要开发语言并且采用FastAPI框架进行后端系统的开发工作"
            )
            mem_low.confidence = 0.3
            mem_low.importance = 0.2

            mem_high = MagicMock()
            mem_high.id = uuid.uuid4()
            mem_high.title = "High quality"
            mem_high.content = (
                "项目使用Python作为主要开发语言并且采用FastAPI框架进行后端系统的开发任务"
            )
            mem_high.confidence = 0.9
            mem_high.importance = 0.9

            mock_result = MagicMock()
            mock_result.all.return_value = [mem_low, mem_high]

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx = MagicMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

            with patch("apps.worker.tasks.async_session_maker", return_value=mock_session_ctx):
                result = await task_auto_consolidate_similar({})

            assert len(result["suggestions"]) == 1
            assert result["suggestions"][0]["recommended_keeper"] == str(mem_high.id)
        finally:
            config_module.parasitic_evolution_config.auto_consolidate_enabled = original
