"""记忆列表的质量分箱过滤（质量分布页下钻）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from packages.domain.models import Memory, Workspace

LONG = "知识内容" * 20


async def _seed(db_session) -> tuple[str, dict[str, Memory]]:
    # 引擎是 session 级共享内存库：每次用唯一名称，避免跨用例串扰
    name = f"quality-filters-{uuid.uuid4().hex[:8]}"
    ws = Workspace(name=name)
    db_session.add(ws)
    await db_session.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = {
        "low": Memory(
            workspace_id=ws.id,
            title="低置信",
            content=LONG,
            type="fact",
            confidence=0.3,
            importance=0.9,
            usage_count=0,
        ),
        "mid": Memory(
            workspace_id=ws.id,
            title="中置信",
            content=LONG,
            type="fact",
            confidence=0.55,
            importance=0.55,
            usage_count=3,
        ),
        "high": Memory(
            workspace_id=ws.id,
            title="高置信",
            content=LONG,
            type="fact",
            confidence=0.9,
            importance=0.2,
            usage_count=25,
            last_used_at=now - timedelta(days=1),
        ),
        "stale": Memory(
            workspace_id=ws.id,
            title="陈旧记忆",
            content=LONG,
            type="fact",
            confidence=0.6,
            importance=0.6,
            usage_count=0,
            created_at=now - timedelta(days=120),
        ),
    }
    db_session.add_all(rows.values())
    await db_session.commit()
    return name, rows


async def _titles(client, workspace: str, **params) -> set[str]:
    resp = await client.get(
        "/v1/memories", params={"workspace_id": workspace, "limit": 50, **params}
    )
    assert resp.status_code == 200, resp.text
    return {item["title"] for item in resp.json()["items"]}


async def test_confidence_range_filters(client, db_session):
    name, _ = await _seed(db_session)

    assert await _titles(client, name, max_confidence=0.4) == {"低置信"}
    assert await _titles(client, name, min_confidence=0.4, max_confidence=0.7) == {
        "中置信",
        "陈旧记忆",
    }
    assert await _titles(client, name, min_confidence=0.7) == {"高置信"}


async def test_importance_range_filters(client, db_session):
    name, _ = await _seed(db_session)

    assert await _titles(client, name, min_importance=0.8) == {"低置信"}
    assert await _titles(client, name, max_importance=0.3) == {"高置信"}


async def test_usage_bin_filters(client, db_session):
    name, _ = await _seed(db_session)

    assert await _titles(client, name, usage="unused") == {"低置信", "陈旧记忆"}
    assert await _titles(client, name, usage="low") == {"中置信"}
    assert await _titles(client, name, usage="high") == {"高置信"}


async def test_decay_bin_filters(client, db_session):
    name, _ = await _seed(db_session)

    # 陈旧记忆创建于 120 天前且从未使用 → stale；高置信昨天用过 → fresh
    assert await _titles(client, name, decay="stale") == {"陈旧记忆"}
    fresh = await _titles(client, name, decay="fresh")
    assert "低置信" in fresh and "高置信" in fresh
