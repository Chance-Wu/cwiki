"""memory_search 的读路径策略：本地优先、弱命中回落 API、API 不可用降级。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from adapters.mcp.mcp_server import MCPServer
from adapters.mcp.outbox import WriteAheadOutbox


@pytest.fixture
def server(tmp_path):
    client = AsyncMock()
    instance = MCPServer(client)
    instance.outbox = WriteAheadOutbox(tmp_path / "outbox")
    return instance, client


def _local(strong: bool) -> dict:
    if not strong:
        return {
            "available": True,
            "source": "local",
            "results": [],
            "total": 0,
            "insufficient": True,
            "reason": "no_relevant_match",
        }
    return {
        "available": True,
        "source": "local",
        "results": [{"id": "m1", "title": "Redis", "content": "x", "score": 1.0, "coverage": 0.9}],
        "total": 1,
        "insufficient": False,
    }


async def test_strong_local_hit_skips_api(server):
    instance, client = server
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(True)):
        result = await instance._handle_tool("memory_search", {"keyword": "redis"})
    assert result["source"] == "local"
    assert result["results"][0]["id"] == "m1"
    assert "degraded" not in result
    client.search.assert_not_called()


async def test_weak_local_hit_falls_through_to_api(server):
    instance, client = server
    client.search.return_value = {"results": [{"id": "api-1"}], "total": 1}
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(False)):
        result = await instance._handle_tool("memory_search", {"keyword": "redis"})
    assert result["results"][0]["id"] == "api-1"
    client.search.assert_called_once()


async def test_weak_local_hit_degrades_when_api_down(server):
    instance, client = server
    client.search.side_effect = httpx.ConnectError("api down")
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(False)):
        result = await instance._handle_tool("memory_search", {"keyword": "redis"})
    assert result["degraded"] is True
    assert result["results"] == []
    assert any("本地只读索引" in warning for warning in result["warnings"])


async def test_semantic_search_stays_api_first(server):
    instance, client = server
    client.search.return_value = {"results": [{"id": "api-1"}], "total": 1}
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(True)) as local:
        await instance._handle_tool("memory_search", {"keyword": "redis", "mode": "semantic"})
    local.assert_not_called()
    assert client.search.call_args.kwargs["mode"] == "semantic"


async def test_semantic_search_falls_back_to_local(server):
    instance, client = server
    client.search.side_effect = httpx.ReadTimeout("timeout")
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(True)):
        result = await instance._handle_tool(
            "memory_search", {"keyword": "redis", "mode": "semantic"}
        )
    assert result["degraded"] is True
    assert any("semantic" in warning for warning in result["warnings"])


async def test_curated_strong_local_context_skips_api(server):
    instance, client = server
    local_context = {
        "available": True,
        "context": "## Redis\n\n内容",
        "items": [{"id": "m1", "metadata": {"coverage": 0.9}}],
        "total": 1,
        "source": "local",
    }
    with patch(
        "adapters.mcp.mcp_server.build_local_context", return_value=local_context
    ) as builder:
        result = await instance._handle_tool(
            "memory_search", {"keyword": "redis", "curated": True, "workspace_name": "web"}
        )
    assert result["items"][0]["id"] == "m1"
    assert "degraded" not in result
    assert builder.call_args.kwargs["workspace"] == "web"
    client.get_context.assert_not_called()


async def test_curated_weak_local_context_degrades_when_api_down(server):
    instance, client = server
    client.get_context.side_effect = httpx.ConnectError("api down")
    local_context = {
        "available": True,
        "context": "## Redis\n\n内容",
        "items": [{"id": "m1"}],
        "total": 1,
        "source": "local",
    }
    with patch("adapters.mcp.mcp_server.build_local_context", return_value=local_context):
        result = await instance._handle_tool(
            "memory_search", {"keyword": "redis", "curated": True, "workspace_name": "web"}
        )
    assert result["degraded"] is True
    assert result["items"][0]["id"] == "m1"


async def test_unavailable_local_index_reports_error(server):
    instance, client = server
    client.search.side_effect = httpx.ConnectError("api down")
    with patch(
        "adapters.mcp.mcp_server.search_local",
        return_value={"available": False, "reason": "database_not_found", "results": []},
    ):
        result = await instance._handle_tool("memory_search", {"keyword": "redis"})
    assert result["degraded"] is True
    assert "本地只读索引不可用" in result["error"]


async def test_client_error_is_not_masked_by_local_fallback(server):
    instance, client = server
    request = httpx.Request("POST", "http://test/v1/search")
    response = httpx.Response(400, request=request, json={"detail": "bad filter"})
    client.search.side_effect = httpx.HTTPStatusError(
        "bad request", request=request, response=response
    )
    with patch("adapters.mcp.mcp_server.search_local", return_value=_local(False)):
        result = await instance._handle_tool("memory_search", {"keyword": "redis"})
    assert "error" in result
    client.search.assert_called_once()
