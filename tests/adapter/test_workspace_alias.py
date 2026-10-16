"""MCP workspace 参数别名。

文档与工具 schema 使用 ``workspace_name``，而 _handle_tool 仍接受历史上
的 ``workspace_id`` 写法，以兼容绕过 schema 校验的调用方。两个键必须能
路由到所有工作区作用域的工具（并回退到默认工作区），且对下标取键的
handler 不会抛 KeyError。
"""

from unittest.mock import AsyncMock

import pytest

from adapters.qoder.mcp_server import DEFAULT_WORKSPACE, MCPServer
from adapters.qoder.outbox import WriteAheadOutbox

TITLE = "Workspace alias regression"
CONTENT = "workspace_id 键与 workspace_name 键必须被同等解析并路由到同一工作区"


@pytest.fixture
def server(tmp_path):
    client = AsyncMock()
    instance = MCPServer(client)
    instance.outbox = WriteAheadOutbox(tmp_path / "outbox")
    return instance, client


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"workspace_id": "cwiki"}, "cwiki"),
        ({"workspace_name": "msp-caa"}, "msp-caa"),
        ({}, DEFAULT_WORKSPACE),
    ],
)
async def test_export_routes_both_keys_and_default(server, arguments, expected):
    instance, client = server
    client.export_data.return_value = {"memories": [], "exported_at": "t"}
    result = await instance._handle_tool("memory_export", arguments)
    assert client.export_data.call_args.args[0] == expected
    assert result["workspace_id"] == expected


async def test_review_handlers_accept_workspace_id_key(server):
    instance, client = server
    client.get_review_stats.return_value = {"total": 0}
    stats = await instance._handle_tool("memory_review_stats", {"workspace_id": "cwiki"})
    assert client.get_review_stats.call_args.kwargs["workspace_id"] == "cwiki"
    assert stats["workspace_id"] == "cwiki"

    client.get_due_reviews.return_value = []
    due = await instance._handle_tool("memory_review_due", {"workspace_id": "cwiki"})
    assert client.get_due_reviews.call_args.kwargs["workspace_id"] == "cwiki"
    assert due["workspace_id"] == "cwiki"


async def test_checkpoint_subscript_key_never_raises(server):
    instance, client = server
    client.agent_session_id = "sess-1"
    client.event_session_id = None
    client.list_session_notes.return_value = []
    result = await instance._handle_tool("memory_checkpoint", {"workspace_id": "cwiki"})
    assert isinstance(result, dict)
    assert client.list_session_notes.call_args.kwargs["workspace_id"] == "cwiki"


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"workspace_id": "cwiki"}, "cwiki"),
        ({"workspace_name": "msp-caa"}, "msp-caa"),
        ({}, "session-ws"),
    ],
)
async def test_save_workspace_precedence(server, arguments, expected):
    instance, client = server
    client.submit_candidate.return_value = {"candidate": {"id": "c1"}, "similar_items": []}
    instance.session_workspace = "session-ws"
    await instance._handle_tool("memory_save", {"title": TITLE, "content": CONTENT, **arguments})
    assert client.submit_candidate.call_args.kwargs["workspace_id"] == expected


async def test_status_accepts_workspace_id_key(server):
    instance, client = server
    client.get_memory_status.return_value = {"status": "ok"}
    await instance._handle_tool("memory_status", {"workspace_id": "cwiki"})
    assert client.get_memory_status.call_args.kwargs["workspace_id"] == "cwiki"
