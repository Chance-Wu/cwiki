"""宿主无关 hook CLI 的 fail-open 与捕获落盘测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from adapters.hooks import decisions
from adapters.hooks.envelope import HookEvent

ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str], payload: dict | None, tmp_path: Path, extra_env: dict | None = None):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "CWIKI_HOOK_STATE_DIR": str(tmp_path / "state"),
        # 注册表也必须隔离：refresh() 对所有事件生效，否则测试 cwd 会写入真实状态目录
        "CWIKI_STATE_DIR": str(tmp_path / "workspace-state"),
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


def _three_prompts(session_id: str, cwd: str, tmp_path: Path) -> None:
    env = {"CWIKI_WRITE_WATCH_MIN_DURATION": "0"}
    for index in range(3):
        result = _run(
            ["qoder", "user-prompt-submit"],
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "cwd": cwd,
                "prompt": f"问题 {index}：请解释这段代码",
            },
            tmp_path,
            env,
        )
        assert result.returncode == 0


def test_session_without_save_reminds_next_session(tmp_path):
    cwd = "/tmp/project-gamma"
    _three_prompts("s-gamma", cwd, tmp_path)
    ended = _run(
        ["qoder", "session-end"],
        {"hook_event_name": "SessionEnd", "session_id": "s-gamma", "cwd": cwd, "reason": "exit"},
        tmp_path,
        {"CWIKI_WRITE_WATCH_MIN_DURATION": "0"},
    )
    assert ended.returncode == 0

    started = _run(
        ["qoder", "session-start"],
        {"hook_event_name": "SessionStart", "session_id": "s-gamma-2", "cwd": cwd},
        tmp_path,
    )
    context = json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "收尾提醒" in context


def test_memory_save_clears_pending_reminder(tmp_path):
    cwd = "/tmp/project-delta"
    _three_prompts("s-delta", cwd, tmp_path)
    _run(
        ["qoder", "session-end"],
        {"hook_event_name": "SessionEnd", "session_id": "s-delta", "cwd": cwd, "reason": "exit"},
        tmp_path,
        {"CWIKI_WRITE_WATCH_MIN_DURATION": "0"},
    )

    saved = _run(
        ["qoder", "pre-tool-use"],
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s-delta",
            "cwd": cwd,
            "tool_name": "mcp__cwiki__memory_save",
            "tool_input": {},
        },
        tmp_path,
    )
    assert saved.returncode == 0

    started = _run(
        ["qoder", "session-start"],
        {"hook_event_name": "SessionStart", "session_id": "s-delta-2", "cwd": cwd},
        tmp_path,
    )
    context = json.loads(started.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "收尾提醒" not in context


def test_short_session_does_not_remind(tmp_path, monkeypatch):
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(tmp_path / "unit-state"))
    monkeypatch.setenv("CWIKI_WRITE_WATCH_MIN_DURATION", "0")
    decisions.note_prompt("qoder", "short-1", "proj-short")
    decisions.note_prompt("qoder", "short-1", "proj-short")
    decisions.audit(
        HookEvent(host="qoder", event="session-end", session_id="short-1", workspace="proj-short")
    )
    assert decisions.pop_reminder("qoder", "proj-short") == ""


def test_transcript_fallback_counts_turns_and_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(tmp_path / "transcript-state"))
    transcript = tmp_path / "session.jsonl"
    user_turns = [
        {"type": "user", "message": {"role": "user", "content": f"问题{i}"}} for i in range(4)
    ]
    transcript.write_text("\n".join(json.dumps(entry) for entry in user_turns), encoding="utf-8")
    decisions.audit(
        HookEvent(
            host="qoder",
            event="session-end",
            session_id="t-1",
            workspace="proj-t",
            transcript_path=str(transcript),
        )
    )
    assert "收尾提醒" in decisions.pop_reminder("qoder", "proj-t")

    saved_turn = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "name": "mcp__cwiki__memory_save", "input": {}}],
        },
    }
    transcript.write_text(
        "\n".join(json.dumps(entry) for entry in [*user_turns, saved_turn]),
        encoding="utf-8",
    )
    decisions.audit(
        HookEvent(
            host="qoder",
            event="session-end",
            session_id="t-2",
            workspace="proj-t2",
            transcript_path=str(transcript),
        )
    )
    assert decisions.pop_reminder("qoder", "proj-t2") == ""


def test_reminder_shows_at_most_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(tmp_path / "show-state"))
    monkeypatch.setenv("CWIKI_WRITE_WATCH_MIN_DURATION", "0")
    for _ in range(3):
        decisions.note_prompt("qoder", "show-1", "proj-show")
    decisions.audit(
        HookEvent(host="qoder", event="session-end", session_id="show-1", workspace="proj-show")
    )
    assert "收尾提醒" in decisions.pop_reminder("qoder", "proj-show")
    assert "收尾提醒" in decisions.pop_reminder("qoder", "proj-show")
    assert decisions.pop_reminder("qoder", "proj-show") == ""
