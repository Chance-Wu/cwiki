"""动态工作区注册表：hook 写入 → MCP 解析到 Agent 当前项目。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str], payload: dict | None, state_dir: Path):
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "CWIKI_HOOK_STATE_DIR": str(state_dir / "spool"),
        "CWIKI_STATE_DIR": str(state_dir),
        "CWIKI_API_URL": "http://127.0.0.1:9",
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


def test_hook_updates_registry_and_mcp_reads_it(tmp_path):
    state = tmp_path / "state"
    # hook 在项目 A 触发
    r1 = _run(
        ["qoder", "user-prompt-submit"],
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "在项目里干活",
            "cwd": "/Users/alice/code-space/msp-caa",
        },
        state,
    )
    assert r1.returncode == 0
    registry = json.loads((state / "current-workspace-qoder.json").read_text())
    assert registry["workspace"] == "msp-caa"
    assert registry["host"] == "qoder"

    # MCP 读到动态工作区（CWIKI_HOST=qoder → 读本宿主的 per-host 文件）
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, '.'); "
                "from adapters.mcp.mcp_server import current_workspace; "
                "print(current_workspace())"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "CWIKI_STATE_DIR": str(state),
            "CWIKI_HOST": "qoder",
        },
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "msp-caa"


def test_registry_isolated_between_hosts(tmp_path):
    """qoder 写 msp-caa、claude 写别的区：各宿主只解析到自己 hook 的项目。"""
    state = tmp_path / "state"
    state.mkdir(parents=True)
    now = time.time()
    (state / "current-workspace-qoder.json").write_text(
        json.dumps({"workspace": "msp-caa", "host": "qoder", "updated_at": now})
    )
    (state / "current-workspace-claude.json").write_text(
        json.dumps({"workspace": "other-proj", "host": "claude", "updated_at": now})
    )

    def resolve(host: str) -> str:
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, '.'); "
                    "from adapters.mcp.mcp_server import current_workspace; "
                    "print(current_workspace())"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "CWIKI_STATE_DIR": str(state),
                "CWIKI_HOST": host,
            },
        )
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    assert resolve("qoder") == "msp-caa"
    assert resolve("claude") == "other-proj"


def test_legacy_shared_registry_only_matches_own_host(tmp_path):
    """旧版共享文件：host 与本宿主不符 → 忽略（兼容未重启的旧 hook，但不串区）。"""
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "current-workspace.json").write_text(
        json.dumps({"workspace": "qoder-proj", "host": "qoder", "updated_at": time.time()})
    )

    def resolve(host: str) -> str:
        r = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, '.'); "
                    "from adapters.mcp.mcp_server import current_workspace; "
                    "print(current_workspace())"
                ),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "CWIKI_STATE_DIR": str(state),
                "CWIKI_HOST": host,
            },
        )
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    assert resolve("qoder") == "qoder-proj"  # host 匹配 → 兼容读取
    assert resolve("claude") == "default"  # host 不符 → 忽略，回落静态


def test_stale_registry_falls_back_to_static(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "current-workspace-qoder.json").write_text(
        json.dumps({"workspace": "old-project", "host": "qoder", "updated_at": time.time() - 9999})
    )
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; sys.path.insert(0, '.'); "
                "from adapters.mcp.mcp_server import current_workspace; "
                "print(current_workspace())"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "CWIKI_STATE_DIR": str(state),
            "CWIKI_HOST": "qoder",
        },
    )
    assert r.returncode == 0
    # 过期注册 → 回落静态推导（本测试环境无 env → default）
    assert r.stdout.strip() == "default"


def test_repo_root_binds_cwiki_workspace(tmp_path):
    """cwiki 仓库自身也是合法项目：hook cwd=仓库根 → 注册表写 cwiki。"""
    state = tmp_path / "state"
    _run(
        ["qoder", "user-prompt-submit"],
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s2",
            "prompt": "x" * 20,
            "cwd": str(ROOT),
        },
        state,
    )
    registry = json.loads((state / "current-workspace-qoder.json").read_text())
    assert registry["workspace"] == "cwiki"


def test_home_workspace_not_written_by_hook(tmp_path):
    """home 目录不是项目：hook 不应写注册表。"""
    state = tmp_path / "state"
    _run(
        ["qoder", "user-prompt-submit"],
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s3",
            "prompt": "x" * 20,
            "cwd": str(Path.home()),
        },
        state,
    )
    assert not (state / "current-workspace.json").exists()
    assert not (state / "current-workspace-qoder.json").exists()


def test_roots_list_sets_server_workspace(tmp_path):
    """宿主经 roots/list 声明项目根 → MCP 实例记住该工作区。"""
    import asyncio
    from unittest.mock import Mock

    from adapters.mcp.mcp_server import MCPServer

    async def run():
        server = MCPServer(Mock())
        resp = await server.handle_message(
            {
                "id": 1,
                "method": "roots/list",
                "params": {
                    "roots": [
                        {
                            "uri": "file:///Users/alice/code-space/heilan-msp-hongkong",
                            "name": "heilan",
                        },
                    ]
                },
            }
        )
        assert resp["result"]["roots"]
        return server

    server = asyncio.run(run())
    assert server.roots_workspace == "heilan-msp-hongkong"
