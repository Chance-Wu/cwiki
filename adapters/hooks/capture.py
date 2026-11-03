"""把 hook 事件写成捕获记录，并通过 capture API 投递。

工具失败事件不捕获：平凡的命令错误与瞬时噪声占绝大多数，
进入待整理后 0 转化；真实的失败教训由事件/checkpoint 链路提炼。
"""

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
# 必须小于宿主 hook 超时（SessionStart 5s），否则 API 慢时内层先超时
POST_TIMEOUT_SECONDS = 3
_SECRET_PATTERNS = [
    re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,})"),
    re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]{12,})"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]{4,}"),
    re.compile(r"(?i)(token\s*[=:]\s*)[^\s,;]{8,}"),
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
    # post-tool-failure 不再捕获：失败内容不进待整理
    return None


def store(event: HookEvent) -> None:
    record = build_record(event)
    if record is None:
        return
    try:
        append(event.host, event.session_id, record)
    except Exception:  # spool 失败不得影响宿主会话
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
        with urllib.request.urlopen(request, timeout=POST_TIMEOUT_SECONDS) as response:
            json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False, set()
    # accepted 与 duplicates 都算已投递；rejected 也移除，避免毒记录永久重试
    return True, {str(r.get("record_id")) for r in records}


def drain(host: str, max_batches: int = 5) -> dict[str, int]:
    delivered = 0
    try:
        return _drain(host, max_batches)
    except Exception:  # 投递失败只保留积压，不阻塞 hook
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
