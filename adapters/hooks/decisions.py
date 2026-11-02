"""SessionStart 写入决策注入与 SessionEnd 收尾审计。

前半部分从 config 读取 agent_policy.write_decisions 生成提示。规则只在
``memory_save`` 之后复核候选，无法发现"整轮会话根本没提交"；后半部分统计
会话活动，零写入时把提醒落盘，由下一次 SessionStart 注入一次。任何异常都
fail-open，不阻塞宿主。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import recall
from .envelope import HookEvent
from .profiles import derive_workspace_from_dir
from .spool import state_root

MIN_PROMPTS = 3
MIN_DURATION_SECONDS = 10 * 60
TRANSCRIPT_MIN_PROMPTS = 4
REMINDER_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_SHOWS = 2
MAX_TRANSCRIPT_BYTES = 4 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def build_hint(workspace: str) -> str:
    """返回写入决策摘要；未启用时回退旧的 must_save 提示。"""
    try:
        from packages.domain.config import agent_policy_config
        from packages.domain.write_decisions import build_agent_hint

        policy = agent_policy_config.write_decisions
        if policy.enabled:
            return build_agent_hint(policy, workspace)
        return recall.must_save_hint()
    except Exception:
        return ""


def note_prompt(
    host: str, session_id: str | None, workspace: str, prompt: str | None = None
) -> None:
    """UserPromptSubmit：累加本会话的提问次数与起止时间（slash 命令不计）。"""
    if not session_id or session_id == "unknown":
        return
    if prompt and prompt.lstrip().startswith("/"):
        return
    try:
        now = time.time()
        path = _session_path(host, session_id)
        data = _load(path) or {}
        data.update(
            {
                "session_id": session_id,
                "workspace": workspace,
                "prompts": int(data.get("prompts", 0) or 0) + 1,
                "first_at": float(data.get("first_at", now) or now),
                "last_at": now,
            }
        )
        _store(path, data)
    except (OSError, ValueError, TypeError):
        return


def note_tool_use(host: str, payload: dict[str, Any]) -> None:
    """PreToolUse：识别 memory_save，记录工作区级保存时间并清除待提醒。"""
    try:
        from .workspace_inject import tool_suffix

        if tool_suffix(payload) != "memory_save":
            return
        workspace = derive_workspace_from_dir(str(payload.get("cwd") or ""))
        _store(
            _saves_path(host, workspace),
            {"workspace": workspace, "last_saved_at": time.time()},
        )
        _drop(_pending_path(host, workspace))
    except (OSError, ValueError, TypeError):
        return


def audit(event: HookEvent) -> None:
    """SessionEnd：判定本会话是否"有活动、零写入"，是则写待提醒。"""
    if event.event != "session-end":
        return
    try:
        _audit(event)
    except (OSError, ValueError, TypeError):
        return
    finally:
        _drop(_session_path(event.host, event.session_id))


def prune(host: str, now: float | None = None) -> None:
    """清理过期会话计数与待提醒，避免状态目录无限增长。"""
    cutoff = (now or time.time()) - _ttl()
    for path in _session_dir(host).iterdir():
        _drop_if_old(path, cutoff)
    for path in _pending_dir(host).iterdir():
        _drop_if_old(path, cutoff)


def pop_reminder(host: str, workspace: str) -> str:
    """SessionStart：取走本工作区提醒；最多展示 MAX_SHOWS 次或直到过期。"""
    try:
        path = _pending_path(host, workspace)
        data = _load(path)
        if not data:
            return ""
        if time.time() - float(data.get("created_at", 0) or 0) > _ttl():
            _drop(path)
            return ""
        shown = int(data.get("shown", 0) or 0)
        if shown >= MAX_SHOWS:
            _drop(path)
            return ""
        data["shown"] = shown + 1
        _store(path, data)
        return _render(data)
    except (OSError, ValueError, TypeError):
        return ""


def _audit(event: HookEvent) -> None:
    activity = _load(_session_path(event.host, event.session_id)) or {}
    prompts = int(activity.get("prompts", 0) or 0)
    first_at = float(activity.get("first_at", 0) or 0)
    last_at = float(activity.get("last_at", first_at) or first_at)
    duration = max(0.0, last_at - first_at)

    transcript_saves = 0
    from_transcript = False
    if prompts == 0 and event.transcript_path:
        scanned = _scan_transcript(event.transcript_path)
        prompts = scanned["prompts"]
        transcript_saves = scanned["saves"]
        from_transcript = True

    if prompts <= 0:
        return
    if from_transcript:
        if prompts < TRANSCRIPT_MIN_PROMPTS:
            return
    elif prompts < _min_prompts() or duration < _min_duration():
        return
    if transcript_saves > 0:
        return
    if first_at and _saved_since(event.host, event.workspace, first_at):
        return

    _store(
        _pending_path(event.host, event.workspace),
        {
            "workspace": event.workspace,
            "session_id": event.session_id,
            "prompts": prompts,
            "duration_s": round(duration, 1) if not from_transcript else None,
            "created_at": time.time(),
            "shown": 0,
        },
    )


def _saved_since(host: str, workspace: str, since: float) -> bool:
    data = _load(_saves_path(host, workspace)) or {}
    try:
        return float(data.get("last_saved_at", 0) or 0) >= since
    except (ValueError, TypeError):
        return False


def _render(data: dict[str, Any]) -> str:
    created = float(data.get("created_at", 0) or 0)
    try:
        day = datetime.fromtimestamp(created).strftime("%m-%d")
    except (OSError, OverflowError, ValueError):
        day = "上次"
    prompts = int(data.get("prompts", 0) or 0)
    return (
        f"cwiki 收尾提醒：{day} 的会话（约 {prompts} 轮）没有提交 memory_save。"
        "请回看决策、原理、偏好、踩坑并补交；确无内容可忽略。"
    )


def _scan_transcript(path_value: str) -> dict[str, int]:
    """只统计用户提问数与 memory_save 调用数；不保存任何原文。"""
    result = {"prompts": 0, "saves": 0}
    try:
        path = Path(path_value)
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > MAX_TRANSCRIPT_BYTES:
                fh.seek(size - MAX_TRANSCRIPT_BYTES)
                fh.readline()
            for raw in fh:
                try:
                    entry = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if _is_user_text(entry):
                    result["prompts"] += 1
                result["saves"] += _count_saves(entry)
    except OSError:
        pass
    return result


def _is_user_text(entry: dict[str, Any]) -> bool:
    message = entry.get("message")
    message = message if isinstance(message, dict) else {}
    if str(entry.get("type") or message.get("role") or "") != "user":
        return False
    content = message.get("content", entry.get("content"))
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(block, dict)
            and block.get("type") == "text"
            and str(block.get("text") or "").strip()
            for block in content
        )
    return False


def _count_saves(entry: dict[str, Any]) -> int:
    message = entry.get("message")
    message = message if isinstance(message, dict) else {}
    if str(entry.get("type") or message.get("role") or "") != "assistant":
        return 0
    content = message.get("content", entry.get("content"))
    if not isinstance(content, list):
        return 0
    count = 0
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = str(block.get("name") or "")
        if name.rsplit("__", 1)[-1] == "memory_save":
            count += 1
        elif name == "mcp_call":
            args = block.get("input")
            args = args if isinstance(args, dict) else {}
            inner = str(args.get("toolName") or args.get("tool_name") or "")
            if inner.rsplit("__", 1)[-1] == "memory_save":
                count += 1
    return count


def _state_dir(host: str) -> Path:
    path = state_root() / "session-audit" / _safe(host)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_dir(host: str) -> Path:
    path = _state_dir(host) / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pending_dir(host: str) -> Path:
    path = _state_dir(host) / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _saves_path(host: str, workspace: str) -> Path:
    return _state_dir(host) / "saves" / f"{_safe(workspace)}.json"


def _session_path(host: str, session_id: str) -> Path:
    return _session_dir(host) / f"{_safe(session_id)}.json"


def _pending_path(host: str, workspace: str) -> Path:
    return _pending_dir(host) / f"{_safe(workspace)}.json"


def _safe(value: str, limit: int = 120) -> str:
    cleaned = _SAFE.sub("-", value).strip("-")
    return cleaned[:limit] or "unknown"


def _load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _store(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return


def _drop(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _drop_if_old(path: Path, cutoff: float) -> None:
    try:
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _min_prompts() -> int:
    return _env_int("CWIKI_WRITE_WATCH_MIN_PROMPTS", MIN_PROMPTS)


def _min_duration() -> float:
    return float(_env_int("CWIKI_WRITE_WATCH_MIN_DURATION", MIN_DURATION_SECONDS))


def _ttl() -> float:
    return float(_env_int("CWIKI_WRITE_WATCH_TTL", REMINDER_TTL_SECONDS))


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default
