"""apps/worker/tasks.py 测试 — 辅助函数、注册、embedding 任务。"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import apps.worker.tasks as tasks_module
from apps.worker.tasks import (
    register_tasks,
    task_auto_consolidate_similar,
    task_generate_candidate_embedding,
)
from packages.domain.config import parasitic_evolution_config
from packages.domain.database import Base
from packages.domain.models import Memory, MemoryLifecycleEvent, MemoryRelation, Workspace
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.similarity import jaccard_from_sets
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.indexer import MemoryIndexer
from packages.storage.vector_index import VectorIndex


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
    def test_registers_all_nine_tasks(self):
        queue = MagicMock()
        register_tasks(queue)
        assert queue.register.call_count == 9

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
            "auto_consolidate_similar",
            "check_review_reminders",
            "periodic_meta_export",
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

        with patch("apps.worker.tasks.async_session_maker") as mock_session:
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

        with patch("apps.worker.tasks.async_session_maker") as mock_session:
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(RuntimeError, match="Embedding generation returned None"):
                await task_generate_candidate_embedding(ctx, candidate_id)


MERGE_CONTENT = "项目使用 Python 与 FastAPI 构建后端服务，记忆检索依赖 BM25 与向量余弦融合排序。"


class TestAutoConsolidateMerge:
    async def test_auto_merge_persists_and_converges_files_and_vectors(self, tmp_path, monkeypatch):
        engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        file_store = FileStore(tmp_path / "mirrors")
        indexer = MemoryIndexer(
            str(tmp_path / "index.sqlite"),
            file_store,
            vector_index_path=str(tmp_path / "vectors.npz"),
            embedding_dimensions=3,
        )
        await indexer.init_db()
        indexer._embedding_service = SimpleNamespace(
            generate_embedding=AsyncMock(return_value=[0.5, 0.5, 0.5])
        )

        async with sessions() as db:
            ws = Workspace(name="merge-ws")
            db.add(ws)
            await db.flush()
            keeper = Memory(
                workspace_id=ws.id,
                title="Merge keeper",
                content=MERGE_CONTENT,
                type="fact",
                confidence=0.9,
                importance=0.9,
            )
            source = Memory(
                workspace_id=ws.id,
                title="Merge source",
                content=MERGE_CONTENT,
                type="fact",
                confidence=0.2,
                importance=0.2,
            )
            db.add_all([keeper, source])
            await db.commit()
            keeper_id, source_id = keeper.id, source.id
            workspace = ws.name

        for memory_id, title in ((keeper_id, "Merge keeper"), (source_id, "Merge source")):
            mirror = MemoryFile(id=str(memory_id), title=title, content=MERGE_CONTENT, type="fact")
            file_store.save(mirror, workspace_name=workspace)
            await indexer.index_memory(mirror, [0.1, 0.2, 0.3])
        await indexer.save_vector_index()
        assert {str(keeper_id), str(source_id)} <= set(indexer.vector_index.vectors)

        class _FakeBM25:
            def search(self, query, top_k):
                return [(str(keeper_id), 1.0), (str(source_id), 1.0)]

        fake_engine = SimpleNamespace(get_bm25_index=AsyncMock(return_value=_FakeBM25()))

        monkeypatch.setattr("packages.retrieval.engine.get_retrieval_engine", lambda: fake_engine)
        monkeypatch.setattr("apps.worker.tasks.async_session_maker", sessions)
        monkeypatch.setattr("apps.api.file_sync.get_file_store", lambda: file_store)
        monkeypatch.setattr("apps.api.file_sync.get_memory_indexer", lambda: indexer)
        monkeypatch.setattr(tasks_module, "_consolidate_last_snapshot", None)
        monkeypatch.setattr(parasitic_evolution_config, "auto_consolidate_enabled", True)
        monkeypatch.setattr(parasitic_evolution_config, "auto_merge_enabled", True)
        monkeypatch.setattr(parasitic_evolution_config, "auto_merge_threshold", 0.9)
        monkeypatch.setattr(tasks_module.Path, "home", lambda: tmp_path / "home")

        queue = AsyncMock()
        try:
            result = await task_auto_consolidate_similar({"queue": queue})

            assert result["auto_merged_count"] == 1

            # DB 状态已提交：源记忆归档，保留记忆已合并且带待生成的 embedding。
            async with sessions() as db:
                assert (await db.get(Memory, source_id)).status == "archived"
                keeper_row = await db.get(Memory, keeper_id)
                assert keeper_row.content == f"{MERGE_CONTENT}\n\n{MERGE_CONTENT}"
                assert keeper_row.embedding is None
                relations = (await db.execute(select(MemoryRelation))).scalars().all()
                events = (
                    (
                        await db.execute(
                            select(MemoryLifecycleEvent).where(
                                MemoryLifecycleEvent.event_type == "auto_merged"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            assert [(r.relation_type, r.target_memory_id) for r in relations] == [
                ("supersedes", source_id)
            ]
            assert len(events) == 1

            # 向量已从内存和磁盘移除；每条记忆都排队了收敛任务。
            assert str(keeper_id) not in indexer.vector_index.vectors
            assert str(source_id) not in indexer.vector_index.vectors
            reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
            assert reloaded.vectors == {}
            queue.enqueue.assert_any_await("generate_embedding", str(keeper_id))
            queue.enqueue.assert_any_await("generate_embedding", str(source_id))

            # 文件镜像与已提交状态保持一致。
            source_mirror = file_store.load(workspace, "fact", "Merge source", str(source_id))
            assert source_mirror.status == "archived"
            keeper_mirror = file_store.load(workspace, "fact", "Merge keeper", str(keeper_id))
            assert keeper_mirror.content == f"{MERGE_CONTENT}\n\n{MERGE_CONTENT}"
        finally:
            await indexer.close()
            await engine.dispose()
