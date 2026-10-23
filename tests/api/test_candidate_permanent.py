"""候选永久声明在提交与审批链路中的保真测试。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from packages.domain.models import CandidateMemory, Memory
from packages.memory.service import approve_candidate, merge_candidate


@pytest.fixture
async def workspace_id(client: httpx.AsyncClient) -> str:
    resp = await client.post("/v1/workspaces", json={"name": f"permanent-{uuid.uuid4()}"})
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_candidate_permanent_is_saved_and_copied_on_approval(
    client: httpx.AsyncClient,
    db_session,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    response = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": workspace_id,
            "title": "候选永久声明保真",
            "content": (
                "## 场景\n用户明确要求长期保留的知识在提交候选时声明永久。\n\n"
                "## 知识\n永久标记必须随候选进入正式记忆，避免审批后重新补标。\n\n"
                "## 边界\n永久记忆不参与自动合并归档，普通记忆不受影响。"
            ),
            "type": "fact",
            "is_permanent": True,
            "permanent_reason": "用户指定长期保留",
        },
    )
    assert response.status_code == 201, response.text
    candidate_payload = response.json()["candidate"]
    assert candidate_payload["is_permanent"] is True
    assert candidate_payload["permanent_reason"] == "用户指定长期保留"

    candidate = await db_session.get(CandidateMemory, uuid.UUID(candidate_payload["id"]))
    memory = await approve_candidate(db_session, candidate)

    assert memory.is_permanent is True
    assert memory.permanent_reason == "用户指定长期保留"


async def test_permanent_reason_is_ignored_without_flag(
    client: httpx.AsyncClient,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    response = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": workspace_id,
            "title": "非永久候选不保留原因",
            "content": (
                "## 场景\n提交方只传了 permanent_reason，没有声明永久。\n\n"
                "## 知识\n原因文本不应在非永久候选上留存。\n\n"
                "## 边界\n仅影响候选字段，不改变正文。"
            ),
            "type": "fact",
            "permanent_reason": "误传的原因",
        },
    )
    assert response.status_code == 201, response.text
    candidate_payload = response.json()["candidate"]
    assert candidate_payload["is_permanent"] is False
    assert candidate_payload["permanent_reason"] is None


async def test_merge_candidate_propagates_permanent_flag(
    client: httpx.AsyncClient,
    db_session,
    workspace_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("apps.api.routes.candidates.queue.enqueue", AsyncMock())

    response = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": workspace_id,
            "title": "合并时保留永久声明",
            "content": (
                "## 场景\n永久候选被审核合并进已有记忆。\n\n"
                "## 知识\n目标记忆应继承永久标记与原因，避免用户指定被合并流程吞掉。\n\n"
                "## 边界\n仅影响永久字段，不改变合并正文。"
            ),
            "type": "fact",
            "is_permanent": True,
            "permanent_reason": "用户指定长期保留",
        },
    )
    assert response.status_code == 201, response.text
    candidate = await db_session.get(CandidateMemory, uuid.UUID(response.json()["candidate"]["id"]))

    target = Memory(
        workspace_id=uuid.UUID(workspace_id),
        title="已有目标记忆",
        content="已有目标记忆正文，内容足够长以通过校验。",
        type="fact",
    )
    db_session.add(target)
    await db_session.flush()

    merged = await merge_candidate(
        db_session,
        candidate,
        target,
        "已有目标记忆正文，内容足够长以通过校验。\n\n## 合并补充\n新增的永久知识。",
    )

    assert merged.is_permanent is True
    assert merged.permanent_reason == "用户指定长期保留"
