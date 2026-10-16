"""事件 API 端点测试。"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_workspace(client: AsyncClient) -> None:
    resp = await client.post("/v1/workspaces", json={"name": "test-workspace"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test-workspace"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_workspaces(client: AsyncClient) -> None:
    await client.post("/v1/workspaces", json={"name": "ws1"})
    resp = await client.get("/v1/workspaces")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_register_agent(client: AsyncClient) -> None:
    ws_resp = await client.post("/v1/workspaces", json={"name": "test-ws"})
    ws_id = ws_resp.json()["id"]

    resp = await client.post(
        "/v1/agents",
        json={
            "workspace_id": ws_id,
            "name": "Qoder",
            "type": "coding_agent",
            "adapter": "qoder",
            "version": "1.0",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Qoder"
    assert data["adapter"] == "qoder"


@pytest.mark.asyncio
async def test_event_idempotency(client: AsyncClient) -> None:
    ws_resp = await client.post("/v1/workspaces", json={"name": "test-ws"})
    ws_id = ws_resp.json()["id"]

    agent_resp = await client.post(
        "/v1/agents",
        json={
            "workspace_id": ws_id,
            "name": "TestAgent",
            "type": "test",
            "adapter": "generic",
        },
    )
    agent_id = agent_resp.json()["id"]

    session_resp = await client.post(
        "/v1/sessions",
        json={
            "workspace_id": ws_id,
            "agent_id": agent_id,
            "external_session_id": "ext-session-001",
        },
    )
    session_id = session_resp.json()["id"]

    event_payload = {
        "protocol_version": "1",
        "event_type": "session.started",
        "agent": str(agent_id),
        "session": str(session_id),
        "workspace": str(ws_id),
        "sequence": 1,
        "timestamp": "2026-09-11T12:00:00Z",
        "payload": {"cwd": "/test"},
    }

    resp1 = await client.post("/v1/events", json=event_payload)
    assert resp1.status_code == 201
    assert resp1.json()["duplicate"] is False

    resp2 = await client.post("/v1/events", json=event_payload)
    assert resp2.status_code == 201
    assert resp2.json()["duplicate"] is True
