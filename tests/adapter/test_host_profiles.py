"""HostProfile 收敛：宿主差异集中声明，未知宿主安全回落。"""

from __future__ import annotations

import json
from pathlib import Path

from adapters.hooks import profiles

ROOT = Path(__file__).resolve().parents[2]
QODER_HOOKS = ROOT / "adapters" / "qoder" / "hooks" / "hooks.json"


def test_unknown_host_falls_back_to_generic():
    profile = profiles.profile_for("unknown-host")
    assert profile.name == "generic"
    assert dict(profile.native_events) == {}
    assert profile.project_env == ()
    assert profiles.supported_events("unknown-host") == set()
    assert profiles.recall_mode("unknown-host") == "none"
    assert profiles.render_context("unknown-host", "session-start", "x") == {}


def test_qoder_profile_declares_all_hook_events():
    profile = profiles.PROFILES["qoder"]
    assert set(profile.native_events) == {
        "session-start",
        "user-prompt-submit",
        "pre-tool-use",
        "post-compact",
        "post-tool-failure",
        "session-end",
    }
    assert profile.recall_mode == "per_prompt"
    assert profile.capture_events == {"post-compact", "post-tool-failure", "session-end"}
    assert profile.context_shape == "hook_specific_output"


def test_cursor_uses_separate_context_shape_and_no_prompt_recall():
    assert profiles.supported_events("cursor") == {
        "session-start",
        "post-tool-failure",
        "session-end",
    }
    assert profiles.recall_mode("cursor") == "session_start"
    assert profiles.render_context("cursor", "session-start", "hello") == {
        "additional_context": "hello"
    }


def test_render_context_rejects_event_not_in_profile():
    assert profiles.render_context("qoder", "drain", "x") == {}


def test_normalize_event_requires_matching_native_name():
    payload = {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/repo/web"}
    assert profiles.normalize_event("qoder", "session-start", payload) is not None
    assert profiles.normalize_event("qoder", "session-end", payload) is None


def test_workspace_env_order_is_profile_driven(monkeypatch):
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "/repo/cursor-project")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/repo/claude-project")
    event = profiles.normalize_event(
        "cursor", "session-start", {"hook_event_name": "sessionStart", "session_id": "s1"}
    )
    assert event is not None
    assert event.workspace == "cursor-project"


def test_committed_qoder_hooks_json_matches_profile():
    committed = json.loads(QODER_HOOKS.read_text(encoding="utf-8"))
    generated = profiles.render_hooks_config("qoder", env={"PYTHONPATH": "."})
    assert committed == generated


def test_render_hooks_config_groups_commands_by_native_event():
    config = profiles.render_hooks_config(
        "qoder",
        command_prefix='"/abs/python" -m adapters.hooks',
        env={"PYTHONPATH": "/repo"},
    )
    hooks = config["hooks"]
    assert set(hooks) == {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostCompact",
        "PostToolUseFailure",
        "SessionEnd",
    }
    assert hooks["PreToolUse"][0]["matcher"] == "mcp_call|mcp__.*"
    session_end = [item["command"] for group in hooks["SessionEnd"] for item in group["hooks"]]
    assert session_end == [
        '"/abs/python" -m adapters.hooks qoder session-end',
        '"/abs/python" -m adapters.hooks qoder drain',
    ]
    assert all(
        item["env"]["PYTHONPATH"] == "/repo"
        for group in hooks["PostCompact"]
        for item in group["hooks"]
    )
