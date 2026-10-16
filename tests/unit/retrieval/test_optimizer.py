"""packages.retrieval.optimizer 测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.retrieval.optimizer import _OPTIMIZE_PROMPT, OptimizationResult, optimize_memory


class TestOptimizerPrompt:
    def test_prompt_has_placeholders(self):
        assert "{memory_type}" in _OPTIMIZE_PROMPT
        assert "{title}" in _OPTIMIZE_PROMPT
        assert "{content}" in _OPTIMIZE_PROMPT


class TestOptimizeMemory:
    @pytest.mark.asyncio
    async def test_returns_none_without_api_key(self):
        with patch("packages.retrieval.optimizer.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            result = await optimize_memory("title", "content", "fact")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_optimization_result_on_success(self):
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"title": "opt", "content": "opt body", "changes": "made shorter"}'
                )
            )
        ]

        mock_completions = MagicMock()
        mock_completions.create = AsyncMock(return_value=mock_response)

        mock_chat = MagicMock()
        mock_chat.completions = mock_completions

        mock_client = MagicMock()
        mock_client.chat = mock_chat

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncOpenAI.return_value = mock_client

        with (
            patch("packages.retrieval.optimizer.settings") as mock_settings,
            patch.dict("sys.modules", {"openai": mock_openai_module}),
        ):
            mock_settings.openai_api_key = "test-key"

            result = await optimize_memory("title", "content", "fact")

        assert isinstance(result, OptimizationResult)
        assert result.title == "opt"
        assert result.content == "opt body"
        assert result.changes == "made shorter"

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        with (
            patch("packages.retrieval.optimizer.settings") as mock_settings,
            patch.dict("sys.modules", {"openai": None}),
        ):
            mock_settings.openai_api_key = "test-key"

            result = await optimize_memory("title", "content", "fact")
            assert result is None
