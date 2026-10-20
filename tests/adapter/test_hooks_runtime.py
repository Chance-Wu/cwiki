"""宿主无关 hook CLI 的 fail-open 与捕获落盘测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str], payload: dict | None, tmp_path: Path, extra_env: dict | None = None):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "CWIKI_HOOK_STATE_DIR": str(tmp_path / "state"),
        "CWIKI_API_URL": "http://127.0.0.1:9",
        **(extra_env or {}),
    }
    return subprocess.run(
        [sys.executable, "-m", "adapters.hooks", *args],
        input=json.dumps(payload).encode() if payload is not None else b"",
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_session_start_emits_context(tmp_path):
    result = _run(
        ["qoder", "session-start"],
        {"hook_event_name": "SessionStart", "session_id": "s1"},
        tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "memory_search" in data["hookSpecificOutput"]["additionalContext"]


def test_invalid_input_is_fail_open(tmp_path):
    result = _run(["qoder", "session-start"], None, tmp_path)
    assert result.returncode == 0
    assert result.stdout == b""


def test_mismatched_event_is_fail_open(tmp_path):
    result = _run(
        ["qoder", "user-prompt-submit"],
        {"hook_event_name": "SessionStart", "prompt": "hello"},
        tmp_path,
    )
    assert result.returncode == 0
    assert result.stdout == b""


def test_post_compact_writes_full_content_to_spool(tmp_path):
    content = "压缩摘要 " + "细节" * 3000
    result = _run(
        ["qoder", "post-compact"],
        {
            "hook_event_name": "PostCompact",
            "session_id": "session-compact",
            "cwd": "/tmp/project-alpha",
            "compact_summary": content,
        },
        tmp_path,
    )
    assert result.returncode == 0
    files = list((tmp_path / "state" / "qoder").glob("*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert records[0]["kind"] == "compact_summary"
    assert records[0]["workspace"] == "project-alpha"
    assert records[0]["content"] == content


def test_tool_failure_redacts_secret_and_skips_interrupt(tmp_path):
    result = _run(
        ["qoder", "post-tool-failure"],
        {
            "hook_event_name": "PostToolUseFailure",
            "session_id": "session-fail",
            "cwd": "/tmp/project-beta",
            "tool_name": "Bash",
            "error": "curl -H 'Authorization: Bearer sk-abcdefghijklmnop' failed",
            "is_interrupt": False,
        },
        tmp_path,
    )
    assert result.returncode == 0
    files = list((tmp_path / "state" / "qoder").glob("*.jsonl"))
    record = json.loads(files[0].read_text().splitlines()[0])
    assert "sk-abcdefghijklmnop" not in record["content"]
    assert "[REDACTED]" in record["content"]

    interrupted = _run(
        ["qoder", "post-tool-failure"],
        {
            "hook_event_name": "PostToolUseFailure",
            "session_id": "session-interrupt",
            "error": "cancelled",
            "is_interrupt": True,
        },
        tmp_path,
    )
    assert interrupted.returncode == 0
    assert len(list((tmp_path / "state" / "qoder").glob("session-interrupt*.jsonl"))) == 0


def test_claude_and_cursor_share_the_runtime(tmp_path):
    claude = _run(
        ["claude", "session-start"],
        {"hook_event_name": "SessionStart", "session_id": "c1"},
        tmp_path,
    )
    assert json.loads(claude.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"

    cursor = _run(
        ["cursor", "session-start"],
        {"session_id": "cur1"},
        tmp_path,
    )
    assert json.loads(cursor.stdout)["additional_context"]
