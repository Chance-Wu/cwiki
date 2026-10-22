"""Checkpoint manager extracted from MCPServer.

Handles checkpoint-related operations: fetching events/notes,
validating candidates, submitting via outbox, and recording watermarks.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("cwiki.mcp.checkpoint")

# Checkpoint 增量时间窗口参数
DEFAULT_SINCE_MINUTES = 60
MIN_WINDOW_MINUTES = 5
MAX_WINDOW_MINUTES = 120
CHECKPOINT_FETCH_LIMIT = 200


class CheckpointManager:
    """Checkpoint 操作管理器。

    通过依赖注入避免循环导入：接收辅助函数作为构造参数。
    """

    def __init__(
        self,
        client: Any,
        outbox: Any,
        outbox_submit: Any,
        outbox_done: Any,
        safe_error: Any,
        make_write_id: Any,
        security_error: Any,
        summarize_notes_by_type: Any,
        build_event_analysis_report: Any,
    ) -> None:
        self._client = client
        self._outbox = outbox
        self._outbox_submit = outbox_submit
        self._outbox_done = outbox_done
        self._safe_error = safe_error
        self._make_write_id = make_write_id
        self._security_error = security_error
        self._summarize_notes_by_type = summarize_notes_by_type
        self._build_event_analysis_report = build_event_analysis_report

    @property
    def outbox(self) -> Any:
        return self._outbox

    @outbox.setter
    def outbox(self, value: Any) -> None:
        self._outbox = value

    async def fetch_events(
        self,
        workspace_id: str,
        event_session_id: str | None,
        since_minutes: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """为 checkpoint 拉取原始事件。返回 (events, error_dict|None)。"""
        if not event_session_id:
            return [], {
                "stage": "events",
                "error": "无关联的 event_session_id；"
                "请确保通过正常流程创建 agent session（会自动关联 event session）。",
            }
        try:
            events = await self._client.get_raw_events(
                workspace_id=workspace_id,
                session_id=event_session_id,
                since_minutes=since_minutes,
                limit=CHECKPOINT_FETCH_LIMIT,
            )
            return events, None
        except Exception as exc:
            logger.warning("Failed to fetch events for checkpoint: %s", self._safe_error(exc))
            return [], {"stage": "events", "error": self._safe_error(exc)}

    async def fetch_notes(
        self,
        session_id: str,
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """为 checkpoint 拉取会话笔记。返回 (notes, error_dict|None)。"""
        try:
            notes = await self._client.list_session_notes(
                session_id=session_id,
                limit=CHECKPOINT_FETCH_LIMIT,
                workspace_id=workspace_id,
            )
            return notes, None
        except Exception as exc:
            logger.warning(
                "Failed to fetch session notes for checkpoint: %s", self._safe_error(exc)
            )
            return [], {"stage": "notes", "error": self._safe_error(exc)}

    async def submit_candidates(
        self,
        candidates: list[dict[str, Any]],
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """经 outbox 提交校验后的候选。返回 (submitted, errors)。"""
        submitted: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for candidate in candidates:
            write_id = self._make_write_id(candidate["content"], prefix="cp")
            frozen = {
                "title": candidate["title"],
                "content": candidate["content"],
                "type": candidate["type"],
                "workspace_id": workspace_id,
            }
            resp, cp_outbox_entry, exc = await self._outbox_submit(
                "memory_checkpoint", frozen, workspace_id, write_id
            )
            if exc is not None:
                errors.append(
                    {
                        "stage": "submit",
                        "error": self._safe_error(exc),
                        "cached": cp_outbox_entry is not None,
                    }
                )
                continue
            assert resp is not None
            candidate_id = resp["candidate"]["id"]
            submitted.append(
                {
                    "title": candidate["title"],
                    "type": candidate["type"],
                    "source": candidate.get("source", "unknown"),
                    "candidate_id": candidate_id,
                    "delivery": "confirmed",
                }
            )
            # formalize 失败计入 errors 以阻止水位前进：下次 checkpoint 借
            # client_write_id 幂等去重重新提交并重试 formalize，自愈闭环。
            for note_id in candidate.get("note_ids", []):
                try:
                    await self._client.formalize_session_note(str(note_id))
                except Exception as formalize_exc:
                    errors.append(
                        {
                            "stage": "formalize",
                            "error": self._safe_error(formalize_exc),
                            "note_id": str(note_id),
                        }
                    )
            if cp_outbox_entry:
                warning = self._outbox_done(workspace_id, cp_outbox_entry["id"])
                if warning:
                    logger.warning("Checkpoint outbox cleanup: %s", warning)
        return submitted, errors

    def validate_candidates(
        self,
        candidates: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """校验并过滤候选，失败项追加到 errors。"""
        from packages.domain.types import validate_memory_content, validate_memory_title

        safe: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                validate_memory_title(candidate["title"])
                validate_memory_content(candidate["content"])
            except ValueError as exc:
                errors.append({"stage": "validation", "error": str(exc)})
                continue
            security_error = self._security_error(candidate["content"])
            if security_error:
                errors.append({"stage": "security", **security_error})
            else:
                safe.append(candidate)
        return safe

    def compute_window(
        self,
        session_id: str,
        workspace_id: str,
        event_session_id: str | None,
        collection_started_at: datetime,
    ) -> tuple[int, bool, str | None]:
        """计算 checkpoint 的增量时间窗口。

        返回 (since_minutes, window_truncated, last_checkpoint_iso)。
        """
        last_checkpoint = self._outbox.get_last_checkpoint(
            session_id, workspace_id, event_session_id=event_session_id
        )
        since_minutes = DEFAULT_SINCE_MINUTES
        window_truncated = False
        if last_checkpoint:
            try:
                last_dt = datetime.fromisoformat(last_checkpoint)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                # 向上取整并加 1 分钟重叠：补偿 API 相对时钟偏差与请求延迟
                delta_minutes = (
                    math.ceil((collection_started_at - last_dt).total_seconds() / 60) + 1
                )
                window_truncated = delta_minutes > MAX_WINDOW_MINUTES
                since_minutes = min(max(delta_minutes, MIN_WINDOW_MINUTES), MAX_WINDOW_MINUTES)
            except (ValueError, TypeError):
                window_truncated = True
        return since_minutes, window_truncated, last_checkpoint

    async def build_result(
        self,
        *,
        dry_run: bool,
        trigger_reason: str,
        input_status: dict[str, Any],
        since_minutes: int,
        window_truncated: bool,
        collection_started_at: datetime,
        last_checkpoint: str | None,
        events: list[dict[str, Any]],
        all_notes: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        submitted: list[dict[str, Any]],
        workspace_id: str,
        errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """组装 checkpoint 响应体。"""
        from adapters.mcp.signal_engine import CONTENT_PREVIEW_LENGTH

        unformalized = [n for n in all_notes if not n.get("formalized", False)]

        result: dict[str, Any] = {
            "status": "ok",
            "dry_run": dry_run,
            "trigger_reason": trigger_reason,
            "input_status": input_status,
            "input_window": {
                "since_minutes": since_minutes,
                "event_limit": CHECKPOINT_FETCH_LIMIT,
                "note_limit": CHECKPOINT_FETCH_LIMIT,
                "limit_reached": len(events) >= CHECKPOINT_FETCH_LIMIT
                or len(all_notes) >= CHECKPOINT_FETCH_LIMIT,
                "time_window_truncated": window_truncated,
                "collection_started_at": collection_started_at.isoformat(),
                "incremental": last_checkpoint is not None,
            },
            "hint": "仅检查已采集事件和笔记，不代表完整对话已完成语义检查。",
            "events_analyzed": len(events),
            "notes_analyzed": len(all_notes),
            "unformalized_notes": len(unformalized),
            "candidates_extracted": len(candidates),
        }

        if dry_run:
            result["candidates_preview"] = [
                {
                    "title": c["title"],
                    "type": c["type"],
                    "source": c.get("source", "unknown"),
                    "content_preview": c["content"][:CONTENT_PREVIEW_LENGTH],
                }
                for c in candidates
            ]
            result["message"] = (
                "dry_run 模式：仅分析不提交；预览可能截短，实际提交保留来源正文，"
                "不要用预览代替完整内容。"
            )
        else:
            result["candidates_submitted"] = len(submitted)
            result["submitted"] = submitted

        if unformalized:
            summaries = self._summarize_notes_by_type(all_notes)
            result["notes_summary"] = {
                "total_unformalized": len(unformalized),
                "group_summaries": summaries,
                "action": "摘要仅用于定位信号；用 memory_save 整理时回到原始上下文，保留完整细节，不要仅复述摘要",
            }

        if events:
            worker_candidates = []
            try:
                worker_candidates = await self._client.get_workers_candidates(
                    workspace_id=workspace_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch worker candidates for checkpoint: %s", self._safe_error(exc)
                )
                errors.append({"stage": "worker_candidates", "error": self._safe_error(exc)})
            result["event_analysis"] = self._build_event_analysis_report(
                events,
                worker_candidates,
            )

        return result

    async def finalize(
        self,
        result: dict[str, Any],
        *,
        session_id: str,
        workspace_id: str,
        event_session_id: str | None,
        collection_started_at: datetime,
        input_status: dict[str, Any],
        submitted: list[dict[str, Any]],
        dry_run: bool,
        errors: list[dict[str, Any]],
        warnings: list[str],
    ) -> dict[str, Any]:
        """记录水位、确定最终状态并附加 errors/warnings。"""
        if (
            not errors
            and submitted
            and not dry_run
            and all(state in ("available", "empty") for state in input_status.values())
        ):
            try:
                self._outbox.record_checkpoint(
                    session_id,
                    workspace_id,
                    collection_started_at.isoformat(),
                    event_session_id=event_session_id,
                )
            except Exception as exc:
                errors.append({"stage": "watermark", "error": self._safe_error(exc)})
        if errors:
            result["status"] = (
                "error"
                if all(state == "unavailable" for state in input_status.values())
                else "partial"
            )
            result["errors"] = errors
            result["error"] = "检查点未完整完成，请查看 errors；已提交的候选无需重复提交。"
        if warnings:
            result["warnings"] = warnings
        return result
