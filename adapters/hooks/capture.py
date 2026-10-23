"""把 hook 事件写成捕获记录，并通过 capture API 投递。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from .envelope import HookEvent
from .spool import append, load, remove_delivered

MAX_CONTENT = 50000
MAX_BATCH = 100
_SECRET_PATTERNS = [
    re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,})"),
    re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]{12,})"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]{4,}"),
    re.compile(r"(?i)(token\s*[=:]\s*)[^\s,;]{8,}"),
]

# 瞬时环境噪声：网络/DNS/代理/超时/网关错误，重复出现且不可复用
_TRANSIENT_FAILURE_PATTERNS = [
    re.compile(r"(?i)\b(ECONNREFUSED|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN)\b"),
    re.compile(r"(?i)(getaddrinfo|name or service not known|name resolution)"),
    re.compile(r"(?i)(connection (refused|reset|timed out|aborted|closed))"),
    re.compile(r"(?i)(network is unreachable|no route to host|proxy error)"),
    re.compile(r"(?i)(certificate verify failed|certificate has expired|ssl error)"),
    re.compile(r"(?i)(timed out|timeout after|operation timed out)"),
    re.compile(r"(?i)(HTTP (502|503|504)|status[ =:]+(502|503|504))"),
    re.compile(r"(?i)error during web fetch"),
    re.compile(r"(?i)(NATIVE_BROWSER_VIEWPORT_UNAVAILABLE|in-app browser|page is blank)"),
    re.compile(r"(?i)failed to terminate process tree"),
]
# 宿主/工具协议噪声：参数或 schema 用错、上下文过期，属于调用方式问题，
# 不是可跨会话复用的知识；采集后只会变成 0 转化的收件箱垃圾
_PROTOCOL_FAILURE_PATTERNS = [
    re.compile(r"MCP_(AGENT_INPUT_INVALID|CONTEXT_STALE|SESSION_)"),
    re.compile(r'(?i)("code"\s*:\s*"invalid"|invalid tool input|tool input validation)'),
]


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + "[REDACTED]", text)
    return text


def _fit(text: str) -> str:
    if len(text) <= MAX_CONTENT:
        return text
    # 明确标记截断，不静默；完整原文由调用方/宿主保留
    marker = "\n\n[truncated by cwiki at 50000 chars]"
    return text[: MAX_CONTENT - len(marker)] + marker


def _record_id(event: HookEvent, content: str) -> str:
    raw = f"{event.host}|{event.event}|{event.session_id}|{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def should_capture_failure(tool_name: str | None, error_type: str | None, error: str) -> bool:
    """过滤不可复用的失败：瞬时网络问题与宿主/工具协议误用不写入收件箱。

    保守策略：无法判定为噪声的一律保留（构建失败、测试失败、业务异常等）。
    """
    text = f"{tool_name or ''} {error_type or ''} {error}"
    if any(pattern.search(text) for pattern in _PROTOCOL_FAILURE_PATTERNS):
        return False
    return not any(pattern.search(text) for pattern in _TRANSIENT_FAILURE_PATTERNS)


def build_record(event: HookEvent) -> dict[str, Any] | None:
    if event.event == "session-end":
        return {
            "record_id": _record_id(event, event.reason or "end"),
            "kind": "session_end",
            "session_id": event.session_id,
            "workspace": event.workspace,
            "cwd": event.cwd,
            "content": (event.reason or "")[:200],
            "signal_type": "other",
            "occurred_at": event.occurred_at.isoformat(),
        }
    if event.event == "post-compact":
        content = redact((event.summary or "").strip())
        if not content:
            return None
        return {
            "record_id": _record_id(event, content),
            "kind": "compact_summary",
            "session_id": event.session_id,
            "workspace": event.workspace,
            "cwd": event.cwd,
            "content": _fit(content),
            "signal_type": "session_snapshot",
            "occurred_at": event.occurred_at.isoformat(),
        }
    if event.event == "post-tool-failure":
        if event.is_interrupt:
            return None
        error = redact((event.error or "").strip())
        if not error:
            return None
        if not should_capture_failure(event.tool_name, event.error_type, error):
            return None
        content = f"工具失败：{event.tool_name or 'unknown'}\n{error}"
        return {
            "record_id": _record_id(event, content),
            "kind": "tool_failure",
            "session_id": event.session_id,
            "workspace": event.workspace,
            "cwd": event.cwd,
            "content": _fit(content),
            "signal_type": "issue",
            "occurred_at": event.occurred_at.isoformat(),
        }
    return None


def store(event: HookEvent) -> None:
    record = build_record(event)
    if record is None:
        return
    try:
        append(event.host, event.session_id, record)
    except OSError:
        return
    drain(event.host, max_batches=1)


def _post(host: str, records: list[dict[str, Any]]) -> tuple[bool, set[str]]:
    body = json.dumps({"host": host, "records": records}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{os.environ.get('CWIKI_API_URL', 'http://127.0.0.1:5172').rstrip('/')}"
        "/v1/integrations/agent/capture",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False, set()
    # accepted 与 duplicates 都算已投递；rejected 也移除，避免毒记录永久重试
    return True, {str(r.get("record_id")) for r in records}


def drain(host: str, max_batches: int = 5) -> dict[str, int]:
    delivered = 0
    try:
        return _drain(host, max_batches)
    except OSError:
        return {"delivered": delivered}


def _drain(host: str, max_batches: int) -> dict[str, int]:
    delivered = 0
    for _ in range(max_batches):
        items = load(host, limit=MAX_BATCH)
        if not items:
            break
        records = [record for _, record in items]
        ok, _ = _post(host, records)
        if not ok:
            break
        ids = {str(record.get("record_id")) for record in records}
        remove_delivered(host, ids)
        delivered += len(records)
    return {"delivered": delivered}
