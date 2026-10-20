#!/usr/bin/env python3
"""为 Qoder 之外的常用 Agent 写入 cwiki 接入配置。

用法：
    python scripts/setup_agent.py --host claude --project /path/to/project
    python scripts/setup_agent.py --host cursor --project /path/to/project
    python scripts/setup_agent.py --host codex  --project /path/to/project
    python scripts/setup_agent.py --host claude --project ... --dry-run

原则：只管理 ``<!-- cwiki:begin -->`` 区块与 ``cwiki`` 配置条目，
保留用户已有内容；JSON 解析失败/冲突时中止该宿主，不覆盖文件。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "templates" / "agent-instructions.md"
BEGIN = "<!-- cwiki:begin -->"
END = "<!-- cwiki:end -->"

# sys.executable 会被写入宿主（Claude Code / Cursor / Codex）的 MCP / hooks
# 配置，必须先切换到 .venv 解释器，避免把无项目依赖的系统 python 写进去
# （会让宿主 MCP server 启动即崩、连接失败）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.common import ensure_venv_interpreter

ensure_venv_interpreter(ROOT)


def _command(host: str, event: str) -> str:
    exe = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    return f"{exe} -m adapters.hooks {host} {event}"


def _hook_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT)}


def _mcp_server(workspace: str, host: str) -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "adapters.mcp"],
        "cwd": str(ROOT),
        "env": {
            "PYTHONPATH": str(ROOT),
            "CWIKI_WORKSPACE": workspace,
            "CWIKI_HOST": host,
            "CWIKI_WORKSPACE_DIR": str(Path.cwd()),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, data: dict[str, Any], dry_run: bool) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if dry_run:
        print(f"[dry-run] write {path}")
        print(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _merge_instructions(path: Path, body: str, dry_run: bool) -> None:
    block = f"{BEGIN}\n{body.strip()}\n{END}"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if BEGIN in existing or END in existing:
        if existing.count(BEGIN) != 1 or existing.count(END) != 1:
            raise SystemExit(f"broken cwiki markers in {path}")
        start = existing.index(BEGIN)
        end = existing.index(END) + len(END)
        updated = existing[:start] + block + existing[end:]
    else:
        updated = (existing.rstrip() + "\n\n" if existing.strip() else "") + block + "\n"
    if dry_run:
        print(f"[dry-run] write {path}")
        print(updated)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")


def _install_skill(source: Path, target_dir: Path, dry_run: bool) -> None:
    target = target_dir / source.name
    if dry_run:
        print(f"[dry-run] link {target} -> {source}")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)
    try:
        os.symlink(source, target, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)


def _merge_event(
    entries: list[dict[str, Any]], host: str, addition: dict[str, Any]
) -> list[dict[str, Any]]:
    """保留用户已有 hook 条目，只替换本 host 的 cwiki 条目。"""
    marker = f"adapters.hooks {host}"
    kept = [
        entry
        for entry in entries
        if not any(marker in str(hook.get("command", "")) for hook in entry.get("hooks", []))
    ]
    kept.append(addition)
    return kept


def install_claude(project: Path, home: Path, workspace: str, dry_run: bool) -> None:
    settings_path = home / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    hooks = settings.setdefault("hooks", {})
    # event -> (matcher, commands)；PreToolUse 用 updatedInput 做确定性工作区注入
    events = {
        "SessionStart": (None, ["session-start"]),
        "UserPromptSubmit": (None, ["user-prompt-submit"]),
        "PreToolUse": ("mcp__.*", ["pre-tool-use"]),
        "PostCompact": (None, ["post-compact"]),
        "PostToolUseFailure": (None, ["post-tool-use-failure"]),
        "SessionEnd": (None, ["session-end", "drain"]),
    }
    async_commands = {"post-compact", "post-tool-use-failure", "session-end"}
    for event, (matcher, commands) in events.items():
        addition = {
            **({"matcher": matcher} if matcher else {}),
            "hooks": [
                {
                    "type": "command",
                    "command": _command("claude", command),
                    "timeout": 10,
                    "env": _hook_env(),
                    **({"async": True} if command in async_commands else {}),
                }
                for command in commands
            ],
        }
        existing = hooks.get(event)
        hooks[event] = _merge_event(
            existing if isinstance(existing, list) else [], "claude", addition
        )
    _write_json(settings_path, settings, dry_run)

    mcp_path = project / ".mcp.json"
    mcp = _read_json(mcp_path)
    mcp.setdefault("mcpServers", {})["cwiki"] = _mcp_server(workspace, "claude")
    _write_json(mcp_path, mcp, dry_run)

    _merge_instructions(home / ".claude" / "CLAUDE.md", TEMPLATE.read_text("utf-8"), dry_run)
    _install_skill(ROOT / "skills" / "cwiki-save", home / ".claude" / "skills", dry_run)


def install_cursor(project: Path, home: Path, workspace: str, dry_run: bool) -> None:
    mcp_path = project / ".cursor" / "mcp.json"
    mcp = _read_json(mcp_path)
    mcp.setdefault("mcpServers", {})["cwiki"] = _mcp_server(workspace, "cursor")
    _write_json(mcp_path, mcp, dry_run)

    hooks_path = project / ".cursor" / "hooks.json"
    hooks = _read_json(hooks_path)
    hooks["version"] = 1
    event_map = hooks.setdefault("hooks", {})
    for event, command in (
        ("sessionStart", "session-start"),
        ("postToolUseFailure", "post-tool-use-failure"),
        ("sessionEnd", "session-end"),
    ):
        addition = {"command": _command("cursor", command), "timeout": 10}
        existing = event_map.get(event)
        entries = existing if isinstance(existing, list) else []
        marker = "adapters.hooks cursor"
        kept = [entry for entry in entries if marker not in str(entry.get("command", ""))]
        kept.append(addition)
        event_map[event] = kept
    _write_json(hooks_path, hooks, dry_run)

    rule = TEMPLATE.read_text("utf-8").strip()
    rule_path = project / ".cursor" / "rules" / "cwiki.mdc"
    content = f"---\ndescription: cwiki memory\nglobs: ['**/*']\nalwaysApply: true\n---\n\n{rule}\n"
    if dry_run:
        print(f"[dry-run] write {rule_path}")
        print(content)
    else:
        rule_path.parent.mkdir(parents=True, exist_ok=True)
        rule_path.write_text(content, encoding="utf-8")


def install_codex(project: Path, home: Path, workspace: str, dry_run: bool) -> None:
    config = home / ".codex" / "config.toml"
    block = f"""# cwiki:begin
[mcp_servers.cwiki]
command = {json.dumps(sys.executable)}
args = ["-m", "adapters.mcp"]
cwd = {json.dumps(str(ROOT))}
env = {{ PYTHONPATH = {json.dumps(str(ROOT))}, CWIKI_WORKSPACE = {json.dumps(workspace)}, CWIKI_HOST = "codex" }}
# cwiki:end
"""
    existing = config.read_text(encoding="utf-8") if config.exists() else ""
    if "# cwiki:begin" in existing or "# cwiki:end" in existing:
        if existing.count("# cwiki:begin") != 1 or existing.count("# cwiki:end") != 1:
            raise SystemExit(f"broken cwiki markers in {config}")
        start = existing.index("# cwiki:begin")
        end = existing.index("# cwiki:end") + len("# cwiki:end")
        updated = existing[:start] + block.rstrip() + existing[end:]
    else:
        updated = (existing.rstrip() + "\n\n" if existing.strip() else "") + block
    if dry_run:
        print(f"[dry-run] write {config}")
        print(updated)
    else:
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(updated, encoding="utf-8")

    _merge_instructions(home / ".codex" / "AGENTS.md", TEMPLATE.read_text("utf-8"), dry_run)
    _install_skill(ROOT / "skills" / "cwiki-save", home / ".codex" / "skills", dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=["claude", "cursor", "codex"])
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--home", type=Path, default=Path.home(), help="测试用 home 覆盖")
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    home = args.home.expanduser().resolve()
    workspace = args.workspace or project.name
    print(f"host={args.host} project={project} workspace={workspace}")
    if args.host == "claude":
        install_claude(project, home, workspace, args.dry_run)
    elif args.host == "cursor":
        install_cursor(project, home, workspace, args.dry_run)
    else:
        install_codex(project, home, workspace, args.dry_run)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
