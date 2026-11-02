"""候选列表策略筛选：质量门控 / 价值分 / 重复度。"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import update

from packages.domain.models import CandidateMemory


async def _workspace(client: httpx.AsyncClient, name: str) -> str:
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _candidate(client: httpx.AsyncClient, ws_id: str, title: str, key: str) -> str:
    resp = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws_id,
            "title": title,
            "content": (
                f"{title} 的完整正文内容，包含足够的背景、约束与操作细节，用于验证候选策略筛选。"
            ),
            "type": "fact",
            "source": "manual",
            "client_write_id": key,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["candidate"]["id"]


async def _set_scores(db_session, candidate_id: str, **values) -> None:
    await db_session.execute(
        update(CandidateMemory)
        .where(CandidateMemory.id == uuid.UUID(candidate_id))
        .values(**values)
    )
    await db_session.commit()


async def test_candidates_filter_by_quality_gate(client, db_session):
    ws_id = await _workspace(client, "cand-filter-gate")
    high = await _candidate(client, ws_id, "高门控候选", "cand-gate-1")
    low = await _candidate(client, ws_id, "低门控候选", "cand-gate-2")

    await _set_scores(db_session, high, quality_gate_score=0.9)
    await _set_scores(db_session, low, quality_gate_score=0.4)

    resp = await client.get(
        "/v1/candidates",
        params={"workspace_id": ws_id, "min_quality_gate": 0.75},
    )
    assert resp.status_code == 200, resp.text
    titles = {item["title"] for item in resp.json()["items"]}
    assert "高门控候选" in titles
    assert "低门控候选" not in titles


async def test_candidates_filter_by_value_and_duplicate(client, db_session):
    ws_id = await _workspace(client, "cand-filter-value")
    keep = await _candidate(client, ws_id, "高价值低重复", "cand-value-1")
    low_value = await _candidate(client, ws_id, "低价值候选", "cand-value-2")
    high_dup = await _candidate(client, ws_id, "高重复候选", "cand-value-3")

    await _set_scores(db_session, keep, value_score=0.9, duplicate_probability=0.1)
    await _set_scores(db_session, low_value, value_score=0.4, duplicate_probability=0.1)
    await _set_scores(db_session, high_dup, value_score=0.9, duplicate_probability=0.8)

    resp = await client.get(
        "/v1/candidates",
        params={"workspace_id": ws_id, "min_value": 0.8, "max_duplicate": 0.5},
    )
    assert resp.status_code == 200, resp.text
    titles = {item["title"] for item in resp.json()["items"]}
    assert "高价值低重复" in titles
    assert "低价值候选" not in titles
    assert "高重复候选" not in titles
