"""Adapter 单测隔离：不读取真实 ~/.cwiki/state 的动态工作区注册表。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_dynamic_workspace(monkeypatch, tmp_path):
    from adapters.mcp import mcp_server

    monkeypatch.setattr(
        mcp_server, "_DYNAMIC_WS_FILE", tmp_path / "state" / "current-workspace.json"
    )
