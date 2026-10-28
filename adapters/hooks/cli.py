"""宿主无关的 hook 命令入口。

用法：
    python -m adapters.hooks <host> <event>

host: qoder | claude | cursor | codex | generic
event: session-start | user-prompt-submit | post-compact |
       post-tool-failure | session-end | drain

所有失败都 fail-open：只写固定 stderr 诊断，退出 0，绝不阻塞宿主。
"""

from __future__ import annotations

import json
import os
import sys
from typing import NoReturn

from . import capture, decisions, profiles, recall, workspace_inject
from .workspace_registry import refresh

MAX_INPUT_BYTES = 1024 * 1024
EVENTS = {
    "session-start",
    "user-prompt-submit",
    "pre-tool-use",
    "post-compact",
    "post-tool-failure",
    "session-end",
    "drain",
}
HOSTS = profiles.HOST_NAMES
REMINDER = (
    "cwiki: 会话开始或切换话题时用 memory_search 检索相关记忆；"
    "出现用户纠正、技术决策、踩坑、约定、可复用资源时，按 cwiki-save skill "
    "用 memory_save 提交；回答后可用 memory_feedback 标记有用/无用；"
    "错误记忆用 memory_forget 归档。无真实信号就跳过，不凑条数。"
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("non-JSON constant")


def _diagnose(reason: str) -> None:
    try:
        os.write(sys.stderr.fileno(), f"cwiki-hook: skipped ({reason}).\n".encode("ascii"))
    except (OSError, ValueError):
        pass


def _read_payload() -> dict[str, object] | None:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            _diagnose("input too large")
            return None
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError, RecursionError):
        _diagnose("invalid input")
        return None
    if not isinstance(payload, dict):
        _diagnose("input is not object")
        return None
    return payload


def _write_json(payload: dict[str, object]) -> None:
    if not payload:
        return
    try:
        data = (json.dumps(payload, ensure_ascii=True) + "\n").encode("ascii")
        while data:
            written = os.write(sys.stdout.fileno(), data)
            if written == 0:
                raise OSError("output unavailable")
            data = data[written:]
    except (OSError, ValueError):
        _diagnose("output unavailable")


def main() -> int:
    try:
        return _dispatch()
    except Exception:  # fail-open：任何意外都不能阻塞宿主
        _diagnose("internal error")
        return 0


def _dispatch() -> int:
    args = sys.argv[1:]
    if len(args) != 2:
        _diagnose("expected <host> <event>")
        return 0
    host, event = args
    if host not in HOSTS or event not in EVENTS:
        _diagnose("unknown host or event")
        return 0

    if event == "drain":
        capture.drain(host)
        return 0

    payload = _read_payload()
    if payload is None:
        return 0

    if event == "pre-tool-use":
        # 工具执行前的确定性归属注入：payload 自带本会话 cwd，
        # 多窗口并发下比注册表（last-write-wins）可靠。
        # 不刷新注册表——每次工具调用都触发，高频写反而放大跨会话竞态。
        updated = workspace_inject.updated_input(payload)
        if updated is not None:
            _write_json(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "updatedInput": updated,
                    }
                }
            )
        return 0

    normalized = profiles.normalize_event(host, event, payload)
    if normalized is None:
        _diagnose("event not supported by host")
        return 0

    # 无论哪种事件，都把"Agent 当前所在项目"同步给 MCP 动态注册表；
    # MCP 是长驻进程，只有 hook 拿得到宿主刚刚切到哪个项目。
    refresh(normalized.workspace, host)

    if event == "session-start":
        parts = [REMINDER]
        hint = decisions.build_hint(normalized.workspace)
        if hint:
            parts.append(hint)
        head = recall.build_session_head(normalized.workspace)
        if head:
            parts.append(head)
        _write_json(profiles.render_context(host, event, "\n\n".join(parts)))
        # 先输出再补投：补投含 HTTP，API 慢时不能挤掉本次会话注入
        capture.drain(host, max_batches=1)
        return 0

    if event == "user-prompt-submit":
        if profiles.recall_mode(host) != "per_prompt" or not normalized.prompt:
            return 0
        text = recall.build_context(normalized.prompt, normalized.workspace)
        _write_json(profiles.render_context(host, event, text))
        return 0

    if event in {"post-compact", "post-tool-failure"}:
        capture.store(normalized)
        return 0

    if event == "session-end":
        capture.store(normalized)
        capture.drain(host, max_batches=1)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
