"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestComputeFreshness、TestRerankContextResults、TestFitToTokenBudget、TestDeduplicateResults。
"""

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
