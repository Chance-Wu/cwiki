"""PostToolUseFailure 不捕获：工具失败内容一律不进入待整理收件箱。"""

from __future__ import annotations

from adapters.hooks.capture import build_record
from adapters.hooks.envelope import HookEvent


def _event(error: str, tool_name: str = "Bash", error_type: str | None = None) -> HookEvent:
    return HookEvent(
        host="qoder",
        event="post-tool-failure",
        session_id="s1",
        workspace="web",
        cwd="/repo/web",
        tool_name=tool_name,
        error=error,
        error_type=error_type,
    )


def test_tool_failure_is_never_captured():
    event = _event("Exit code 1\nModuleNotFoundError: No module named 'uvicorn'")
    assert build_record(event) is None


def test_trivial_shell_failure_is_not_captured():
    event = _event("Exit code 1 /usr/bin/bash: line 1: cd: apps/web: No such file or directory")
    assert build_record(event) is None


def test_interrupt_is_not_captured():
    event = _event("Exit code 1")
    event.is_interrupt = True
    assert build_record(event) is None


def test_empty_error_is_not_captured():
    event = _event("   ")
    assert build_record(event) is None


def test_compact_summary_is_still_captured():
    event = HookEvent(
        host="qoder",
        event="post-compact",
        session_id="s1",
        workspace="web",
        cwd="/repo/web",
        summary="会话压缩摘要",
    )
    record = build_record(event)
    assert record is not None
    assert record["kind"] == "compact_summary"
    assert "会话压缩摘要" in record["content"]
