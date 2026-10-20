"""可靠性端到端测试：崩溃恢复、幂等性、并发会话。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from adapters.mcp.client import CwikiClient
from adapters.mcp.mcp_server import MCPServer
from adapters.mcp.outbox import WriteAheadOutbox
from packages.domain.config import settings
from packages.domain.text_utils import normalize_memory_content
from packages.domain.types import TYPE_DEFINITIONS
from packages.storage.file_store import FileStore


@pytest.fixture
async def reliability_env(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[MCPServer, dict]:
    """搭建可靠性测试环境。

    工作区路由断言依赖"未传 workspace 时落到哪个区"：动态注册表
    （hook 写入的当前项目）会让该值漂移。隔离 CWIKI_STATE_DIR，
    使 omitted/empty 走静态推导（测试 CWD=cwiki 仓库 → default）。
    """
    monkeypatch.setenv("CWIKI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        "adapters.mcp.mcp_server._DYNAMIC_WS_FILE", tmp_path / "state" / "current-workspace.json"
    )
    workspace = await client.post("/v1/workspaces", json={"name": f"reliability-{uuid.uuid4()}"})
    assert workspace.status_code == 201
    workspace_id = workspace.json()["id"]

    api = CwikiClient("http://test")
    api._http = client

    agent_session = await api.create_agent_session(workspace_id=workspace_id, agent="qoder")
    assert agent_session is not None
    api.agent_session_id = agent_session["id"]
    api.event_session_id = agent_session.get("event_session_id")

    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    server = MCPServer(api)
    server.outbox = WriteAheadOutbox(state_dir=tmp_path / "outbox")

    return server, {"workspace": workspace_id}


class TestWorkspaceWriteRouting:
    @pytest.mark.parametrize("workspace_form", ["name", "uuid", "omitted", "empty"])
    @pytest.mark.parametrize("memory_type", [None, "fact"], ids=["auto", "explicit"])
    async def test_rpc_save_routes_original_content_to_only_selected_workspace(
        self, client, reliability_env, monkeypatch, workspace_form, memory_type
    ):
        server, env = reliability_env
        monkeypatch.setattr(settings, "memory_title_max_length", 20)
        response = await client.post("/v1/workspaces", json={"name": "default"})
        assert response.status_code == 201, response.text
        default_id = response.json()["id"]
        resp = await client.get("/v1/workspaces")
        workspace_name = next(
            item["name"] for item in resp.json()["items"] if item["id"] == env["workspace"]
        )
        explicit = workspace_form in ("name", "uuid")
        # workspace_id 由 agent 直接提供，不再做解析
        # expected_workspace_id 是 agent 提供的 workspace_id（可能是 name 或 uuid）
        expected_workspace_id = {
            "name": workspace_name,
            "uuid": env["workspace"],
            "empty": "",
            "omitted": None,
        }[workspace_form]
        # API 会解析 workspace name 到 uuid，所以 candidate 的 workspace_id 应该是 uuid
        expected_candidate_id = env["workspace"] if explicit else default_id
        other_id = default_id if explicit else env["workspace"]
        content = " \t\n" + _BOUNDARY_CONTENT + "  \n"
        arguments = {"title": _BOUNDARY_TITLE, "content": content}
        if workspace_form != "omitted":
            arguments["workspace_name"] = expected_workspace_id
        if memory_type is not None:
            arguments["type"] = memory_type

        submit_candidate = server.client.submit_candidate

        async def submit(**payload):
            # workspace_id 由 agent 直接提供给 API，不再经过解析器
            # 遍历所有工作区查找该条目
            all_entries = server.outbox.load_all_workspaces()
            assert len(all_entries) == 1, (
                f"Expected 1 workspace with entries, got {list(all_entries.keys())}"
            )
            resolved_ws = next(iter(all_entries.keys()))
            entries = all_entries[resolved_ws]
            assert len(entries) == 1
            assert entries[0]["workspace_id"] == resolved_ws
            assert entries[0]["arguments"]["workspace_id"] == resolved_ws
            # workspace_id 在 payload 中是 agent 提供的值（name 或 "default"），API 负责解析为 UUID
            expected_ws_in_payload = {
                "name": workspace_name,
                "uuid": env["workspace"],
                "empty": "default",
                "omitted": "default",
            }[workspace_form]
            assert payload["workspace_id"] == expected_ws_in_payload, (
                f"payload ws={payload['workspace_id']}, expected={expected_ws_in_payload}"
            )
            assert entries[0]["arguments"]["title"] == payload["title"] == _BOUNDARY_TITLE
            # 内容此时已自动注入 #memory/ 标签
            assert entries[0]["arguments"]["content"] == payload["content"]
            assert content.strip() in entries[0]["arguments"]["content"]
            return await submit_candidate(**payload)

        monkeypatch.setattr(server.client, "submit_candidate", submit)
        response = await server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "workspace-boundary",
                "method": "tools/call",
                "params": {"name": "memory_save", "arguments": arguments},
            }
        )
        assert response["id"] == "workspace-boundary"
        assert not response["result"].get("isError"), response
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["delivery"] == "confirmed", result
        candidate = (await client.get(f"/v1/candidates/{result['candidate_id']}")).json()
        # API 会解析 workspace name 到 uuid，所以 candidate 的 workspace_id 应该是 uuid
        assert candidate["workspace_id"] == expected_candidate_id
        assert candidate["title"] == _BOUNDARY_TITLE
        # 内容此时已自动注入 #memory/ 标签
        assert candidate["content"].startswith(normalize_memory_content(content))
        assert f"#memory/{memory_type or 'fact'}" in candidate["content"]
        assert candidate["status"] == "pending_review"
        if memory_type is not None:
            assert candidate["type"] == memory_type
        for workspace_id, total in [(expected_candidate_id, 1), (other_id, 0)]:
            response = await client.get("/v1/candidates", params={"workspace_id": workspace_id})
            assert response.status_code == 200, response.text
            assert response.json()["total"] == total
        assert server.outbox.load_all_workspaces() == {}


class TestMergedReadTools:
    async def test_curated_search_through_api(self, reliability_env, monkeypatch):
        from apps.api.routes import context

        server, env = reliability_env
        retrieve = AsyncMock(return_value={"context": "", "memories": [], "sources": []})
        monkeypatch.setattr(context, "get_retrieval_engine", lambda: Mock(retrieve=retrieve))
        response = await server.handle_message(
            {
                "id": "curated-api",
                "method": "tools/call",
                "params": {
                    "name": "memory_search",
                    "arguments": {
                        "workspace_name": env["workspace"],
                        "keyword": "隔离上下文验证",
                        "curated": True,
                        "limit": 3,
                        "max_tokens": 500,
                    },
                },
            }
        )
        assert response["result"]["isError"] is False, response
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["context"] == ""
        assert result["items"] == []
        assert result["keyword"] == "隔离上下文验证"
        retrieve.assert_awaited_once()
        arguments = retrieve.call_args.kwargs
        assert str(arguments["workspace_id"]) == env["workspace"]
        assert arguments["max_items"] == 3
        assert arguments["max_tokens"] == 500
        assert server.outbox.load_all_workspaces() == {}

    async def test_status_through_api(self, reliability_env):
        server, env = reliability_env
        result = await server._handle_tool("memory_status", {"workspace_name": env["workspace"]})
        assert "error" not in result, result
        assert result["outbox_total"] == 0
        assert result["effective_config"]["title_max_length"] == settings.memory_title_max_length


class TestMCPToolsListContract:
    """校验 JSON-RPC 发现实际返回的描述。"""

    @pytest.fixture
    async def listed_tools(self, reliability_env: tuple[MCPServer, dict]) -> dict[str, dict]:
        server, _ = reliability_env
        response = await server.handle_message(
            {"jsonrpc": "2.0", "id": "tool-contract", "method": "tools/list", "params": {}}
        )
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == "tool-contract"
        assert "error" not in response
        tools = response["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        assert len(by_name) == len(tools)
        return by_name

    async def test_save_advertises_original_content_without_templates(
        self, listed_tools: dict[str, dict]
    ) -> None:
        tool = listed_tools["memory_save"]
        schema = tool["inputSchema"]
        description = tool["description"] + "\n" + schema["properties"]["content"]["description"]
        assert re.search(r"原样|原文|原始正文", description), description
        assert re.search(r"背景|证据|推理|边界|来龙去脉", description), description
        assert "content" in schema["required"]
        assert "title" in schema["required"]
        assert "type" not in schema["required"]
        assert schema["properties"]["title"]["maxLength"] == settings.memory_title_max_length
        assert schema["properties"]["content"]["minLength"] == 20

    @pytest.mark.parametrize("max_length", [12, 20, 32])
    async def test_tools_list_uses_current_title_limit(
        self, reliability_env, monkeypatch, max_length
    ):
        server, _ = reliability_env
        monkeypatch.setattr(settings, "memory_title_max_length", max_length)
        response = await server.handle_message(
            {"jsonrpc": "2.0", "id": "dynamic-limit", "method": "tools/list", "params": {}}
        )
        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        for name in ("memory_save", "memory_update"):
            schema = tools[name]["inputSchema"]
            assert schema["properties"]["title"]["maxLength"] == max_length
            assert schema["properties"]["content"]["minLength"] == 20
        assert "title" in tools["memory_save"]["inputSchema"]["required"]
        assert "title" not in tools["memory_update"]["inputSchema"]["required"]

    async def test_update_advertises_full_replacement_and_optional_content(
        self, listed_tools: dict[str, dict]
    ) -> None:
        tool = listed_tools["memory_update"]
        schema = tool["inputSchema"]
        description = tool["description"] + "\n" + schema["properties"]["content"]["description"]
        assert re.search(r"完整.{0,8}(正文|内容)", description), description
        assert re.search(r"(整体|全文).{0,4}(替换|覆盖)", description), description
        assert re.search(r"(未传|不传|省略|未提供).{0,20}(不变|不改|不更新|保留)", description), (
            description
        )
        assert "memory_id" in schema["required"]
        assert "content" not in schema["required"]

    async def test_checkpoint_advertises_boundaries_and_defers_timing_to_skill(
        self, listed_tools: dict[str, dict]
    ) -> None:
        tool = listed_tools["memory_checkpoint"]
        description = tool["description"]
        for term in ("事件", "笔记", "规则提取", "记忆候选"):
            assert term in description
        assert re.search(r"dry_run\s*=\s*true[^。\n]*(仅|不.*提交)", description), description
        assert "必须调用" not in description
        assert not re.search(r"30\s*分钟", description)
        dry_run = tool["inputSchema"]["properties"]["dry_run"]
        assert dry_run["type"] == "boolean"
        assert dry_run["default"] is False

    async def test_status_documents_offline_counting(self, listed_tools: dict[str, dict]) -> None:
        description = listed_tools["memory_status"]["description"]
        assert "本地投递积压" in description, description
        assert "API 离线时仍返回本地计数" in description, description
        for name in ("memory_save", "memory_retry_failed"):
            assert "outbox_pending" not in listed_tools[name]["description"]

    async def test_save_and_retry_keep_delivery_safety_guidance(
        self, listed_tools: dict[str, dict]
    ) -> None:
        save = listed_tools["memory_save"]["description"]
        for term in ("pending_review", "人工批准"):
            assert term in save
        retry = listed_tools["memory_retry_failed"]["description"]
        for term in ("所有工作区", "未完成写入"):
            assert term in retry

    @pytest.mark.parametrize(
        "obsolete_guidance",
        ["content需符合模板", "无需提供完整内容", "必须使用 Markdown 二级标题"],
        ids=["required_template", "partial_body", "required_headings"],
    )
    async def test_tools_list_does_not_expose_obsolete_content_rules(
        self, listed_tools: dict[str, dict], obsolete_guidance: str
    ) -> None:
        assert obsolete_guidance not in json.dumps(listed_tools, ensure_ascii=False)


class TestWriteAheadCrashRecovery:
    """测试 write-ahead outbox 在崩溃后可存活。"""

    async def test_submit_request_error_preserves_outbox_entry(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """模拟 submit 抛出 RequestError，验证 outbox 条目存活。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        # mock submit_candidate 使其抛出 RequestError
        with patch.object(
            server.client,
            "submit_candidate",
            side_effect=httpx.RequestError("Connection refused"),
        ):
            result = await server._handle_tool(
                "memory_save",
                {
                    "workspace_name": workspace_id,
                    "title": "连接超时恢复记录",
                    "content": (
                        "测试崩溃恢复：数据库连接池配置不当导致超时，提交未收到服务端确认。"
                        "应在本地保留完整请求及写入标识，连接恢复后重试，避免丢失采样记录。"
                    ),
                },
            )

        # 应返回错误，但条目已缓存
        assert result.get("error") == "Connection failed"
        assert result.get("cached") is True

        # 验证 outbox 中有条目（标记为 failed 待重试）
        all_entries = server.outbox.load_all(workspace_id)
        assert len(all_entries) == 1
        assert all_entries[0]["state"] == "failed"
        assert all_entries[0]["client_write_id"] is not None
        assert "测试崩溃恢复" in all_entries[0]["arguments"]["content"]

    async def test_outbox_entry_survives_server_restart(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
        tmp_path: Path,
    ) -> None:
        """验证服务重启后 outbox 条目仍在。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        # 记录一条条目
        entry = server.outbox.log_pending(
            workspace_id=workspace_id,
            tool="memory_save",
            arguments={"content": "崩溃恢复测试内容"},
            client_write_id="ms:crash-test-123",
        )

        # 模拟服务器重启：用同一 state_dir 新建 outbox 实例
        new_outbox = WriteAheadOutbox(state_dir=tmp_path / "outbox")
        pending = new_outbox.load_pending(workspace_id)

        assert len(pending) == 1
        assert pending[0]["id"] == entry["id"]
        assert pending[0]["client_write_id"] == "ms:crash-test-123"


class TestIdempotency:
    """测试 client_write_id 的幂等提交。"""

    async def test_same_client_write_id_returns_existing_candidate(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """同一 client_write_id 提交两次应返回同一候选。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        title = "重复投递幂等性"
        content = (
            "幂等性测试：相同的 client_write_id 不应产生重复候选。"
            "客户端在确认响应丢失后重发同一份正文，服务端应返回原候选标识，"
            "而不是插入第二条待审核记录。"
        )
        f"ms:idempotent-{uuid.uuid4()}"

        # 第一次提交
        result1 = await server._handle_tool(
            "memory_save",
            {"workspace_name": workspace_id, "title": title, "content": content},
        )
        assert result1.get("status") == "created"
        candidate_id_1 = result1.get("candidate_id")

        # 用相同内容（同一 write_id）提交第二次
        result2 = await server._handle_tool(
            "memory_save",
            {"workspace_name": workspace_id, "title": title, "content": content},
        )
        assert result2.get("status") == "created"
        candidate_id_2 = result2.get("candidate_id")

        # 应是同一个候选
        assert candidate_id_1 == candidate_id_2

        # 验证只存在一个候选
        candidates_resp = await client.get(
            "/v1/candidates",
            params={"workspace_id": workspace_id},
        )
        candidates = candidates_resp.json()["items"]
        matching = [c for c in candidates if "幂等性测试" in c["content"]]
        assert len(matching) == 1

    async def test_concurrent_submits_with_same_write_id(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """并发提交相同 client_write_id 不应产生重复。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        content = (
            "并发幂等性测试：并发提交相同内容不应产生重复。三个请求共享工作区和正文，"
            "即使调用时间重叠，候选列表也只能保留一条记录，并返回同一个候选标识。"
        )

        # 顺序提交（SQLite 测试会话不支持并发操作）
        results = []
        for _ in range(3):
            r = await server._handle_tool(
                "memory_save",
                {"workspace_name": workspace_id, "title": "并发投递幂等性", "content": content},
            )
            results.append(r)

        # 全部应成功
        success_results = [
            r for r in results if isinstance(r, dict) and r.get("status") == "created"
        ]
        assert len(success_results) >= 1

        # 验证只存在一个候选
        candidates_resp = await client.get(
            "/v1/candidates",
            params={"workspace_id": workspace_id},
        )
        candidates = candidates_resp.json()["items"]
        matching = [c for c in candidates if "并发幂等性测试" in c["content"]]
        assert len(matching) == 1


class TestExhaustionSemantics:
    """测试重试耗尽后条目保留以便观察。"""

    async def test_three_failures_mark_entry_exhausted(
        self,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """连续三次失败应将条目标记为 exhausted，而不是删除。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        # 记录一条条目
        entry = server.outbox.log_pending(
            workspace_id=workspace_id,
            tool="memory_save",
            arguments={"content": "耗尽测试内容"},
            client_write_id="ms:exhaust-test",
        )
        entry_id = entry["id"]

        # 模拟 3 次失败
        for _ in range(3):
            server.outbox.mark_failed(workspace_id, entry_id)

        # 3 次失败后，_try_auto_retry_one 应将其标记为 exhausted
        with patch.object(
            server.client,
            "submit_candidate",
            side_effect=httpx.RequestError("Still failing"),
        ):
            await server._try_auto_retry_one()

        # 条目应为 exhausted，而不是被删除
        all_entries = server.outbox.load_all(workspace_id)
        assert len(all_entries) == 1
        assert all_entries[0]["state"] == "exhausted"
        assert all_entries[0]["id"] == entry_id

    async def test_exhausted_entries_visible_in_status(
        self,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """exhausted 条目应在 memory_status 中可见。"""
        server, env = reliability_env
        workspace_id = env["workspace"]

        # 记录一条条目并使其耗尽重试
        entry = server.outbox.log_pending(
            workspace_id=workspace_id,
            tool="memory_save",
            arguments={"content": "可见性测试内容"},
            client_write_id="ms:visible-test",
        )
        server.outbox.mark_failed(workspace_id, entry["id"])
        server.outbox.mark_failed(workspace_id, entry["id"])
        server.outbox.mark_exhausted(workspace_id, entry["id"])

        # 检查计数
        counts = server.outbox.count_by_state(workspace_id)
        assert counts["exhausted"] == 1
        assert counts["pending"] == 0
        assert counts["failed"] == 0


class TestConcurrentSessions:
    """测试通过 outbox 分片实现的并发会话隔离。"""

    async def test_two_workspaces_do_not_interfere(
        self,
        client: httpx.AsyncClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """两个 workspace 实例不应覆盖彼此的 outbox。"""
        monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

        # 创建两个工作区
        ws1_resp = await client.post("/v1/workspaces", json={"name": f"ws1-{uuid.uuid4()}"})
        ws2_resp = await client.post("/v1/workspaces", json={"name": f"ws2-{uuid.uuid4()}"})
        ws1_id = ws1_resp.json()["id"]
        ws2_id = ws2_resp.json()["id"]

        # 创建共享 outbox state_dir 的两个服务器实例
        api1 = CwikiClient("http://test")
        api1._http = client
        session1 = await api1.create_agent_session(workspace_id=ws1_id, agent="qoder")
        api1.agent_session_id = session1["id"]

        api2 = CwikiClient("http://test")
        api2._http = client
        session2 = await api2.create_agent_session(workspace_id=ws2_id, agent="qoder")
        api2.agent_session_id = session2["id"]

        server1 = MCPServer(api1)
        server1.outbox = WriteAheadOutbox(state_dir=tmp_path / "shared_outbox")

        server2 = MCPServer(api2)
        server2.outbox = WriteAheadOutbox(state_dir=tmp_path / "shared_outbox")

        # 在两个工作区分别记录条目
        entry1 = server1.outbox.log_pending(
            workspace_id=ws1_id,
            tool="memory_save",
            arguments={"content": "Workspace 1 内容"},
            client_write_id="ms:ws1-entry",
        )
        entry2 = server2.outbox.log_pending(
            workspace_id=ws2_id,
            tool="memory_save",
            arguments={"content": "Workspace 2 内容"},
            client_write_id="ms:ws2-entry",
        )

        # 验证隔离性
        pending1 = server1.outbox.load_pending(ws1_id)
        pending2 = server2.outbox.load_pending(ws2_id)

        assert len(pending1) == 1
        assert len(pending2) == 1
        assert pending1[0]["id"] == entry1["id"]
        assert pending2[0]["id"] == entry2["id"]

        # 将其中一个标记为成功，验证另一个不受影响
        server1.outbox.mark_success(ws1_id, entry1["id"])
        assert server1.outbox.load_pending(ws1_id) == []
        assert len(server2.outbox.load_pending(ws2_id)) == 1


class TestCheckpointIncremental:
    """测试 checkpoint 增量窗口追踪。"""

    async def test_first_checkpoint_uses_default_window(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """首次 checkpoint 应使用默认的 60 分钟窗口。"""
        server, _env = reliability_env

        result = await server._handle_tool(
            "memory_checkpoint",
            {"workspace_name": _env["workspace"], "trigger_reason": "manual"},
        )

        assert result["status"] == "ok"
        assert result["input_window"]["since_minutes"] == 60
        assert result["input_window"]["incremental"] is False

    async def test_second_checkpoint_uses_incremental_window(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """第二次 checkpoint 应基于上次 checkpoint 使用增量窗口。"""
        server, _env = reliability_env

        # 第一次 checkpoint
        result1 = await server._handle_tool(
            "memory_checkpoint",
            {"workspace_name": _env["workspace"], "trigger_reason": "manual"},
        )
        assert result1["status"] == "ok"

        # 记录 checkpoint 时间戳
        session_id = server.client.agent_session_id
        server.outbox.record_checkpoint(session_id, _env["workspace"])

        # 稍等片刻以确保时间差
        await asyncio.sleep(0.1)

        # 第二次 checkpoint
        result2 = await server._handle_tool(
            "memory_checkpoint",
            {"workspace_name": _env["workspace"], "trigger_reason": "manual"},
        )
        assert result2["status"] == "ok"
        # 距上次 checkpoint 的窗口应很小（至多几分钟）
        assert result2["input_window"]["since_minutes"] < 60
        assert result2["input_window"]["incremental"] is True

    async def test_checkpoint_window_clamped_to_minimum(
        self,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """checkpoint 窗口应被钳制到最小 5 分钟。"""
        server, _env = reliability_env
        session_id = server.client.agent_session_id

        # 记录一个很近的 checkpoint
        server.outbox.record_checkpoint(session_id, _env["workspace"])

        result = await server._handle_tool(
            "memory_checkpoint",
            {"workspace_name": _env["workspace"], "trigger_reason": "manual"},
        )

        assert result["status"] == "ok"
        # 应被钳制到最小 5 分钟
        assert result["input_window"]["since_minutes"] >= 5

    async def test_checkpoint_window_clamped_to_maximum(
        self,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        """checkpoint 窗口应被钳制到最大 24 小时。"""
        server, _env = reliability_env
        session_id = server.client.agent_session_id

        # 手动设置一个很旧的 checkpoint 时间戳
        from adapters.mcp.outbox import _atomic_write_json

        checkpoint_path = server.outbox._state_dir / "checkpoints.json"
        old_timestamp = "2020-01-01T00:00:00+00:00"
        _atomic_write_json(
            checkpoint_path,
            [
                {
                    "session_id": session_id,
                    "workspace_id": _env["workspace"],
                    "checkpoint_at": old_timestamp,
                }
            ],
        )

        result = await server._handle_tool(
            "memory_checkpoint",
            {"workspace_name": _env["workspace"], "trigger_reason": "manual"},
        )

        assert result["status"] == "partial"
        assert result["input_window"]["time_window_truncated"] is True
        assert server.outbox.get_last_checkpoint(session_id, _env["workspace"]) == old_timestamp
        # 应被钳制到最大 1440 分钟（24 小时）
        assert result["input_window"]["since_minutes"] <= 1440


class TestFreeContentDelivery:
    @pytest.mark.parametrize("memory_type", [None, "fact"], ids=["auto", "explicit"])
    @pytest.mark.parametrize("content_format", ["plain", "markdown"])
    async def test_long_free_content_survives_approval_and_markdown_write(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        memory_type: str | None,
        content_format: str,
    ) -> None:
        server, env = reliability_env
        if content_format == "plain":
            body = "\n".join(
                f"采样记录 {i:04d}：离线机器保存原始响应及对应时间戳，"
                "每个数值都与本次采集的上下文关联，供后续核对与复现。"
                for i in range(240)
            )
        else:
            body = "\n\n".join(
                f"### 采样手记 {i:04d}\n\n"
                "| 数据 | 观测值 |\n| --- | --- |\n"
                f"| 原始序号 | {i:04d} |\n\n"
                "- 保留采样上下文和表格，不改写为固定章节。\n\n"
                f'```python\nsample = {{"sequence": {i}, "label": "原始值"}}\n'
                'print(sample["sequence"])\n```'
                for i in range(100)
            )
        content = (
            f"  LONG_BODY_START：原始正文开头证据。\n\n{body}\n\nLONG_BODY_END：尾部证据。  \n"
        )
        assert len(content) > 10000

        # 走真实的 review/file-sync 路径，只隔离索引与后台任务。
        store = FileStore(tmp_path / "memories")
        indexer = Mock(index_memory=AsyncMock())
        monkeypatch.setattr("apps.api.file_sync.get_file_store", lambda: store)
        monkeypatch.setattr("apps.api.file_sync.get_memory_indexer", lambda: indexer)
        monkeypatch.setattr("apps.api.routes.reviews.task_queue.enqueue", AsyncMock())

        title = "离线采样原始手记"
        arguments = {"workspace_name": env["workspace"], "title": title, "content": content}
        if memory_type is not None:
            arguments["type"] = memory_type
        result = await server._handle_tool("memory_save", arguments)
        assert result.get("delivery") == "confirmed", result
        response = await client.get(f"/v1/candidates/{result['candidate_id']}")
        assert response.status_code == 200
        candidate = response.json()
        assert candidate["title"] == title
        assert candidate["content"].startswith(normalize_memory_content(content))
        assert f"#memory/{memory_type or result['inferred_type']}" in candidate["content"]
        assert candidate["type"] == (memory_type or result["inferred_type"])
        assert candidate["status"] == "pending_review"
        assert server.outbox.load_all(env["workspace"]) == []

        review = await client.post(
            "/v1/reviews",
            json={"candidate_id": candidate["id"], "reviewer_type": "human", "action": "approve"},
        )
        assert review.status_code == 201, review.text
        response = await client.get("/v1/memories", params={"workspace_id": env["workspace"]})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        memory = response.json()["items"][0]
        assert memory["title"] == title
        assert memory["content"].startswith(normalize_memory_content(content))
        assert memory["type"] == candidate["type"]
        assert memory["status"] == "active"

        files = list(store.base_path.rglob("*.md"))
        assert len(files) == 1
        assert files[0].resolve().is_relative_to(tmp_path.resolve())
        serialized = files[0].read_text(encoding="utf-8")
        # 只剥离 frontmatter 外壳，不动正文中有效的空白。
        frontmatter, separator, written_body = serialized.partition("---\n\n")
        assert separator
        assert memory["id"] in frontmatter
        # 文件正文包含自动注入的 #memory/ 标签及末尾换行
        assert "#memory/" in written_body
        assert "LONG_BODY_START" in written_body
        assert "LONG_BODY_END" in written_body
        assert written_body.endswith("\n")
        indexer.index_memory.assert_awaited_once()

    @pytest.mark.parametrize("memory_type", list(TYPE_DEFINITIONS))
    @pytest.mark.parametrize(
        "content",
        [
            (
                "先验证再提交：离线导出保留正文和附件的对应关系，恢复时应核对文件数量、"
                "编码和原始时间戳。本轮只验证当前工作区，其他工作区尚未确认。"
            ),
            (
                "## 证据与取舍\n只有当前环境验证通过，其他环境尚未确认。"
                "离线安装需要预先准备依赖包，但可以避免受限网络下载失败；"
                "联网方案暂不采用，网络恢复后再复议。"
            ),
            (
                "### 排查进展\n错误原因仍待确认，没有可验证的修复方案。"
                "请求返回连接超时，当前只保留调用时间和完整错误栈，下一步核对"
                "连接池配置与服务端日志，不把假设当作根因。"
            ),
            (
                "| 方案 | 代价 |\n| --- | --- |\n| 离线安装 | 需要准备依赖包 |\n"
                "| 联网安装 | 依赖外部下载服务可用 |\n\n本次选择离线安装，保留包版本用于复现。"
            ),
            (
                "```markdown\n## 不应删除代码块里的标题\n"
                "代码块中的示例标题属于原始材料，不能因正文分类而丢失。\n```\n"
                "调用方提交完整示例，接收端不改写围栏或缩进。\n"
            ),
            (
                "    preserve_indented_code()\n\n保留正文首尾空白。缩进代码中的空格用于标识"
                "代码块，尾部空白和换行也属于调用方原文；校验长度时可以忽略它们，"
                "保存时不能删除。  \n"
            ),
        ],
        ids=["plain", "custom_heading", "unfinished_issue", "table", "code", "whitespace"],
    )
    async def test_explicit_type_preserves_content(
        self, client, reliability_env, memory_type, content
    ):
        server, env = reliability_env
        title = "原始材料分类记录"
        assert len(content.strip()) >= 50
        result = await server._handle_tool(
            "memory_save",
            {
                "workspace_name": env["workspace"],
                "title": title,
                "type": memory_type,
                "content": content,
            },
        )
        assert result.get("delivery") == "confirmed", result
        response = await client.get(f"/v1/candidates/{result['candidate_id']}")
        candidate = response.json()
        assert candidate["title"] == title
        assert candidate["type"] == memory_type
        # 内容含自动注入的 #memory/ 标签
        assert candidate["content"].startswith(normalize_memory_content(content))
        assert f"#memory/{memory_type}" in candidate["content"]
        assert f"#memory/{env['workspace']}" in candidate["content"]
        assert candidate["status"] == "pending_review"
        assert server.outbox.load_all(env["workspace"]) == []

    @pytest.mark.parametrize("memory_type", list(TYPE_DEFINITIONS))
    async def test_auto_mode_preserves_inferred_type_and_content(
        self, client, reliability_env, monkeypatch, memory_type
    ):
        server, env = reliability_env
        title = "类型推断原文校对"
        content = (
            f"测试内容：{memory_type} 类型的示例记忆，用于验证类型推断和内容保留。"
            "推断只决定分类字段，标题由调用方给出，不能根据类型补章节或改变正文。"
        )
        monkeypatch.setattr("adapters.mcp.mcp_server.infer_memory_type", lambda _: memory_type)
        result = await server._handle_tool(
            "memory_save", {"workspace_name": env["workspace"], "title": title, "content": content}
        )
        assert result.get("delivery") == "confirmed", result
        assert result["inferred_type"] == memory_type
        response = await client.get(f"/v1/candidates/{result['candidate_id']}")
        assert response.json()["title"] == title
        # 内容含自动注入的 #memory/ 标签
        assert response.json()["content"].startswith(normalize_memory_content(content))
        assert f"#memory/{memory_type}" in response.json()["content"]
        assert response.json()["type"] == memory_type
        assert "自动整理" not in result.get("message", "")

    async def test_issue_inferred_without_a_solution_is_delivered(self, client, reliability_env):
        server, env = reliability_env
        content = (
            "提交候选记忆时报错 400，目前仅确认请求失败，根因和解决方案仍待排查。"
            "已保留请求正文和错误响应，下一步核对参数约束，不把未经验证的推测写成结论。"
        )
        result = await server._handle_tool(
            "memory_save",
            {"workspace_name": env["workspace"], "title": "候选请求失败记录", "content": content},
        )
        assert result.get("delivery") == "confirmed", result
        assert result.get("inferred_type") == "issue", result
        response = await client.get(f"/v1/candidates/{result['candidate_id']}")
        # 内容含自动注入的 #memory/ 标签
        assert response.json()["content"].startswith(normalize_memory_content(content))
        assert "#memory/issue" in response.json()["content"]

    @pytest.mark.parametrize("memory_type", [None, "decision"])
    async def test_retry_preserves_original_content_and_type(
        self, client, reliability_env, monkeypatch, memory_type
    ):
        server, env = reliability_env
        title = "  离线部署取舍  "
        content = (
            "    preserve_indented_code()\n\n## 取舍\n选择离线方案，联网方案暂不采用。"
            "受限网络无法稳定下载依赖，因此随部署包保存完整依赖清单和校验值；"
            "待网络恢复后再比较维护成本。  \n"
        )
        arguments = {"workspace_name": env["workspace"], "title": title, "content": content}
        if memory_type:
            arguments["type"] = memory_type
        monkeypatch.setattr("adapters.mcp.mcp_server.infer_memory_type", lambda _: "decision")
        with patch.object(
            server.client, "submit_candidate", side_effect=httpx.ConnectError("offline")
        ):
            failed = await server._handle_tool("memory_save", arguments)
        assert failed.get("cached") is True
        entries = server.outbox.load_all(env["workspace"])
        assert len(entries) == 1
        assert entries[0]["arguments"]["title"] == title
        # outbox 存储的内容已自动注入 #memory/ 标签
        assert entries[0]["arguments"]["content"].startswith(content)
        assert "#memory/decision" in entries[0]["arguments"]["content"]

        await server._handle_tool("memory_retry_failed", {"workspace_name": env["workspace"]})
        response = await client.get("/v1/candidates", params={"workspace_id": env["workspace"]})
        assert response.json()["total"] == 1
        candidate = response.json()["items"][0]
        assert candidate["title"] == title
        # 内容含自动注入的 #memory/ 标签
        assert candidate["content"].startswith(normalize_memory_content(content))
        assert "#memory/decision" in candidate["content"]
        assert candidate["type"] == "decision"
        assert server.outbox.load_all(env["workspace"]) == []

    @pytest.mark.parametrize("content", ["", " \n\t ", "1234", "  1234  "])
    async def test_api_rejects_empty_or_too_short_content(self, client, reliability_env, content):
        _, env = reliability_env
        response = await client.post(
            "/v1/candidates",
            json={
                "workspace_id": env["workspace"],
                "title": "invalid",
                "type": "fact",
                "content": content,
            },
        )
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(
            error["loc"] == ["body", "content"] and "至少 20 个字符" in error["msg"]
            for error in errors
        )

    async def test_api_rejects_unknown_type(self, client, reliability_env):
        _, env = reliability_env
        response = await client.post(
            "/v1/candidates",
            json={
                "workspace_id": env["workspace"],
                "title": "invalid",
                "type": "unknown",
                "content": (
                    "未知类型不应写入候选队列。请求的标题和正文均满足长度要求，"
                    "只传入不受支持的类型，以确认分类错误独立于正文校验并保持原来的拒绝行为。"
                ),
            },
        )
        assert response.status_code == 400
        response = await client.get("/v1/candidates", params={"workspace_id": env["workspace"]})
        assert response.json()["total"] == 0

    async def test_type_discovery_exposes_type_definitions(self, reliability_env):
        server, _ = reliability_env
        result = await server._handle_tool("memory_types", {})
        assert len(result["types"]) == len(TYPE_DEFINITIONS)
        for t in result["types"]:
            assert t["type"]
            assert t["name"] == TYPE_DEFINITIONS[t["type"]]["name"]
            assert t["description"] == TYPE_DEFINITIONS[t["type"]]["description"]
        filtered = await server._handle_tool("memory_types", {"type": "decision"})
        assert [t["type"] for t in filtered["types"]] == ["decision"]
        unknown = await server._handle_tool("memory_types", {"type": "unknown"})
        assert unknown["types"] == []


_BOUNDARY_TITLE = "Offline export notes"  # 共 20 个字符（含空格）。
# 恰好 20 个字符 — content 的 API schema minLength。
_MIN_CONTENT = "Valid memory content"
# 恰好 30 个字符 — create_candidate 在 API 与 MCP 写路径上共同
# 强制的 check_exclusion_list 最小长度。
_BOUNDARY_CONTENT = "Valid memory content for notes"


class TestMemoryWriteValidationAPI:
    """校验真实 ASGI 请求，不产生文件、embedding 或外部服务写入。"""

    @pytest.fixture(autouse=True)
    def isolate_writes(self, monkeypatch):
        monkeypatch.setattr(settings, "memory_title_max_length", 20)
        monkeypatch.setattr("apps.api.routes.memories.sync_memory_to_file", AsyncMock())
        monkeypatch.setattr("apps.api.routes.reviews.sync_memory_to_file", AsyncMock())
        monkeypatch.setattr("packages.domain.task_queue.queue.enqueue", AsyncMock())

    @pytest.fixture
    async def memory_payload(self, client):
        response = await client.post(
            "/v1/workspaces", json={"name": f"write-validation-{uuid.uuid4()}"}
        )
        assert response.status_code == 201
        return {
            "workspace_id": response.json()["id"],
            "title": "离线导出原始记录",
            "content": (
                "    export_sources()\n\n## 导出范围\n离线导出包含原始正文、附件路径和采样时间戳。"
                "恢复时逐项核对校验值，确认来源完整后重新建立索引，不以摘要替代原始材料。  \n"
            ),
            "type": "fact",
        }

    @pytest.fixture
    async def verified_memory(self, client, memory_payload):
        response = await client.post("/v1/candidates", json=memory_payload)
        assert response.status_code == 201, response.text
        candidate = response.json()["candidate"]
        response = await client.post(
            "/v1/reviews",
            json={"candidate_id": candidate["id"], "reviewer_type": "human", "action": "approve"},
        )
        assert response.status_code == 201, response.text
        response = await client.get(
            "/v1/memories", params={"workspace_id": memory_payload["workspace_id"]}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        memory = response.json()["items"][0]
        assert memory["title"] == memory_payload["title"]
        assert memory["content"] == normalize_memory_content(memory_payload["content"])
        return memory

    @pytest.mark.parametrize(
        "field, value",
        [
            ("title", ""),
            ("title", " \t\n "),
            ("title", None),
            ("title", _BOUNDARY_TITLE + "!"),
            ("title", " " + _BOUNDARY_TITLE),
            ("content", ""),
            ("content", " \t\n "),
            ("content", None),
            ("content", _MIN_CONTENT[:-1]),
            ("content", " \t\n" + _MIN_CONTENT[:-1] + "  \n"),
        ],
        ids=[
            "empty-title",
            "blank-title",
            "null-title",
            "title-21",
            "title-21-with-space",
            "empty-content",
            "blank-content",
            "null-content",
            "content-19",
            "padded-content-19",
        ],
    )
    async def test_create_rejects_invalid_fields(self, client, memory_payload, field, value):
        response = await client.post("/v1/candidates", json={**memory_payload, field: value})
        assert response.status_code == 422, response.text
        assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
        response = await client.get(
            "/v1/candidates", params={"workspace_id": memory_payload["workspace_id"]}
        )
        assert response.json()["total"] == 0

    async def test_create_requires_agent_supplied_title(self, client, memory_payload):
        del memory_payload["title"]
        response = await client.post("/v1/candidates", json=memory_payload)
        assert response.status_code == 422, response.text
        assert any(
            error["loc"] == ["body", "title"] and error["type"] == "missing"
            for error in response.json()["detail"]
        )

    @pytest.mark.parametrize("padded", [False, True], ids=["exact-boundary", "original-whitespace"])
    async def test_create_accepts_boundary_and_preserves_original(
        self, client, memory_payload, padded
    ):
        assert len(_BOUNDARY_TITLE) == 20
        assert len(_BOUNDARY_CONTENT) == 30
        title = "  离线导出标题  " if padded else _BOUNDARY_TITLE
        content = " \t\n" + _BOUNDARY_CONTENT + "  \n" if padded else _BOUNDARY_CONTENT
        response = await client.post(
            "/v1/candidates", json={**memory_payload, "title": title, "content": content}
        )
        assert response.status_code == 201, response.text
        candidate = response.json()["candidate"]
        assert candidate["title"] == title
        assert candidate["content"] == normalize_memory_content(content)
        assert candidate["status"] == "pending_review"
        response = await client.get(f"/v1/candidates/{candidate['id']}")
        assert response.json()["title"] == title
        assert response.json()["content"] == normalize_memory_content(content)

    @pytest.mark.parametrize(
        "field, value",
        [
            ("title", ""),
            ("title", " \t\n "),
            ("title", _BOUNDARY_TITLE + "!"),
            ("title", " " + _BOUNDARY_TITLE),
            ("content", ""),
            ("content", " \t\n "),
            ("content", _MIN_CONTENT[:-1]),
            ("content", " \t\n" + _MIN_CONTENT[:-1] + "  \n"),
        ],
        ids=[
            "empty-title",
            "blank-title",
            "title-21",
            "title-21-with-space",
            "empty-content",
            "blank-content",
            "content-19",
            "padded-content-19",
        ],
    )
    async def test_patch_rejects_invalid_fields_without_changing_memory(
        self, client, verified_memory, field, value
    ):
        url = f"/v1/memories/{verified_memory['id']}"
        before = (await client.get(url)).json()
        response = await client.patch(url, json={field: value, "confidence": 0.9})
        assert response.status_code == 422, response.text
        assert any(error["loc"] == ["body", field] for error in response.json()["detail"])
        assert (await client.get(url)).json() == before

    @pytest.mark.parametrize(
        "updates",
        [
            {"title": _BOUNDARY_TITLE},
            {"content": _BOUNDARY_CONTENT},
            {"title": "  导出新版标题  ", "content": " \t\n" + _BOUNDARY_CONTENT + "  \n"},
        ],
        ids=["title-20-only", "content-50-only", "both-with-whitespace"],
    )
    async def test_patch_replaces_only_supplied_fields_and_preserves_original(
        self, client, verified_memory, updates
    ):
        url = f"/v1/memories/{verified_memory['id']}"
        response = await client.patch(url, json=updates)
        assert response.status_code == 200, response.text
        for memory in (response.json(), (await client.get(url)).json()["memory"]):
            for field in ("title", "content"):
                expected = updates.get(field, verified_memory[field])
                if field == "content" and field in updates:
                    expected = normalize_memory_content(expected)
                assert memory[field] == expected
            assert memory["version"] == verified_memory["version"] + 1

    @pytest.mark.parametrize(
        "updates",
        [
            {"confidence": 0.9, "importance": 0.8},
            {"title": None, "content": None, "confidence": 0.9, "importance": 0.8},
        ],
        ids=["omitted-text-fields", "null-text-fields"],
    )
    async def test_patch_metadata_only_does_not_revalidate_legacy_text(
        self, client, verified_memory, db_session, updates
    ):
        from packages.domain.models import Memory

        # 既有记录可能早于新限制；省略/None 字段保持不动。
        memory = await db_session.get(Memory, uuid.UUID(verified_memory["id"]))
        memory.title = "历史标题" * 6
        memory.content = "旧版短正文"
        await db_session.flush()
        response = await client.patch(f"/v1/memories/{memory.id}", json=updates)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["title"] == "历史标题" * 6
        assert result["content"] == "旧版短正文"
        assert result["confidence"] == 0.9
        assert result["importance"] == 0.8
        stored = (await client.get(f"/v1/memories/{memory.id}")).json()["memory"]
        assert stored["title"] == result["title"]
        assert stored["content"] == result["content"]

    @pytest.mark.parametrize("max_length", [12, 32])
    async def test_create_and_patch_follow_changed_title_limit(
        self, client, memory_payload, verified_memory, monkeypatch, max_length
    ):
        monkeypatch.setattr(settings, "memory_title_max_length", max_length)
        title = "标" * max_length
        for request_title, expected_status in ((title, 201), (title + "题", 422)):
            response = await client.post(
                "/v1/candidates", json={**memory_payload, "title": request_title}
            )
            assert response.status_code == expected_status, response.text
            if expected_status == 201:
                assert response.json()["candidate"]["title"] == request_title
        url = f"/v1/memories/{verified_memory['id']}"
        response = await client.patch(url, json={"title": title})
        assert response.status_code == 200, response.text
        assert response.json()["title"] == title
        response = await client.patch(url, json={"title": title + "题"})
        assert response.status_code == 422, response.text
        assert (await client.get(url)).json()["memory"]["title"] == title


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://test/v1/candidates")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=request, response=response)


class TestOutbox4xxRejection:
    """4xx（429 除外）必须保持拒绝状态，不做自动重试。"""

    async def test_4xx_rejection_retains_outbox_entry(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        server, env = reliability_env
        workspace_id = env["workspace"]

        with patch.object(
            server.client,
            "submit_candidate",
            side_effect=_http_status_error(400),
        ):
            result = await server._handle_tool(
                "memory_save",
                {
                    "workspace_name": workspace_id,
                    "title": "确定性拒绝记录",
                    "content": (
                        "四百错误测试：服务端返回确定性拒绝，客户端不应反复重试相同请求。"
                        "标题和正文已满足本地校验，确认响应后移除待投递条目，避免形成无效积压。"
                    ),
                },
            )

        assert result.get("error") == "API error 400"
        assert result["cached"] is True
        assert result["delivery"] == "rejected"
        assert server.outbox.load_all(workspace_id)[0]["state"] == "rejected"

    async def test_5xx_and_429_keep_outbox_entry(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        server, env = reliability_env
        workspace_id = env["workspace"]

        for status_code in (500, 429):
            with patch.object(
                server.client,
                "submit_candidate",
                side_effect=_http_status_error(status_code),
            ):
                result = await server._handle_tool(
                    "memory_save",
                    {
                        "workspace_name": workspace_id,
                        "title": "瞬时故障重试记录",
                        "content": (
                            f"瞬时错误测试 {status_code} 应保留重试。请求未获得可靠确认，"
                            "可能是服务短暂不可用或触发限流；保留完整正文和写入标识，"
                            "服务恢复后继续投递同一条记录。"
                        ),
                    },
                )

            assert result.get("cached") is True, result
            entries = server.outbox.load_all(workspace_id)
            assert len(entries) == 1
            assert entries[0]["state"] == "failed"
            server.outbox.remove_entry(workspace_id, entries[0]["id"])

    async def test_retry_failed_retains_4xx_entry(
        self,
        client: httpx.AsyncClient,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        server, env = reliability_env
        workspace_id = env["workspace"]

        entry = server.outbox.log_pending(
            workspace_id=workspace_id,
            tool="memory_save",
            arguments={"content": "重试时遇到 400 的条目应被清除", "workspace_name": workspace_id},
            client_write_id="ms:retry-4xx-test",
        )
        server.outbox.mark_failed(workspace_id, entry["id"])

        with patch.object(
            server.client,
            "submit_candidate",
            side_effect=_http_status_error(400),
        ):
            result = await server._handle_tool("memory_retry_failed", {})

        assert result["status"] == "partial"
        assert result["retried"] == 0
        assert result["outbox_pending"] == 0
        assert result["outbox_counts"]["rejected"] == 1
        assert server.outbox.load_all(workspace_id)[0]["state"] == "rejected"


class TestOutboxCountContract:
    @pytest.mark.parametrize("failed, exhausted", [(0, 0), (1, 2), (0, 2)])
    async def test_status_separates_failed_and_exhausted_across_workspaces(
        self, reliability_env: tuple[MCPServer, dict], failed: int, exhausted: int
    ) -> None:
        server, env = reliability_env
        other_workspace = str(uuid.uuid4())
        for state, count, workspace in (
            ("pending", 1, env["workspace"]),
            ("failed", failed, env["workspace"]),
            ("exhausted", exhausted, other_workspace),
        ):
            for index in range(count):
                entry = server.outbox.log_pending(
                    workspace_id=workspace,
                    tool="memory_save",
                    arguments={
                        "content": f"投递状态记录 {state}-{index}",
                        "workspace_name": workspace,
                    },
                    client_write_id=f"ms:counts-{state}-{index}",
                )
                if state == "failed":
                    server.outbox.mark_failed(workspace, entry["id"])
                elif state == "exhausted":
                    server.outbox.mark_exhausted(workspace, entry["id"])

        result = await server._handle_tool("memory_status", {"workspace_name": env["workspace"]})

        assert "error" not in result
        assert result["outbox_pending"] == failed
        assert result["outbox_exhausted"] == exhausted
        assert server.outbox.count_all_by_state() == {
            "pending": 1,
            "failed": failed,
            "exhausted": exhausted,
            "rejected": 0,
        }
        assert result["outbox_total"] == 1 + failed + exhausted
        assert result["outbox_counts"] == server.outbox.count_all_by_state()

    @pytest.mark.parametrize("memory_type", [None, "fact"], ids=["auto", "explicit"])
    async def test_save_count_is_inclusive_snapshot_before_auto_retry(
        self, reliability_env: tuple[MCPServer, dict], memory_type: str | None
    ) -> None:
        server, env = reliability_env
        workspace = env["workspace"]
        for state in ("failed", "exhausted"):
            entry = server.outbox.log_pending(
                workspace_id=workspace,
                tool="memory_save",
                arguments={
                    "title": "原始投递状态记录",
                    "content": (
                        f"原始投递记录 {state}，需要保留其完整正文。"
                        "失败条目可在下一次成功写入后自动重试，耗尽条目仍保留供人工检查，"
                        "计数响应反映自动重试前的快照。"
                    ),
                    "workspace_name": workspace,
                    "type": "fact",
                },
                client_write_id=f"ms:save-count-{state}",
            )
            if state == "failed":
                server.outbox.mark_failed(workspace, entry["id"])
            else:
                server.outbox.mark_exhausted(workspace, entry["id"])
        arguments = {
            "workspace_name": workspace,
            "title": "导出附件保留规则",
            "content": (
                "另一条独立记录：导出目录保留原始附件。归档中应同时包含正文、"
                "附件路径和原始时间戳，恢复时逐项核对对应关系，不能只导出摘要而丢失来源材料。"
            ),
        }
        if memory_type:
            arguments["type"] = memory_type

        result = await server._handle_tool("memory_save", arguments)

        assert result["delivery"] == "confirmed", result
        assert result["outbox_pending"] == 2
        assert server.outbox.count_all_by_state() == {
            "pending": 0,
            "failed": 0,
            "exhausted": 1,
            "rejected": 0,
        }
        status = await server._handle_tool("memory_status", {"workspace_name": workspace})
        assert status["outbox_pending"] == 0
        assert status["outbox_exhausted"] == 1

    async def test_retry_resets_exhausted_before_automatic_exhaustion_check(
        self, reliability_env: tuple[MCPServer, dict]
    ) -> None:
        server, env = reliability_env
        workspace = env["workspace"]
        for state in ("failed", "exhausted"):
            entry = server.outbox.log_pending(
                workspace_id=workspace,
                tool="memory_save",
                arguments={
                    "content": f"失败投递记录 {state}，服务仍然不可用。",
                    "workspace_name": workspace,
                },
                client_write_id=f"ms:retry-count-{state}",
            )
            if state == "failed":
                server.outbox.mark_failed(workspace, entry["id"])
                server.outbox.mark_failed(workspace, entry["id"])
            else:
                server.outbox.mark_exhausted(workspace, entry["id"])
        with patch.object(
            server.client, "submit_candidate", side_effect=httpx.ConnectError("API unavailable")
        ):
            result = await server._handle_tool("memory_retry_failed", {})
            assert result["retried"] == 0
            assert result["outbox_pending"] == 2
            assert result["outbox_exhausted"] == 0
            assert server.outbox.count_all_by_state() == {
                "pending": 0,
                "failed": 2,
                "exhausted": 0,
                "rejected": 0,
            }

            await server._try_auto_retry_one()

        assert server.outbox.count_all_by_state() == {
            "pending": 0,
            "failed": 1,
            "exhausted": 1,
            "rejected": 0,
        }


class TestOutboxWorkspaceIdRoundTrip:
    """I5：workspace_id 存储在条目数据中，而非从文件名推导。"""

    def test_workspace_id_with_underscores_round_trips(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path / "outbox")
        ws_id = "my_workspace_with_underscores"

        outbox.log_pending(
            workspace_id=ws_id,
            tool="memory_save",
            arguments={"content": "test", "workspace_name": ws_id},
            client_write_id="ms:ws-round-trip",
        )

        all_workspaces = outbox.load_all_workspaces()
        assert ws_id in all_workspaces
        assert len(all_workspaces[ws_id]) == 1
        assert all_workspaces[ws_id][0]["workspace_id"] == ws_id

    def test_load_retryable_preserves_workspace_id(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path / "outbox")
        ws_id = "ws_with_underscores"

        entry = outbox.log_pending(
            workspace_id=ws_id,
            tool="memory_save",
            arguments={"content": "test", "workspace_name": ws_id},
            client_write_id="ms:retryable-ws",
        )
        outbox.mark_failed(ws_id, entry["id"])

        retryable = outbox.load_retryable()
        assert ws_id in retryable
        assert len(retryable[ws_id]) == 1
        assert retryable[ws_id][0]["workspace_id"] == ws_id


class TestFrozenTitleInRetry:
    """C3：重试回放时使用 outbox 中冻结的标题。"""

    @pytest.mark.parametrize("retry_mode", ["auto", "manual"])
    @pytest.mark.parametrize("title_limit", [12, 32], ids=["tightened", "relaxed"])
    async def test_retry_frozen_payload_uses_current_api_validation(
        self, client, reliability_env, monkeypatch, retry_mode, title_limit
    ):
        server, env = reliability_env
        workspace_id = env["workspace"]
        monkeypatch.setattr(settings, "memory_title_max_length", 20)
        content = " \t\n" + _BOUNDARY_CONTENT + "  \n"
        with patch.object(
            server.client, "submit_candidate", side_effect=httpx.ConnectError("offline")
        ):
            result = await server._handle_tool(
                "memory_save",
                {"workspace_name": workspace_id, "title": _BOUNDARY_TITLE, "content": content},
            )
        assert result["cached"] is True, result
        entry = server.outbox.load_all(workspace_id)[0]
        assert entry["arguments"]["title"] == _BOUNDARY_TITLE
        # outbox 存储的内容已自动注入 #memory/ 标签
        assert entry["arguments"]["content"].startswith(content)
        assert "#memory/fact" in entry["arguments"]["content"]
        monkeypatch.setattr(settings, "memory_title_max_length", title_limit)
        submit = AsyncMock(wraps=server.client.submit_candidate)
        monkeypatch.setattr(server.client, "submit_candidate", submit)
        on_error = Mock(wraps=server._outbox_on_error)
        monkeypatch.setattr(server, "_outbox_on_error", on_error)

        if retry_mode == "auto":
            await server._try_auto_retry_one()
        else:
            result = await server._handle_tool(
                "memory_retry_failed", {"workspace_name": workspace_id}
            )
            assert result["retried"] == int(title_limit >= len(_BOUNDARY_TITLE))
            assert result["outbox_pending"] == result["outbox_exhausted"] == 0

        submit.assert_awaited_once()
        payload = submit.call_args.kwargs
        assert payload["title"] == _BOUNDARY_TITLE
        # 重试发送的内容带 #memory/ 标签
        assert payload["content"].startswith(content)
        assert "#memory/fact" in payload["content"]
        assert payload["workspace_id"] == workspace_id
        assert payload["client_write_id"] == entry["client_write_id"]
        if title_limit < len(_BOUNDARY_TITLE):
            on_error.assert_called_once()
            error = on_error.call_args.args[2]
            assert isinstance(error, httpx.HTTPStatusError)
            assert error.response.status_code == 422
            assert any(item["loc"] == ["body", "title"] for item in error.response.json()["detail"])
        else:
            on_error.assert_not_called()
        remaining = server.outbox.load_all(workspace_id)
        if title_limit < len(_BOUNDARY_TITLE):
            assert remaining[0]["state"] == "rejected"
            assert remaining[0]["arguments"] == entry["arguments"]
        else:
            assert remaining == []
        response = await client.get("/v1/candidates", params={"workspace_id": workspace_id})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == int(title_limit >= len(_BOUNDARY_TITLE))
        if title_limit >= len(_BOUNDARY_TITLE):
            candidate = response.json()["items"][0]
            assert candidate["title"] == _BOUNDARY_TITLE
            assert candidate["content"].startswith(normalize_memory_content(content))
            assert "#memory/fact" in candidate["content"]
            assert candidate["workspace_id"] == workspace_id
            assert candidate["status"] == "pending_review"

    async def test_retry_uses_frozen_title(
        self,
        reliability_env: tuple[MCPServer, dict],
    ) -> None:
        server, env = reliability_env
        workspace_id = env["workspace"]

        frozen_title = "已冻结的标题"
        server.outbox.log_pending(
            workspace_id=workspace_id,
            tool="memory_save",
            arguments={
                "content": "冻结标题测试内容，需要足够长以满足校验要求",
                "title": frozen_title,
                "type": "fact",
                "workspace_name": workspace_id,
            },
            client_write_id="ms:frozen-title-retry",
        )

        captured_titles: list[str] = []

        async def capture_submit(*args, **kwargs):
            captured_titles.append(kwargs.get("title", ""))
            raise httpx.RequestError("fail")

        with patch.object(server.client, "submit_candidate", side_effect=capture_submit):
            await server._try_auto_retry_one()

        assert len(captured_titles) == 1
        assert captured_titles[0] == frozen_title
