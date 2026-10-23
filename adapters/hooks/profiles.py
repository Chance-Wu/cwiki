"""宿主差异的薄适配：事件名、项目目录环境变量、输出形状。

core 只认归一化事件；这里不实现业务，只做字段映射。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .envelope import HookEvent

# DeepSeek Harness（dsh）无原生 hooks 事件流；其 Agent 经 MCP 工具直连，
# 捕获由用户/宿主脚本经 capture API 提交。这里注册 session-start 供
# 手动/CI 场景调用（如 dsh 子任务启动脚本）。
NATIVE_EVENTS: dict[str, dict[str, str]] = {
    "dsh": {
        "session-start": "SessionStart",
    },
    "qoder": {
        "session-start": "SessionStart",
        "user-prompt-submit": "UserPromptSubmit",
        "pre-tool-use": "PreToolUse",
        "post-compact": "PostCompact",
        "post-tool-failure": "PostToolUseFailure",
        "session-end": "SessionEnd",
    },
    "claude": {
        "session-start": "SessionStart",
        "user-prompt-submit": "UserPromptSubmit",
        "pre-tool-use": "PreToolUse",
        "post-compact": "PostCompact",
        "post-tool-failure": "PostToolUseFailure",
        "session-end": "SessionEnd",
    },
    "cursor": {
        "session-start": "sessionStart",
        "post-tool-failure": "postToolUseFailure",
        "session-end": "sessionEnd",
    },
}

PROJECT_ENV = {
    # DSH 实测不导出项目目录 env（只有 DSH_HOME/DSH_PROFILE/DSH_SESSION_ID 等），
    # dsh 的归属靠安装器写入的 CWIKI_WORKSPACE_DIR；无 hooks 时此表仅手动调用生效。
    "dsh": ("CWIKI_WORKSPACE_DIR", "CWIKI_PROJECT_DIR"),
    "qoder": ("QODER_PROJECT_DIR",),
    "claude": ("CLAUDE_PROJECT_DIR",),
    "cursor": ("CURSOR_PROJECT_DIR", "CLAUDE_PROJECT_DIR"),
}

RECALL_MODE = {
    "qoder": "per_prompt",
    "claude": "per_prompt",
    "cursor": "session_start",
    "dsh": "none",
    "codex": "none",
    "generic": "none",
}

CAPTURE_EVENTS = {
    "qoder": {"post-compact", "post-tool-failure", "session-end"},
    "claude": {"post-compact", "post-tool-failure", "session-end"},
    "cursor": {"post-tool-failure", "session-end"},
    "codex": set(),
    "generic": set(),
}

_WORKSPACE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def supported_events(host: str) -> set[str]:
    events = set(NATIVE_EVENTS.get(host, {}))
    if host == "cursor":
        # Cursor 的 beforeSubmitPrompt 不能注入 context；不注册 per-prompt 事件
        events.discard("user-prompt-submit")
    return events


def normalize_event(host: str, event: str, payload: dict[str, Any]) -> HookEvent | None:
    native = NATIVE_EVENTS.get(host, {}).get(event)
    if native is None:
        return None
    if host in {"qoder", "claude"}:
        incoming = payload.get("hook_event_name")
        if incoming is not None and incoming != native:
            return None

    prompt = payload.get("prompt") if event == "user-prompt-submit" else None
    summary = None
    if event == "post-compact":
        summary = payload.get("compact_summary") or payload.get("summary")
    error = None
    error_type = None
    tool_name = None
    is_interrupt = False
    if event == "post-tool-failure":
        error = payload.get("error") or payload.get("error_message")
        error_type = payload.get("error_type") or payload.get("failure_type")
        tool_name = payload.get("tool_name")
        is_interrupt = bool(payload.get("is_interrupt"))

    return HookEvent(
        host=host,
        event=event,
        session_id=_as_str(payload.get("session_id")) or "unknown",
        cwd=_as_str(payload.get("cwd")),
        workspace=workspace_from(host, payload),
        prompt=_as_str(prompt),
        summary=_as_str(summary),
        tool_name=_as_str(tool_name),
        error=_as_str(error),
        error_type=_as_str(error_type),
        is_interrupt=is_interrupt,
        reason=_as_str(payload.get("reason")),
        transcript_path=_as_str(payload.get("transcript_path")),
    )


def clean_workspace_name(candidate: str | None) -> str | None:
    """把任意目录路径清洗成合法工作区名；垃圾名 → None（绝不放行）。

    权威判据，三处同源（hook 推导 / MCP 核心 / 安装器）。宿主把会话路径编码成
    目录名时形如 ``--Users-alice-repo--``，这类名必须整体拒绝：**先判前缀再
    strip("-")**——反过来的话 ``--Users-...`` 会被洗白成看似合法的
    ``Users-...``，让记忆落进错误的工作区归属。
    """
    if not candidate:
        return None
    try:
        raw = _WORKSPACE_RE.sub("-", Path(candidate).name)
    except (OSError, ValueError):
        return None
    # 以 "-" 开头（宿主编码的 --path--）或形如 C--Users（盘符编码）一律拒绝
    if raw.startswith("-") or re.match(r"^[A-Za-z]--", raw):
        return None
    name = raw.strip("-")
    # 首字符须为字母/数字（API 白名单）——一并挡掉 "." ".." ".hidden"；
    # 8 位十六进制是哈希目录名，不是项目名
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        return None
    if re.fullmatch(r"[0-9a-f]{8}", name):
        return None
    # 折叠连字符（my--project / a--b）同样按宿主编码路径处理：这类目录名
    # strip("-") 后仍合法，会伪装成一个"看起来正常"的项目名，把记忆写进
    # 从未存在过的工作区归属。真实项目名极少出现连续 --，宁可拒绝。
    if "--" in name:
        return None
    # 超长沿用既有截断语义（API 白名单上限 64）
    return name[:64]


def derive_workspace_from_dir(candidate: str) -> str:
    """从项目目录路径推导合法工作区名；非用户项目/非法名 → default。

    与 workspace_from 的规则一致但不看 env——PreToolUse 直接信任本次调用
    payload 里的 cwd（多窗口宿主下插件子进程 env 未必反映本会话项目）。
    """
    if not candidate:
        return "default"
    try:
        path = Path(candidate)
    except (OSError, ValueError):
        return "default"
    # 只有 home 说明宿主未带项目目录；cwiki 仓库自身也是合法项目（cwiki）。
    if path == Path.home():
        return "default"
    return clean_workspace_name(candidate) or "default"


def workspace_from(host: str, payload: dict[str, Any]) -> str:
    candidate = None
    for env_name in PROJECT_ENV.get(host, ()):
        candidate = os.environ.get(env_name)
        if candidate:
            break
    if not candidate:
        candidate = _as_str(payload.get("cwd"))
    # candidate 仍可能是 None（宿主既无 env 也未传 cwd）
    return derive_workspace_from_dir(candidate or "")


def render_context(host: str, event: str, text: str) -> dict[str, Any]:
    if not text:
        return {}
    if host == "cursor":
        return {"additional_context": text}
    native = NATIVE_EVENTS.get(host, {}).get(event)
    if native is None:
        return {}
    return {"hookSpecificOutput": {"hookEventName": native, "additionalContext": text}}


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
