"""写入策略在候选创建端点的行为测试。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from packages.domain.config import settings
from packages.domain.write_policy import WritePolicy, WriteRule


@pytest.fixture
async def workspace(client: httpx.AsyncClient) -> tuple[str, str]:
    name = f"policy-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"], name


def _enable_policy(monkeypatch: pytest.MonkeyPatch, *rules: WriteRule) -> None:
    monkeypatch.setattr(settings, "write_policy", WritePolicy(enabled=True, rules=tuple(rules)))


async def _post(
    client: httpx.AsyncClient,
    workspace_id: str,
    *,
    title: str,
    content: str,
    memory_type: str = "fact",
    tags: list[str] | None = None,
) -> httpx.Response:
    return await client.post(
        "/v1/candidates",
        json={
            "workspace_id": workspace_id,
            "title": title,
            "content": content,
            "type": memory_type,
            "tags": tags or [],
        },
    )


async def test_policy_reject_returns_4xx_with_rule_id(
    client: httpx.AsyncClient,
    workspace: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, _ = workspace
    _enable_policy(
        monkeypatch,
        WriteRule(
            id="deny-network-noise",
            action="reject",
            types=("issue",),
            keywords=("econnreset",),
            reason="网络抖动无需入库",
        ),
    )
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    response = await _post(
        client,
        workspace_id,
        title="连接重置排查",
        content="运行时出现 ECONNRESET，连接被对端重置，需要排查上游超时配置与重试次数。",
        memory_type="issue",
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "deny-network-noise" in detail
    assert "网络抖动无需入库" in detail


async def test_policy_auto_and_review_are_recorded_on_candidate(
    client: httpx.AsyncClient,
    workspace: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, workspace_name = workspace
    _enable_policy(
        monkeypatch,
        WriteRule(
            id="pinned-auto",
            action="auto",
            workspaces=(workspace_name.casefold(),),
            tags=("pinned",),
            reason="用户指定长期保留",
        ),
        WriteRule(id="issues-review", action="review", types=("issue",)),
    )
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    auto_response = await _post(
        client,
        workspace_id,
        title="置顶约定",
        content="这是一条由写入策略自动生效的约定，正文包含足够的上下文与边界说明。",
        tags=["pinned"],
    )
    assert auto_response.status_code == 201, auto_response.text
    auto_candidate = auto_response.json()["candidate"]
    assert auto_candidate["policy_rule_id"] == "pinned-auto"
    assert auto_candidate["policy_action"] == "auto"
    assert auto_candidate["policy_reason"] == "用户指定长期保留"

    review_response = await _post(
        client,
        workspace_id,
        title="异常排查结论",
        content="这是一条需要人工确认的异常结论，正文包含现象、根因与验证步骤的完整记录。",
        memory_type="issue",
    )
    assert review_response.status_code == 201, review_response.text
    review_candidate = review_response.json()["candidate"]
    assert review_candidate["policy_rule_id"] == "issues-review"
    assert review_candidate["policy_action"] == "review"


async def test_policy_no_match_keeps_default_behavior(
    client: httpx.AsyncClient,
    workspace: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, _ = workspace
    _enable_policy(
        monkeypatch,
        WriteRule(id="only-decisions", action="auto", types=("decision",)),
    )
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    response = await _post(
        client,
        workspace_id,
        title="普通事实",
        content="这是一条没有命中任何写入策略规则的普通事实记忆，正文足够长以通过校验。",
    )

    assert response.status_code == 201, response.text
    candidate = response.json()["candidate"]
    assert candidate["policy_rule_id"] is None
    assert candidate["policy_action"] is None
    assert candidate["policy_reason"] is None
