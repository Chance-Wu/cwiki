"""记忆列表/详情增强端点测试：utility_score、last_used_at、反馈明细、检索命中历史。

覆盖 P2-B1 三个端点：
- GET /v1/memories（列表补 utility_score 与 last_used_at）
- GET /v1/memories/{id}/feedback（反馈明细，404 与空列表区分）
- GET /v1/memories/{id}/retrieval-history（检索命中历史，limit 与空 metadata 降级）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.domain.models import (
    Memory,
    MemoryFeedback,
    MemoryUsage,
    RetrievalTrace,
    RetrievalTraceItem,
    Workspace,
)

# 统一基准时间：全部显式指定 created_at，避免 SQLite CURRENT_TIMESTAMP
# 秒级精度导致同一事务内的记录时间相同、倒序断言不稳定
_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


async def _create_workspace(db_session, name: str) -> Workspace:
    """创建独立 workspace，保证测试间数据隔离。"""
    ws = Workspace(name=name)
    db_session.add(ws)
    await db_session.flush()
    return ws


async def _create_memory(
    db_session,
    ws: Workspace,
    title: str,
    *,
    last_used_at: datetime | None = None,
) -> Memory:
    """创建一条 active 记忆并落库（flush 即可让同会话路由可见）。"""
    mem = Memory(
        workspace_id=ws.id,
        title=title,
        content=f"content of {title}",
        type="fact",
        status="active",
        last_used_at=last_used_at,
    )
    db_session.add(mem)
    await db_session.flush()
    return mem


# ===========================================================================
# GET /v1/memories：utility_score 与 last_used_at
# ===========================================================================


class TestListMemoriesUtility:
    async def test_list_returns_utility_and_last_used_at(self, client, db_session):
        ws = await _create_workspace(db_session, "list-util")
        used_at = _NOW - timedelta(hours=2)
        mem_used = await _create_memory(db_session, ws, "Used memory", last_used_at=None)
        # 无信号对照记忆：只需要存在于列表里，id 不参与断言
        await _create_memory(db_session, ws, "Unused memory")
        db_session.add(
            MemoryUsage(
                workspace_id=ws.id,
                memory_id=mem_used.id,
                stage="used",
                created_at=used_at,
            )
        )
        db_session.add(
            MemoryFeedback(
                workspace_id=ws.id,
                memory_id=mem_used.id,
                feedback_type="useful",
                source_type="human",
                created_at=used_at,
            )
        )
        await db_session.commit()

        resp = await client.get(f"/v1/memories?workspace_id={ws.name}")
        assert resp.status_code == 200
        items = {item["title"]: item for item in resp.json()["items"]}

        # 有信号的记忆：效用分为正，last_used_at 取 usage 流水最近时间
        used_item = items["Used memory"]
        assert used_item["utility_score"] is not None
        assert used_item["utility_score"] > 0
        assert used_item["last_used_at"] is not None

        # 无任何信号的记忆：先验底分约 0.145，last_used_at 为 null
        fresh_item = items["Unused memory"]
        assert fresh_item["utility_score"] == pytest.approx(0.145, abs=1e-4)
        assert fresh_item["last_used_at"] is None

    async def test_list_last_used_at_prefers_newer_usage_over_column(self, client, db_session):
        """memory.last_used_at 列较旧、usage 流水较新时，取流水的较新值。"""
        ws = await _create_workspace(db_session, "list-fresh")
        mem = await _create_memory(
            db_session, ws, "Stale column", last_used_at=_NOW - timedelta(days=30)
        )
        db_session.add(
            MemoryUsage(
                workspace_id=ws.id,
                memory_id=mem.id,
                stage="retrieved",
                created_at=_NOW - timedelta(hours=1),
            )
        )
        await db_session.commit()

        resp = await client.get(f"/v1/memories?workspace_id={ws.name}")
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["title"] == "Stale column")
        # 输出为 naive UTC（去 tzinfo），且明显新于 30 天前的列值
        assert item["last_used_at"] is not None
        assert item["last_used_at"].startswith("2025-06-01T11:")
        assert not item["last_used_at"].endswith("+00:00")

    async def test_list_utility_null_when_aggregation_degrades(
        self, client, db_session, monkeypatch
    ):
        """聚合降级（空映射）时 utility_score 为 null 而非 0，区分"没算过"。"""
        ws = await _create_workspace(db_session, "list-null")
        await _create_memory(db_session, ws, "Any memory")

        async def _broken(db, memories):
            return {}

        monkeypatch.setattr("apps.api.routes.memories.aggregate_utility_scores", _broken)
        resp = await client.get(f"/v1/memories?workspace_id={ws.name}")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert item["utility_score"] is None


# ===========================================================================
# GET /v1/memories/{id}/feedback：反馈明细
# ===========================================================================


class TestMemoryFeedbackDetails:
    async def test_feedback_memory_not_found_returns_404(self, client):
        resp = await client.get(f"/v1/memories/{uuid.uuid4()}/feedback")
        assert resp.status_code == 404

    async def test_feedback_empty_list_for_memory_without_feedback(self, client, db_session):
        ws = await _create_workspace(db_session, "fb-empty")
        mem = await _create_memory(db_session, ws, "No feedback")
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["memory_id"] == str(mem.id)
        assert data["total"] == 0
        assert data["items"] == []

    async def test_feedback_ordered_desc_with_source_fields(self, client, db_session):
        """明细按时间倒序；human 条目无 agent 名，agent 条目带 source_id。"""
        ws = await _create_workspace(db_session, "fb-order")
        mem = await _create_memory(db_session, ws, "Feedback target")
        older_at = _NOW - timedelta(days=1)
        newer_at = _NOW - timedelta(hours=1)
        db_session.add(
            MemoryFeedback(
                workspace_id=ws.id,
                memory_id=mem.id,
                feedback_type="useful",
                source_type="human",
                reason="手动确认正确",
                created_at=older_at,
            )
        )
        db_session.add(
            MemoryFeedback(
                workspace_id=ws.id,
                memory_id=mem.id,
                feedback_type="not_useful",
                source_type="agent",
                source_id="coder-agent",
                reason="与最新代码冲突",
                created_at=newer_at,
            )
        )
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/feedback")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

        first, second = data["items"]
        assert first["source_type"] == "agent"
        assert first["source_id"] == "coder-agent"
        assert first["reason"] == "与最新代码冲突"
        assert first["feedback_type"] == "not_useful"
        assert first["created_at"].startswith("2025-06-01T11:")
        assert second["source_type"] == "human"
        assert second["source_id"] is None

    async def test_feedback_limit_is_capped(self, client, db_session):
        ws = await _create_workspace(db_session, "fb-limit")
        mem = await _create_memory(db_session, ws, "Feedback cap")
        for idx in range(3):
            db_session.add(
                MemoryFeedback(
                    workspace_id=ws.id,
                    memory_id=mem.id,
                    feedback_type="useful",
                    source_type="human",
                    created_at=_NOW - timedelta(minutes=idx),
                )
            )
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/feedback?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        # 倒序截断：保留最新的两条
        assert data["items"][0]["created_at"] >= data["items"][1]["created_at"]


# ===========================================================================
# GET /v1/memories/{id}/retrieval-history：检索命中历史
# ===========================================================================


async def _add_trace_with_hit(
    db_session,
    ws: Workspace,
    mem: Memory,
    keyword: str,
    created_at: datetime,
    *,
    rank: int = 1,
    score: float = 0.5,
    metadata: dict | None = None,
) -> RetrievalTrace:
    """构造一次带命中的检索 trace + final 阶段 trace item。"""
    trace = RetrievalTrace(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        keyword=keyword,
        metadata_=metadata,
        created_at=created_at,
    )
    db_session.add(trace)
    await db_session.flush()
    db_session.add(
        RetrievalTraceItem(
            trace_id=trace.id,
            memory_id=mem.id,
            stage="final",
            rank=rank,
            score=score,
            used=True,
            created_at=created_at,
        )
    )
    return trace


class TestMemoryRetrievalHistory:
    async def test_history_memory_not_found_returns_404(self, client):
        resp = await client.get(f"/v1/memories/{uuid.uuid4()}/retrieval-history")
        assert resp.status_code == 404

    async def test_history_empty_for_memory_never_hit(self, client, db_session):
        ws = await _create_workspace(db_session, "hist-empty")
        mem = await _create_memory(db_session, ws, "Never hit")
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/retrieval-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["memory_id"] == str(mem.id)
        assert data["total"] == 0
        assert data["items"] == []

    async def test_history_returns_hits_desc_with_signals(self, client, db_session):
        ws = await _create_workspace(db_session, "hist-signal")
        mem = await _create_memory(db_session, ws, "Hit memory")
        other_id = str(uuid.uuid4())
        mem_key = str(mem.id)
        metadata = {
            "signals": {
                mem_key: {"bm25": 1.5, "vector": 0.8, "rrf": 0.03, "rerank": 0.9, "utility": 0.4},
                other_id: {"bm25": 2.0},
            },
            "filter_reasons": [
                {"memory_id": other_id, "stage": "entry", "reason": "stale"},
                {"memory_id": mem_key, "stage": "entry", "reason": "low_confidence"},
            ],
        }
        t_old = await _add_trace_with_hit(
            db_session,
            ws,
            mem,
            "old query",
            _NOW - timedelta(days=2),
            rank=3,
            score=0.42,
        )
        t_new = await _add_trace_with_hit(
            db_session,
            ws,
            mem,
            "new query",
            _NOW - timedelta(hours=1),
            rank=1,
            score=0.91,
            metadata=metadata,
        )
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/retrieval-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

        newest, oldest = data["items"]
        assert newest["query"] == "new query"
        assert newest["rank"] == 1
        assert newest["score"] == pytest.approx(0.91)
        assert newest["used"] is True
        assert newest["signals"] == {
            "bm25": 1.5,
            "vector": 0.8,
            "rrf": 0.03,
            "rerank": 0.9,
            "utility": 0.4,
        }
        # filter_reasons 只保留本记忆的条目，其他记忆的原因不串扰
        assert newest["filter_reasons"] == [
            {"memory_id": mem_key, "stage": "entry", "reason": "low_confidence"}
        ]
        assert newest["trace_id"] == str(t_new.id)

        assert oldest["query"] == "old query"
        assert oldest["rank"] == 3
        assert oldest["trace_id"] == str(t_old.id)
        assert oldest["signals"] == {}
        assert oldest["filter_reasons"] == []

    async def test_history_defaults_to_five_and_caps_at_twenty(self, client, db_session):
        ws = await _create_workspace(db_session, "hist-limit")
        mem = await _create_memory(db_session, ws, "Frequently hit")
        for idx in range(7):
            await _add_trace_with_hit(
                db_session,
                ws,
                mem,
                f"query {idx}",
                _NOW - timedelta(hours=idx),
            )
        await db_session.commit()

        # 默认 limit=5，total 仍反映全部命中次数
        resp = await client.get(f"/v1/memories/{mem.id}/retrieval-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 7
        assert len(data["items"]) == 5
        # 倒序：最新的排最前
        assert data["items"][0]["query"] == "query 0"

        # 超上限被 422 拒绝
        resp = await client.get(f"/v1/memories/{mem.id}/retrieval-history?limit=21")
        assert resp.status_code == 422

    async def test_history_null_metadata_degrades_to_empty(self, client, db_session):
        """explain 关闭时 trace 无 metadata，signals/filter_reasons 空默认。"""
        ws = await _create_workspace(db_session, "hist-nometa")
        mem = await _create_memory(db_session, ws, "No meta hit")
        await _add_trace_with_hit(
            db_session, ws, mem, "bare query", _NOW - timedelta(hours=3), metadata=None
        )
        await db_session.commit()

        resp = await client.get(f"/v1/memories/{mem.id}/retrieval-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        hit = data["items"][0]
        assert hit["query"] == "bare query"
        assert hit["signals"] == {}
        assert hit["filter_reasons"] == []


# 兜底：确认数据确实入库（防止夹具静默失败导致空跑）
async def test_fixture_rows_persisted_in_session(db_session):
    ws = await _create_workspace(db_session, "persist-check")
    mem = await _create_memory(db_session, ws, "Persist probe")
    await db_session.commit()
    result = await db_session.execute(select(Memory).where(Memory.id == mem.id))
    assert result.scalar_one_or_none() is not None
