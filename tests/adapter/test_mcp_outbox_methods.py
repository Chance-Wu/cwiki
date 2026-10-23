"""Unit tests for MCPServer outbox methods.

Tests the outbox-related methods that will be extracted during refactoring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from adapters.mcp.mcp_server import MCPServer
from adapters.mcp.outbox_manager import ReplayRejected, WriteUnconfirmedError


@pytest.fixture
def mock_client():
    """Mock CwikiClient."""
    client = AsyncMock()
    client.submit_candidate = AsyncMock(return_value={"candidate": {"id": "cand-123"}})
    return client


@pytest.fixture
def mock_outbox():
    """Mock WriteAheadOutbox."""
    outbox = MagicMock()
    outbox.log_pending = Mock(return_value={"id": "entry-1", "workspace_id": "ws-1"})
    outbox.mark_success = Mock()
    outbox.mark_failed = Mock()
    outbox.mark_rejected = Mock()
    outbox.mark_exhausted = Mock()
    outbox.count_all_by_state = Mock(
        return_value={"pending": 1, "failed": 2, "exhausted": 1, "rejected": 0}
    )
    outbox.load_retryable = Mock(return_value={})
    outbox.reset_all_exhausted = Mock(return_value=0)
    outbox.update_entry = Mock()
    return outbox


@pytest.fixture
def server(mock_client, mock_outbox):
    """MCPServer instance with mocked dependencies."""
    srv = MCPServer(mock_client)
    srv.outbox = mock_outbox
    # Also update the OutboxManager's outbox reference
    srv._outbox_manager.outbox = mock_outbox
    srv.session_workspace = "default-ws"
    srv._drain_task = None
    return srv


class TestOutboxLog:
    def test_delegates_to_outbox(self, server, mock_outbox):
        """_outbox_log delegates to outbox.log_pending."""
        result = server._outbox_log("ws-1", "memory_save", {"content": "test"}, "write-1")
        mock_outbox.log_pending.assert_called_once_with(
            "ws-1", "memory_save", {"content": "test"}, "write-1"
        )
        assert result == {"id": "entry-1", "workspace_id": "ws-1"}


class TestOutboxDone:
    def test_mark_success_returns_none(self, server, mock_outbox):
        """_outbox_done marks success and returns None."""
        result = server._outbox_done("ws-1", "entry-1")
        mock_outbox.mark_success.assert_called_once_with("ws-1", "entry-1")
        assert result is None

    def test_mark_success_failure_returns_warning(self, server, mock_outbox):
        """_outbox_done returns warning if mark_success fails."""
        mock_outbox.mark_success.side_effect = Exception("disk error")
        result = server._outbox_done("ws-1", "entry-1")
        assert result is not None
        assert "outbox 清理失败" in result


class TestOutboxFail:
    def test_delegates_to_outbox(self, server, mock_outbox):
        """_outbox_fail delegates to outbox.mark_failed."""
        server._outbox_fail("ws-1", "entry-1")
        mock_outbox.mark_failed.assert_called_once_with("ws-1", "entry-1")


class TestOutboxSummary:
    def test_aggregates_counts(self, server, mock_outbox):
        """_outbox_summary aggregates counts from outbox."""
        result = server._outbox_summary()
        assert result["outbox_counts"] == {
            "pending": 1,
            "failed": 2,
            "exhausted": 1,
            "rejected": 0,
        }
        assert result["outbox_total"] == 4
        assert result["outbox_pending"] == 3  # failed + exhausted (non-status tool)
        assert result["outbox_exhausted"] == 1

    def test_status_tool_excludes_exhausted(self, server, mock_outbox):
        """_outbox_summary with status_tool=True excludes exhausted from pending."""
        result = server._outbox_summary(status_tool=True)
        assert result["outbox_pending"] == 2  # failed only

    def test_outbox_unavailable_returns_error(self, server, mock_outbox):
        """_outbox_summary returns error dict if outbox fails."""
        mock_outbox.count_all_by_state.side_effect = Exception("corrupt")
        result = server._outbox_summary()
        assert result["outbox_counts"] is None
        assert result["outbox_error"] == "本地 outbox 计数不可用"


class TestOutboxOnError:
    def test_client_rejection_marks_rejected(self, server, mock_outbox):
        """_outbox_on_error marks rejected for client rejection."""
        # _is_client_rejection checks for ReplayRejected or httpx.HTTPStatusError with 4xx
        exc = ReplayRejected("Client rejected: invalid schema")
        server._outbox_on_error("ws-1", "entry-1", exc)
        mock_outbox.mark_rejected.assert_called_once()
        mock_outbox.mark_failed.assert_not_called()

    def test_other_error_marks_failed(self, server, mock_outbox):
        """_outbox_on_error marks failed for other errors."""
        exc = Exception("Network timeout")
        server._outbox_on_error("ws-1", "entry-1", exc)
        mock_outbox.mark_failed.assert_called_once()
        mock_outbox.mark_rejected.assert_not_called()

    def test_empty_entry_id_is_noop(self, server, mock_outbox):
        """_outbox_on_error with empty entry_id does nothing."""
        server._outbox_on_error("ws-1", "", Exception("error"))
        mock_outbox.mark_failed.assert_not_called()
        mock_outbox.mark_rejected.assert_not_called()


class TestSubmitWrite:
    @pytest.mark.asyncio
    async def test_infers_type_for_save(self, server, mock_client):
        """_submit_write infers memory type for memory_save."""
        args = {"content": "test content", "workspace_id": "ws-1"}
        result = await server._submit_write("memory_save", args, "write-1")
        assert result == {"candidate": {"id": "cand-123"}}
        # Verify submit_candidate was called with inferred type
        call_kwargs = mock_client.submit_candidate.call_args[1]
        assert call_kwargs["memory_type"] == "fact"

    @pytest.mark.asyncio
    async def test_uses_explicit_type(self, server, mock_client):
        """_submit_write uses explicit type if provided."""
        args = {"content": "test", "type": "decision", "workspace_id": "ws-1"}
        await server._submit_write("memory_save", args, "write-1")
        call_kwargs = mock_client.submit_candidate.call_args[1]
        assert call_kwargs["memory_type"] == "decision"

    @pytest.mark.asyncio
    async def test_raises_for_unsupported_tool(self, server):
        """_submit_write raises ReplayRejected for unsupported tool."""
        with pytest.raises(ReplayRejected, match="Unsupported outbox tool"):
            await server._submit_write("memory_update", {}, "write-1")

    @pytest.mark.asyncio
    async def test_raises_when_no_candidate_id(self, server, mock_client):
        """_submit_write raises WriteUnconfirmedError if no candidate ID."""
        mock_client.submit_candidate.return_value = {"candidate": {}}
        with pytest.raises(WriteUnconfirmedError):
            await server._submit_write("memory_save", {"content": "test"}, "write-1")

    @pytest.mark.asyncio
    async def test_updates_entry_with_inferred_type(self, server, mock_outbox):
        """_submit_write updates entry with inferred type."""
        args = {"content": "test"}
        entry = {"id": "entry-1", "workspace_id": "ws-1"}
        await server._submit_write("memory_save", args, "write-1", entry)
        mock_outbox.update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_forwards_permanent_flags_for_save(self, server, mock_client):
        """_submit_write forwards permanent flags stored in the frozen payload."""
        args = {
            "content": "test",
            "workspace_id": "ws-1",
            "is_permanent": True,
            "permanent_reason": "用户指定长期保留",
        }
        await server._submit_write("memory_save", args, "write-1")
        call_kwargs = mock_client.submit_candidate.call_args[1]
        assert call_kwargs["is_permanent"] is True
        assert call_kwargs["permanent_reason"] == "用户指定长期保留"

    @pytest.mark.asyncio
    async def test_ignores_permanent_reason_without_flag(self, server, mock_client):
        """未声明永久时，原因文本不应传给 API。"""
        args = {"content": "test", "workspace_id": "ws-1", "permanent_reason": "误传"}
        await server._submit_write("memory_save", args, "write-1")
        call_kwargs = mock_client.submit_candidate.call_args[1]
        assert "is_permanent" not in call_kwargs
        assert "permanent_reason" not in call_kwargs


class TestOutboxSubmit:
    @pytest.mark.asyncio
    async def test_orchestrates_log_submit_done(self, server, mock_outbox, mock_client):
        """_outbox_submit orchestrates log, submit, and returns result."""
        result, entry, exc = await server._outbox_submit(
            "memory_save", {"content": "test"}, "ws-1", "write-1"
        )
        assert result == {"candidate": {"id": "cand-123"}}
        assert entry == {"id": "entry-1", "workspace_id": "ws-1"}
        assert exc is None
        mock_outbox.log_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self, server, mock_outbox, mock_client):
        """_outbox_submit returns error tuple on failure."""
        mock_client.submit_candidate.side_effect = Exception("network error")
        result, entry, exc = await server._outbox_submit(
            "memory_save", {"content": "test"}, "ws-1", "write-1"
        )
        assert result is None
        assert entry is not None
        assert exc is not None
        assert "network error" in str(exc)


class TestReplayEntry:
    @pytest.mark.asyncio
    async def test_replays_and_marks_done(self, server, mock_outbox, mock_client):
        """_replay_entry replays entry and marks done."""
        write = {
            "id": "entry-1",
            "workspace_id": "ws-1",
            "tool": "memory_save",
            "arguments": {"content": "test", "workspace_id": "ws-1"},
            "client_write_id": "write-1",
        }
        result = await server._replay_entry("ws-1", write)
        assert result is None  # Success returns None
        mock_client.submit_candidate.assert_called_once()
        mock_outbox.mark_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_suspicious_content(self, server, monkeypatch):
        """_replay_entry rejects suspicious content."""
        # 重放编排在 MCPServer 上，安全检测注入点也在该模块
        monkeypatch.setattr(
            "adapters.mcp.mcp_server._security_error",
            Mock(return_value={"error": "suspicious content", "security_flag": "test"}),
        )
        write = {
            "id": "entry-1",
            "workspace_id": "ws-1",
            "tool": "memory_save",
            "arguments": {"content": "normal content", "workspace_id": "ws-1"},
        }
        result = await server._replay_entry("ws-1", write)
        assert result is not None
        assert "error" in result
        assert "Suspicious content blocked" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_unsupported_tool(self, server):
        """_replay_entry rejects unsupported tool."""
        write = {
            "id": "entry-1",
            "workspace_id": "ws-1",
            "tool": "memory_update",
            "arguments": {},
        }
        result = await server._replay_entry("ws-1", write)
        assert result is not None
        assert "Unsupported outbox tool" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self, server, mock_client):
        """_replay_entry returns error dict on failure."""
        mock_client.submit_candidate.side_effect = Exception("network error")
        write = {
            "id": "entry-1",
            "workspace_id": "ws-1",
            "tool": "memory_save",
            "arguments": {"content": "test", "workspace_id": "ws-1"},
        }
        result = await server._replay_entry("ws-1", write)
        assert result is not None
        assert "error" in result
        assert result["entry_id"] == "entry-1"


class TestAutoRetryAllowed:
    def test_allows_pending_state(self, server):
        """_auto_retry_allowed allows pending state."""
        write = {"state": "pending", "attempts": 0}
        assert server._auto_retry_allowed("ws-1", write) is True

    def test_allows_failed_state(self, server):
        """_auto_retry_allowed allows failed state."""
        write = {"state": "failed", "attempts": 1}
        assert server._auto_retry_allowed("ws-1", write) is True

    def test_rejects_exhausted_state(self, server, mock_outbox):
        """_auto_retry_allowed rejects exhausted state."""
        write = {"state": "exhausted", "attempts": 5, "id": "entry-1"}
        assert server._auto_retry_allowed("ws-1", write) is False
        # Should not mark exhausted again
        mock_outbox.mark_exhausted.assert_not_called()

    def test_marks_exhausted_when_max_attempts(self, server, mock_outbox):
        """_auto_retry_allowed marks exhausted when max attempts reached."""
        write = {"state": "failed", "attempts": 5, "id": "entry-1"}
        assert server._auto_retry_allowed("ws-1", write) is False
        mock_outbox.mark_exhausted.assert_called_once_with("ws-1", "entry-1")


class TestTryAutoRetryOne:
    @pytest.mark.asyncio
    async def test_retries_one_entry(self, server, mock_outbox, mock_client):
        """_try_auto_retry_one retries at most one entry."""
        mock_outbox.load_retryable.return_value = {
            "ws-1": [
                {
                    "id": "entry-1",
                    "workspace_id": "ws-1",
                    "state": "failed",
                    "attempts": 1,
                    "tool": "memory_save",
                    "arguments": {"content": "test", "workspace_id": "ws-1"},
                },
                {
                    "id": "entry-2",
                    "workspace_id": "ws-1",
                    "state": "failed",
                    "attempts": 1,
                    "tool": "memory_save",
                    "arguments": {"content": "test2", "workspace_id": "ws-1"},
                },
            ]
        }
        await server._try_auto_retry_one()
        # Should only retry one entry
        assert mock_client.submit_candidate.call_count == 1

    @pytest.mark.asyncio
    async def test_respects_backoff(self, server, mock_outbox):
        """_try_auto_retry_one respects backoff when requested."""
        mock_outbox.load_retryable.return_value = {
            "ws-1": [
                {
                    "id": "entry-1",
                    "workspace_id": "ws-1",
                    "state": "failed",
                    "attempts": 2,
                    "last_error_at": datetime.now(UTC).isoformat(),
                    "tool": "memory_save",
                    "arguments": {"content": "test", "workspace_id": "ws-1"},
                }
            ]
        }
        await server._try_auto_retry_one(respect_backoff=True)
        # Should skip due to backoff
        assert server.client.submit_candidate.call_count == 0


class TestDrainOutbox:
    @pytest.mark.asyncio
    async def test_drains_all_retryable(self, server, mock_outbox, mock_client):
        """_drain_outbox drains all retryable entries."""
        mock_outbox.load_retryable.return_value = {
            "ws-1": [
                {
                    "id": "entry-1",
                    "workspace_id": "ws-1",
                    "state": "failed",
                    "attempts": 1,
                    "tool": "memory_save",
                    "arguments": {"content": "test1", "workspace_id": "ws-1"},
                },
                {
                    "id": "entry-2",
                    "workspace_id": "ws-1",
                    "state": "failed",
                    "attempts": 1,
                    "tool": "memory_save",
                    "arguments": {"content": "test2", "workspace_id": "ws-1"},
                },
            ]
        }
        await server._drain_outbox()
        assert mock_client.submit_candidate.call_count == 2

    @pytest.mark.asyncio
    async def test_resets_exhausted_before_drain(self, server, mock_outbox):
        """_drain_outbox resets exhausted entries before draining."""
        mock_outbox.reset_all_exhausted.return_value = 3
        await server._drain_outbox()
        mock_outbox.reset_all_exhausted.assert_called_once()
