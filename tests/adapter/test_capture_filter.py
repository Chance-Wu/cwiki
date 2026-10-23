"""PostToolUseFailure 降噪：瞬时网络/协议失败不进入收件箱。"""

from __future__ import annotations

import pytest

from adapters.hooks.capture import build_record, should_capture_failure
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


@pytest.mark.parametrize(
    ("tool", "error", "error_type"),
    [
        ("WebFetch", 'Error during web fetch for "https://github.com/x"', None),
        ("Bash", "curl: (7) Failed to connect: ECONNREFUSED 127.0.0.1:5172", None),
        ("Bash", "getaddrinfo ENOTFOUND registry.npmjs.org", None),
        ("WebFetch", "Operation timed out after 30000ms", None),
        ("WebFetch", "certificate verify failed: certificate has expired", None),
        ("manage_mcp", "MCP_AGENT_INPUT_INVALID", None),
        ("query_mcp", "MCP_CONTEXT_STALE", None),
        ("present_visualization", '{"code":"invalid","message":"Cannot render"}', None),
        ("mcp_call", "NATIVE_BROWSER_VIEWPORT_UNAVAILABLE: no visible viewport", None),
        ("mcp_call", "The selected in-app browser page is blank.", None),
        ("TaskStop", "Failed to terminate process tree pid=5712", None),
    ],
)
def test_transient_or_protocol_failure_is_dropped(tool, error, error_type):
    assert should_capture_failure(tool, error_type, error) is False
    assert build_record(_event(error, tool, error_type)) is None


@pytest.mark.parametrize(
    ("tool", "error", "error_type"),
    [
        ("Bash", "Exit code 1\nModuleNotFoundError: No module named 'uvicorn'", None),
        ("Bash", "FAILED tests/test_api.py::test_health - AssertionError", None),
        ("Bash", "error[E0308]: mismatched types", "compile_error"),
        ("Bash", "Traceback (most recent call last):\n  File ...", None),
        ("Write", "Permission denied: /etc/hosts", None),
    ],
)
def test_actionable_failure_is_kept(tool, error, error_type):
    assert should_capture_failure(tool, error_type, error) is True
    record = build_record(_event(error, tool, error_type))
    assert record is not None
    assert record["kind"] == "tool_failure"
    assert record["signal_type"] == "issue"
    assert error.splitlines()[0] in record["content"]


def test_interrupt_is_still_dropped():
    event = _event("Exit code 1", tool_name="Bash")
    event.is_interrupt = True
    assert build_record(event) is None


def test_secret_is_redacted_before_store():
    record = build_record(_event("token = abcdefgh12345678 failed"))
    assert record is not None
    assert "abcdefgh12345678" not in record["content"]
    assert "[REDACTED]" in record["content"]
