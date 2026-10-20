"""app.auth_token Bearer 鉴权测试（W7-05 修复）。

默认（token 为空）全部端点保持零鉴权；配置后受保护端点要求
`Authorization: Bearer <token>`，缺失/错误返回 401。
以 GET /v1/task-queue-status 为探针——它只读内存队列快照，
不依赖 lifespan 初始化的存储组件。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from packages.domain.config import settings

PROBE_PATH = "/v1/task-queue-status"


async def _get(headers: dict[str, str] | None = None):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(PROBE_PATH, headers=headers or {})


@pytest.mark.asyncio
async def test_open_when_token_not_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_auth_token", "")
    resp = await _get()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_token_rejected_when_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_auth_token", "secret123")
    resp = await _get()
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    assert resp.json()["detail"]


@pytest.mark.asyncio
async def test_wrong_token_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_auth_token", "secret123")
    resp = await _get({"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_correct_token_accepted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_auth_token", "secret123")
    resp = await _get({"Authorization": "Bearer secret123"})
    assert resp.status_code == 200
    assert resp.json()["counts"]


@pytest.mark.asyncio
async def test_retry_endpoint_protected_too(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "api_auth_token", "secret123")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/task-queue/retry", json={"task_id": "00000000-0000-0000-0000-000000000000"}
        )
    assert resp.status_code == 401
