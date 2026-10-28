"""非 Qoder 宿主的全局配置写入测试（Claude / Cursor / Codex）。"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.setup_agent import (
    BEGIN,
    END,
    install_claude,
    install_codex,
    install_cursor,
)


def _count_block(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    return text.count(BEGIN), text.count(END)


def test_install_claude_merges_and_is_idempotent(tmp_path):
    home = tmp_path / "home"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]
                }
            }
        ),
        encoding="utf-8",
    )

    install_claude(home, dry_run=False)
    install_claude(home, dry_run=False)

    data = json.loads(settings.read_text(encoding="utf-8"))
    entries = data["hooks"]["SessionStart"]
    commands = [h["command"] for group in entries for h in group["hooks"]]
    assert "echo user-hook" in commands
    assert sum("adapters.hooks claude session-start" in c for c in commands) == 1

    mcp = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["cwiki"]
    assert server["args"] == ["-m", "adapters.mcp"]
    assert server["env"]["CWIKI_HOST"] == "claude"
    assert "CWIKI_WORKSPACE" not in server["env"]
    assert "cwd" not in server

    claude_md = home / ".claude" / "CLAUDE.md"
    assert _count_block(claude_md) == (1, 1)
    assert (home / ".claude" / "skills" / "cwiki-save" / "SKILL.md").exists()


def test_install_claude_hook_commands_are_known_runtime_events(tmp_path):
    """写入的 hook 命令必须能被 adapters/hooks/cli.py 执行。

    曾经写 post-tool-use-failure（cli 只认 post-tool-failure），导致失败捕获永不触发。
    """
    from adapters.hooks.cli import EVENTS

    home = tmp_path / "home"
    install_claude(home, dry_run=False)

    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for groups in settings["hooks"].values()
        for group in groups
        for hook in group.get("hooks", [])
    ]
    event_tokens = {
        command.split()[-1] for command in commands if "adapters.hooks claude" in command
    }
    assert event_tokens
    assert event_tokens <= EVENTS
    assert "post-tool-failure" in event_tokens


def test_install_cursor_writes_global_mcp(tmp_path):
    home = tmp_path / "home"

    install_cursor(home, dry_run=False)

    mcp = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["cwiki"]
    assert server["args"] == ["-m", "adapters.mcp"]
    assert server["env"]["CWIKI_HOST"] == "cursor"
    assert "CWIKI_WORKSPACE" not in server["env"]
    assert "cwd" not in server


def test_install_codex_uses_managed_toml_block(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt"\n', encoding="utf-8")

    install_codex(home, dry_run=False)
    install_codex(home, dry_run=False)

    text = config.read_text(encoding="utf-8")
    assert text.count("# cwiki:begin") == 1
    assert "[mcp_servers.cwiki]" in text
    assert 'CWIKI_HOST = "codex"' in text
    assert "CWIKI_WORKSPACE" not in text
    assert "cwd =" not in text
    assert 'model = "gpt"' in text
    assert _count_block(home / ".codex" / "AGENTS.md") == (1, 1)
