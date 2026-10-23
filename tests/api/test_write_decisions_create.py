"""写入决策在候选创建端点的准入行为测试。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from packages.domain.config import agent_policy_config
from packages.domain.models import CandidateMemory, Memory
from packages.domain.write_decisions import WriteDecisionPolicy, WriteDecisionRule


@pytest.fixture
async def workspace(client: httpx.AsyncClient) -> str:
    resp = await client.post("/v1/workspaces", json={"name": f"decision-{uuid.uuid4()}"})
    assert resp.status_code == 201
    return resp.json()["id"]


def _set_policy(monkeypatch: pytest.MonkeyPatch, *rules: WriteDecisionRule, **kwargs) -> None:
    policy = WriteDecisionPolicy(
        enabled=kwargs.pop("enabled", True),
        default_action=kwargs.pop("default_action", "write"),
        rules=tuple(rules),
    )
    monkeypatch.setattr(agent_policy_config, "write_decisions", policy)
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())


async def _post(
    client: httpx.AsyncClient,
    workspace_id: str,
    *,
    title: str,
    content: str,
    memory_type: str = "fact",
    tags: list[str] | None = None,
    client_write_id: str | None = None,
) -> httpx.Response:
    body: dict = {
        "workspace_id": workspace_id,
        "title": title,
        "content": content,
        "type": memory_type,
        "tags": tags or [],
    }
    if client_write_id:
        body["client_write_id"] = client_write_id
    return await client.post("/v1/candidates", json=body)


async def test_skip_rule_rejects_without_candidate(
    client: httpx.AsyncClient,
    db_session,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(
        monkeypatch,
        WriteDecisionRule(
            id="deny-noise",
            action="skip",
            description="网络抖动无需入库",
            keywords=("ECONNRESET",),
        ),
    )

    response = await _post(
        client,
        workspace,
        title="连接重置排查",
        content="运行时出现 ECONNRESET，连接被对端重置，需要排查上游超时与重试配置。",
        memory_type="issue",
    )

    assert response.status_code == 400, response.text
    data = response.json()
    assert data["code"] == "write_decision_skip"
    assert data["write_decision"]["rule_id"] == "deny-noise"
    assert data["write_decision"]["action"] == "skip"
    count = (
        await db_session.execute(select(func.count()).select_from(CandidateMemory))
    ).scalar_one()
    assert count == 0


async def test_write_rule_admits_candidate(
    client: httpx.AsyncClient,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(
        monkeypatch,
        WriteDecisionRule(id="allow-decisions", action="write", keywords=("决策",)),
    )

    response = await _post(
        client,
        workspace,
        title="允许写入的决策",
        content="这条内容命中写入规则，应正常创建候选并记录命中的规则，便于后续审核。",
    )

    assert response.status_code == 201, response.text
    candidate = response.json()["candidate"]
    assert candidate["decision_rule_id"] == "allow-decisions"
    assert candidate["decision_action"] == "write"


async def test_default_skip_rejects_when_no_rule_matches(
    client: httpx.AsyncClient,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(monkeypatch, default_action="skip")

    response = await _post(
        client,
        workspace,
        title="默认不写入",
        content="没有任何规则命中时，默认动作 skip 会拒绝写入，不创建候选。",
    )

    assert response.status_code == 400, response.text
    data = response.json()
    assert data["code"] == "write_decision_skip"
    assert data["write_decision"]["action"] == "skip"
    assert data["write_decision"]["rule_id"] is None


async def test_update_rule_rejects_when_similar_memory_exists(
    client: httpx.AsyncClient,
    db_session,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(
        monkeypatch,
        WriteDecisionRule(
            id="update-existing",
            action="update",
            description="已有记忆需要补充时更新",
            keywords=("补充",),
        ),
    )
    title = "部署约定补充"
    content = "部署约定需要补充边界条件：仅在测试环境使用，生产环境必须走审批流程。"
    memory = Memory(
        workspace_id=uuid.UUID(workspace),
        title=title,
        content=content,
        type="fact",
        status="active",
    )
    db_session.add(memory)
    await db_session.commit()

    response = await _post(client, workspace, title=title, content=content)

    assert response.status_code == 409, response.text
    data = response.json()
    assert data["code"] == "write_decision_update"
    decision = data["write_decision"]
    assert decision["action"] == "update"
    assert decision["rule_id"] == "update-existing"
    assert decision["target_memory_id"] == str(memory.id)
    assert decision["target_title"] == title


async def test_update_rule_falls_back_when_no_similar_memory(
    client: httpx.AsyncClient,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(
        monkeypatch,
        WriteDecisionRule(id="update-existing", action="update", keywords=("补充",)),
    )
    unique = uuid.uuid4().hex
    response = await _post(
        client,
        workspace,
        title=f"独立新知识 {unique[:8]}",
        content=f"这是一条全新的独立知识，补充了唯一标识 {unique}，与现有记忆没有相似目标。",
    )

    assert response.status_code == 201, response.text
    candidate = response.json()["candidate"]
    assert candidate["decision_rule_id"] == "update-existing"
    assert candidate["decision_action"] == "write"
    assert "回退默认动作" in candidate["decision_reason"]


async def test_disabled_policy_leaves_decision_fields_empty(
    client: httpx.AsyncClient,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_policy(monkeypatch, enabled=False, default_action="skip")

    response = await _post(
        client,
        workspace,
        title="停用策略",
        content="策略停用后候选不应携带任何 decision 字段，行为完全沿用原流程。",
    )

    assert response.status_code == 201, response.text
    candidate = response.json()["candidate"]
    assert candidate["decision_rule_id"] is None
    assert candidate["decision_action"] is None
    assert candidate["decision_reason"] is None


async def test_idempotent_replay_does_not_reevaluate_decision(
    client: httpx.AsyncClient,
    workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_policy = WriteDecisionPolicy(
        enabled=True,
        default_action="write",
        rules=(WriteDecisionRule(id="admit", action="write", keywords=("幂等",)),),
    )
    _set_policy(monkeypatch, *write_policy.rules)
    write_id = f"idem-{uuid.uuid4()}"
    payload = {
        "title": "幂等候选",
        "content": "幂等写入测试内容，包含足够的上下文与唯一标识，用于验证重放不再重评决策。",
        "client_write_id": write_id,
    }

    first = await _post(client, workspace, **payload)
    assert first.status_code == 201, first.text
    first_candidate = first.json()["candidate"]
    assert first_candidate["decision_action"] == "write"

    # 规则改成 skip 后重放同一 client_write_id：应直接返回已有候选，不重新拒绝
    _set_policy(
        monkeypatch,
        WriteDecisionRule(id="deny", action="skip", keywords=("幂等",)),
    )
    second = await _post(client, workspace, **payload)
    assert second.status_code == 201, second.text
    assert second.json()["candidate"]["id"] == first_candidate["id"]
    assert second.json()["candidate"]["decision_action"] == "write"
