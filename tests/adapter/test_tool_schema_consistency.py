"""工具 schema 与实现常量的契约一致性：防描述与实现再次漂移。"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from adapters.mcp import mcp_server
from adapters.mcp.tool_definitions import build_tool_definitions
from packages.domain.types import MIN_CONTENT_LENGTH

_TOOLS = {tool["name"]: tool for tool in build_tool_definitions()}


def _props(name: str) -> dict:
    return _TOOLS[name]["inputSchema"]["properties"]


def test_memory_save_min_length_matches_domain_constant() -> None:
    assert _props("memory_save")["content"]["minLength"] == MIN_CONTENT_LENGTH


def test_search_mode_enum_matches_implementation() -> None:
    props = _props("memory_search")
    assert set(props["mode"]["enum"]) == {"hybrid", "semantic"}
    # curated 后端上限 50，schema 描述必须提示（实现会夹紧到 50）
    assert "50" in props["limit"]["description"]


def test_memory_tags_limit_default_matches_client() -> None:
    props = _props("memory_tags")
    assert props["limit"]["default"] == 20
    assert "按标签过滤时" in props["limit"]["description"]


@pytest.fixture
def server():
    client = Mock()
    client.get_context = AsyncMock(return_value={"items": [], "context": ""})
    srv = mcp_server.MCPServer(client)
    srv.session_workspace = "ws"
    return srv, client


async def test_curated_limit_clamped_to_backend_max(server, monkeypatch):
    srv, client = server
    monkeypatch.setattr(srv, "_local_context_lookup", AsyncMock(return_value=None))

    await srv._handle_tool("memory_search", {"keyword": "x", "curated": True, "limit": 100})

    assert client.get_context.call_args.kwargs["max_items"] == 50
