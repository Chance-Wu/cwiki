#!/usr/bin/env python3
"""为 Qoder 之外的常用 Agent 注册全局 cwiki 接入配置。

用法：
    python scripts/setup_agent.py --host claude
    python scripts/setup_agent.py --host cursor
    python scripts/setup_agent.py --host codex
    python scripts/setup_agent.py --host claude --dry-run

原则：只管理 ``<!-- cwiki:begin -->`` 区块与 ``cwiki`` 配置条目，
保留用户已有内容；JSON 解析失败/冲突时中止该宿主，不覆盖文件。
MCP 一律注册到宿主用户级配置，不写项目级文件；工作区归属由运行期
（hooks / MCP 实时解析）决定。
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
# 与 Qoder 共用同一份受管区块正文，避免两块模板各自漂移
TEMPLATE = Path(__file__).resolve().parent / "templates" / "cwiki-agents-block.md"
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
    # 宿主可能经 shell 执行 hook：Windows 反斜杠会被 bash 吞掉，统一正斜杠
    exe = sys.executable.replace("\\", "/")
    if " " in exe:
        exe = f'"{exe}"'
    return f"{exe} -m adapters.hooks {host} {event}"


def _hook_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT)}


def _mcp_server(host: str) -> dict[str, Any]:
    """全局 MCP 条目：不绑定项目与工作区，归属由运行期解析。"""
    return {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "adapters.mcp"],
        "env": {
            "PYTHONPATH": str(ROOT),
            "CWIKI_HOST": host,
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
            raise SystemExit(
                f"broken cwiki markers in {path}; "
                "remove duplicate or reversed cwiki:begin / cwiki:end markers and retry"
            )
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


def install_claude(home: Path, dry_run: bool) -> None:
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

    # Claude Code 用户级 MCP 配置位于 ~/.claude.json
    mcp_path = home / ".claude.json"
    mcp = _read_json(mcp_path)
    mcp.setdefault("mcpServers", {})["cwiki"] = _mcp_server("claude")
    _write_json(mcp_path, mcp, dry_run)

    _merge_instructions(home / ".claude" / "CLAUDE.md", TEMPLATE.read_text("utf-8"), dry_run)
    _install_skill(ROOT / "skills" / "cwiki-save", home / ".claude" / "skills", dry_run)


def install_cursor(home: Path, dry_run: bool) -> None:
    """Cursor 用户级 MCP 配置（~/.cursor/mcp.json）。

    Cursor 的 hooks 与 rules 只有项目级入口，故不再写入；工作区归属由运行期
    （MCP roots / 目录推导）决定，需要 hooks 时请手动在项目内配置。
    """
    mcp_path = home / ".cursor" / "mcp.json"
    mcp = _read_json(mcp_path)
    mcp.setdefault("mcpServers", {})["cwiki"] = _mcp_server("cursor")
    _write_json(mcp_path, mcp, dry_run)


def install_codex(home: Path, dry_run: bool) -> None:
    config = home / ".codex" / "config.toml"
    block = f"""# cwiki:begin
[mcp_servers.cwiki]
command = {json.dumps(sys.executable)}
args = ["-m", "adapters.mcp"]
env = {{ PYTHONPATH = {json.dumps(str(ROOT))}, CWIKI_HOST = "codex" }}
# cwiki:end
"""
    existing = config.read_text(encoding="utf-8") if config.exists() else ""
    if "# cwiki:begin" in existing or "# cwiki:end" in existing:
        if existing.count("# cwiki:begin") != 1 or existing.count("# cwiki:end") != 1:
            raise SystemExit(
                f"broken cwiki markers in {config}; "
                "remove duplicate or reversed cwiki:begin / cwiki:end markers and retry"
            )
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
    parser.add_argument("--home", type=Path, default=Path.home(), help="测试用 home 覆盖")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    print(f"host={args.host} home={home}")
    if args.host == "claude":
        install_claude(home, args.dry_run)
    elif args.host == "cursor":
        install_cursor(home, args.dry_run)
    else:
        install_codex(home, args.dry_run)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
