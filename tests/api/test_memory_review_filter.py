"""记忆库学习状态筛选与掌握度字段。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, ReviewSchedule, Workspace


async def _seed(db: AsyncSession):
    ws = Workspace(id=uuid.uuid4(), name=f"review-filter-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    due = Memory(
        workspace_id=ws.id, title="Due", content="知识内容" * 20, type="fact", status="active"
    )
    familiar = Memory(
        workspace_id=ws.id,
        title="Familiar",
        content="知识内容" * 20,
        type="fact",
        status="active",
    )
    unscheduled = Memory(
        workspace_id=ws.id,
        title="Unscheduled",
        content="知识内容" * 20,
        type="fact",
        status="active",
    )
    db.add_all([due, familiar, unscheduled])
    await db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    db.add_all(
        [
            ReviewSchedule(
                workspace_id=ws.id,
                memory_id=due.id,
                ease_factor=2.5,
                interval_days=1,
                repetitions=0,
                next_review=now - timedelta(days=1),
            ),
            ReviewSchedule(
                workspace_id=ws.id,
                memory_id=familiar.id,
                ease_factor=2.5,
                interval_days=6,
                repetitions=3,
                next_review=now + timedelta(days=10),
            ),
        ]
    )
    await db.commit()
    return ws, due, familiar, unscheduled


async def _titles(client: AsyncClient, ws: Workspace, review_status: str) -> set[str]:
    response = await client.get(
        "/v1/memories",
        params={"workspace_id": ws.name, "review_status": review_status, "limit": 50},
    )
    assert response.status_code == 200, response.text
    return {item["title"] for item in response.json()["items"]}


async def test_review_status_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    ws, _, _, _ = await _seed(db_session)

    assert await _titles(client, ws, "due") == {"Due"}
    assert await _titles(client, ws, "familiar") == {"Familiar"}
    assert await _titles(client, ws, "new") == {"Due"}
    assert await _titles(client, ws, "unscheduled") == {"Unscheduled"}
    assert await _titles(client, ws, "mastered") == set()


async def test_list_items_include_mastery_fields(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws, _, _, _ = await _seed(db_session)

    response = await client.get(
        "/v1/memories",
        params={"workspace_id": ws.name, "limit": 50},
    )
    assert response.status_code == 200, response.text
    by_id = {item["title"]: item for item in response.json()["items"]}

    assert by_id["Due"]["mastery_level"] == "new"
    assert by_id["Due"]["next_review"] is not None
    assert by_id["Familiar"]["mastery_level"] == "familiar"
    assert by_id["Unscheduled"]["mastery_level"] is None
    assert by_id["Unscheduled"]["next_review"] is None
