"""宿主差异的薄适配：事件名、项目目录环境变量、输出形状。

core 只认归一化事件；这里不实现业务，只做字段映射。所有宿主差异集中在
``HostProfile``，新增宿主只需注册一个 profile。
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from .envelope import HookEvent

ContextShape = Literal["hook_specific_output", "additional_context"]


@dataclass(frozen=True)
class HookCommandSpec:
    """一条宿主 hook 命令：归一化事件 → 可执行命令的属性。"""

    event: str
    timeout: int = 5
    async_: bool = False
    matcher: str | None = None
    # 同一原生事件挂多条命令时（如 SessionEnd + drain）显式指定归属
    native_event: str | None = None


@dataclass(frozen=True)
class HostProfile:
    """单个宿主的事件、环境变量、召回模式与输出形状。"""

    name: str
    native_events: Mapping[str, str] = field(default_factory=dict)
    project_env: tuple[str, ...] = ()
    recall_mode: str = "none"
    capture_events: frozenset[str] = frozenset()
    context_shape: ContextShape = "hook_specific_output"
    # 宿主能否在 UserPromptSubmit 阶段注入上下文（Cursor 不支持）
    prompt_context: bool = True
    hook_commands: tuple[HookCommandSpec, ...] = ()


def _profile(
    name: str,
    native_events: dict[str, str],
    *,
    project_env: tuple[str, ...] = (),
    recall_mode: str = "none",
    capture_events: frozenset[str] = frozenset(),
    context_shape: ContextShape = "hook_specific_output",
    prompt_context: bool = True,
    hook_commands: tuple[HookCommandSpec, ...] = (),
) -> HostProfile:
    return HostProfile(
        name=name,
        native_events=MappingProxyType(native_events),
        project_env=project_env,
        recall_mode=recall_mode,
        capture_events=capture_events,
        context_shape=context_shape,
        prompt_context=prompt_context,
        hook_commands=hook_commands,
    )


def _full_hook_commands() -> tuple[HookCommandSpec, ...]:
    """Qoder / Claude 共用的完整事件集；SessionEnd 额外挂 drain。"""
    return (
        HookCommandSpec("session-start", 5),
        HookCommandSpec("user-prompt-submit", 3),
        HookCommandSpec("pre-tool-use", 3, matcher="mcp_call|mcp__.*"),
        HookCommandSpec("post-compact", 10, async_=True),
        HookCommandSpec("post-tool-failure", 5, async_=True),
        HookCommandSpec("session-end", 10, async_=True),
        HookCommandSpec("drain", 10, async_=True, native_event="SessionEnd"),
    )


PROFILES: dict[str, HostProfile] = {
    # DeepSeek Harness（dsh）无原生 hooks 事件流；其 Agent 经 MCP 工具直连，
    # 捕获由用户/宿主脚本经 capture API 提交。这里注册 session-start 供
    # 手动/CI 场景调用（如 dsh 子任务启动脚本）。
    "dsh": _profile(
        "dsh",
        {"session-start": "SessionStart"},
        # DSH 实测不导出项目目录 env（只有 DSH_HOME/DSH_PROFILE/DSH_SESSION_ID 等），
        # dsh 的归属靠安装器写入的 CWIKI_WORKSPACE_DIR；无 hooks 时此表仅手动调用生效。
        project_env=("CWIKI_WORKSPACE_DIR", "CWIKI_PROJECT_DIR"),
        hook_commands=(HookCommandSpec("session-start", 5),),
    ),
    "qoder": _profile(
        "qoder",
        {
            "session-start": "SessionStart",
            "user-prompt-submit": "UserPromptSubmit",
            "pre-tool-use": "PreToolUse",
            "post-compact": "PostCompact",
            "post-tool-failure": "PostToolUseFailure",
            "session-end": "SessionEnd",
        },
        project_env=("QODER_PROJECT_DIR",),
        recall_mode="per_prompt",
        capture_events=frozenset({"post-compact", "post-tool-failure", "session-end"}),
        hook_commands=_full_hook_commands(),
    ),
    "claude": _profile(
        "claude",
        {
            "session-start": "SessionStart",
            "user-prompt-submit": "UserPromptSubmit",
            "pre-tool-use": "PreToolUse",
            "post-compact": "PostCompact",
            "post-tool-failure": "PostToolUseFailure",
            "session-end": "SessionEnd",
        },
        project_env=("CLAUDE_PROJECT_DIR",),
        recall_mode="per_prompt",
        capture_events=frozenset({"post-compact", "post-tool-failure", "session-end"}),
        hook_commands=_full_hook_commands(),
    ),
    # Cursor 的 beforeSubmitPrompt 不能注入 context；不注册 per-prompt 事件
    "cursor": _profile(
        "cursor",
        {
            "session-start": "sessionStart",
            "post-tool-failure": "postToolUseFailure",
            "session-end": "sessionEnd",
        },
        project_env=("CURSOR_PROJECT_DIR", "CLAUDE_PROJECT_DIR"),
        recall_mode="session_start",
        capture_events=frozenset({"post-tool-failure", "session-end"}),
        context_shape="additional_context",
        prompt_context=False,
        hook_commands=(
            HookCommandSpec("session-start", 5),
            HookCommandSpec("post-tool-failure", 5, async_=True),
            HookCommandSpec("session-end", 10, async_=True),
        ),
    ),
    "codex": _profile("codex", {}),
    "generic": _profile("generic", {}),
}

HOST_NAMES = frozenset(PROFILES)

_WORKSPACE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def profile_for(host: str) -> HostProfile:
    """未知宿主回落到空 profile（不认任何事件，也不注入上下文）。"""
    return PROFILES.get(host) or PROFILES["generic"]


def recall_mode(host: str) -> str:
    return profile_for(host).recall_mode


def render_hooks_config(
    host: str,
    *,
    command_prefix: str = "python -m adapters.hooks",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """由 profile 生成宿主 hooks 配置。

    同一原生事件的多条命令（SessionEnd + drain）合并到一个 matcher 下。
    ``command_prefix`` 由安装器替换为绝对解释器；``env`` 存在时逐命令注入。
    """
    profile = profile_for(host)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for spec in profile.hook_commands:
        native = spec.native_event or profile.native_events.get(spec.event)
        if native is None:
            continue
        groups = grouped.get(native)
        if groups is None:
            wrapper: dict[str, Any] = {}
            if spec.matcher:
                wrapper["matcher"] = spec.matcher
            wrapper["hooks"] = []
            groups = [wrapper]
            grouped[native] = groups
        command: dict[str, Any] = {
            "type": "command",
            "command": f"{command_prefix} {host} {spec.event}",
            "timeout": spec.timeout,
        }
        if spec.async_:
            command["async"] = True
        if env is not None:
            command["env"] = dict(env)
        groups[0]["hooks"].append(command)
    return {"hooks": grouped}


def supported_events(host: str) -> set[str]:
    profile = profile_for(host)
    events = set(profile.native_events)
    if not profile.prompt_context:
        events.discard("user-prompt-submit")
    return events


def normalize_event(host: str, event: str, payload: dict[str, Any]) -> HookEvent | None:
    native = profile_for(host).native_events.get(event)
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
    for env_name in profile_for(host).project_env:
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
    profile = profile_for(host)
    if profile.context_shape == "additional_context":
        return {"additional_context": text}
    native = profile.native_events.get(event)
    if native is None:
        return {}
    return {"hookSpecificOutput": {"hookEventName": native, "additionalContext": text}}


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
