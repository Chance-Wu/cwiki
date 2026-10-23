"""MCP 标签参数的协议契约测试。"""

from adapters.mcp.client import CwikiClient
from adapters.mcp.tool_definitions import build_tool_definitions


def _tools() -> dict[str, dict]:
    return {tool["name"]: tool for tool in build_tool_definitions()}


def test_save_update_and_search_expose_tags() -> None:
    tools = _tools()

    assert "tags" in tools["memory_save"]["inputSchema"]["properties"]
    assert "tags" in tools["memory_update"]["inputSchema"]["properties"]
    search_filters = tools["memory_search"]["inputSchema"]["properties"]["filters"]
    assert "tags" in search_filters["properties"]


def test_save_exposes_permanent_flags() -> None:
    props = _tools()["memory_save"]["inputSchema"]["properties"]

    assert props["is_permanent"]["type"] == "boolean"
    assert "permanent_reason" in props


async def test_client_submit_candidate_forwards_permanent(monkeypatch) -> None:
    client = CwikiClient("http://127.0.0.1:5172")
    captured: dict = {}

    async def fake_request(method, path, *, json_body=None, **kwargs):
        captured["body"] = json_body
        return {"candidate": {}}

    monkeypatch.setattr(client, "_request", fake_request)

    await client.submit_candidate(
        title="永久记忆",
        content="用户指定长期保留的内容",
        memory_type="fact",
        workspace_id="ws-1",
        is_permanent=True,
        permanent_reason="用户指定",
    )

    assert captured["body"]["is_permanent"] is True
    assert captured["body"]["permanent_reason"] == "用户指定"


async def test_client_search_forwards_tags(monkeypatch) -> None:
    client = CwikiClient("http://127.0.0.1:5172")
    captured: dict = {}

    async def fake_request(method, path, *, json_body=None, **kwargs):
        captured["body"] = json_body
        return {"results": []}

    monkeypatch.setattr(client, "_request", fake_request)

    await client.search("标签检索", None, tags=["cwiki"])

    assert captured["body"]["tags"] == ["cwiki"]
