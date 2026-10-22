"""Outbox manager: write-ahead log, retry, and background drain.

Extracted from MCPServer to reduce class size and improve cohesion.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from adapters.mcp.outbox import WriteAheadOutbox

logger = logging.getLogger(__name__)

# Outbox retry constants
AUTO_RETRY_INTERVAL = 30.0
MAX_AUTO_RETRY_ATTEMPTS = 3
DRAIN_ENTRY_INTERVAL = 0.5


class ReplayRejected(Exception):
    """Raised when a replay is rejected (e.g., unsupported tool or security check)."""


class WriteUnconfirmedError(Exception):
    """Raised when a write cannot be confirmed by the API."""


class OutboxManager:
    """Manages outbox operations for MCPServer.
    
    This class encapsulates all write-ahead log, retry, and background drain
    logic, reducing MCPServer's responsibility and improving testability.
    """

    def __init__(
        self,
        client: Any,
        outbox: WriteAheadOutbox,
        workspace_resolver: Callable[[], str | None],
        classify_memory_type: Callable[[str], str],
        is_client_rejection: Callable[[Exception], bool],
        make_write_id: Callable[..., str],
        safe_error: Callable[[Exception], str],
        security_error: Callable[[str], dict[str, Any] | None],
    ) -> None:
        """Initialize OutboxManager.
        
        Args:
            client: CwikiClient instance for API calls
            outbox: WriteAheadOutbox instance for persistence
            workspace_resolver: Callable that returns current workspace ID
            classify_memory_type: Function to classify memory type from content
            is_client_rejection: Function to check if exception is client rejection
            make_write_id: Function to generate write ID from content
            safe_error: Function to safely extract error message
            security_error: Function to check content for security issues
        """
        self.client = client
        self.outbox = outbox
        self._workspace_resolver = workspace_resolver
        self._classify_memory_type = classify_memory_type
        self._is_client_rejection = is_client_rejection
        self._make_write_id = make_write_id
        self._safe_error = safe_error
        self._security_error = security_error
        self._drain_task: asyncio.Task[None] | None = None

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

    async def submit(
        self,
        tool: str,
        args: dict[str, Any],
        workspace_id: str,
        write_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
        """Orchestrate log → submit → return (response, entry, error).
        
        Combines log, submit_write, and on_error into a single workflow.
        """
        frozen = dict(args)
        entry = self.log(workspace_id, tool, frozen, write_id)
        try:
            response = await self.submit_write(tool, frozen, write_id, entry)
            return response, entry, None
        except Exception as exc:
            if entry:
                self.on_error(workspace_id, entry["id"], exc)
            return None, entry, exc

    async def replay_entry(
        self, workspace_id: str, write: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Replay a single outbox entry.
        
        This is the unified replay path for startup drain, auto-retry, and
        manual retry.
        """
        try:
            if write.get("tool") not in ("memory_save", "memory_checkpoint"):
                raise ReplayRejected("Unsupported outbox tool")
            args = write["arguments"]
            content = args.get("wrapped_content")
            if self._security_error(content if content is not None else args.get("content", "")):
                raise ReplayRejected("Suspicious content blocked")
            write_id = write.get("client_write_id") or self._make_write_id(
                args.get("content", ""),
                prefix="cp" if write["tool"] == "memory_checkpoint" else "ms",
            )
            response = await self.submit_write(write["tool"], args, write_id, write)
            warning = self.done(workspace_id, write["id"])
            if warning:
                return {
                    "entry_id": write["id"],
                    "error": warning,
                    "delivery": "confirmed",
                    "candidate_id": response["candidate"]["id"],
                }
            return None
        except Exception as exc:
            self.on_error(workspace_id, write["id"], exc)
            reason = self._safe_error(exc)
            logger.warning("Outbox replay failed: %s", reason)
            return {"entry_id": write["id"], "error": reason}

    def auto_retry_allowed(self, workspace_id: str, write: dict[str, Any]) -> bool:
        """Check if auto-retry is allowed for this entry."""
        if write.get("state", "pending") not in ("pending", "failed"):
            return False
        if write.get("attempts", 0) >= MAX_AUTO_RETRY_ATTEMPTS:
            self.outbox.mark_exhausted(workspace_id, write["id"])
            return False
        return True

    async def try_auto_retry_one(self, *, respect_backoff: bool = False) -> None:
        """Retry at most one retryable entry.
        
        When respect_backoff is True, skips entries that haven't waited long
        enough based on exponential backoff.
        """
        for workspace_id, entries in self.outbox.load_retryable().items():
            for write in entries:
                if not self.auto_retry_allowed(workspace_id, write):
                    continue
                if respect_backoff and write.get("last_error_at"):
                    try:
                        last_error = datetime.fromisoformat(write["last_error_at"])
                        delay = AUTO_RETRY_INTERVAL * 2 ** max(write.get("attempts", 1) - 1, 0)
                        if (datetime.now(UTC) - last_error).total_seconds() < delay:
                            continue
                    except (ValueError, TypeError):
                        pass
                await self.replay_entry(workspace_id, write)
                return

    async def drain(self) -> None:
        """Drain all retryable entries once.
        
        Resets exhausted entries first, then processes all retryable entries
        with a delay between each.
        """
        reset = self.outbox.reset_all_exhausted()
        if reset:
            logger.info("Reset %d exhausted outbox entries for retry", reset)
        total = 0
        succeeded = 0
        failed = 0
        for workspace_id, entries in self.outbox.load_retryable().items():
            for write in entries:
                if not self.auto_retry_allowed(workspace_id, write):
                    continue
                total += 1
                result = await self.replay_entry(workspace_id, write)
                if result is None or result.get("delivery") == "confirmed":
                    succeeded += 1
                else:
                    failed += 1
                if total > 0:
                    await asyncio.sleep(DRAIN_ENTRY_INTERVAL)
        if total > 0:
            logger.info(
                "Outbox drain: %d total, %d succeeded, %d failed", total, succeeded, failed
            )

    def start_background_drain(self) -> None:
        """Start background drain task if not already running."""
        if self._drain_task and not self._drain_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._drain_task = loop.create_task(self._background_drain())
        except RuntimeError:
            logger.debug("No running loop; skipping background outbox drain")

    async def _background_drain(self) -> None:
        """Background task that drains the outbox."""
        try:
            await self.drain()
        except Exception as exc:
            logger.warning("Background outbox drain failed: %s", self._safe_error(exc))
        finally:
            self._drain_task = None
