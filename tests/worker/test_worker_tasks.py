"""apps/worker/tasks.py 测试 — 辅助函数、注册、embedding 任务。"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.worker.tasks import (
    register_tasks,
    task_generate_candidate_embedding,
)
from packages.domain.database import Base
from packages.domain.models import Memory, MemoryRelation, Workspace
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.similarity import jaccard_from_sets


class TestJaccardFromSets:
    def test_identical_sets(self):
        tokens = {"a", "b", "c"}
        assert jaccard_from_sets(tokens, tokens) == 1.0

    def test_disjoint_sets(self):
        assert jaccard_from_sets({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        sim = jaccard_from_sets({"a", "b", "c"}, {"b", "c", "d"})
        assert sim == pytest.approx(0.5)

    def test_empty_first(self):
        assert jaccard_from_sets(set(), {"a"}) == 0.0

    def test_empty_second(self):
        assert jaccard_from_sets({"a"}, set()) == 0.0

    def test_both_empty(self):
        assert jaccard_from_sets(set(), set()) == 0.0


class TestRegisterTasks:
    def test_registers_all_tasks(self):
        queue = MagicMock()
        register_tasks(queue)
        assert queue.register.call_count == 10

    def test_registers_expected_task_names(self):
        queue = MagicMock()
        register_tasks(queue)
        registered_names = [call.args[0] for call in queue.register.call_args_list]
        expected = [
            "finalize_episode",
            "score_candidate",
            "generate_embedding",
            "generate_candidate_embedding",
            "batch_generate_embeddings",
            "dedup_check",
            "check_review_reminders",
            "periodic_meta_export",
            "auto_discover_relations",
            "prune_stale_relations",
        ]
        assert registered_names == expected


class TestGenerateCandidateEmbedding:
    @pytest.mark.parametrize("memory_type", ["decision", "reference"])
    @pytest.mark.parametrize(
        "content",
        [
            "  修复了一个 bug，保留原始纯文本，不添加固定标题。\n\n",
            "\n# 自由笔记\n\n- 修复 bug\n\n```python\nprint('error')\n```\n\n",
        ],
        ids=["plain_text", "free_markdown"],
    )
    async def test_preserves_content_and_type_and_only_enqueues_score(self, content, memory_type):
        candidate_id = str(uuid.uuid4())
        mock_candidate = MagicMock()
        mock_candidate.id = uuid.UUID(candidate_id)
        mock_candidate.title = "bug 修复记录"
        mock_candidate.content = content
        mock_candidate.type = memory_type
        mock_candidate.source = "memory_save"
        mock_candidate.workspace_id = uuid.uuid4()
        mock_candidate.embedding = None

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_candidate
        mock_db.execute.return_value = mock_result

        embedding = [0.1, 0.2, 0.3]
        mock_embedding_service = AsyncMock()
        mock_embedding_service.generate_embedding.return_value = embedding

        mock_queue = AsyncMock()
        ctx = {"embedding_service": mock_embedding_service, "queue": mock_queue}

        with patch("apps.worker.tasks.embedding.async_session_maker") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await task_generate_candidate_embedding(ctx, candidate_id)

        assert result == {"status": "completed", "candidate_id": candidate_id}
        assert mock_candidate.content == content
        assert mock_candidate.type == memory_type
        assert mock_candidate.embedding == embedding
        mock_embedding_service.generate_embedding.assert_awaited_once_with(
            format_memory_for_embedding(mock_candidate.title, content)
        )
        mock_db.commit.assert_awaited_once_with()
        mock_queue.enqueue.assert_awaited_once_with(
            "score_candidate", candidate_id, str(mock_candidate.workspace_id)
        )


class TestEmbeddingFailureRaises:
    """embedding 失败时 task_generate_candidate_embedding 必须抛异常，
    让任务队列可以重试，而不是静默返回错误字典。"""

    async def test_none_embedding_raises_runtime_error(self):
        candidate_id = str(uuid.uuid4())
        mock_candidate = MagicMock()
        mock_candidate.id = uuid.UUID(candidate_id)
        mock_candidate.title = "Test"
        mock_candidate.content = "Test content"
        mock_candidate.source = "memory_save"
        mock_candidate.workspace_id = uuid.uuid4()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_candidate
        mock_db.execute.return_value = mock_result

        mock_embedding_service = AsyncMock()
        mock_embedding_service.generate_embedding.return_value = None

        mock_queue = AsyncMock()
        ctx = {"embedding_service": mock_embedding_service, "queue": mock_queue}

        with patch("apps.worker.tasks.embedding.async_session_maker") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RuntimeError, match="Embedding generation returned None"):
                await task_generate_candidate_embedding(ctx, candidate_id)


class TestPruneStaleRelations:
    @pytest.fixture
    async def env(self, tmp_path, monkeypatch):
        from datetime import UTC, datetime, timedelta

        from apps.worker.tasks import maintenance

        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(maintenance, "async_session_maker", sessions)
        monkeypatch.setattr(
            maintenance.parasitic_evolution_config, "relation_auto_edge_ttl_days", 30
        )
        monkeypatch.setattr(maintenance.parasitic_evolution_config, "auto_relation_threshold", 0.75)

        async with sessions() as db:
            ws = Workspace(name="aging-ws")
            db.add(ws)
            await db.flush()
            mems = [
                Memory(workspace_id=ws.id, title=f"M{i}", content="内容" * 10, type="fact")
                for i in range(4)
            ]
            db.add_all(mems)
            await db.flush()
            now = datetime.now(UTC).replace(tzinfo=None)
            old = now - timedelta(days=60)
            db.add_all(
                [
                    # 应删除：auto、旧、低置信、从未强化
                    MemoryRelation(
                        source_memory_id=mems[0].id,
                        target_memory_id=mems[1].id,
                        relation_type="related",
                        confidence=0.6,
                        created_by="auto",
                        created_at=old,
                    ),
                    # 保留：被强化过
                    MemoryRelation(
                        source_memory_id=mems[1].id,
                        target_memory_id=mems[2].id,
                        relation_type="related",
                        confidence=0.6,
                        strength=0.5,
                        last_reinforced_at=old,
                        created_by="auto",
                        created_at=old,
                    ),
                    # 保留：人工边（即便很旧）
                    MemoryRelation(
                        source_memory_id=mems[2].id,
                        target_memory_id=mems[3].id,
                        relation_type="related",
                        confidence=0.6,
                        created_by="manual",
                        created_at=old,
                    ),
                    # 保留：未到 TTL
                    MemoryRelation(
                        source_memory_id=mems[3].id,
                        target_memory_id=mems[0].id,
                        relation_type="related",
                        confidence=0.6,
                        created_by="auto",
                        created_at=now,
                    ),
                ]
            )
            await db.commit()

        yield maintenance, sessions, select, MemoryRelation
        await engine.dispose()

    async def test_deletes_only_stale_auto_edges(self, env):
        maintenance, sessions, select, MemoryRelation = env
        result = await maintenance.task_prune_stale_relations({})

        assert result["status"] == "completed"
        assert result["deleted"] == 1
        async with sessions() as db:
            rows = (await db.execute(select(MemoryRelation))).scalars().all()
        assert len(rows) == 3
        assert {rel.created_by for rel in rows} == {"auto", "manual"}

    async def test_ttl_zero_disables_task(self, env, monkeypatch):
        maintenance, _sessions, _select, _rel = env
        monkeypatch.setattr(
            maintenance.parasitic_evolution_config, "relation_auto_edge_ttl_days", 0
        )
        result = await maintenance.task_prune_stale_relations({})
        assert result["status"] == "disabled"
