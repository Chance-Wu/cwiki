"""client_write_id 幂等键在候选创建上的幂等性测试。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
async def workspace_id(client: httpx.AsyncClient) -> str:
    resp = await client.post("/v1/workspaces", json={"name": f"idem-{uuid.uuid4()}"})
    assert resp.status_code == 201
    return resp.json()["id"]


def _candidate_body(workspace_id: str, **overrides: object) -> dict:
    body = {
        "workspace_id": workspace_id,
        "title": "测试幂等键",
        "content": "## 场景\n测试环境中验证幂等键功能\n\n## 知识\nclient_write_id 可以防止重试产生重复候选\n\n## 原因\n网络重试可能导致重复提交，幂等键确保只产生一条候选",
        "type": "fact",
    }
    body.update(overrides)
    return body


async def test_duplicate_client_write_id_returns_existing(
    client: httpx.AsyncClient,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())
    write_id = f"idem:{uuid.uuid4().hex[:12]}"
    body = _candidate_body(workspace_id, client_write_id=write_id)

    first = await client.post("/v1/candidates", json=body)
    assert first.status_code == 201
    first_id = first.json()["candidate"]["id"]

    second = await client.post("/v1/candidates", json=body)
    assert second.status_code == 201
    assert second.json()["candidate"]["id"] == first_id


async def test_different_client_write_id_creates_separate(
    client: httpx.AsyncClient,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    first = await client.post(
        "/v1/candidates",
        json=_candidate_body(workspace_id, client_write_id=f"a:{uuid.uuid4().hex[:12]}"),
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/candidates",
        json=_candidate_body(workspace_id, client_write_id=f"b:{uuid.uuid4().hex[:12]}"),
    )
    assert second.status_code == 201
    assert second.json()["candidate"]["id"] != first.json()["candidate"]["id"]


async def test_null_client_write_id_always_creates_new(
    client: httpx.AsyncClient,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())
    body = _candidate_body(workspace_id)

    first = await client.post("/v1/candidates", json=body)
    assert first.status_code == 201

    second = await client.post("/v1/candidates", json=body)
    assert second.status_code == 201
    assert second.json()["candidate"]["id"] != first.json()["candidate"]["id"]


async def test_client_write_id_scoped_per_workspace(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())
    ws1 = await client.post("/v1/workspaces", json={"name": f"ws1-{uuid.uuid4()}"})
    ws2 = await client.post("/v1/workspaces", json={"name": f"ws2-{uuid.uuid4()}"})
    ws1_id = ws1.json()["id"]
    ws2_id = ws2.json()["id"]

    write_id = f"shared:{uuid.uuid4().hex[:12]}"

    first = await client.post(
        "/v1/candidates",
        json=_candidate_body(ws1_id, client_write_id=write_id),
    )
    assert first.status_code == 201

    second = await client.post(
        "/v1/candidates",
        json=_candidate_body(ws2_id, client_write_id=write_id),
    )
    assert second.status_code == 201
    assert second.json()["candidate"]["id"] != first.json()["candidate"]["id"]


async def test_client_write_id_in_read_schema(
    client: httpx.AsyncClient,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())
    write_id = f"read:{uuid.uuid4().hex[:12]}"
    resp = await client.post(
        "/v1/candidates",
        json=_candidate_body(workspace_id, client_write_id=write_id),
    )
    assert resp.status_code == 201
    assert resp.json()["candidate"]["client_write_id"] == write_id
