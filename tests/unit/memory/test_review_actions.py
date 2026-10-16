"""复审动作失败路径测试（POST /v1/reviews 与 /v1/reviews/batch）。

每个测试使用独立的内存引擎和类生产的 get_db 语义（每请求一个会话、
成功才提交），因此失败复审的回滚不会冲掉此前请求创建的数据。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def review_engine() -> AsyncGenerator:
    eng = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def review_client(
    review_engine, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    """类生产的 get_db 客户端：每请求一个会话，成功才提交。"""
    from apps.api.auth import AgentIdentity
    from apps.api.deps import get_current_agent, get_db
    from apps.api.main import app

    test_identity = AgentIdentity(
        agent_id="test-agent",
        workspace_id="default",
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(bind=review_engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_get_current_agent() -> AgentIdentity:
        return test_identity

    monkeypatch.setattr("apps.api.routes.reviews.task_queue.enqueue", AsyncMock())
    monkeypatch.setattr("apps.api.routes.reviews.sync_memory_to_file", AsyncMock())

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_agent] = override_get_current_agent
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def review_env(review_client: AsyncClient) -> str:
    """隔离工作区，mock 任务队列与文件同步。"""
    r = await review_client.post("/v1/workspaces", json={"name": f"review-{uuid.uuid4()}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def make_candidate(client: AsyncClient, ws: str, title: str) -> str:
    r = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws,
            "title": title,
            "content": (
                f"## 场景\n审核操作测试用候选 {title}。\n\n"
                f"## 知识\n唯一测试内容，校验码 {uuid.uuid4().hex[:12]}，仅用于验证审核端点行为。\n\n"
                f"## 原因\n测试数据，用于验证审核端点的行为契约。"
            ),
            "type": "fact",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["candidate"]["id"]


async def candidate_status(client: AsyncClient, cand_id: str) -> str:
    r = await client.get(f"/v1/candidates/{cand_id}")
    assert r.status_code == 200, r.text
    return r.json()["status"]


async def approve_to_memory(client: AsyncClient, ws: str, title: str) -> str:
    """批准一个新候选并返回创建出的 verified 记忆 id。"""
    cand_id = await make_candidate(client, ws, title)
    r = await client.post(
        "/v1/reviews",
        json={"candidate_id": cand_id, "reviewer_type": "human", "action": "approve"},
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/v1/memories?workspace_id={ws}&limit=100")
    assert r.status_code == 200, r.text
    matches = [m for m in r.json()["items"] if m["title"] == title]
    assert len(matches) == 1, f"expected exactly one memory titled {title!r}"
    return matches[0]["id"]


class TestReviewActionFailures:
    async def test_nonexistent_candidate_returns_404(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": str(uuid.uuid4()),
                "reviewer_type": "human",
                "action": "approve",
            },
        )
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    async def test_already_reviewed_candidate_returns_409(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"dup-review {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "approve"},
        )
        assert r.status_code == 201

        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "reject"},
        )
        assert r.status_code == 409
        assert "already in 'approved'" in r.json()["detail"]

    async def test_edit_without_content_returns_400(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"edit-missing {uuid.uuid4().hex[:6]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "edit"},
        )
        assert r.status_code == 400
        assert "edited_content is required" in r.json()["detail"]
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_merge_without_required_fields_returns_400(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"merge-miss {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "merge"},
        )
        assert r.status_code == 400
        assert "merged_content and merge_target_memory_id are required" in r.json()["detail"]

        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "merge",
                "merge_target_memory_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 400
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_merge_with_missing_target_returns_404(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"merge-404 {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "merge",
                "merged_content": "The merged memory preserves both sources and verifies the missing target error.",
                "merge_target_memory_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 404
        assert "Target memory" in r.json()["detail"]
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_update_without_target_returns_400(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"update-miss {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "update"},
        )
        assert r.status_code == 400
        assert "merge_target_memory_id is required" in r.json()["detail"]

    async def test_update_with_missing_target_returns_404(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"update-404 {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "update",
                "merge_target_memory_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 404
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_unknown_action_returns_400(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_id = await make_candidate(
            review_client, review_env, f"bad-action {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "destroy"},
        )
        assert r.status_code == 400
        assert "Unknown action: destroy" in r.json()["detail"]
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_failed_action_then_later_succeeds(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        """失败的动作必须干净回滚，且候选仍可复审。"""
        cand_id = await make_candidate(
            review_client, review_env, f"retry-fail {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "merge",
                "merge_target_memory_id": str(uuid.uuid4()),
                "merged_content": "This merge has no target and must leave the original candidate available for review.",
            },
        )
        assert r.status_code == 404

        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "later"},
        )
        assert r.status_code == 201
        assert await candidate_status(review_client, cand_id) == "deferred"


class TestReviewActionSuccessPaths:
    async def test_later_and_reject_actions(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        deferred_id = await make_candidate(
            review_client, review_env, f"defer-me {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": deferred_id, "reviewer_type": "human", "action": "later"},
        )
        assert r.status_code == 201
        assert await candidate_status(review_client, deferred_id) == "deferred"

        rejected_id = await make_candidate(
            review_client, review_env, f"reject-me {uuid.uuid4().hex[:8]}"
        )
        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": rejected_id,
                "reviewer_type": "human",
                "action": "reject",
                "reason": "not reusable",
            },
        )
        assert r.status_code == 201
        # reject 隔离留存：行不删除，可恢复为 pending_review
        assert await candidate_status(review_client, rejected_id) == "rejected"
        r = await review_client.post(f"/v1/candidates/{rejected_id}/restore")
        assert r.status_code == 200
        assert await candidate_status(review_client, rejected_id) == "pending_review"

    async def test_merge_action_updates_target(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        marker = f"merged marker {uuid.uuid4().hex[:12]}"
        target_id = await approve_to_memory(
            review_client, review_env, f"merge-dst {uuid.uuid4().hex[:8]}"
        )
        cand_id = await make_candidate(
            review_client, review_env, f"merge-src {uuid.uuid4().hex[:8]}"
        )

        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "merge",
                "merged_content": f"## 场景\n合并后内容。\n\n## 知识\n包含标记 {marker} 的合并文本。\n\n## 原因\n验证 merge action 生效。",
                "merge_target_memory_id": target_id,
            },
        )
        assert r.status_code == 201, r.text
        assert await candidate_status(review_client, cand_id) == "merged"

        r = await review_client.get(f"/v1/memories/{target_id}")
        assert r.status_code == 200
        assert marker in r.json()["memory"]["content"]

    async def test_update_action_replaces_target(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        cand_title = f"update-src {uuid.uuid4().hex[:8]}"
        target_id = await approve_to_memory(
            review_client, review_env, f"update-dst {uuid.uuid4().hex[:8]}"
        )
        cand_id = await make_candidate(review_client, review_env, cand_title)

        r = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "update",
                "merge_target_memory_id": target_id,
            },
        )
        assert r.status_code == 201, r.text

        r = await review_client.get(f"/v1/memories/{target_id}")
        assert r.status_code == 200
        assert r.json()["memory"]["title"] == cand_title


class TestReviewContentLimits:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("edited_title", ""),
            ("edited_title", " \n\t "),
            ("edited_title", "题" * 81),
            ("edited_content", "文" * 19),
            ("edited_content", " \n" + "文" * 19 + "\t "),
            ("merged_content", "文" * 19),
        ],
    )
    async def test_invalid_edits_leave_candidate_pending(
        self, review_client: AsyncClient, review_env: str, field: str, value: str
    ) -> None:
        cand_id = await make_candidate(review_client, review_env, "审核校验")
        payload = {
            "candidate_id": cand_id,
            "reviewer_type": "human",
            "action": "merge" if field == "merged_content" else "edit",
            "edited_content": "文" * 50,
            field: value,
        }
        response = await review_client.post("/v1/reviews", json=payload)
        assert response.status_code == 422
        assert await candidate_status(review_client, cand_id) == "pending_review"

    async def test_boundary_edit_preserves_original_content(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        from packages.domain.text_utils import normalize_memory_content

        cand_id = await make_candidate(review_client, review_env, "审核边界")
        title = "题" * 20
        content = " \n" + "文" * 50 + "\t "
        expected = normalize_memory_content(content)
        response = await review_client.post(
            "/v1/reviews",
            json={
                "candidate_id": cand_id,
                "reviewer_type": "human",
                "action": "edit",
                "edited_title": title,
                "edited_content": content,
            },
        )
        assert response.status_code == 201, response.text
        memories = await review_client.get("/v1/memories", params={"workspace_id": review_env})
        memory = next(item for item in memories.json()["items"] if item["title"] == title)
        assert memory["content"] == expected


class TestBatchReview:
    async def test_batch_reports_per_item_failures(
        self, review_client: AsyncClient, review_env: str
    ) -> None:
        ok_id = await make_candidate(review_client, review_env, f"batch-ok {uuid.uuid4().hex[:8]}")
        reused_id = await make_candidate(
            review_client, review_env, f"batch-reuse {uuid.uuid4().hex[:8]}"
        )
        unsupported_id = await make_candidate(
            review_client, review_env, f"batch-bad {uuid.uuid4().hex[:8]}"
        )

        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": reused_id, "reviewer_type": "human", "action": "approve"},
        )
        assert r.status_code == 201

        r = await review_client.post(
            "/v1/reviews/batch",
            json={
                "items": [
                    {"candidate_id": ok_id, "action": "approve"},
                    {"candidate_id": str(uuid.uuid4()), "action": "approve"},
                    {"candidate_id": reused_id, "action": "reject"},
                    {"candidate_id": unsupported_id, "action": "merge"},
                ],
                "reviewer_type": "human",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        assert body["succeeded"] == 1
        assert body["failed"] == 3

        by_id = {item["candidate_id"]: item for item in body["results"]}
        assert by_id[ok_id]["success"] is True
        assert any("not found" in item.get("error", "") for item in body["results"])
        assert any("already in 'approved'" in item.get("error", "") for item in body["results"])
        assert any("Batch mode only supports" in item.get("error", "") for item in body["results"])


DENY_CONTENT = (
    "## 场景\n发布流程缓存预热。\n\n## 知识\n发布流程中禁止提前预热缓存。\n\n"
    "## 原因\n提前预热可能导致缓存雪崩，因此禁止。"
)
ALLOW_CONTENT = (
    "## 场景\n发布流程缓存预热。\n\n## 知识\n发布流程中允许提前预热缓存。\n\n"
    "## 原因\n提前预热可以降低发布后的首查延迟。"
)
CONFLICT_EMBEDDING = [1.0] + [0.0] * 511


async def make_candidate_with_content(client: AsyncClient, ws: str, content: str) -> str:
    r = await client.post(
        "/v1/candidates",
        json={
            "workspace_id": ws,
            "title": f"冲突检测 {uuid.uuid4().hex[:8]}",
            "content": content,
            "type": "fact",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["candidate"]["id"]


class TestWriteTimeConflictDetection:
    """审批时检查必须能立即看到新记忆的 embedding。

    候选获批时 DB 的 embedding 列仍为 NULL，因此审批流程会向关系检测和
    写时冲突检测传入共享的请求内向量。
    """

    async def _seed_existing_memory(self, review_engine, ws_id: str, content: str) -> uuid.UUID:
        from packages.domain.models import Memory

        memory_id = uuid.uuid4()
        async with AsyncSession(bind=review_engine, expire_on_commit=False) as db:
            db.add(
                Memory(
                    id=memory_id,
                    workspace_id=uuid.UUID(ws_id),
                    title="发布流程缓存预热规则",
                    content=content,
                    type="fact",
                    source="mcp",
                    status="active",
                    version=1,
                    embedding=list(CONFLICT_EMBEDDING),
                )
            )
            await db.commit()
        return memory_id

    async def _fetch_conflicts(self, review_engine) -> list:
        from sqlalchemy import select

        from packages.domain.models import MemoryConflict

        async with AsyncSession(bind=review_engine, expire_on_commit=False) as db:
            result = await db.execute(select(MemoryConflict))
            return list(result.scalars().all())

    async def test_single_approval_records_conflict_with_shared_embedding(
        self, review_client: AsyncClient, review_env: str, review_engine, monkeypatch
    ) -> None:
        from packages.domain.config import parasitic_evolution_config

        monkeypatch.setattr(parasitic_evolution_config, "memory_relations_enabled", True)
        monkeypatch.setattr(parasitic_evolution_config, "write_time_conflict_enabled", True)

        existing_id = await self._seed_existing_memory(review_engine, review_env, DENY_CONTENT)

        embedding_service = AsyncMock()
        embedding_service.generate_embedding = AsyncMock(return_value=list(CONFLICT_EMBEDDING))
        monkeypatch.setattr(
            "packages.retrieval.embedding.get_embedding_service", lambda: embedding_service
        )

        cand_id = await make_candidate_with_content(review_client, review_env, ALLOW_CONTENT)
        embedding_service.generate_embedding.reset_mock()

        r = await review_client.post(
            "/v1/reviews",
            json={"candidate_id": cand_id, "reviewer_type": "human", "action": "approve"},
        )
        assert r.status_code == 201, r.text

        # 关系与冲突在每次审批中共享同一次生成
        assert embedding_service.generate_embedding.await_count == 1

        conflicts = await self._fetch_conflicts(review_engine)
        assert len(conflicts) == 1
        assert conflicts[0].memory_id == existing_id
        assert conflicts[0].conflict_type == "contradiction"
        assert conflicts[0].evidence["similarity"] > 0.7

    async def test_batch_approval_records_conflict(
        self, review_client: AsyncClient, review_env: str, review_engine, monkeypatch
    ) -> None:
        from packages.domain.config import parasitic_evolution_config

        monkeypatch.setattr(parasitic_evolution_config, "memory_relations_enabled", True)
        monkeypatch.setattr(parasitic_evolution_config, "write_time_conflict_enabled", True)

        existing_id = await self._seed_existing_memory(review_engine, review_env, DENY_CONTENT)

        embedding_service = AsyncMock()
        embedding_service.generate_embedding = AsyncMock(return_value=list(CONFLICT_EMBEDDING))
        monkeypatch.setattr(
            "packages.retrieval.embedding.get_embedding_service", lambda: embedding_service
        )

        cand_id = await make_candidate_with_content(review_client, review_env, ALLOW_CONTENT)
        embedding_service.generate_embedding.reset_mock()

        r = await review_client.post(
            "/v1/reviews/batch",
            json={
                "items": [{"candidate_id": cand_id, "action": "approve"}],
                "reviewer_type": "human",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["succeeded"] == 1

        assert embedding_service.generate_embedding.await_count == 1

        conflicts = await self._fetch_conflicts(review_engine)
        assert len(conflicts) == 1
        assert conflicts[0].memory_id == existing_id
        assert conflicts[0].evidence["similarity"] > 0.7
