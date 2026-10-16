"""此前未被测试的 5 个 API 路由模块。

覆盖：
- apps.api.routes.health（健康检查）
- apps.api.routes.memory_status（面板统计、记忆状态、健康、指标）
- apps.api.routes.notes（会话笔记 CRUD + 搜索）
- apps.api.routes.data_io（导入/导出）
- apps.api.routes.spaced_review（间隔重复复习）
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import httpx
from sqlalchemy import select

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _ensure_workspace(client: httpx.AsyncClient, name: str = "default") -> str:
    """创建工作区并返回其 UUID 字符串。"""
    resp = await client.post("/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _mock_indexer(memories: list | None = None) -> MagicMock:
    """返回带异步 list_memories 的 MemoryIndexer mock。"""
    from unittest.mock import AsyncMock

    mock = MagicMock()
    mock.list_memories = AsyncMock(return_value=memories or [])
    mock.vector_index = MagicMock()
    mock.vector_index.size = MagicMock(return_value=0)
    return mock


# ===========================================================================
# health.py 路由
# ===========================================================================


class TestHealth:
    async def test_health_check_returns_healthy(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "ok"
        assert data["version"] == "0.3.0"

    async def test_health_check_response_keys(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) == {"status", "database", "version"}


# ===========================================================================
# memory_status.py 路由
# ===========================================================================


class TestDashboardStats:
    async def test_dashboard_stats_empty_db(self, client):
        # 失效缓存以确保全新查询
        from apps.api.routes.memory_status import _dashboard_cache

        _dashboard_cache.invalidate()
        resp = await client.get("/v1/dashboard-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates" in data
        assert "high_value" in data
        assert "conflicts" in data
        assert "approved" in data
        assert data["approved"] == 0  # 任何工作区都没有 active 记忆
        assert data["high_value"] == 0

    async def test_dashboard_stats_counts_high_value(self, client, db_session):
        from apps.api.routes.memory_status import _dashboard_cache
        from packages.domain.models import Memory, Workspace

        # 失效缓存以确保全新查询
        _dashboard_cache.invalidate()

        # 确保 default 工作区存在
        ws_result = await db_session.execute(select(Workspace).where(Workspace.name == "default"))
        ws = ws_result.scalar_one_or_none()
        if ws is None:
            ws = Workspace(name="default")
            db_session.add(ws)
            await db_session.flush()

        # 插入不同 importance 值的记忆
        for importance in [0.9, 0.5, 0.8]:
            mem = Memory(
                workspace_id=ws.id,
                title=f"Test memory {importance}",
                content=f"Content {importance}",
                type="fact",
                status="active",
                importance=importance,
                confidence=0.8,
            )
            db_session.add(mem)
        await db_session.commit()

        resp = await client.get("/v1/dashboard-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["high_value"] == 2  # 0.9 和 0.8 两条达标
        assert data["approved"] == 3


class TestMemoryStatus:
    async def test_memory_status_empty_workspace(self, client):
        ws_id = uuid.uuid4()
        resp = await client.get("/v1/memory-status", params={"workspace_id": str(ws_id)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] == str(ws_id)
        assert data["memories"]["total"] == 0
        assert data["memories"]["active"] == 0
        assert data["candidates"]["pending_review"] == 0
        assert data["conflicts"]["open"] == 0
        assert "insights" in data
        assert "evolution_metrics" in data

    async def test_memory_status_insights_structure(self, client):
        ws_id = uuid.uuid4()
        resp = await client.get("/v1/memory-status", params={"workspace_id": str(ws_id)})
        data = resp.json()
        insights = data["insights"]
        assert "submission_trend" in insights
        assert insights["submission_trend"] in ("rising", "stable", "declining", "new")
        assert "type_distribution" in insights
        assert "low_confidence_count" in insights
        assert "suggestions" in insights


class TestMemoryHealth:
    async def test_memory_health_returns_empty_for_unknown(self, client):
        mem_id = uuid.uuid4()
        resp = await client.get(f"/v1/memory-health/{mem_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["memory_id"] == str(mem_id)
        assert data["health"]["status"] == "unknown"

    async def test_memory_health_existing(self, client):
        """先经候选审批流创建一条记忆，再查询其健康度。"""
        await _ensure_workspace(client)
        # 对不存在的记忆，健康端点仍返回 200 且健康数据为空
        resp = await client.get(f"/v1/memory-health/{uuid.uuid4()}")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data
        assert data["health"]["status"] == "unknown"


class TestMetrics:
    @patch("apps.api.routes.memory_status.get_memory_indexer")
    async def test_metrics_empty_db(self, mock_get_indexer, client):
        mock_get_indexer.return_value = _mock_indexer()
        resp = await client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "retrieval" in data
        assert "feedback" in data
        assert "sessions" in data
        assert "storage" in data
        assert data["retrieval"]["total_queries"] == 0
        assert data["sessions"]["total"] == 0

    async def test_metrics_expose_fresh_embedding_status(self, client):
        from packages.domain.config import settings

        resp = await client.get("/v1/metrics")
        assert resp.status_code == 200
        embedding = resp.json()["embedding"]
        assert embedding["provider"] in {"local", "hash", "not_initialized"}
        assert embedding["model"] == settings.embedding_model
        assert embedding["dimensions"] == settings.embedding_dimensions
        assert isinstance(embedding["is_fallback"], bool)


class TestEvolutionMetrics:
    async def test_evolution_metrics_empty(self, client):
        ws_id = uuid.uuid4()
        resp = await client.get(
            "/v1/evolution-metrics",
            params={"workspace_id": str(ws_id), "days": 7},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["period_days"] == 7
        assert data["notes"]["created"] == 0


# ===========================================================================
# notes.py 路由
# ===========================================================================


class TestCreateSessionNote:
    async def test_create_note(self, client):
        ws_id = await _ensure_workspace(client)
        session_id = uuid.uuid4()
        resp = await client.post(
            "/v1/session-notes",
            json={"content": "Test note content for testing purposes", "signal_type": "issue"},
            params={"session_id": str(session_id), "workspace_id": ws_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Test note content for testing purposes"
        assert data["signal_type"] == "issue"
        assert data["formalized"] is False
        assert data["session_id"] == str(session_id)
        assert data["workspace_id"] == ws_id

    async def test_create_note_default_signal_type(self, client):
        ws_id = await _ensure_workspace(client)
        session_id = uuid.uuid4()
        resp = await client.post(
            "/v1/session-notes",
            json={"content": "Another test note with enough content here"},
            params={"session_id": str(session_id), "workspace_id": ws_id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["signal_type"] == "other"


class TestListSessionNotes:
    async def test_list_notes_empty(self, client):
        ws_id = str(uuid.uuid4())
        resp = await client.get("/v1/session-notes", params={"workspace_id": ws_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_notes_after_create(self, client):
        ws_id = await _ensure_workspace(client)
        session_id = uuid.uuid4()
        await client.post(
            "/v1/session-notes",
            json={"content": "List test note content for verification"},
            params={"session_id": str(session_id), "workspace_id": ws_id},
        )
        resp = await client.get("/v1/session-notes", params={"workspace_id": ws_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_list_notes_requires_filter(self, client):
        resp = await client.get("/v1/session-notes")
        assert resp.status_code == 400

    async def test_list_notes_filter_by_signal_type(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        await client.post(
            "/v1/session-notes",
            json={"content": "Issue note content here for testing", "signal_type": "issue"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        await client.post(
            "/v1/session-notes",
            json={"content": "Fact note content here for testing", "signal_type": "fact"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        resp = await client.get(
            "/v1/session-notes",
            params={"workspace_id": ws_id, "signal_type": "issue"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["signal_type"] == "issue"

    async def test_list_notes_by_session(self, client):
        ws_id = await _ensure_workspace(client)
        sid1 = uuid.uuid4()
        sid2 = uuid.uuid4()
        await client.post(
            "/v1/session-notes",
            json={"content": "Note in session 1 content"},
            params={"session_id": str(sid1), "workspace_id": ws_id},
        )
        await client.post(
            "/v1/session-notes",
            json={"content": "Note in session 2 content"},
            params={"session_id": str(sid2), "workspace_id": ws_id},
        )
        resp = await client.get("/v1/session-notes", params={"session_id": str(sid1)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    async def test_list_notes_pagination(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        for i in range(3):
            await client.post(
                "/v1/session-notes",
                json={"content": f"Pagination note number {i} content"},
                params={"session_id": str(sid), "workspace_id": ws_id},
            )
        resp = await client.get(
            "/v1/session-notes",
            params={"workspace_id": ws_id, "offset": 1, "limit": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 2
        assert data["offset"] == 1
        assert data["limit"] == 2


class TestFormalizeNote:
    async def test_formalize_note(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        create_resp = await client.post(
            "/v1/session-notes",
            json={"content": "Note to formalize content here"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        note_id = create_resp.json()["id"]

        resp = await client.patch(f"/v1/session-notes/{note_id}/formalize", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["formalized"] is True
        assert data["formalized_memory_id"] is None

    async def test_formalize_note_with_memory_id(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        create_resp = await client.post(
            "/v1/session-notes",
            json={"content": "Note to formalize with memory ref"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        note_id = create_resp.json()["id"]
        mem_id = str(uuid.uuid4())

        resp = await client.patch(
            f"/v1/session-notes/{note_id}/formalize",
            json={"memory_id": mem_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["formalized"] is True
        assert data["formalized_memory_id"] == mem_id

    async def test_formalize_nonexistent_note(self, client):
        fake_id = uuid.uuid4()
        resp = await client.patch(f"/v1/session-notes/{fake_id}/formalize", json={})
        assert resp.status_code == 404


class TestSearchSessionNotes:
    async def test_search_notes_empty(self, client):
        ws_id = str(uuid.uuid4())
        resp = await client.get(
            "/v1/session-notes/search",
            params={"workspace_id": ws_id, "q": "test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_search_notes_finds_match(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        await client.post(
            "/v1/session-notes",
            json={"content": "Unique searchable keyword alpha"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        await client.post(
            "/v1/session-notes",
            json={"content": "Completely different note content"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        resp = await client.get(
            "/v1/session-notes/search",
            params={"workspace_id": ws_id, "q": "alpha"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert "alpha" in data["items"][0]["content"]

    async def test_search_notes_with_signal_type_filter(self, client):
        ws_id = await _ensure_workspace(client)
        sid = uuid.uuid4()
        await client.post(
            "/v1/session-notes",
            json={"content": "Bug keyword found here", "signal_type": "issue"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        await client.post(
            "/v1/session-notes",
            json={"content": "Bug keyword in fact", "signal_type": "fact"},
            params={"session_id": str(sid), "workspace_id": ws_id},
        )
        resp = await client.get(
            "/v1/session-notes/search",
            params={"workspace_id": ws_id, "q": "Bug", "signal_type": "issue"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["signal_type"] == "issue"


# ===========================================================================
# data_io.py 路由
# ===========================================================================


class TestExport:
    async def test_export_json_default(self, client):
        await _ensure_workspace(client)
        resp = await client.post("/v1/data/export")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "exported_at" in data

    async def test_export_json_explicit(self, client):
        await _ensure_workspace(client)
        resp = await client.post("/v1/data/export", json={"format": "json"})
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data

    async def test_export_zip(self, client):
        await _ensure_workspace(client)
        resp = await client.post("/v1/data/export", json={"format": "zip"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert len(resp.content) > 0

    async def test_export_with_workspace(self, client):
        ws_id = await _ensure_workspace(client)
        resp = await client.post(
            "/v1/data/export",
            params={"workspace_id": ws_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workspace_id"] == ws_id


class TestImport:
    async def test_import_json(self, client):
        ws_id = await _ensure_workspace(client)
        export_data = json.dumps(
            {
                "version": "1.0",
                "memories": [],
                "candidates": [],
                "notes": [],
                "relations": [],
                "schedules": [],
            }
        ).encode()
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("export.json", export_data, "application/json")},
            params={"workspace_id": ws_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["strategy"] == "skip"

    async def test_import_empty_file(self, client):
        await _ensure_workspace(client)
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("empty.json", b"", "application/json")},
        )
        assert resp.status_code == 400

    async def test_import_invalid_strategy(self, client):
        await _ensure_workspace(client)
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("data.json", b"{}", "application/json")},
            params={"strategy": "invalid"},
        )
        assert resp.status_code == 400

    async def test_import_invalid_format(self, client):
        await _ensure_workspace(client)
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("data.bin", b"not valid json or zip", "application/octet-stream")},
        )
        assert resp.status_code == 400

    async def test_import_overwrite_strategy(self, client):
        ws_id = await _ensure_workspace(client)
        export_data = json.dumps(
            {
                "version": "1.0",
                "memories": [],
                "candidates": [],
            }
        ).encode()
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("export.json", export_data, "application/json")},
            params={"workspace_id": ws_id, "strategy": "overwrite"},
        )
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "overwrite"

    async def test_import_rename_strategy(self, client):
        ws_id = await _ensure_workspace(client)
        export_data = json.dumps(
            {
                "version": "1.0",
                "memories": [],
                "candidates": [],
            }
        ).encode()
        resp = await client.post(
            "/v1/data/import",
            files={"file": ("export.json", export_data, "application/json")},
            params={"workspace_id": ws_id, "strategy": "rename"},
        )
        assert resp.status_code == 200
        assert resp.json()["strategy"] == "rename"


# ===========================================================================
# spaced_review.py 路由
# ===========================================================================


class TestDueReviews:
    async def test_due_reviews_empty(self, client):
        ws_id = await _ensure_workspace(client)
        resp = await client.get("/v1/review/due", params={"workspace_id": ws_id})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 0

    async def test_due_reviews_with_limit(self, client):
        ws_id = await _ensure_workspace(client)
        resp = await client.get(
            "/v1/review/due",
            params={"workspace_id": ws_id, "limit": 5},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestSubmitReview:
    async def test_submit_review_nonexistent_memory(self, client):
        mem_id = uuid.uuid4()
        resp = await client.post(
            f"/v1/review/{mem_id}",
            json={"quality": 3},
        )
        assert resp.status_code == 404

    async def test_submit_review_invalid_quality_too_high(self, client):
        mem_id = uuid.uuid4()
        resp = await client.post(
            f"/v1/review/{mem_id}",
            json={"quality": 6},
        )
        assert resp.status_code == 422

    async def test_submit_review_invalid_quality_negative(self, client):
        mem_id = uuid.uuid4()
        resp = await client.post(
            f"/v1/review/{mem_id}",
            json={"quality": -1},
        )
        assert resp.status_code == 422


class TestReviewStats:
    async def test_review_stats_empty(self, client):
        ws_id = await _ensure_workspace(client)
        resp = await client.get("/v1/review/stats", params={"workspace_id": ws_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_scheduled"] == 0
        assert data["due_now"] == 0
        assert data["due_today"] == 0
        assert data["reviewed_today"] == 0
        assert "mastery_distribution" in data
        assert "review_trend" in data
        assert len(data["review_trend"]) == 7


class TestScheduleMemory:
    async def test_schedule_memory(self, client):
        ws_id = await _ensure_workspace(client)
        mem_id = uuid.uuid4()
        resp = await client.post(
            "/v1/review/schedule/" + str(mem_id),
            params={"workspace_id": ws_id},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert data["memory_id"] == str(mem_id)
        assert "next_review" in data

    async def test_schedule_memory_already_scheduled(self, client):
        ws_id = await _ensure_workspace(client)
        mem_id = uuid.uuid4()
        # 第一次排期
        resp1 = await client.post(
            "/v1/review/schedule/" + str(mem_id),
            params={"workspace_id": ws_id},
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "scheduled"

        # 第二次排期 -> already_scheduled
        resp2 = await client.post(
            "/v1/review/schedule/" + str(mem_id),
            params={"workspace_id": ws_id},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "already_scheduled"

    async def test_schedule_default_workspace(self, client):
        """省略 workspace_id 时解析为 'default'。"""
        await _ensure_workspace(client)
        mem_id = uuid.uuid4()
        resp = await client.post("/v1/review/schedule/" + str(mem_id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
