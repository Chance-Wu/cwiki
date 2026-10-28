#!/usr/bin/env python3
"""cwiki MCP 服务器 —— stdio 传输（宿主无关核心）。

通过 cwiki API 提供记忆查询与提交类 MCP 工具。任何 MCP 宿主
（Qoder / Claude Code / Cursor / Codex / 自研 Agent）以
``python -m adapters.mcp`` 启动本进程，经 stdio 逐行 JSON-RPC 2.0 通信。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
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
from packages.domain.version import app_version

try:
    from packages.memory.content_security import check_injection
except ImportError:
    check_injection = None  # type: ignore[assignment]

try:
    from packages.memory.type_classifier import infer_memory_type
except ImportError:
    infer_memory_type = None  # type: ignore[assignment]


try:
    from packages.memory.memory_gap import detect_memory_gap
except ImportError:
    detect_memory_gap = None  # type: ignore[assignment]

try:
    from packages.domain.config import parasitic_evolution_config
except ImportError:
    parasitic_evolution_config = None  # type: ignore[assignment]

from adapters.hooks.profiles import clean_workspace_name
from adapters.mcp.checkpoint_manager import CHECKPOINT_FETCH_LIMIT, CheckpointManager
from adapters.mcp.client import CwikiClient, MemoryUpdateUncertainError
from adapters.mcp.local_index import STRONG_COVERAGE, build_local_context, search_local
from adapters.mcp.outbox import WriteAheadOutbox
from adapters.mcp.outbox_manager import OutboxManager, ReplayRejected, WriteUnconfirmedError

# -- 抽取出的子模块（signal_engine / transport 等纯逻辑已拆分，便于测试替换）--
from adapters.mcp.signal_engine import AUTO_GROUP_SIGNAL_TYPE
from adapters.mcp.signal_engine import (
    build_event_analysis_report as _build_event_analysis_report,
)
from adapters.mcp.signal_engine import (
    extract_memories_from_events as _extract_memories_from_events,
)
from adapters.mcp.signal_engine import (
    summarize_notes_by_type as _summarize_notes_by_type,
)
from adapters.mcp.tool_definitions import build_tool_definitions
from adapters.mcp.transport import (
    INVALID_REQUEST_ERROR,
    MAX_MESSAGE_BYTES,
    OVERSIZE_ERROR,
    PARSE_ERROR,
    SESSION_INIT_TIMEOUT,
)
from adapters.mcp.transport import (
    get_git_info as _get_git_info,
)
from adapters.mcp.transport import (
    stdin_reader as _stdin_reader,
)
from adapters.mcp.transport import (
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

# 宿主项目目录候选 env（按宿主声明顺序；通用宿主可自行声明 CWIKI_PROJECT_DIR）。
# 安装器在项目级 MCP 配置里写入 CWIKI_WORKSPACE 时，其优先级高于目录推导。
# 注：DSH 从不导出项目目录 env（实测只有 DSH_HOME/DSH_PROFILE/DSH_SESSION_ID
# 等），dsh 的归属靠安装器写入 CWIKI_WORKSPACE/CWIKI_WORKSPACE_DIR。
_PROJECT_DIR_ENV: tuple[str, ...] = (
    "CWIKI_WORKSPACE_DIR",
    "CWIKI_PROJECT_DIR",
    "QODER_PROJECT_DIR",
    "CLAUDE_PROJECT_DIR",
    "CURSOR_PROJECT_DIR",
)
# 合法工作区名校验
_VALID_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _derive_workspace() -> str:
    """推导宿主当前绑定的项目工作区。

    优先级：安装器显式写入的 CWIKI_WORKSPACE > 宿主项目目录 env > 进程 CWD。
    目录名清洗统一走 hooks.profiles.clean_workspace_name（三处同源）：拒绝宿主
    编码的 --path-- / C--Users-… 形态与 8 位哈希名，无法得到合法名时回落
    default，绝不产生垃圾工作区。
    """
    explicit = os.environ.get("CWIKI_WORKSPACE")
    if explicit and _VALID_WORKSPACE_RE.fullmatch(explicit):
        return explicit

    for env_name in _PROJECT_DIR_ENV:
        candidate = os.environ.get(env_name)
        if candidate:
            name = clean_workspace_name(candidate)
            if name:
                return name

    try:
        cwd = Path.cwd()
    except OSError:
        return DEFAULT_WORKSPACE
    # CWD 若是 cwiki 自身（API/适配器所在仓库）或 home，说明宿主未传项目目录，
    # 此时不应把 cwiki 项目当作用户项目——回落 default。
    if cwd == Path(__file__).resolve().parents[2] or cwd == Path.home():
        return DEFAULT_WORKSPACE
    return clean_workspace_name(str(cwd)) or DEFAULT_WORKSPACE


# 会话工作区：宿主绑定项目（由 _derive_workspace 推导），而非硬编码 default。
SESSION_WORKSPACE = _derive_workspace()

# ---- 运行时动态工作区：宿主 hook 实时告知的"当前项目" ----
# hook（UserPromptSubmit 等）带 cwd 时把目录名按宿主写入
# ~/.cwiki/state/current-workspace-<host>.json，MCP 每次工具调用优先读
# 自己宿主的文件——宿主切换项目后无需重启，且别的宿主在别的项目触发
# hook 不会污染本会话归属（旧版共享单文件存在跨宿主串区）。
_DYNAMIC_WS_FILE = (
    Path(os.environ.get("CWIKI_STATE_DIR", "~/.cwiki/state")).expanduser()
    / "current-workspace.json"
)
_DYNAMIC_WS_TTL_SECONDS = 30 * 60  # 30 分钟未更新视为过期，回落静态推导


def _dynamic_workspace() -> str | None:
    """读取本宿主最近写入的动态工作区（带 TTL 与宿主隔离）。

    由 hook 在每次 prompt/会话事件时刷新；MCP 是长驻进程，静态 env 只反映
    启动时刻的项目，动态文件才反映"Agent 现在在哪个项目"。
    优先读 per-host 文件；旧版共享 current-workspace.json 仅当 host 字段
    匹配本宿主时兜底，兼容尚未重启的旧 hook。
    """
    per_host = _DYNAMIC_WS_FILE.with_name(f"current-workspace-{HOST_ID}.json")
    now = time.time()
    for path in (per_host, _DYNAMIC_WS_FILE):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        name = payload.get("workspace")
        ts = payload.get("updated_at", 0)
        if not isinstance(name, str) or not name or not _VALID_WORKSPACE_RE.fullmatch(name):
            continue
        if path == _DYNAMIC_WS_FILE and payload.get("host") not in (None, HOST_ID):
            continue
        try:
            if now - float(ts) > _DYNAMIC_WS_TTL_SECONDS:
                continue
        except (TypeError, ValueError):
            continue
        return name
    return None


def current_workspace() -> str:
    """Agent 当前绑定的工作区（每次工具调用实时解析）。

    优先级：宿主 hook 刚写入的动态注册表（含 TTL）
          > 会话级 roots 工作区（MCPServer 实例属性，见 current_workspace_for）
          > 静态推导（安装期 env/CWD）。
    """
    return _dynamic_workspace() or SESSION_WORKSPACE


def current_workspace_for(server: MCPServer) -> str:
    """带 server 实例信号的解析：hook 注册表 > roots > 静态。"""
    return _dynamic_workspace() or server.roots_workspace or SESSION_WORKSPACE


REQUEST_TIMEOUT = float(os.environ.get("CWIKI_TIMEOUT", "10.0"))
AUTO_RETRY_INTERVAL = 30.0
DEFAULT_SINCE_MINUTES = 60
MAX_WINDOW_MINUTES = 1440
MIN_WINDOW_MINUTES = 5
MAX_AUTO_RETRY_ATTEMPTS = 3
DRAIN_ENTRY_INTERVAL = 0.5
MIN_NOTES_FOR_AUTO_GROUP = 3
STALE_SESSION_MAX_AGE = timedelta(hours=24)
NULL_SESSION_ID = "00000000-0000-0000-0000-000000000000"

# 宿主标识：宿主可在 MCP env 里显式声明（CWIKI_HOST=claude|cursor|codex…）；
# 未声明时按启动模块名推断——adapters.mcp 视为 generic，旧 qoder shim 报 qoder。
HOST_ID = os.environ.get("CWIKI_HOST") or "generic"

# JSON-RPC 2.0 标准错误码
_JSONRPC_METHOD_NOT_FOUND = -32601

# plugin.json 是 Qoder 插件资产；它的 version 决定 Qoder 插件缓存路径
# （scripts/setup.py plugin_cache_dir），是「插件构建版本」而非「cwiki 包版本」，
# 因此与包版本解耦：serverInfo 优先报包版本，仅在元数据缺失时回落此文件。
_PLUGIN_JSON_PATH = Path(__file__).resolve().parents[1] / "qoder" / ".qoder-plugin" / "plugin.json"


def _plugin_version() -> str:
    """返回 initialize 响应 serverInfo 的版本号。

    权威源是 pyproject.toml 的 [project] version（经 importlib.metadata 读取），
    保证 MCP 握手版本与 /v1/health、/openapi.json 一致；元数据不可读时才回落
    读 plugin.json（Qoder 插件资产），两者都缺失回落 0.0.0。

    历史上 serverInfo 只读 plugin.json，而 health 用 APP_VERSION、openapi 用
    FastAPI(version=) 字面量，三个口径分别为 0.1.0 / 0.3.0 / 0.4.1，
    宿主排查「连的是哪个版本」时会得到互相矛盾的答案。
    """
    package_version = app_version()
    if package_version != "0.0.0":
        return package_version
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


def _safe_error(exc: Exception) -> str:
    """把异常转成固定的、不含敏感信息的安全文案（写回 Agent 响应）。"""
    if isinstance(exc, WriteUnconfirmedError):
        return "API acknowledgement missing or invalid"
    if isinstance(exc, ReplayRejected):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
            if isinstance(detail, dict):
                detail = detail.get("hint") or detail.get("reason") or detail.get("code")
            if detail:
                return f"API error {exc.response.status_code}: {detail}"
        except (ValueError, KeyError):
            pass
        return f"API error {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "Connection failed"
    return f"Operation failed ({type(exc).__name__})"


def _write_decision_payload(exc: Exception) -> dict[str, Any] | None:
    """从 API 4xx 响应中提取写入决策的结构化信息。"""
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    try:
        data = exc.response.json()
    except ValueError:
        return None
    payload = data.get("write_decision") if isinstance(data, dict) else None
    return payload if isinstance(payload, dict) else None


def _is_client_rejection(exc: Exception) -> bool:
    """API 明确拒绝载荷（4xx 且非 429 限流）时为 True。"""
    return isinstance(exc, ReplayRejected) or (
        isinstance(exc, httpx.HTTPStatusError)
        and 400 <= exc.response.status_code < 500
        and exc.response.status_code != 429
    )


def _api_unavailable(exc: httpx.HTTPError) -> bool:
    """连接级失败或 5xx 才允许读路径降级；4xx 是请求错误，必须原样返回。"""
    if isinstance(exc, httpx.RequestError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


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


def _make_write_id(
    content: str,
    prefix: str = "ms",
    *,
    title: str = "",
    memory_type: str = "",
    workspace: str = "",
) -> str:
    """从内容（及标题/类型/工作区）生成确定性的 client_write_id。

    取 SHA-256 前 16 个十六进制字符：相同输入重试得到相同幂等键，由服务端/
    outbox 去重。标题参与哈希——只改标题的重新提交不会再命中旧候选。
    未提供标题等字段时退化为纯内容哈希（checkpoint 等旧调用保持兼容）。
    """
    if title or memory_type or workspace:
        material = f"{title}\x1f{memory_type}\x1f{workspace}\x1f{content}"
    else:
        material = content
    digest = hashlib.sha256(material.encode()).hexdigest()[:16]
    return f"{prefix}:{digest}"


_SAVE_ISSUE_KEYS = frozenset(("error", "outbox_warning", "outbox_error"))

# 单条正文上限：避免一次工具调用接近 MCP 帧上限（8MB）被传输层拒绝，
# 同时保证工具响应不会灌爆宿主上下文
SAVE_CONTENT_MAX_BYTES = 256 * 1024
# 导入载荷上限：超过后引导改用 Web 控制台导入
IMPORT_PAYLOAD_MAX_BYTES = 2 * 1024 * 1024


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
        workspace = workspace_id or current_workspace()
        repository, branch = await asyncio.to_thread(_get_git_info)
        result = await self.client.create_agent_session(
            workspace_id=workspace,
            agent=HOST_ID,
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
            workspace_id=self.workspace or current_workspace(),
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
            "memory_feedback",
            "memory_forget",
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
        "memory_relation_create": "_handle_memory_relation_create",
        "memory_relation_delete": "_handle_memory_relation_delete",
        "memory_tags": "_handle_memory_tags",
        "memory_update": "_handle_memory_update",
        "memory_feedback": "_handle_memory_feedback",
        "memory_forget": "_handle_memory_forget",
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
        self.session_workspace: str | None = None
        # 宿主经 roots/list 声明的项目工作区（与 hook 注册表互补）
        self.roots_workspace: str | None = None
        self._outbox_manager = OutboxManager(
            client=client,
            outbox=self.outbox,
            workspace_resolver=lambda: self._resolved_workspace({}),
            classify_memory_type=_classify_memory_type,
            is_client_rejection=_is_client_rejection,
            safe_error=_safe_error,
        )
        self._checkpoint_manager = CheckpointManager(
            client=client,
            outbox=self.outbox,
            outbox_submit=self._outbox_submit,
            outbox_done=self._outbox_done,
            safe_error=_safe_error,
            make_write_id=_make_write_id,
            security_error=_security_error,
            summarize_notes_by_type=_summarize_notes_by_type,
            build_event_analysis_report=_build_event_analysis_report,
        )
        self._config_stamp = self._config_disk_stamp()
        self._config_error: str | None = None
        self._drain_task: asyncio.Task[None] | None = None

    def _resolved_workspace(self, arguments: dict[str, Any]) -> str:
        """本次调用的目标工作区：显式参数 > 实时归属 > 会话快照 > default。

        ``default`` 表示“归属未知”，不能覆盖实时归属或已记录的会话工作区；
        实时归属非 default 时同步会话快照，避免长驻进程沿用首次解析结果。
        """
        explicit = arguments.get("workspace_name") or arguments.get("workspace_id")
        if isinstance(explicit, str) and explicit:
            return explicit
        live = current_workspace_for(self)
        if live and live != DEFAULT_WORKSPACE:
            if self.session_workspace != live:
                logger.debug(
                    "Workspace attribution updated: %s -> %s", self.session_workspace, live
                )
                self.session_workspace = live
            return live
        if self.session_workspace and self.session_workspace != DEFAULT_WORKSPACE:
            return self.session_workspace
        return DEFAULT_WORKSPACE

    @property
    def outbox(self) -> WriteAheadOutbox:
        return self._outbox

    @outbox.setter
    def outbox(self, value: WriteAheadOutbox) -> None:
        """替换 outbox 时同步管理器引用，避免二者读到不同实例。"""
        self._outbox = value
        manager = getattr(self, "_outbox_manager", None)
        if manager is not None:
            manager.outbox = value
        checkpoint_manager = getattr(self, "_checkpoint_manager", None)
        if checkpoint_manager is not None:
            checkpoint_manager.outbox = value

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
                domain_config.agent_policy_config.reload()
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
        return self._outbox_manager.log(workspace_id, tool, arguments, client_write_id)

    def _outbox_done(self, workspace_id: str, entry_id: str) -> str | None:
        return self._outbox_manager.done(workspace_id, entry_id)

    def _outbox_fail(self, workspace_id: str, entry_id: str) -> None:
        self._outbox_manager.fail(workspace_id, entry_id)

    def _outbox_summary(self, *, status_tool: bool = False) -> dict[str, Any]:
        return self._outbox_manager.summary(status_tool=status_tool)

    def _outbox_on_error(self, workspace_id: str, entry_id: str, exc: Exception) -> None:
        """保留被拒绝的载荷供人工恢复；不落盘响应体或凭据。"""
        self._outbox_manager.on_error(workspace_id, entry_id, exc)

    async def _submit_write(
        self, tool: str, args: dict[str, Any], write_id: str, entry: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """提交已冻结的 save/checkpoint 载荷；workspace 在写前日志之后才解析。"""
        return await self._outbox_manager.submit_write(tool, args, write_id, entry)

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
            logger.info("Outbox drain: %d total, %d succeeded, %d failed", total, succeeded, failed)

    def _start_background_drain(self) -> None:
        if self._drain_task and not self._drain_task.done():
            return
        try:
            self._drain_task = asyncio.get_running_loop().create_task(self._background_drain())
        except RuntimeError:
            logger.debug("No running loop; skipping background outbox drain")

    async def _background_drain(self) -> None:
        try:
            await self._drain_outbox()
        except Exception as exc:
            logger.warning("Background outbox drain failed: %s", _safe_error(exc))
        finally:
            self._drain_task = None

    # -- 各工具处理器（自 _handle_tool 抽出）-----------------------------------

    async def _search_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        limit = arguments.get("limit", 10)
        max_tokens = arguments.get("max_tokens", 5000)
        local = self._local_context_lookup(arguments, limit, max_tokens)
        result: dict[str, Any] | None = None
        if local is not None and self._local_context_is_strong(local):
            result = local
        else:
            try:
                result = await self.client.get_context(
                    query=arguments["keyword"],
                    workspace_id=arguments["workspace_id"],
                    project=arguments.get("project"),
                    max_items=limit,
                    max_tokens=max_tokens,
                )
            except httpx.HTTPError as exc:
                if not _api_unavailable(exc):
                    raise
                if local is None:
                    result = self._local_unavailable_error()
                else:
                    result = self._mark_degraded(local, type(exc).__name__)
                    if arguments.get("project"):
                        result["warnings"].append("project 过滤已忽略（本地降级不支持）")

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
        # 各分支下被静默忽略的参数显式回显，避免 Agent 以为过滤/模式已生效
        ignored: list[str] = []
        if curated:
            mode = arguments.get("mode")
            if mode is not None and mode != "hybrid":
                ignored.append("mode（curated=true 固定走上下文组装）")
            if arguments.get("filters"):
                ignored.append("filters（curated=true 固定走上下文组装）")
            fallback = workspace or current_workspace_for(self)
            arguments["workspace_id"] = fallback
            arguments["workspace_name"] = fallback
            result = await self._search_context(arguments)
            if ignored:
                result.setdefault("warnings", []).append(f"参数已忽略：{'；'.join(ignored)}")
            return result
        mode = arguments.get("mode", "hybrid")
        filters = arguments.get("filters")
        tags = None
        if isinstance(filters, dict):
            tags = filters.get("tags")
            if tags is not None:
                filters = {k: v for k, v in filters.items() if k != "tags"}
                arguments["filters"] = filters or None
        if mode == "semantic":
            if arguments.get("filters"):
                ignored.append("filters（semantic 模式不支持过滤，需要过滤请用 hybrid）")
            if tags:
                ignored.append("filters.tags（semantic 模式不支持标签过滤）")
            # semantic 是显式语义请求：仍 API 优先，失败才降级本地关键词
            try:
                result = await self.client.recall(
                    query=arguments["keyword"],
                    workspace_id=workspace,
                    limit=arguments.get("limit", 10),
                )
            except httpx.HTTPError as exc:
                if not _api_unavailable(exc):
                    raise
                local = self._local_search_lookup(arguments, workspace, tags)
                if local is None:
                    result = self._local_unavailable_error()
                else:
                    result = self._mark_degraded(local, type(exc).__name__, semantic=True)
        else:
            # 本地优先：强命中直接返回（不依赖 API）；弱命中/空结果才请求 API 补语义
            local = self._local_search_lookup(arguments, workspace, tags)
            if local is not None and self._local_search_is_strong(local):
                result = local
            else:
                search_kwargs: dict[str, Any] = {
                    "query": arguments["keyword"],
                    "workspace_id": workspace,
                    "filters": arguments.get("filters"),
                    "limit": arguments.get("limit", 10),
                }
                if tags is not None:
                    search_kwargs["tags"] = tags
                try:
                    result = await self.client.search(**search_kwargs)
                except httpx.HTTPError as exc:
                    if not _api_unavailable(exc):
                        raise
                    if local is None:
                        result = self._local_unavailable_error()
                    else:
                        result = self._mark_degraded(local, type(exc).__name__)
        if ignored:
            result.setdefault("warnings", []).append(f"参数已忽略：{'；'.join(ignored)}")
        return result

    def _local_search_lookup(
        self,
        arguments: dict[str, Any],
        workspace: str | None,
        tags: list[str] | None,
    ) -> dict[str, Any] | None:
        """本地只读检索；DB 不可读时返回 None。"""
        filters = arguments.get("filters")
        memory_type = filters.get("type") if isinstance(filters, dict) else None
        min_confidence = filters.get("min_confidence") if isinstance(filters, dict) else None
        result = search_local(
            arguments["keyword"],
            workspace=workspace,
            limit=arguments.get("limit", 10),
            memory_type=memory_type if isinstance(memory_type, str) else None,
            min_confidence=min_confidence if isinstance(min_confidence, (int, float)) else None,
            tags=[str(tag) for tag in tags] if tags else None,
        )
        return result if result.get("available") else None

    @staticmethod
    def _local_search_is_strong(result: dict[str, Any]) -> bool:
        results = result.get("results") or []
        if not results:
            return False
        coverage = results[0].get("coverage")
        return isinstance(coverage, (int, float)) and coverage >= STRONG_COVERAGE

    def _local_context_lookup(
        self,
        arguments: dict[str, Any],
        limit: int,
        max_tokens: int,
    ) -> dict[str, Any] | None:
        result = build_local_context(
            workspace=str(arguments["workspace_id"]),
            query=arguments["keyword"],
            max_items=limit,
            max_tokens=max_tokens,
        )
        return result if result.get("available") else None

    @staticmethod
    def _local_context_is_strong(result: dict[str, Any]) -> bool:
        items = result.get("items") or []
        if not items:
            return False
        metadata = items[0].get("metadata") or {}
        coverage = metadata.get("coverage")
        return isinstance(coverage, (int, float)) and coverage >= STRONG_COVERAGE

    @staticmethod
    def _mark_degraded(
        result: dict[str, Any], reason: str, *, semantic: bool = False
    ) -> dict[str, Any]:
        """标注「API 不可用 → 本地关键词」的降级结果。"""
        result["degraded"] = True
        warnings = result.setdefault("warnings", [])
        warnings.append(
            f"cwiki API 不可用（{reason}），已回落本地只读索引：仅关键词检索，无语义召回与重排。"
        )
        if semantic:
            warnings.append("semantic 模式已降级为本地关键词检索。")
        return result

    @staticmethod
    def _local_unavailable_error() -> dict[str, Any]:
        return {
            "error": "cwiki API 不可用，且本地只读索引不可用",
            "hint": "确认 cwiki-data/cwiki.db 存在且未被加密/锁死；必要时启动 API。",
            "degraded": True,
            "source": "local",
        }

    async def _handle_memory_save(self, arguments: dict[str, Any]) -> dict[str, Any]:
        title, content = arguments.get("title"), arguments.get("content")
        if not isinstance(content, str):
            return {"error": "content 为必填字符串"}
        if not isinstance(title, str) or not title.strip():
            return {"error": "title 为必填参数"}
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > SAVE_CONTENT_MAX_BYTES:
            return {
                "error": (
                    f"content 为 {content_bytes / 1024:.0f}KB，超过单条上限 "
                    f"{SAVE_CONTENT_MAX_BYTES // 1024}KB。请拆分多条记忆或精简正文。"
                )
            }
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
        # 非法 type 不拒绝而是回落推断：宿主模型常受"记忆类型"概念影响传
        # project/note 等（Qoder 实测高频踩坑），拒绝只会白白丢失一次捕获；
        # 类型仅作分类，推断结果在返回体的 inferred_type 字段回显，可复核。
        if specified_type is not None and (
            not isinstance(specified_type, str) or specified_type not in TYPE_DEFINITIONS
        ):
            logger.info(
                "Ignoring unsupported memory type %r; falling back to inference", specified_type
            )
            specified_type = None
        memory_type = specified_type or _classify_memory_type(content)
        if memory_type not in TYPE_DEFINITIONS:
            memory_type = "fact"
        explicit_workspace = arguments.get("workspace_name") or arguments.get("workspace_id")
        if explicit_workspace is not None and not isinstance(explicit_workspace, str):
            return {"error": "workspace_id 必须是字符串"}
        workspace = self._resolved_workspace(arguments)
        # 自动补齐缺失的 #memory/ 标签；type 与 workspace 的校验相互独立
        missing_tags = [
            tag for tag in (f"#memory/{memory_type}", f"#memory/{workspace}") if tag not in content
        ]
        if missing_tags:
            content = content + "\n\n" + " ".join(missing_tags)
        frozen: dict[str, Any] = {
            "title": title,
            "content": content,
            "type": memory_type,
            "workspace_id": workspace,
        }
        tags = arguments.get("tags")
        if tags:
            frozen["tags"] = tags
        if arguments.get("is_permanent") is True:
            frozen["is_permanent"] = True
            permanent_reason = arguments.get("permanent_reason")
            if isinstance(permanent_reason, str) and permanent_reason.strip():
                frozen["permanent_reason"] = permanent_reason.strip()[:500]
        write_id = _make_write_id(
            content, title=title.strip(), memory_type=memory_type, workspace=workspace
        )
        # 旧版幂等键只含正文：随请求附带，服务端双查一版，避免升级后重复候选
        frozen["legacy_client_write_id"] = _make_write_id(content)
        response, entry, exc = await self._outbox_submit("memory_save", frozen, workspace, write_id)
        if exc is not None:
            rejected = _is_client_rejection(exc)
            decision_payload = _write_decision_payload(exc)
            result = {
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
            if decision_payload:
                result["write_decision"] = decision_payload
                result["hint"] = (
                    "命中写入决策规则：skip 表示不应写入；"
                    "update 表示应使用 memory_update 更新 target_memory_id 指向的记忆。"
                )
            return result
        assert response is not None
        created = bool(response.get("created", True))
        similar_items = response.get("similar_items", [])
        candidate_payload = response.get("candidate", {})
        result = {
            "status": "created",
            "created": created,
            "candidate_id": candidate_payload.get("id"),
            "title": title,
            "inferred_type": memory_type,
            # 回显实际归属工作区：Agent/用户可校验"归到正确的区"，
            # 归属错误能当场发现而不是事后在别的区找不到
            "workspace": workspace,
            "message": "已按原文提交，等待人工审核",
            "similar_memories": similar_items,
        }
        if frozen.get("is_permanent"):
            result["is_permanent"] = True
        policy_action = candidate_payload.get("policy_action")
        if policy_action:
            result["policy"] = {
                "rule": candidate_payload.get("policy_rule_id"),
                "action": policy_action,
                "reason": candidate_payload.get("policy_reason"),
            }
            if policy_action == "auto":
                result["message"] = "已提交，评分完成后按写入策略自动生效"
            elif policy_action == "review":
                result["message"] = "已提交，写入策略要求人工审核"
        decision_action = candidate_payload.get("decision_action")
        if decision_action:
            result["decision"] = {
                "rule": candidate_payload.get("decision_rule_id"),
                "action": decision_action,
                "reason": candidate_payload.get("decision_reason"),
            }
            if decision_action == "review":
                result["message"] = "已提交，写入决策规则要求人工审核"
        if similar_items:
            result["hint"] = (
                response.get("hint")
                or "发现相似记忆，请核对完整来源；修正已有记忆可使用 memory_update。"
            )
        if not created:
            # 幂等命中：同标题/类型/正文的候选已存在，不能谎报 created
            result["status"] = "deduplicated"
            result["message"] = "相同标题/类型/正文的候选已存在（幂等命中），未新建"
            result["hint"] = (
                "如需修改标题或正文，请在审核时编辑该候选；已转正记忆请用 memory_update。"
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
                or current_workspace_for(self)
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
            "write_policy_enabled": settings.write_policy.enabled,
            "write_policy_rules": [rule.id for rule in settings.write_policy.rules],
            "write_decisions_enabled": domain_config.agent_policy_config.write_decisions.enabled,
            "write_decisions_default_action": (
                domain_config.agent_policy_config.write_decisions.default_action
            ),
            "write_decisions_rules": [
                rule.id for rule in domain_config.agent_policy_config.write_decisions.rules
            ],
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

    async def _handle_memory_relation_create(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.client.create_memory_relation(
            memory_id=arguments["memory_id"],
            target_memory_id=arguments["target_memory_id"],
            relation_type=arguments["relation_type"],
            confidence=arguments.get("confidence", 1.0),
        )

    async def _handle_memory_relation_delete(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.client.delete_memory_relation(
            memory_id=arguments["memory_id"],
            relation_id=arguments["relation_id"],
        )

    async def _handle_memory_tags(self, arguments: dict[str, Any]) -> dict[str, Any]:
        # 与其他工具一致：schema 契约是 workspace_name，workspace_id 仅作旧调用兜底
        workspace_id = arguments.get("workspace_name") or arguments.get("workspace_id")
        tags_filter = arguments.get("tags")
        if tags_filter:
            # 按标签过滤记忆
            return await self.client.search_memories_by_tags(
                workspace_id=workspace_id,
                tags=tags_filter,
                limit=arguments.get("limit", 20),
            )
        else:
            # 列出所有标签
            return await self.client.list_tags(workspace_id=workspace_id)

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
                tags=arguments.get("tags"),
                reason=arguments.get("reason"),
                is_permanent=arguments.get("is_permanent"),
                permanent_reason=arguments.get("permanent_reason"),
                expected_version=version_kwargs.get("expected_version"),
            )
        except MemoryUpdateUncertainError:
            return {
                "error": "更新结果不确定，可能已生效；未自动重试。",
                "delivery": "unconfirmed",
                "hint": "请先回读当前记忆正文和版本，核对结果后再决定是否重试。",
            }

    async def _handle_memory_feedback(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = arguments.get("memory_id")
        feedback_type = arguments.get("feedback_type")
        if not isinstance(memory_id, str) or not memory_id:
            return {"error": "memory_id 为必填字符串"}
        if feedback_type not in {"useful", "not_useful", "outdated", "wrong"}:
            return {"error": "feedback_type 必须是 useful/not_useful/outdated/wrong"}
        workspace = arguments.get("workspace_id") or current_workspace_for(self)
        try:
            result = await self.client.submit_feedback(
                memory_id=memory_id,
                workspace_id=workspace,
                feedback_type=feedback_type,
                reason=arguments.get("reason"),
            )
        except Exception as exc:
            return {"error": _safe_error(exc)}
        return {
            "status": "recorded",
            "memory_id": memory_id,
            "feedback_type": feedback_type,
            "feedback": result,
        }

    async def _handle_memory_forget(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory_id = arguments.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            return {"error": "memory_id 为必填字符串"}
        try:
            result = await self.client.update_memory(
                memory_id=memory_id,
                status="archived",
                reason=arguments.get("reason") or "agent requested forget",
            )
        except MemoryUpdateUncertainError:
            return {
                "error": "归档结果不确定，可能已生效；未自动重试。",
                "delivery": "unconfirmed",
                "hint": "请先查询记忆状态确认；已归档可恢复为 active。",
            }
        except Exception as exc:
            return {"error": _safe_error(exc)}
        return {
            "status": "archived",
            "restorable": True,
            "memory_id": memory_id,
            "memory": result,
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
        return await self._checkpoint_manager.fetch_events(
            workspace_id, event_session_id, since_minutes
        )

    async def _checkpoint_fetch_notes(
        self,
        session_id: str,
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """为 checkpoint 拉取会话笔记。返回 (notes, error_dict|None)。"""
        return await self._checkpoint_manager.fetch_notes(session_id, workspace_id)

    async def _checkpoint_submit_candidates(
        self,
        candidates: list[dict[str, Any]],
        workspace_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """经 outbox 提交校验后的候选。返回 (submitted, rejected, errors)。"""
        return await self._checkpoint_manager.submit_candidates(candidates, workspace_id)

    def _checkpoint_validate_candidates(
        self,
        candidates: list[dict[str, Any]],
        errors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """校验并过滤候选，失败项追加到 errors。"""
        return self._checkpoint_manager.validate_candidates(candidates, errors)

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
        return self._checkpoint_manager.compute_window(
            session_id, workspace_id, event_session_id, collection_started_at
        )

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
        return await self._checkpoint_manager.build_result(
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
        rejected: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """记录水位、确定最终状态并附加 errors/warnings。"""
        return await self._checkpoint_manager.finalize(
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
            rejected=rejected,
        )

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
        rejected: list[dict[str, Any]] = []
        if not dry_run:
            submitted, rejected, submit_errors = await self._checkpoint_submit_candidates(
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
            rejected=rejected,
        )

    # 工具响应整体进入模型上下文：导出超过该体积（序列化后字节）时拒绝，
    # 提示改用 Web 控制台导出，避免一次性灌爆上下文
    EXPORT_MAX_BYTES = 512 * 1024

    async def _handle_memory_export(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or current_workspace_for(self)
        entities = arguments.get("entities")
        data = await self.client.export_data(workspace_id, fmt="json", entities=entities)
        payload_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        counts = {
            key: len(data[key])
            for key in ("memories", "candidates", "notes", "relations", "schedules")
            if key in data
        }
        if payload_bytes > self.EXPORT_MAX_BYTES:
            return {
                "error": (
                    f"导出数据 {payload_bytes / 1024:.0f}KB 超过工具响应上限 "
                    f"{self.EXPORT_MAX_BYTES / 1024:.0f}KB（counts={counts}）。"
                    "请缩小范围：用 entities 指定实体类型分批导出，"
                    "或改用 Web 控制台的全量导出。"
                )
            }
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "exported_at": data.get("exported_at"),
            "counts": counts,
            "data": data,
        }

    async def _handle_memory_import(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or current_workspace_for(self)
        strategy = arguments.get("strategy", "skip")
        import_data_payload = arguments.get("data", {})
        payload_bytes = len(json.dumps(import_data_payload, ensure_ascii=False).encode("utf-8"))
        if payload_bytes > IMPORT_PAYLOAD_MAX_BYTES:
            return {
                "error": (
                    f"导入载荷 {payload_bytes / 1024:.0f}KB 超过上限 "
                    f"{IMPORT_PAYLOAD_MAX_BYTES // 1024}KB。请分批导入，"
                    "或改用 Web 控制台的导入功能。"
                )
            }
        import_result = await self.client.import_data(import_data_payload, workspace_id, strategy)
        return {
            "status": "ok",
            "workspace_id": workspace_id,
            "strategy": strategy,
            **import_result,
        }

    # ── 复习工具 handlers ─────────────────────────────────────────────────────

    async def _handle_memory_review_due(self, arguments: dict[str, Any]) -> dict[str, Any]:
        workspace_id = arguments.get("workspace_name") or current_workspace_for(self)
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
        workspace_id = arguments.get("workspace_name") or current_workspace_for(self)
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
        workspace_id = arguments.get("workspace_name") or current_workspace_for(self)
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
                # 双键都写入，使各 handler 无论读取哪个键都能拿到值；
                # 缺失时按“实时归属 > 会话快照 > default”回落（与 memory_save 一致）
                workspace_arg = self._resolved_workspace(arguments)
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

        if method == "roots/list":
            # 宿主声明项目根；由 run_server 在响应路由后刷新动态工作区。
            roots = (params or {}).get("roots") or []
            for root in roots:
                uri = root.get("uri", "") if isinstance(root, dict) else ""
                if uri.startswith("file://"):
                    path = uri.removeprefix("file://")
                    name = clean_workspace_name(path)
                    if name:
                        self.roots_workspace = name
                        break
            return {"jsonrpc": "2.0", "id": req_id, "result": {"roots": roots}}

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
        "cwiki MCP server starting (api=%s, host=%s, workspace=%s)",
        API_BASE_URL,
        HOST_ID,
        current_workspace(),
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
                    workspace_id=current_workspace(),
                    agent=HOST_ID,
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
            # 整行已读完，丢弃该请求后可继续读下一行，无需关闭传输
            await write_response(OVERSIZE_ERROR)
            return _CONTINUE
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
