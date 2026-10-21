"""候选标签在提交与审批链路中的保真测试。"""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from packages.domain.models import CandidateMemory
from packages.memory.service import approve_candidate


@pytest.fixture
async def workspace_id(client: httpx.AsyncClient) -> str:
    resp = await client.post("/v1/workspaces", json={"name": f"tags-{uuid.uuid4()}"})
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_candidate_tags_are_saved_and_copied_on_approval(
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
            "title": "候选标签保真",
            "content": (
                "## 场景\n候选提交时写入标签，审批通过后转为正式记忆。\n\n"
                "## 知识\n标签必须随候选进入正式记忆，避免审批后重新补标。\n\n"
                "## 边界\n仅验证标签字段，不改变候选正文与审批流程。"
            ),
            "type": "fact",
            "tags": ["cwiki", "标签"],
        },
    )
    assert response.status_code == 201, response.text
    candidate_payload = response.json()["candidate"]
    assert candidate_payload.get("tags") == ["cwiki", "标签"]

    candidate = await db_session.get(CandidateMemory, uuid.UUID(candidate_payload["id"]))
    memory = await approve_candidate(db_session, candidate)

    assert memory.tags == ["cwiki", "标签"]
