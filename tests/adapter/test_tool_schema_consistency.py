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


async def test_conflicts_tools_route_to_client(server, monkeypatch):
    """memory_conflicts / memory_conflict_resolve 接通 HTTP 端点并校验入参。"""
    srv, client = server
    client.list_conflicts = AsyncMock(return_value=[{"id": "c1", "status": "open"}])
    client.resolve_conflict = AsyncMock(return_value={"id": "c1", "status": "resolved"})

    result = await srv._handle_tool("memory_conflicts", {"status": "open", "limit": 5})
    assert result["total"] == 1
    client.list_conflicts.assert_awaited_once_with(status="open", limit=5)
    assert "memory_conflict_resolve" in result["hint"]

    resolved = await srv._handle_tool(
        "memory_conflict_resolve",
        {"conflict_id": "c1", "resolution": "保留新结论：已用 memory_update 修正正文"},
    )
    assert resolved["status"] == "ok"
    client.resolve_conflict.assert_awaited_once()

    assert "error" in await srv._handle_tool("memory_conflicts", {"status": "bogus"})
    assert "error" in await srv._handle_tool("memory_conflicts", {"limit": 0})
    assert "error" in await srv._handle_tool(
        "memory_conflict_resolve", {"conflict_id": "c1", "resolution": "短"}
    )
    assert "error" in await srv._handle_tool(
        "memory_conflict_resolve", {"resolution": "足够长的裁决说明"}
    )


async def test_health_and_review_manage_route_to_client(server):
    """memory_health / memory_review_manage 接通端点、区分聚合与单条并校验入参。"""
    srv, client = server
    client.get_health_summary = AsyncMock(
        return_value={"total": 3, "avg_score": 0.8, "distribution": {"healthy": 3}, "reasons": []}
    )
    client.get_memory_health = AsyncMock(
        return_value={
            "memory_id": "m1",
            "utility": {"utility": 0.6},
            "health": {"status": "healthy", "score": 0.9},
        }
    )
    client.manage_review = AsyncMock(return_value={"memory_id": "m1", "next_review_at": None})

    summary = await srv._handle_tool("memory_health", {})
    assert summary["total"] == 3
    # 聚合默认全局：workspace_id 缺省时不带过滤，避免小工作区恒为 0
    assert summary["workspace_id"] == "all"
    client.get_health_summary.assert_awaited_once_with(workspace_id=None)
    await srv._handle_tool("memory_health", {"workspace_name": "cwiki"})
    assert client.get_health_summary.await_args.kwargs["workspace_id"] == "cwiki"

    single = await srv._handle_tool("memory_health", {"memory_id": "m1"})
    assert single["health"]["status"] == "healthy"
    assert single["memory_id"] == "m1"
    client.get_memory_health.assert_awaited_once_with("m1")

    managed = await srv._handle_tool(
        "memory_review_manage", {"memory_id": "m1", "action": "postpone", "days": 7}
    )
    assert managed["days"] == 7
    client.manage_review.assert_awaited_once_with(
        memory_id="m1", action="postpone", workspace_id="ws", days=7
    )

    assert "error" in await srv._handle_tool("memory_health", {"memory_id": 1})
    assert "error" in await srv._handle_tool("memory_review_manage", {"memory_id": "m1"})
    assert "error" in await srv._handle_tool(
        "memory_review_manage", {"memory_id": "m1", "action": "erase"}
    )
    assert "error" in await srv._handle_tool(
        "memory_review_manage", {"memory_id": "m1", "action": "postpone", "days": 0}
    )


async def test_review_quiz_and_answer_submission_route_to_client(server):
    """memory_review_quiz 取题；memory_review_submit 有 answers 时走判分。"""
    srv, client = server
    client.get_review_quiz = AsyncMock(
        return_value={
            "memory_id": "m1",
            "kind": "cloze",
            "prompt": "WAL 需要 [[1]]",
            "blank_count": 1,
        }
    )
    client.submit_review_quiz = AsyncMock(
        return_value={"quality": 4, "correct": 1, "total": 1, "next_review_at": None}
    )
    client.submit_review = AsyncMock(return_value={"quality": 2, "next_review_at": None})

    quiz = await srv._handle_tool("memory_review_quiz", {"memory_id": "m1"})
    assert quiz["quiz"]["blank_count"] == 1
    client.get_review_quiz.assert_awaited_once_with("m1", "ws")

    graded = await srv._handle_tool(
        "memory_review_submit", {"memory_id": "m1", "answers": ["checkpoint"]}
    )
    assert graded["quality"] == 4
    client.submit_review_quiz.assert_awaited_once_with("m1", ["checkpoint"], "ws")
    client.submit_review.assert_not_awaited()

    rated = await srv._handle_tool("memory_review_submit", {"memory_id": "m1", "quality": 2})
    assert rated["quality"] == 2
    client.submit_review.assert_awaited_once_with(memory_id="m1", quality=2, workspace_id="ws")

    assert "error" in await srv._handle_tool("memory_review_quiz", {})
    assert "error" in await srv._handle_tool(
        "memory_review_submit", {"memory_id": "m1", "answers": []}
    )
    assert "error" in await srv._handle_tool(
        "memory_review_submit", {"memory_id": "m1", "answers": ["a", 1]}
    )
    assert "error" in await srv._handle_tool("memory_review_submit", {"memory_id": "m1"})
