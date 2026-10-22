"""Outbox primitives: write-ahead log, submission, and state summaries.

Retry/replay orchestration stays on MCPServer so its hooks remain patchable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from adapters.mcp.outbox import WriteAheadOutbox

logger = logging.getLogger(__name__)


class ReplayRejected(Exception):
    """Raised when a replay is rejected (e.g., unsupported tool or security check)."""


class WriteUnconfirmedError(Exception):
    """Raised when a write cannot be confirmed by the API."""


class OutboxManager:
    """Wraps outbox storage and candidate submission primitives."""

    def __init__(
        self,
        client: Any,
        outbox: WriteAheadOutbox,
        workspace_resolver: Callable[[], str | None],
        classify_memory_type: Callable[[str], str],
        is_client_rejection: Callable[[Exception], bool],
        safe_error: Callable[[Exception], str],
    ) -> None:
        """Initialize OutboxManager.

        Args:
            client: CwikiClient instance for API calls
            outbox: WriteAheadOutbox instance for persistence
            workspace_resolver: Callable that returns current workspace ID
            classify_memory_type: Function to classify memory type from content
            is_client_rejection: Function to check if exception is client rejection
            safe_error: Function to safely extract error message
        """
        self.client = client
        self.outbox = outbox
        self._workspace_resolver = workspace_resolver
        self._classify_memory_type = classify_memory_type
        self._is_client_rejection = is_client_rejection
        self._safe_error = safe_error

    def log(
        self,
        workspace_id: str,
        tool: str,
        arguments: dict[str, Any],
        client_write_id: str,
    ) -> dict[str, Any] | None:
        """Log a pending write to the outbox."""
        return self.outbox.log_pending(workspace_id, tool, arguments, client_write_id)

    def done(self, workspace_id: str, entry_id: str) -> str | None:
        """Mark an entry as successfully completed.

        Returns warning message if cleanup fails, None otherwise.
        """
        try:
            self.outbox.mark_success(workspace_id, entry_id)
        except Exception as exc:
            logger.warning("Acknowledged write cleanup failed: %s", self._safe_error(exc))
            return "API 已确认，但本地 outbox 清理失败；残留条目使用原写入标识重试。"
        return None

    def fail(self, workspace_id: str, entry_id: str) -> None:
        """Mark an entry as failed."""
        self.outbox.mark_failed(workspace_id, entry_id)

    def summary(self, *, status_tool: bool = False) -> dict[str, Any]:
        """Get outbox summary with counts by state."""
        counts = dict.fromkeys(("pending", "failed", "exhausted", "rejected"), 0)
        try:
            counts.update(self.outbox.count_all_by_state())
        except Exception as exc:
            logger.warning("Outbox counts unavailable: %s", self._safe_error(exc))
            return {
                "outbox_counts": None,
                "outbox_total": None,
                "outbox_pending": None,
                "outbox_exhausted": None,
                "outbox_error": "本地 outbox 计数不可用",
            }
        return {
            "outbox_counts": counts,
            "outbox_total": sum(counts.values()),
            "outbox_pending": counts["failed"] + (0 if status_tool else counts["exhausted"]),
            "outbox_exhausted": counts["exhausted"],
        }

    def on_error(self, workspace_id: str, entry_id: str, exc: Exception) -> None:
        """Handle error during write submission.

        Marks as rejected for client rejections, failed otherwise.
        """
        if not entry_id:
            return
        reason = self._safe_error(exc)
        try:
            if self._is_client_rejection(exc):
                self.outbox.mark_rejected(workspace_id, entry_id, reason)
            else:
                self.outbox.mark_failed(workspace_id, entry_id, reason)
        except Exception as disk_exc:
            logger.warning("Outbox failure state update failed: %s", self._safe_error(disk_exc))

    async def submit_write(
        self,
        tool: str,
        args: dict[str, Any],
        write_id: str,
        entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit a frozen save/checkpoint payload to the API.

        Infers memory type if not provided, resolves workspace, and submits
        via client.submit_candidate.
        """
        if tool not in ("memory_save", "memory_checkpoint"):
            raise ReplayRejected("Unsupported outbox tool")
        content = args.get("wrapped_content")
        if content is None:
            content = args.get("content", "")
        memory_type = args.get("type") or args.get("inferred_type")
        if not memory_type:
            memory_type = (
                "fact"
                if tool == "memory_checkpoint" or args.get("wrapped_content") is not None
                else self._classify_memory_type(content)
            )
            args = {**args, "inferred_type": memory_type}
            if entry:
                self.outbox.update_entry(entry["workspace_id"], entry["id"], {"arguments": args})
        workspace = (
            args.get("workspace_id")
            or (entry or {}).get("workspace_id")
            or self._workspace_resolver()
        )
        kwargs: dict[str, Any] = {"source": "memory_save"} if tool == "memory_save" else {}
        if tool == "memory_save" and args.get("tags"):
            kwargs["tags"] = args["tags"]
        response = await self.client.submit_candidate(
            title=args.get("title", ""),
            content=content,
            memory_type=memory_type,
            workspace_id=workspace,
            client_write_id=write_id,
            **kwargs,
        )
        candidate = response.get("candidate") if isinstance(response, dict) else None
        candidate_id = candidate.get("id") if isinstance(candidate, dict) else None
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise WriteUnconfirmedError()
        return response if isinstance(response, dict) else {}
