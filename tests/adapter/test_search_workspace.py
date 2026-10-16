"""memory_search 的作用域路由：省略参数时跨全部工作区，显式指定时保持限定。

省略两个 workspace 键时必须把 ``workspace_id=None`` 透传给 client，
使召回可跨工作区；``workspace_name`` / ``workspace_id`` 参数则继续路由到
对应工作区。``curated=true`` 保持默认工作区回退，因为上下文组装始终
按工作区执行。
"""

from unittest.mock import AsyncMock

import pytest

from adapters.qoder.mcp_server import DEFAULT_WORKSPACE, MCPServer
from adapters.qoder.outbox import WriteAheadOutbox


@pytest.fixture
def server(tmp_path):
    client = AsyncMock()
    instance = MCPServer(client)
    instance.outbox = WriteAheadOutbox(tmp_path / "outbox")
    return instance, client


async def test_hybrid_search_without_workspace_is_global(server):
    instance, client = server
    client.search.return_value = {"results": [], "total": 0}
    await instance._handle_tool("memory_search", {"keyword": "跨库召回"})
    assert client.search.call_args.kwargs["workspace_id"] is None


async def test_hybrid_search_workspace_name_is_scoped(server):
    instance, client = server
    client.search.return_value = {"results": [], "total": 0}
    await instance._handle_tool("memory_search", {"keyword": "跨库召回", "workspace_name": "cwiki"})
    assert client.search.call_args.kwargs["workspace_id"] == "cwiki"


async def test_hybrid_search_workspace_id_alias_is_scoped(server):
    instance, client = server
    client.search.return_value = {"results": [], "total": 0}
    await instance._handle_tool("memory_search", {"keyword": "跨库召回", "workspace_id": "cwiki"})
    assert client.search.call_args.kwargs["workspace_id"] == "cwiki"


async def test_semantic_search_without_workspace_is_global(server):
    instance, client = server
    client.recall.return_value = {"results": [], "total": 0}
    await instance._handle_tool("memory_search", {"keyword": "跨库召回", "mode": "semantic"})
    assert client.recall.call_args.kwargs["workspace_id"] is None


async def test_semantic_search_workspace_name_is_scoped(server):
    instance, client = server
    client.recall.return_value = {"results": [], "total": 0}
    await instance._handle_tool(
        "memory_search", {"keyword": "跨库召回", "mode": "semantic", "workspace_name": "cwiki"}
    )
    assert client.recall.call_args.kwargs["workspace_id"] == "cwiki"


async def test_curated_without_workspace_falls_back_to_default(server):
    instance, client = server
    client.get_context.return_value = {"items": [], "total": 0}
    result = await instance._handle_tool("memory_search", {"keyword": "跨库召回", "curated": True})
    assert isinstance(result, dict)
    assert client.get_context.call_args.kwargs["workspace_id"] == DEFAULT_WORKSPACE


async def test_curated_workspace_name_is_scoped(server):
    instance, client = server
    client.get_context.return_value = {"items": [], "total": 0}
    await instance._handle_tool(
        "memory_search", {"keyword": "跨库召回", "curated": True, "workspace_name": "cwiki"}
    )
    assert client.get_context.call_args.kwargs["workspace_id"] == "cwiki"
