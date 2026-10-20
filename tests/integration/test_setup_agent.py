"""非 Qoder 宿主的配置写入测试（Claude / Cursor / Codex）。"""

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
    project = tmp_path / "project"
    project.mkdir()
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

    install_claude(project, home, "project", dry_run=False)
    install_claude(project, home, "project", dry_run=False)

    data = json.loads(settings.read_text(encoding="utf-8"))
    entries = data["hooks"]["SessionStart"]
    commands = [h["command"] for group in entries for h in group["hooks"]]
    assert "echo user-hook" in commands
    assert sum("adapters.hooks claude session-start" in c for c in commands) == 1

    mcp = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["cwiki"]["args"] == ["-m", "adapters.mcp"]
    assert mcp["mcpServers"]["cwiki"]["env"]["CWIKI_WORKSPACE"] == "project"
    assert mcp["mcpServers"]["cwiki"]["env"]["CWIKI_HOST"] == "claude"

    claude_md = home / ".claude" / "CLAUDE.md"
    assert _count_block(claude_md) == (1, 1)
    assert (home / ".claude" / "skills" / "cwiki-save" / "SKILL.md").exists()


def test_install_cursor_writes_hooks_and_rule(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    hooks_path = project / ".cursor" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [{"command": "echo user-hook"}],
                    "afterFileEdit": [{"command": "echo format"}],
                },
            }
        ),
        encoding="utf-8",
    )

    install_cursor(project, home, "project", dry_run=False)

    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    commands = [entry["command"] for entry in data["hooks"]["sessionStart"]]
    assert "echo user-hook" in commands
    assert any("adapters.hooks cursor session-start" in c for c in commands)
    assert data["hooks"]["afterFileEdit"] == [{"command": "echo format"}]
    assert "postToolUseFailure" in data["hooks"]

    mcp = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["cwiki"]["env"]["CWIKI_WORKSPACE"] == "project"
    assert mcp["mcpServers"]["cwiki"]["env"]["CWIKI_HOST"] == "cursor"
    rule = (project / ".cursor" / "rules" / "cwiki.mdc").read_text(encoding="utf-8")
    assert rule.startswith("---")
    assert "alwaysApply: true" in rule


def test_install_codex_uses_managed_toml_block(tmp_path):
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt"\n', encoding="utf-8")

    install_codex(project, home, "project", dry_run=False)
    install_codex(project, home, "project", dry_run=False)

    text = config.read_text(encoding="utf-8")
    assert text.count("# cwiki:begin") == 1
    assert "[mcp_servers.cwiki]" in text
    assert 'CWIKI_HOST = "codex"' in text
    assert 'model = "gpt"' in text
    assert _count_block(home / ".codex" / "AGENTS.md") == (1, 1)
