#!/usr/bin/env python3
"""cwiki MCP 服务器 —— stdio 传输。

通过 cwiki API 提供记忆查询与提交类 MCP 工具。
作为 Qoder 的子进程运行，经 stdio 以逐行 JSON-RPC 2.0 通信。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import signal
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

try:
    import httpx
except ImportError:
    print(
        json.dumps({"error": "httpx is required. Install with: pip install httpx"}),
        file=sys.stderr,
    )
    sys.exit(1)

from packages.domain import config as domain_config
from packages.domain.config import settings
from packages.domain.types import (
    TYPE_DEFINITIONS,
    validate_memory_content,
    validate_memory_title,
)

try:
    from packages.memory.content_security import check_injection
except ImportError:
    check_injection = None  # type: ignore[assignment]

try:
    from packages.memory.type_classifier import infer_memory_type
except ImportError:
    infer_memory_type = None  # type: ignore[assignment]

try:
    from adapters.qoder.content_processing import (
        format_remember_response as _real_format_remember_response,
    )

    format_remember_response = _real_format_remember_response
except ImportError:

    def format_remember_response(response: dict[str, Any]) -> dict[str, Any]:
        candidate = response.get("candidate", response)
        return {
            "status": "created",
            "candidate_id": candidate.get("id"),
            "message": response.get("hint", "已提交"),
        }


try:
    from packages.memory.memory_gap import detect_memory_gap
except ImportError:
    detect_memory_gap = None  # type: ignore[assignment]

try:
    from packages.domain.config import parasitic_evolution_config
except ImportError:
    parasitic_evolution_config = None  # type: ignore[assignment]

from adapters.qoder.client import CwikiClient, MemoryUpdateUncertainError
from adapters.qoder.outbox import WriteAheadOutbox

# -- 抽取出的子模块（signal_engine / transport 等纯逻辑已拆分，便于测试替换）--
from adapters.qoder.signal_engine import AUTO_GROUP_SIGNAL_TYPE
from adapters.qoder.signal_engine import (
    build_event_analysis_report as _build_event_analysis_report,
)
from adapters.qoder.signal_engine import (
    extract_memories_from_events as _extract_memories_from_events,
)
from adapters.qoder.signal_engine import (
    summarize_notes_by_type as _summarize_notes_by_type,
)
from adapters.qoder.tool_definitions import build_tool_definitions
from adapters.qoder.transport import (
    INVALID_REQUEST_ERROR,
    MAX_MESSAGE_BYTES,
    OVERSIZE_ERROR,
    PARSE_ERROR,
    SESSION_INIT_TIMEOUT,
)
from adapters.qoder.transport import (
    get_git_info as _get_git_info,
)
from adapters.qoder.transport import (
    stdin_reader as _stdin_reader,
)
from adapters.qoder.transport import (
    write_stdout as _write_stdout,
)

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("cwiki-mcp")

# 默认走 IPv4 回环：Windows 上 localhost 优先解析 ::1，连接被拒后的等待会让每次调用多出约 150ms
API_BASE_URL = os.environ.get("CWIKI_API_URL", "http://127.0.0.1:5172")
DEFAULT_WORKSPACE = "default"
REQUEST_TIMEOUT = float(os.environ.get("CWIKI_TIMEOUT", "10.0"))
AUTO_RETRY_INTERVAL = 30.0
CHECKPOINT_FETCH_LIMIT = 200
DEFAULT_SINCE_MINUTES = 60
MAX_WINDOW_MINUTES = 1440
MIN_WINDOW_MINUTES = 5
MAX_AUTO_RETRY_ATTEMPTS = 3
DRAIN_ENTRY_INTERVAL = 0.5
MIN_NOTES_FOR_AUTO_GROUP = 3
STALE_SESSION_MAX_AGE = timedelta(hours=24)
NULL_SESSION_ID = "00000000-0000-0000-0000-000000000000"

# JSON-RPC 2.0 标准错误码
_JSONRPC_METHOD_NOT_FOUND = -32601

_PLUGIN_JSON_PATH = Path(__file__).resolve().parent / ".qoder-plugin" / "plugin.json"


def _plugin_version() -> str:
    """从 plugin.json 读取版本号供 initialize 响应使用；缺失或非法时回落 0.0.0。"""
    try:
        data = json.loads(_PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
        version = data.get("version", "")
        return version if isinstance(version, str) and version else "0.0.0"
    except (OSError, ValueError):
        return "0.0.0"


def _is_stale_agent_session(started_at: object, now: datetime) -> bool:
    """时间戳缺失或无法解析时视为过期，保证清理逻辑仍能执行。"""
    if not isinstance(started_at, str):
        return True
    try:
        parsed = datetime.fromisoformat(started_at)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed >= STALE_SESSION_MAX_AGE


# -- 异常与辅助函数 -----------------------------------------------------------


class ReplayRejected(Exception):
    """只允许传入固定的、不含敏感信息的拒绝原因。"""


class WriteUnconfirmedError(Exception):
    """响应中缺少可用的候选确认信息，写入结果无法确认。"""


def _safe_error(exc: Exception) -> str:
    """把异常转成固定的、不含敏感信息的安全文案（写回 Agent 响应）。"""
    if isinstance(exc, WriteUnconfirmedError):
        return "API acknowledgement missing or invalid"
    if isinstance(exc, ReplayRejected):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if detail:
                return f"API error {exc.response.status_code}: {detail}"
        except (ValueError, KeyError):
            pass
        return f"API error {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "Connection failed"
    return f"Operation failed ({type(exc).__name__})"


def _is_client_rejection(exc: Exception) -> bool:
    """API 明确拒绝载荷（4xx 且非 429 限流）时为 True。"""
    return isinstance(exc, ReplayRejected) or (
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
        and exc.response.status_code != 429
    )


def _classify_memory_type(content: str) -> str:
    """用配置的类型分类器推断记忆类型，无法推断时回落 'fact'。"""
    if infer_memory_type is not None:
        return infer_memory_type(content)
    return "fact"


def _validate_string_fields(
    data: dict[str, Any],
    validators: dict[str, Callable[[str], Any]],
) -> dict[str, Any] | None:
    """校验指定字段是字符串且通过对应验证器。

    首个失败即返回错误 dict；全部通过返回 None。
    """
    for field, validate in validators.items():
        value = data.get(field)
        if value is not None:
            if not isinstance(value, str):
                return {"error": f"{field} 必须是字符串"}
            try:
                validate(value)
            except ValueError as exc:
                return {"error": str(exc)}
    return None


def _security_error(content: str) -> dict[str, Any] | None:
    if check_injection is not None and check_injection(content.strip()):
        return {
            "error": "内容包含可疑的指令注入模式，已被拦截。请检查内容是否安全。",
            "security_flag": "suspicious_content",
        }
    return None


def _make_write_id(content: str, prefix: str = "ms") -> str:
    """从内容生成确定性的 client_write_id。

    取 SHA-256 前 16 个十六进制字符：相同内容重试得到相同幂等键，
    由服务端/outbox 去重，避免崩溃恢复后的重复提交。
    """
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


_SAVE_ISSUE_KEYS = frozenset(("error", "outbox_warning", "outbox_error"))


def _save_result_has_issues(result: dict[str, Any]) -> bool:
    """memory_save 结果包含 error/warning 标记时为 True。"""
    return bool(_SAVE_ISSUE_KEYS & result.keys())


# -- 抽取子模块的向后兼容别名 --------------------------------------------------
# 测试通过在 mcp_server 模块上 monkeypatch 这些名字来替换行为。以下划线为前缀的
# 别名是本文件内部实际使用的引用，monkeypatch mcp_server._X 即可替换调用目标。
#
# 信号引擎（事件分析）别名：
#   _extract_memories_from_events, _summarize_notes_by_type,
#   _build_event_analysis_report  （见上方 import）
#
# 传输层别名：
#   _stdin_reader, _write_stdout, _get_git_info  （见上方 import）
#
# 供测试 monkeypatch 的再导出常量：
#   MAX_MESSAGE_BYTES, SESSION_INIT_TIMEOUT  （见上方 import）


# ---------------------------------------------------------------------------
# Agent 会话生命周期
# ---------------------------------------------------------------------------


class AgentSession:
    """跟踪当前 agent session，用于会话监控与笔记采集。"""

    def __init__(self, client: CwikiClient) -> None:
        self.client = client
        self.session_id: str | None = None
        self.workspace: str | None = None
        self.created = False

    async def create(self, task: str | None = None, workspace_id: str | None = None) -> None:
        if self.created:
            return
        workspace = workspace_id or DEFAULT_WORKSPACE
        repository, branch = await asyncio.to_thread(_get_git_info)
        result = await self.client.create_agent_session(
            workspace_id=workspace,
            agent="qoder",
            repository=repository,
            branch=branch,
            task=task,
        )
        if result and result.get("id"):
            self.created = True
            self.session_id = result["id"]
            self.workspace = workspace
            self.client.agent_session_id = self.session_id
            self.client.event_session_id = result.get("event_session_id")
            logger.info(
                "Created agent session: %s (event_session: %s, workspace: %s, task: %s)",
                self.session_id,
                self.client.event_session_id,
                workspace,
                task,
            )

    async def complete(self, outcome: str = "unknown") -> None:
        if self.session_id:
            await self.client.complete_agent_session(self.session_id, outcome)
            logger.info("Completed agent session: %s", self.session_id)
            self.session_id = None
            self.workspace = None
            self.client.agent_session_id = None
            self.client.event_session_id = None

    def reset(self) -> None:
        self.created = False
        self.session_id = None
        self.workspace = None
        self.client.agent_session_id = None
        self.client.event_session_id = None

    async def auto_group_notes(self) -> None:
        """关停时把未整理笔记汇总为单条摘要笔记，便于下次 checkpoint 处理。"""
        if not self.session_id:
            return
        pending = await self.client.list_session_notes(
            session_id=self.session_id,
            formalized=False,
            limit=100,
        )
        if len(pending) < MIN_NOTES_FOR_AUTO_GROUP:
            return
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for note in pending:
            grouped[note.get("signal_type", "other")].append(note)
        lines = [f"共 {len(pending)} 条未整理笔记："]
        for stype, notes in grouped.items():
            lines.append(f"- {stype}: {len(notes)} 条")
            for n in notes[:3]:
                lines.append(f"  · {n.get('content', '')[:60]}")
        summary = "\n".join(lines)
        await self.client.create_session_note(
            session_id=self.session_id,
            workspace_id=self.workspace or DEFAULT_WORKSPACE,
            content=summary,
            signal_type=AUTO_GROUP_SIGNAL_TYPE,
        )
        logger.info("Auto-grouped %d unformalized notes", len(pending))


# ---------------------------------------------------------------------------
# MCP JSON-RPC 服务器（最小实现，不依赖外部 SDK）
# ---------------------------------------------------------------------------


class MCPServer:
    """最小 MCP 服务器：stdio 上的 JSON-RPC 2.0。

    仅实现 MCP 2024-11-05 所需的方法子集（initialize / tools/list /
    tools/call / ping）；通知类消息（无 id）不回响应。
    """

    # 需要统一解析 workspace 的工具；memory_search 不在其中——其省略 workspace
    # 时须跨全部工作区搜索（见 _handle_memory_search 内的说明）
    _WORKSPACE_TOOLS: frozenset[str] = frozenset(
        {
            "memory_checkpoint",
            "memory_export",
            "memory_import",
            "memory_review_due",
            "memory_review_submit",
            "memory_review_stats",
        }
    )

    # 工具注册表：MCP 工具名 → 处理器方法名；tools/list 由 build_tool_definitions 提供
    _HANDLER_NAMES: ClassVar[dict[str, str]] = {
        "memory_search": "_handle_memory_search",
        "memory_save": "_handle_memory_save",
        "memory_status": "_handle_memory_status",
        "memory_types": "_handle_memory_types",
        "memory_history": "_handle_memory_history",
        "memory_relations": "_handle_memory_relations",
        "memory_update": "_handle_memory_update",
        "memory_retry_failed": "_handle_memory_retry_failed",
        "memory_checkpoint": "_handle_memory_checkpoint",
        "memory_export": "_handle_memory_export",
        "memory_import": "_handle_memory_import",
        "memory_review_due": "_handle_memory_review_due",
        "memory_review_submit": "_handle_memory_review_submit",
        "memory_review_stats": "_handle_memory_review_stats",
    }

    def __init__(self, client: CwikiClient):
        self.client = client
        self.tools = build_tool_definitions()
        self.outbox = WriteAheadOutbox()
        self._config_stamp = self._config_disk_stamp()
        self._config_error: str | None = None
        self.session_workspace: str | None = None
        self._drain_task: asyncio.Task[None] | None = None

    @staticmethod
    def _config_disk_stamp() -> tuple[str, int | None]:
        path = domain_config.CONFIG_PATH
        try:
            return str(path), path.stat().st_mtime_ns
        except OSError:
            return str(path), None

    def _refresh_config(self) -> None:
        stamp = self._config_disk_stamp()
        if stamp != self._config_stamp:
            self._config_stamp = stamp
            try:
                domain_config.reload_yaml_config()
                settings.reload()
                self._config_error = None
            except Exception as exc:
                self._config_error = _safe_error(exc)
                logger.warning("Config refresh failed: %s", self._config_error)

    # -- tool handlers ------------------------------------------------------

    def _outbox_log(
        self,
        workspace_id: str,
        tool: str,
        arguments: dict[str, Any],
        client_write_id: str,
    ) -> dict[str, Any] | None:
        return self.outbox.log_pending(workspace_id, tool, arguments, client_write_id)

    def _outbox_done(self, workspace_id: str, entry_id: str) -> str | None:
        try:
            self.outbox.mark_success(workspace_id, entry_id)
        except Exception as exc:
            logger.warning("Acknowledged write cleanup failed: %s", _safe_error(exc))
            return "API 已确认，但本地 outbox 清理失败；残留条目使用原写入标识重试。"
        return None

    def _outbox_fail(self, workspace_id: str, entry_id: str) -> None:
        self.outbox.mark_failed(workspace_id, entry_id)

    def _outbox_summary(self, *, status_tool: bool = False) -> dict[str, Any]:
        counts = dict.fromkeys(("pending", "failed", "exhausted", "rejected"), 0)
        try:
            counts.update(self.outbox.count_all_by_state())
        except Exception as exc:
            logger.warning("Outbox counts unavailable: %s", _safe_error(exc))
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
            # 保留历史遗留的工具专用字段，兼容只认旧字段的宿主
            "outbox_pending": counts["failed"] + (0 if status_tool else counts["exhausted"]),
            "outbox_exhausted": counts["exhausted"],
        }

    def _outbox_on_error(self, workspace_id: str, entry_id: str, exc: Exception) -> None:
        """保留被拒绝的载荷供人工恢复；不落盘响应体或凭据。"""
        if not entry_id:
            return
        reason = _safe_error(exc)
        try:
            if _is_client_rejection(exc):
                self.outbox.mark_rejected(workspace_id, entry_id, reason)
            else:
                self.outbox.mark_failed(workspace_id, entry_id, reason)
        except Exception as disk_exc:
            # log_pending 已落盘原始载荷；这里只是状态更新，不产生新写入
            logger.warning("Outbox failure state update failed: %s", _safe_error(disk_exc))

    async def _submit_write(
        self, tool: str, args: dict[str, Any], write_id: str, entry: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """提交已冻结的 save/checkpoint 载荷；workspace 在写前日志之后才解析。"""
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
                else _classify_memory_type(content)
            )
            args = {**args, "inferred_type": memory_type}
            if entry:
                self.outbox.update_entry(entry["workspace_id"], entry["id"], {"arguments": args})
        workspace = (
            args.get("workspace_id")
            or (entry or {}).get("workspace_id")
            or self.session_workspace
            or DEFAULT_WORKSPACE
        )
        kwargs = {"source": "memory_save"} if tool == "memory_save" else {}
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
        return response

    async def _outbox_submit(
        self,
        tool: str,
        args: dict[str, Any],
        workspace_id: str,
        write_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, Exception | None]:
        """写 outbox → 提交 → 返回 (response, entry, error)。

        汇总 memory_save 与 memory_checkpoint 共用的
        outbox_log + _submit_write + _outbox_on_error 流程。
        """
        frozen = dict(args)
        entry = self._outbox_log(workspace_id, tool, frozen, write_id)
        try:
            response = await self._submit_write(tool, frozen, write_id, entry)
            return response, entry, None
        except Exception as exc:
            if entry:
                self._outbox_on_error(workspace_id, entry["id"], exc)
            return None, entry, exc

    async def _replay_entry(
        self, workspace_id: str, write: dict[str, Any]
    ) -> dict[str, Any] | None:
        """启动清账、自动重试与手动重试共用的唯一重放路径。"""
        try:
            if write.get("tool") not in ("memory_save", "memory_checkpoint"):
                raise ReplayRejected("Unsupported outbox tool")
            args = write["arguments"]
            content = args.get("wrapped_content")
            if _security_error(content if content is not None else args.get("content", "")):
                raise ReplayRejected("Suspicious content blocked")
            write_id = write.get("client_write_id") or _make_write_id(
                args.get("content", ""),
                prefix="cp" if write["tool"] == "memory_checkpoint" else "ms",
            )
            response = await self._submit_write(write["tool"], args, write_id, write)
            warning = self._outbox_done(workspace_id, write["id"])
            if warning:
                return {
                    "entry_id": write["id"],
                    "error": warning,
                    "delivery": "confirmed",
                    "candidate_id": response["candidate"]["id"],
                }
            return None
        except Exception as exc:
            self._outbox_on_error(workspace_id, write["id"], exc)
            reason = _safe_error(exc)
            logger.warning("Outbox replay failed: %s", reason)
            return {"entry_id": write["id"], "error": reason}

    def _auto_retry_allowed(self, workspace_id: str, write: dict[str, Any]) -> bool:
        if write.get("state", "pending") not in ("pending", "failed"):
            return False
        if write.get("attempts", 0) >= MAX_AUTO_RETRY_ATTEMPTS:
            self.outbox.mark_exhausted(workspace_id, write["id"])
            return False
        return True

    async def _try_auto_retry_one(self, *, respect_backoff: bool = False) -> None:
        """至多重放一条可重试条目；respect_backoff 时按指数退避跳过未到期项。"""
        for workspace_id, entries in self.outbox.load_retryable().items():
            for write in entries:
                if not self._auto_retry_allowed(workspace_id, write):
                    continue
                if respect_backoff and write.get("last_error_at"):
                    try:
                        last_error = datetime.fromisoformat(write["last_error_at"])
                        delay = AUTO_RETRY_INTERVAL * 2 ** max(write.get("attempts", 1) - 1, 0)
                        if (datetime.now(UTC) - last_error).total_seconds() < delay:
                            continue
                    except (ValueError, TypeError):
                        pass
                await self._replay_entry(workspace_id, write)
                return

    async def _drain_outbox(self) -> None:
        """只遍历一次启动时的快照；绝不清理 exhausted 条目的原文。"""
        reset = self.outbox.reset_all_exhausted()
        if reset:
            logger.info("Reset %d exhausted outbox entries for retry", reset)
        total = 0
        succeeded = 0
        failed = 0
        for workspace_id, entries in self.outbox.load_retryable().items():
            for write in entries:
                if not self._auto_retry_allowed(workspace_id, write):
                    continue
                total += 1
                result = await self._replay_entry(workspace_id, write)
                if result is None or result.get("delivery") == "confirmed":
                    succeeded += 1
                else:
                    failed += 1
                if total > 0:
                    await asyncio.sleep(DRAIN_ENTRY_INTERVAL)
        if total > 0:
            logger.info(
                "Outbox drain complete: %d total, %d succeeded, %d failed",
                total,
                succeeded,
                failed,
            )

    def _start_background_drain(self) -> None:
        """后台启动清账，不阻塞首个工具调用。

        若在 notifications/initialized 中同步清账，API 不可用时会卡住整个会话；
        重放靠 client_write_id 幂等，并发执行也安全。
        """
        if self._drain_task is not None and not self._drain_task.done():
            return
        self._drain_task = asyncio.create_task(self._background_drain())

    async def _background_drain(self) -> None:
        try:
            await self._drain_outbox()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Background outbox drain failed: %s", _safe_error(exc))

    # -- 各工具处理器（自 _handle_tool 抽出）-----------------------------------

    async def _search_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 10)
        max_tokens = arguments.get("max_tokens", 5000)
        result = await self.client.get_context(
            query=arguments["keyword"],
            workspace_id=arguments["workspace_id"],
            project=arguments.get("project"),
            max_items=limit,
            max_tokens=max_tokens,
        )
        hints: list[str] = []
        items = result.get("items", [])
        if arguments.get("keyword"):
            gap_detection_on = (
                parasitic_evolution_config is not None
                and parasitic_evolution_config.memory_gap_detection_enabled
            )
            if gap_detection_on and detect_memory_gap is not None:
                gap = detect_memory_gap(arguments["keyword"], items)
                if gap:
                    hints.append(f"{gap['message']}。{gap['suggestion']}")
            elif not items:
                hints.append(
                    f"记忆缺口：'{arguments['keyword']}' 无匹配记忆，"
                    "如掌握相关记忆请调用 memory_save 补充。"
                )
        if hints:
            result["_hints"] = hints
        return result

    async def _handle_memory_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not arguments.get("keyword"):
            arguments["keyword"] = arguments.pop("query", None)
        arguments.pop("query", None)
        curated = arguments.get("curated", False)
        if not isinstance(curated, bool):
            return {"error": "curated 必须是布尔值"}
        if curated:
            limit = arguments.get("limit", 10)
            max_tokens = arguments.get("max_tokens", 5000)
            if type(limit) is not int or not 1 <= limit <= 50:
                return {"error": "curated=true 时 limit 必须是 1–50 的整数"}
            if type(max_tokens) is not int or not 100 <= max_tokens <= 20000:
                return {"error": "max_tokens 必须是 100–20000 的整数"}
        else:
            limit = arguments.get("limit", 10)
            if type(limit) is not int or not 1 <= limit <= 100:
                return {"error": "limit 必须是 1–100 的整数"}
        if not arguments.get("keyword"):
            return {"error": "keyword 或 query 必须提供其一"}
        # memory_search 未纳入 _WORKSPACE_TOOLS：省略 workspace 时 hybrid/semantic
        # 跨全部工作区搜索；curated 的上下文组装仍按工作区执行，省略回落默认工作区
        workspace = arguments.get("workspace_name") or arguments.get("workspace_id")
        if curated:
            fallback = workspace or DEFAULT_WORKSPACE
            arguments["workspace_id"] = fallback
            arguments["workspace_name"] = fallback
            return await self._search_context(arguments)
        mode = arguments.get("mode", "hybrid")
        if mode == "semantic":
            return await self.client.recall(
                query=arguments["keyword"],
                workspace_id=workspace,
                limit=arguments.get("limit", 10),
            )
        else:
            return await self.client.search(
                query=arguments["keyword"],
                workspace_id=workspace,
                filters=arguments.get("filters"),
                limit=arguments.get("limit", 10),
            )

    async def _handle_memory_save(self, arguments: dict[str, Any]) -> dict[str, Any]:
        title, content = arguments.get("title"), arguments.get("content")
        if not isinstance(content, str):
            return {"error": "content 为必填字符串"}
        if not isinstance(title, str) or not title.strip():
            return {"error": "title 为必填参数"}
        validation_error = _validate_string_fields(
            {"title": title, "content": content},
            {"title": validate_memory_title, "content": validate_memory_content},
        )
        if validation_error:
            return validation_error
        security_error = _security_error(content)
        if security_error:
            return security_error
        specified_type = arguments.get("type")
        if "type" in arguments and (
            not isinstance(specified_type, str) or specified_type not in TYPE_DEFINITIONS
        ):
            return {"error": "type 必须是受支持的记忆类型"}
        memory_type = specified_type or _classify_memory_type(content)
        if memory_type not in TYPE_DEFINITIONS:
            memory_type = "fact"
        workspace = (
            arguments.get("workspace_name")
            or arguments.get("workspace_id")
            or self.session_workspace
            or DEFAULT_WORKSPACE
        )
        if not isinstance(workspace, str):
            return {"error": "workspace_id 必须是字符串"}
        # 自动补齐缺失的 #memory/ 标签；type 与 workspace 的校验相互独立
        missing_tags = [
            tag for tag in (f"#memory/{memory_type}", f"#memory/{workspace}") if tag not in content
        ]
        if missing_tags:
            content = content + "\n\n" + " ".join(missing_tags)
        frozen = {
            "title": title,
            "content": content,
            "type": memory_type,
            "workspace_id": workspace,
        }
        write_id = _make_write_id(content)
        response, entry, exc = await self._outbox_submit("memory_save", frozen, workspace, write_id)
        if exc is not None:
            rejected = _is_client_rejection(exc)
            return {
                "error": _safe_error(exc),
                "cached": entry is not None,
                "delivery": "rejected" if rejected else "unconfirmed",
                "message": (
                    "写入被拒绝，原文已保留；修复原因后可手动重试"
                    if rejected and entry
                    else "写入失败，已缓存到本地"
                    if entry
                    else "写入失败且未缓存，请在恢复后重新提交原始内容"
                ),
                "hint": "memory_retry_failed 可手动重试；rejected 不自动重试",
                **self._outbox_summary(),
            }
        assert response is not None
        similar_items = response.get("similar_items", [])
        result = {
            "status": "created",
            "candidate_id": response.get("candidate", {}).get("id"),
            "title": title,
            "inferred_type": memory_type,
            "message": "已按原文提交，等待人工审核",
            "similar_memories": similar_items,
        }
        if similar_items:
            result["hint"] = (
                response.get("hint")
                or "发现相似记忆，请核对完整来源；修正已有记忆可使用 memory_update。"
            )
        result["delivery"] = "confirmed"
        warning = self._outbox_done(workspace, entry["id"]) if entry else None
        if warning:
            result["outbox_warning"] = warning
        result.update(self._outbox_summary())
        return result

    async def _handle_memory_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self._refresh_config()
        try:
            workspace = (
                arguments.get("workspace_name")
                or arguments.get("workspace_id")
                or DEFAULT_WORKSPACE
            )
            result = await self.client.get_memory_status(workspace_id=workspace)
        except Exception as exc:
            result = {"error": _safe_error(exc)}
        result.update(self._outbox_summary(status_tool=True))
        result["effective_config"] = {
            "title_max_length": settings.memory_title_max_length,
            "config_file": str(domain_config.CONFIG_PATH.resolve()),
            "config_mtime_ns": self._config_stamp[1],
            "max_message_bytes": MAX_MESSAGE_BYTES,
        }
        if self._config_error:
            result["config_error"] = self._config_error
        return result

    async def _handle_memory_types(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested_type = arguments.get("type")
        types = []
        for key, tpl in TYPE_DEFINITIONS.items():
            if requested_type and key != requested_type:
                continue
            types.append(
                {
                    "type": key,
                    "name": tpl["name"],
                    "description": tpl.get("description"),
                }
            )
        return {"types": types}

    async def _handle_memory_history(self, arguments: dict[str, Any]) -> dict[str, Any] | list[Any]:
        view = arguments.get("view", "lifecycle")
        if view == "content":
            limit = arguments.get("limit", 10)
            if type(limit) is not int or not 1 <= limit <= 50:
                return {"error": "limit 必须是 1–50 的整数"}
            return await self.client.get_memory_versions(
                memory_id=arguments["memory_id"],
                limit=limit,
            )
        if view != "lifecycle":
            return {"error": "view 必须是 lifecycle 或 content"}
        return await self.client.get_memory_lifecycle(
            memory_id=arguments["memory_id"],
        )

    async def _handle_memory_relations(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.client.get_memory_relations(
            memory_id=arguments["memory_id"],
            depth=arguments.get("depth", 1),
        )

    async def _handle_memory_update(self, arguments: dict[str, Any]) -> dict[str, Any]:
        validation_error = _validate_string_fields(
            arguments,
            {"title": validate_memory_title, "content": validate_memory_content},
        )
        if validation_error:
            return validation_error
        if arguments.get("content") is not None:
            security_error = _security_error(arguments["content"])
            if security_error:
                return security_error
        version_kwargs = {}
        if "expected_version" in arguments:
            version = arguments["expected_version"]
            if type(version) is not int or version < 1:
                return {"error": "expected_version 必须是大于等于 1 的整数"}
            version_kwargs["expected_version"] = version
        try:
            return await self.client.update_memory(
                memory_id=arguments["memory_id"],
                title=arguments.get("title"),
                content=arguments.get("content"),
                confidence=arguments.get("confidence"),
                importance=arguments.get("importance"),
                reason=arguments.get("reason"),
                is_permanent=arguments.get("is_permanent"),
                permanent_reason=arguments.get("permanent_reason"),
                **version_kwargs,
            )
        except MemoryUpdateUncertainError:
            return {
                "error": "更新结果不确定，可能已生效；未自动重试。",
                "delivery": "unconfirmed",
                "hint": "请先回读当前记忆正文和版本，核对结果后再决定是否重试。",
            }

    async def _handle_memory_retry_failed(self, arguments: dict[str, Any]) -> dict[str, Any]:
        retried = 0
        errors = []
        for workspace, entries in self.outbox.load_all_workspaces().items():
            for write in entries:
                state = write.get("state")
                if state not in ("pending", "failed", "exhausted", "rejected"):
                    continue
                if state in ("exhausted", "rejected"):
                    self.outbox.reset_entry(workspace, write["id"])
                error = await self._replay_entry(workspace, write)
                if error:
                    errors.append(error)
                if not error or error.get("delivery") == "confirmed":
                    retried += 1
        result = {
            "status": "partial" if errors else "ok",
            "retried": retried,
            **self._outbox_summary(),
        }
        if errors:
            result.update(error="部分写入未成功，请查看 errors 和 outbox_counts", errors=errors)
        return result

    async def _checkpoint_fetch_events(
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
            events = await self.client.get_raw_events(
                workspace_id=workspace_id,
                session_id=event_session_id,
                since_minutes=since_minutes,
                limit=CHECKPOINT_FETCH_LIMIT,
            )
            return events, None
        except Exception as exc:
            logger.warning("Failed to fetch events for checkpoint: %s", _safe_error(exc))
            return [], {"stage": "events", "error": _safe_error(exc)}

    async def _checkpoint_fetch_notes(
        self,
        session_id: str,
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """为 checkpoint 拉取会话笔记。返回 (notes, error_dict|None)。"""
        try:
            notes = await self.client.list_session_notes(
                session_id=session_id,
                limit=CHECKPOINT_FETCH_LIMIT,
                workspace_id=workspace_id,
            )
            return notes, None
        except Exception as exc:
            logger.warning("Failed to fetch session notes for checkpoint: %s", _safe_error(exc))
            return [], {"stage": "notes", "error": _safe_error(exc)}

    async def _checkpoint_submit_candidates(
        self,
        candidates: list[dict[str, Any]],
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """经 outbox 提交校验后的候选。返回 (submitted, errors)。"""
        submitted: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for candidate in candidates:
            write_id = _make_write_id(candidate["content"], prefix="cp")
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
                        "error": _safe_error(exc),
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
                    await self.client.formalize_session_note(str(note_id))
                except Exception as formalize_exc:
                    errors.append(
                        {
                            "stage": "formalize",
                            "error": _safe_error(formalize_exc),
                            "note_id": str(note_id),
                        }
                    )
            if cp_outbox_entry:
                warning = self._outbox_done(workspace_id, cp_outbox_entry["id"])
                if warning:
                    logger.warning("Checkpoint outbox cleanup: %s", warning)
        return submitted, errors

    @staticmethod
    def _checkpoint_validate_candidates(
        candidates: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """校验并过滤候选，失败项追加到 errors。"""
        safe: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                validate_memory_title(candidate["title"])
                validate_memory_content(candidate["content"])
            except ValueError as exc:
                errors.append({"stage": "validation", "error": str(exc)})
                continue
            security_error = _security_error(candidate["content"])
            if security_error:
                errors.append({"stage": "security", **security_error})
            else:
                safe.append(candidate)
        return safe

    def _compute_checkpoint_window(
        self,
        session_id: str,
        workspace_id: str,
        event_session_id: str | None,
        collection_started_at: datetime,
    ) -> tuple[int, bool, str | None]:
        """计算 checkpoint 的增量时间窗口。

        返回 (since_minutes, window_truncated, last_checkpoint_iso)。
        """
        last_checkpoint = self.outbox.get_last_checkpoint(
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

    async def _build_checkpoint_result(
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
        from adapters.qoder.signal_engine import CONTENT_PREVIEW_LENGTH

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
            summaries = _summarize_notes_by_type(all_notes)
            result["notes_summary"] = {
                "total_unformalized": len(unformalized),
                "group_summaries": summaries,
                "action": "摘要仅用于定位信号；用 memory_save 整理时回到原始上下文，保留完整细节，不要仅复述摘要",
            }

        if events:
            worker_candidates = []
            try:
                worker_candidates = await self.client.get_workers_candidates(
                    workspace_id=workspace_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to fetch worker candidates for checkpoint: %s", _safe_error(exc)
                )
                errors.append({"stage": "worker_candidates", "error": _safe_error(exc)})
            result["event_analysis"] = _build_event_analysis_report(
                events,
                worker_candidates,
            )

        return result

    async def _finalize_checkpoint(
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
                self.outbox.record_checkpoint(
                    session_id,
                    workspace_id,
                    collection_started_at.isoformat(),
                    event_session_id=event_session_id,
                )
            except Exception as exc:
                errors.append({"stage": "watermark", "error": _safe_error(exc)})
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

    async def _handle_memory_checkpoint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        session_id = self.client.agent_session_id
        workspace_id = arguments["workspace_id"]
        trigger_reason = arguments.get("trigger_reason", "manual")
        dry_run = arguments.get("dry_run", False)

        warnings: list[str] = []
        if not session_id:
            warnings.append(
                "无活跃 agent session，检查点可能不完整；"
                "建议使用 memory_save 直接提交，或确保有活跃会话后再调用。"
            )
            session_id = NULL_SESSION_ID

        event_session_id = arguments.get("event_session_id") or self.client.event_session_id
        collection_started_at = datetime.now(UTC)
        since_minutes, window_truncated, last_checkpoint = self._compute_checkpoint_window(
            session_id, workspace_id, event_session_id, collection_started_at
        )

        input_status = {"events": "unavailable", "notes": "unavailable"}
        errors: list[dict[str, Any]] = []

        events, event_err = await self._checkpoint_fetch_events(
            workspace_id, event_session_id, since_minutes
        )
        if event_err:
            errors.append(event_err)
        else:
            input_status["events"] = "available" if events else "empty"

        all_notes, notes_err = await self._checkpoint_fetch_notes(session_id, workspace_id)
        if notes_err:
            errors.append(notes_err)
        else:
            input_status["notes"] = "available" if all_notes else "empty"

        limit_reached = (
            len(events) >= CHECKPOINT_FETCH_LIMIT or len(all_notes) >= CHECKPOINT_FETCH_LIMIT
        )
        if limit_reached or window_truncated:
            errors.append(
                {"stage": "window", "error": "输入达到条数或时间上限，覆盖范围可能不完整"}
            )

        candidates = _extract_memories_from_events(events, all_notes, trigger_reason)
        candidates = self._checkpoint_validate_candidates(candidates, errors)

        submitted: list[dict[str, Any]] = []
        if not dry_run:
            submitted, submit_errors = await self._checkpoint_submit_candidates(
                candidates, workspace_id
            )
            errors.extend(submit_errors)

        result = await self._build_checkpoint_result(
            dry_run=dry_run,
            trigger_reason=trigger_reason,
            input_status=input_status,
            since_minutes=since_minutes,
            window_truncated=window_truncated,
            collection_started_at=collection_started_at,
            last_checkpoint=last_checkpoint,
            events=events,
            all_notes=all_notes,
            candidates=candidates,
            submitted=submitted,
            workspace_id=workspace_id,
            errors=errors,
        )
        return await self._finalize_checkpoint(
            result,
            session_id=session_id,
            workspace_id=workspace_id,
            event_session_id=event_session_id,
            collection_started_at=collection_started_at,
            input_status=input_status,
            submitted=submitted,
            dry_run=dry_run,
            errors=errors,
            warnings=warnings,
        )

    async def _handle_memory_export(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or DEFAULT_WORKSPACE
        entities = arguments.get("entities")
        data = await self.client.export_data(workspace_id, fmt="json", entities=entities)
        counts = {
            key: len(data[key])
            for key in ("memories", "candidates", "notes", "relations", "schedules")
            if key in data
        }
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "exported_at": data.get("exported_at"),
            "counts": counts,
            "data": data,
        }

    async def _handle_memory_import(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or DEFAULT_WORKSPACE
        strategy = arguments.get("strategy", "skip")
        import_data_payload = arguments.get("data", {})
        import_result = await self.client.import_data(import_data_payload, workspace_id, strategy)
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "strategy": strategy,
            **import_result,
        }

    # ── 复习工具 handlers ─────────────────────────────────────────────────────

    async def _handle_memory_review_due(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or DEFAULT_WORKSPACE
        limit = arguments.get("limit", 20)
        if type(limit) is not int or not 1 <= limit <= 100:
            return {"error": "limit 必须是 1–100 的整数"}
        items = await self.client.get_due_reviews(workspace_id=workspace_id, limit=limit)
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "count": len(items),
            "items": items,
        }

    async def _handle_memory_review_submit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = arguments.get("memory_id")
        quality = arguments.get("quality")
        if not isinstance(memory_id, str):
            return {"error": "memory_id 必须是字符串"}
        if type(quality) is not int or not 0 <= quality <= 5:
            return {"error": "quality 必须是 0–5 的整数"}
        workspace_id = arguments.get("workspace_name") or DEFAULT_WORKSPACE
        result = await self.client.submit_review(
            memory_id=memory_id, quality=quality, workspace_id=workspace_id
        )
        return {
            "status": "ok",
            "memory_id": memory_id,
            "quality": quality,
            **result,
        }

    async def _handle_memory_review_stats(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or DEFAULT_WORKSPACE
        stats = await self.client.get_review_stats(workspace_id=workspace_id)
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            **stats,
        }

    async def _handle_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any] | list[Any]:
        arguments = dict(arguments)
        try:
            if name in self._WORKSPACE_TOOLS:
                # 统一解析 workspace：文档与 tool schema 统一使用 workspace_name；
                # 同时接受 workspace_id 作兜底（未经 schema 校验的调用可能沿旧键名），
                # 双键都写入，使各 handler 无论读取哪个键都能拿到值；缺失时回落默认工作区
                workspace_arg = (
                    arguments.get("workspace_name")
                    or arguments.get("workspace_id")
                    or DEFAULT_WORKSPACE
                )
                arguments["workspace_id"] = workspace_arg
                arguments["workspace_name"] = workspace_arg

            handler_name = self._HANDLER_NAMES.get(name)
            if handler_name is None:
                return {"error": f"Unknown tool: {name}"}
            handler = getattr(self, handler_name)

            result: dict[str, Any] | list[Any] = await handler(arguments)

            # 顺带重试的失败不得把已确认的 save 结果改写成失败响应
            if (
                name == "memory_save"
                and isinstance(result, dict)
                and not _save_result_has_issues(result)
            ):
                try:
                    await self._try_auto_retry_one()
                except Exception as exc:
                    logger.warning("Automatic retry unavailable: %s", _safe_error(exc))

            return result

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return {"error": _safe_error(exc)}
        except KeyError as exc:
            return {"error": f"Missing required parameter: {exc.args[0]!r}"}
        except Exception as exc:
            logger.error("Tool operation failed: %s", _safe_error(exc))
            return {"error": "Internal error", "detail": _safe_error(exc)}

    # -- JSON-RPC 分发 --------------------------------------------------------

    async def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """处理单条 JSON-RPC 2.0 消息并返回响应；通知类消息（无 id）返回 None。"""
        method = message.get("method")
        req_id = message.get("id")
        params = message.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "roots": {"listChanged": True}},
                    "serverInfo": {
                        "name": "cwiki",
                        "version": _plugin_version(),
                    },
                },
            }

        if method == "notifications/initialized":
            self._start_background_drain()
            return None

        if method == "tools/list":
            self._refresh_config()
            self.tools = build_tool_definitions()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.tools},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            result = await self._handle_tool(tool_name, tool_args)

            is_error = isinstance(result, dict) and "error" in result
            content_text = json.dumps(result, ensure_ascii=False, indent=2)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": content_text,
                        }
                    ],
                    "isError": is_error,
                },
            }

        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        # 未知方法：带 id 的请求返回 Method not found；通知（无 id）静默忽略
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": _JSONRPC_METHOD_NOT_FOUND,
                    "message": f"Method not found: {method}",
                },
            }

        return None


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def run_server() -> None:
    """从 stdin 逐行读取 JSON-RPC 消息，向 stdout 写回响应。"""
    client = CwikiClient(API_BASE_URL, timeout=REQUEST_TIMEOUT)
    server = MCPServer(client)

    logger.info(
        "cwiki MCP server starting (api=%s, workspace=%s)",
        API_BASE_URL,
        DEFAULT_WORKSPACE,
    )

    reader = _stdin_reader()

    async def write_response(resp: dict[str, Any]) -> None:
        data = json.dumps(resp, ensure_ascii=False) + "\n"
        await _write_stdout(data.encode("utf-8"))

    session = AgentSession(client)

    async def _ensure_session(task: str, workspace: str | None) -> None:
        if session.created:
            return
        try:
            await asyncio.wait_for(session.create(task, workspace), SESSION_INIT_TIMEOUT)
            server.session_workspace = session.workspace
        except Exception as exc:
            logger.warning("Session creation failed: %s", _safe_error(exc))

    async def _cleanup_previous_sessions() -> None:
        try:
            async with asyncio.timeout(SESSION_INIT_TIMEOUT):
                if session.session_id:
                    await session.complete("unknown")
                open_sessions = await client.list_open_agent_sessions(
                    workspace_id=DEFAULT_WORKSPACE,
                    agent="qoder",
                )
                now = datetime.now(UTC)
                for previous_session in open_sessions:
                    previous_id = previous_session.get("id")
                    if not previous_id:
                        continue
                    # 近期会话可能属于并行运行的其他 MCP 实例，只清理闲置超限的
                    if not _is_stale_agent_session(previous_session.get("started_at"), now):
                        continue
                    await client.complete_agent_session(previous_id, "unknown")
        except Exception as exc:
            logger.warning("Session cleanup incomplete: %s", _safe_error(exc))
        session.reset()

    _CONTINUE: dict[str, Any] = {}  # 哨兵对象：区别于任何真实消息与 None

    async def _read_message_line() -> dict[str, Any] | None:
        """读取、解析并校验一行 JSON-RPC 消息。

        返回解析后的消息 dict；``_CONTINUE`` 表示跳过继续，``None`` 表示退出循环。
        解析失败时直接向 stdout 写回错误响应。
        """
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=AUTO_RETRY_INTERVAL)
        except TimeoutError:
            await server._try_auto_retry_one(respect_backoff=True)
            return _CONTINUE
        except ValueError:
            # 超长行可能在换行符到达前就触及 readline 上限；不能无限等待剩余
            # 字节，返回安全错误并关闭传输。
            await write_response(OVERSIZE_ERROR)
            return None
        except OSError:
            logger.info("MCP stdin disconnected")
            return None
        if not line:
            return None
        if len(line) > MAX_MESSAGE_BYTES:
            await write_response(OVERSIZE_ERROR)
            return None
        if not line.strip():
            return _CONTINUE
        try:
            message = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            await write_response(PARSE_ERROR)
            return _CONTINUE
        if not isinstance(message, dict):
            await write_response(INVALID_REQUEST_ERROR)
            return _CONTINUE
        return message

    # SIGINT/SIGTERM 优雅退出
    shutting_down = False
    processing = True
    loop = asyncio.get_running_loop()
    server_task = asyncio.current_task()

    def cancel_server() -> None:
        nonlocal shutting_down
        if processing and not shutting_down:
            shutting_down = True
            logger.info("Received shutdown signal")
            if server_task is not None:
                server_task.cancel()

    def _signal_shutdown(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(cancel_server)

    previous_handlers = {
        sig: signal.signal(sig, _signal_shutdown) for sig in (signal.SIGINT, signal.SIGTERM)
    }

    # 逐行处理消息
    try:
        while True:
            if shutting_down:
                break
            try:
                message = await _read_message_line()
                if message is _CONTINUE:
                    continue
                if message is None:
                    break

                # 新 initialize 到来时，收尾上一个/孤儿会话
                if message.get("method") == "initialize":
                    await _cleanup_previous_sessions()

                params = message.get("params", {})
                is_tool_call = message.get("method") == "tools/call"
                if is_tool_call:
                    tool_name = params.get("name", "")
                    tool_args = params.get("arguments", {}) or {}
                    task = f"使用 {tool_name}" if tool_name else "MCP 工具调用"
                    await _ensure_session(task, tool_args.get("workspace_name"))

                response = await server.handle_message(message)
                if response is not None:
                    try:
                        await write_response(response)
                    except OSError:
                        logger.info("MCP stdout disconnected")
                        break

            except Exception as exc:
                logger.error("Error processing message: %s", _safe_error(exc))
                continue
    except asyncio.CancelledError:
        if not shutting_down:
            raise
    finally:
        processing = False
        drain_task = server._drain_task
        if drain_task is not None and not drain_task.done():
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError:
                pass
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        # 退出前收尾：先汇总未整理笔记，再结束 agent session
        try:
            await session.auto_group_notes()
        except Exception:
            logger.warning("Failed to auto-group notes on shutdown", exc_info=True)
        try:
            await session.complete("unknown")
        except Exception:
            logger.warning("Failed to complete agent session on shutdown", exc_info=True)

        await client.close()
        logger.info("cwiki MCP server shutting down")


def main() -> None:
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Shutting down on interrupt")
        sys.exit(0)


if __name__ == "__main__":
    main()
