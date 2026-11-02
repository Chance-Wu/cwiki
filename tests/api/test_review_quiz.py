"""复习填空 API：出题不泄题、判分自动更新计划并写入历史。"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Memory, ReviewHistory, Workspace

CONTENT = (
    "## 知识\n"
    "ThreadPool 必须设置 max_workers，否则任务会排队。\n\n"
    "```python\nThreadPool(max_workers=4)\n```\n"
)


async def _seed_memory(db: AsyncSession) -> tuple[Workspace, Memory]:
    ws = Workspace(id=uuid.uuid4(), name=f"quiz-ws-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    memory = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="`ThreadPool` 配置",
        content=CONTENT,
        type="fact",
        tags=["python", "并发"],
        source="mcp",
        status="active",
        version=1,
    )
    db.add(memory)
    await db.commit()
    return ws, memory


async def test_get_quiz_does_not_leak_answers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws, memory = await _seed_memory(db_session)

    response = await client.get(
        f"/v1/review/quiz/{memory.id}",
        params={"workspace_id": ws.name},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "cloze"
    assert body["blank_count"] == 1
    assert "____" in body["prompt"]
    assert "ThreadPool" not in body["prompt"].split("```")[0]
    assert "expected_terms" not in body


async def test_submit_quiz_scores_and_updates_schedule(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws, memory = await _seed_memory(db_session)

    response = await client.post(
        f"/v1/review/quiz/{memory.id}",
        params={"workspace_id": ws.name},
        json={"kind": "cloze", "answers": [" threadpool "]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["correct"] is True
    assert body["matched"] == 1
    assert body["total"] == 1
    assert body["quality"] == 5
    assert body["expected_terms"] == ["ThreadPool"]
    assert body["repetitions"] == 1
    assert body["interval_days"] == 1

    history = (
        await db_session.execute(select(ReviewHistory).where(ReviewHistory.memory_id == memory.id))
    ).scalar_one()
    assert history.quality == 5
    assert history.quiz_type == "cloze"
    assert history.quiz_correct is True
    assert '"ThreadPool"' in (history.quiz_expected or "")
    assert "threadpool" in (history.quiz_response or "")

    stats = await client.get(
        "/v1/review/stats",
        params={"workspace_id": ws.name, "tz_offset_minutes": 0},
    )
    assert stats.status_code == 200, stats.text
    stats_body = stats.json()
    assert stats_body["quiz_attempts"] == 1
    assert stats_body["quiz_correct"] == 1
    assert stats_body["quiz_accuracy"] == 1.0


async def test_wrong_answer_maps_to_failure_quality(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws, memory = await _seed_memory(db_session)

    response = await client.post(
        f"/v1/review/quiz/{memory.id}",
        params={"workspace_id": ws.name},
        json={"kind": "cloze", "answers": ["wrong"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["correct"] is False
    assert body["quality"] == 1
    assert body["lapse_streak"] == 1
