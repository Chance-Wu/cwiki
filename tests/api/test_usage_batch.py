"""`/v1/usage/batch` 与 `/v1/usage/gaps`：召回交付信号回流。

回归背景：utility 的 retrieval_success / agent_usage 分量（合计权重 0.55）
长期没有生产者，真实库里 memory_usage 只有 retrieved，进化信号断链。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, MemoryUsage, Workspace


@pytest.fixture
async def seeded(db_session: AsyncSession) -> dict[str, str]:
    ws = Workspace(id=uuid.uuid4(), name="usage-ws")
    db_session.add(ws)
    await db_session.flush()
    hit = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="WAL checkpoint 顺序",
        content="## 知识\n提交前必须 wal_checkpoint(TRUNCATE)。",
        type="fact",
        status="active",
    )
    delivered = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="SQLite 索引重建",
        content="## 知识\n索引文件存在时跳过 embedding 重算。",
        type="lesson",
        status="active",
    )
    db_session.add_all([hit, delivered])
    await db_session.flush()
    # hit 只被检索命中；delivered 既有检索也有交付
    db_session.add_all(
        [MemoryUsage(workspace_id=ws.id, memory_id=hit.id, stage="retrieved") for _ in range(6)]
        + [
            MemoryUsage(workspace_id=ws.id, memory_id=delivered.id, stage="retrieved")
            for _ in range(6)
        ]
        + [MemoryUsage(workspace_id=ws.id, memory_id=delivered.id, stage="used") for _ in range(2)]
    )
    await db_session.commit()
    return {"workspace": ws.name, "hit": str(hit.id), "delivered": str(delivered.id)}


async def _post_batch(client: AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/v1/usage/batch", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def test_delivery_events_recorded_with_memory_workspace(
    client: AsyncClient, db_session: AsyncSession, seeded: dict[str, str]
) -> None:
    result = await _post_batch(
        client,
        {
            "records": [
                {
                    "record_id": "rec-1",
                    "session_id": "host-session-abc",
                    "events": [
                        {"memory_id": seeded["hit"], "stage": "used", "position": 0},
                        {"memory_id": seeded["hit"], "stage": "cited"},
                    ],
                }
            ]
        },
    )
    assert result == {
        "accepted": 2,
        "skipped_duplicates": 0,
        "skipped_unknown": 0,
        "rejected_stages": 0,
    }

    rows = (
        (
            await db_session.execute(
                select(MemoryUsage).where(MemoryUsage.memory_id == seeded["hit"])
            )
        )
        .scalars()
        .all()
    )
    delivery = [r for r in rows if r.stage in ("used", "cited")]
    assert sorted(r.stage for r in delivery) == ["cited", "used"]
    # 工作区归属取记忆行自身，不信任调用方
    ws_id = (
        await db_session.execute(select(Workspace.id).where(Workspace.name == "usage-ws"))
    ).scalar_one()
    assert all(r.workspace_id == ws_id for r in delivery)
    # 非 UUID 的宿主会话 id 归一为稳定 UUID
    assert all(r.session_id is not None for r in delivery)


async def test_same_record_id_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, seeded: dict[str, str]
) -> None:
    body = {
        "records": [
            {
                "record_id": "rec-dup",
                "events": [{"memory_id": seeded["hit"], "stage": "used"}],
            }
        ]
    }
    first = await _post_batch(client, body)
    assert first["accepted"] == 1

    second = await _post_batch(client, body)
    assert second == {
        "accepted": 0,
        "skipped_duplicates": 1,
        "skipped_unknown": 0,
        "rejected_stages": 0,
    }
    count = (
        await db_session.execute(
            select(MemoryUsage.id).where(
                MemoryUsage.memory_id == seeded["hit"], MemoryUsage.stage == "used"
            )
        )
    ).all()
    assert len(count) == 1


async def test_partial_respool_only_new_records_applied(
    client: AsyncClient, db_session: AsyncSession, seeded: dict[str, str]
) -> None:
    """spool 补投：整批重试时旧 record 幂等跳过，新 record 正常入库。"""
    rec_a = {"record_id": "rec-a", "events": [{"memory_id": seeded["hit"], "stage": "used"}]}
    rec_b = {
        "record_id": "rec-b",
        "events": [{"memory_id": seeded["delivered"], "stage": "cited"}],
    }
    assert (await _post_batch(client, {"records": [rec_a]}))["accepted"] == 1
    result = await _post_batch(client, {"records": [rec_a, rec_b]})
    assert result["accepted"] == 1
    assert result["skipped_duplicates"] == 1


async def test_unknown_memory_and_bad_stage_skipped(
    client: AsyncClient, seeded: dict[str, str]
) -> None:
    result = await _post_batch(
        client,
        {
            "records": [
                {
                    "record_id": "rec-x",
                    "events": [
                        {"memory_id": str(uuid.uuid4()), "stage": "used"},
                        {"memory_id": seeded["hit"], "stage": "retrieved"},
                        {"memory_id": seeded["hit"], "stage": "used"},
                    ],
                }
            ]
        },
    )
    # retrieved 由检索引擎自己写，外部不允许伪造
    assert result == {
        "accepted": 1,
        "skipped_duplicates": 0,
        "skipped_unknown": 1,
        "rejected_stages": 1,
    }


async def test_gaps_lists_retrieved_never_delivered(
    client: AsyncClient, seeded: dict[str, str]
) -> None:
    response = await client.get(
        "/v1/usage/gaps",
        params={"workspace": seeded["workspace"], "min_retrievals": 5, "since_days": 30},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    ids = {item["memory_id"] for item in data["items"]}
    # hit 只有 retrieved；delivered 有 used 交付信号，不进缺口
    assert seeded["hit"] in ids
    assert seeded["delivered"] not in ids
