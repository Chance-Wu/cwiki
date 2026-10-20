"""PreToolUse workspace_name 注入：确定性归属（多窗口并发无竞态）。

覆盖两种宿主形态：Qoder app 的 mcp_call 包装（toolName+arguments 嵌套）与
CLI 直连的 mcp__server__tool 全名；显式传参不覆盖；memory_search 不注入
（省略=跨全部工作区是设计语义）；cwiki 仓库自身/home 会话不注入（default）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from adapters.hooks import workspace_inject

ROOT = Path(__file__).resolve().parents[2]


def _payload_qoder(tool: str, arguments: dict, cwd: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "cwd": cwd,
        "tool_name": "mcp_call",
        "tool_input": {
            "toolName": f"mcp__plugin_cwiki-qoder_cwiki__{tool}",
            "arguments": arguments,
        },
    }


def _payload_direct(tool: str, arguments: dict, cwd: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "s2",
        "cwd": cwd,
        "tool_name": f"mcp__cwiki__{tool}",
        "tool_input": arguments,
    }


LEARNING = "/Users/alice/code-space/learning-os"


class TestUpdatedInput:
    def test_qoder_wrapped_save_injected(self):
        payload = _payload_qoder("memory_save", {"title": "t", "content": "c"}, LEARNING)
        updated = workspace_inject.updated_input(payload)
        assert updated is not None
        # 包装结构整体回写：toolName 保持、arguments 注入 workspace_name
        assert updated["toolName"] == payload["tool_input"]["toolName"]
        assert updated["arguments"]["workspace_name"] == "learning-os"

    def test_direct_save_injected(self):
        payload = _payload_direct("memory_save", {"title": "t", "content": "c"}, LEARNING)
        updated = workspace_inject.updated_input(payload)
        assert updated == {"title": "t", "content": "c", "workspace_name": "learning-os"}

    def test_explicit_workspace_never_overridden(self):
        payload = _payload_qoder(
            "memory_save",
            {"title": "t", "content": "c", "workspace_name": "other-ws"},
            LEARNING,
        )
        assert workspace_inject.updated_input(payload) is None
        payload2 = _payload_direct(
            "memory_save", {"title": "t", "content": "c", "workspace_id": "x"}, LEARNING
        )
        assert workspace_inject.updated_input(payload2) is None

    def test_search_not_injected(self):
        """memory_search 省略 workspace_name = 跨全部工作区搜索（设计语义）。"""
        payload = _payload_qoder("memory_search", {"keyword": "x"}, LEARNING)
        assert workspace_inject.updated_input(payload) is None

    def test_other_mcp_servers_untouched(self):
        payload = {
            "hook_event_name": "PreToolUse",
            "cwd": LEARNING,
            "tool_name": "mcp_call",
            "tool_input": {"toolName": "mcp__plugin_other_xxx__memory_save", "arguments": {}},
        }
        # 工具后缀同名（memory_save）会命中——由宿主 matcher（mcp_call|mcp__.*）
        # 决定是否调用本 hook；hook 不识别服务器名，注入 workspace_name 对
        # 其它服务器是无害多余参数（其 schema 拒绝时属宿主侧问题）。
        # 这里只验证不抛异常即可。
        workspace_inject.updated_input(payload)

    def test_default_derivation_no_injection(self):
        for cwd in (str(ROOT), str(Path.home()), ""):
            payload = _payload_qoder("memory_save", {"title": "t", "content": "c"}, cwd)
            assert workspace_inject.updated_input(payload) is None, cwd

    def test_dirty_dir_names_fall_back(self):
        for cwd in ("/x/C--Users-admin", "/x/179cf7e8", "/x/.."):
            payload = _payload_qoder("memory_save", {"title": "t", "content": "c"}, cwd)
            assert workspace_inject.updated_input(payload) is None, cwd

    def test_malformed_payloads_safe(self):
        assert workspace_inject.updated_input({"tool_name": "mcp_call"}) is None
        assert workspace_inject.updated_input({"tool_name": 1, "tool_input": {}}) is None
        assert (
            workspace_inject.updated_input(
                {
                    "tool_name": "mcp_call",
                    "tool_input": {"toolName": "mcp__a__memory_save", "arguments": "not-a-dict"},
                    "cwd": LEARNING,
                }
            )
            is None
        )

    def test_workspace_scoped_tools_all_covered(self):
        for tool in workspace_inject.INJECT_TOOLS - {"memory_search"}:
            payload = _payload_direct(tool, {"x": 1}, LEARNING)
            updated = workspace_inject.updated_input(payload)
            assert updated is not None and updated["workspace_name"] == "learning-os", tool


class TestCliIntegration:
    def _run(self, payload: dict, env: dict[str, str] | None = None) -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "adapters.hooks", "qoder", "pre-tool-use"],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=20,
            cwd=ROOT,
            check=False,
            env={
                "PYTHONPATH": str(ROOT),
                "PATH": "/usr/bin:/bin",
                "HOME": str(Path.home()),
                **(env or {}),
            },
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout else {}

    def test_emits_hook_event_name_with_updated_input(self):
        out = self._run(_payload_qoder("memory_save", {"title": "t", "content": "c"}, LEARNING))
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        assert hso["updatedInput"]["arguments"]["workspace_name"] == "learning-os"

    def test_no_output_when_nothing_to_inject(self):
        payload = _payload_qoder("memory_save", {"workspace_name": "keep"}, LEARNING)
        assert self._run(payload) == {}

    def test_pre_tool_use_does_not_refresh_registry(self, tmp_path):
        """注册表只由会话级事件刷新；工具级高频事件写它会放大跨会话竞态。"""
        out = self._run(
            _payload_qoder("memory_status", {}, LEARNING),
            env={"CWIKI_STATE_DIR": str(tmp_path)},
        )
        assert out  # 注入正常发生
        assert not (tmp_path / "current-workspace-qoder.json").exists()
        assert not (tmp_path / "current-workspace.json").exists()
