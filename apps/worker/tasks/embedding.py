"""Embedding 生成任务：记忆/候选向量与批量补齐。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from apps.worker.tasks._shared import _resolve_embedding_service
from packages.domain.database import async_session_maker
from packages.domain.models import CandidateMemory, Memory
from packages.domain.task_queue import TaskQueue
from packages.domain.text_utils import format_memory_for_embedding

logger = logging.getLogger(__name__)

# mypy no_implicit_reexport 下显式重导出：测试可 patch 本模块的
# async_session_maker 一处覆盖全部任务
__all__ = ["async_session_maker"]


async def task_generate_embedding(ctx: dict[str, Any], memory_id: str) -> dict[str, Any]:
    """为记忆生成向量并更新向量索引。"""
    logger.info("Generating embedding for memory %s", memory_id)

    async with async_session_maker() as db_session:
        mid = uuid.UUID(memory_id)

        memory_query = select(Memory).where(Memory.id == mid)
        memory_result = await db_session.execute(memory_query)
        memory = memory_result.scalar_one_or_none()

        if not memory:
            return {"status": "not_found"}

        if memory.embedding is None and memory.status == "active":
            embedding_service = _resolve_embedding_service(ctx)
            version, title, content = memory.version, memory.title, memory.content
            embedding = await embedding_service.generate_embedding(
                format_memory_for_embedding(title, content)
            )
            if not embedding:
                raise RuntimeError(f"Embedding generation returned None for memory {memory_id}")

            result = await db_session.execute(
                update(Memory)
                .where(
                    Memory.id == mid,
                    Memory.version == version,
                    Memory.title == title,
                    Memory.content == content,
                    Memory.status == "active",
                )
                .values(embedding=embedding)
                .returning(Memory.id)
                .execution_options(synchronize_session=False)
            )
            if result.scalar_one_or_none() is None:
                await db_session.rollback()
                raise RuntimeError(f"Memory {memory_id} changed during embedding generation")
            await db_session.commit()
            await db_session.refresh(memory)
            if memory.version != version:
                raise RuntimeError(f"Memory {memory_id} changed before file synchronization")

        from apps.api.file_sync import sync_memory_to_file

        # 重试/重启时复用已提交的向量；文件同步失败必须回到任务队列重试，
        # 而不能被上报为任务完成（raise_on_error=True）。
        await sync_memory_to_file(
            memory,
            db_session,
            embedding=memory.embedding,
            save_index=True,
            skip_vector_index=memory.embedding is None,
            raise_on_error=True,
        )

        return {"status": "completed", "memory_id": memory_id}


async def task_generate_candidate_embedding(
    ctx: dict[str, Any], candidate_id: str
) -> dict[str, Any]:
    """为候选记忆生成向量，随后触发评分。"""
    logger.info("Generating embedding for candidate %s", candidate_id)

    async with async_session_maker() as db_session:
        cid = uuid.UUID(candidate_id)

        candidate_query = select(CandidateMemory).where(CandidateMemory.id == cid)
        candidate_result = await db_session.execute(candidate_query)
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            return {"status": "not_found"}

        embedding_service = _resolve_embedding_service(ctx)

        embedding = await embedding_service.generate_embedding(
            format_memory_for_embedding(candidate.title, candidate.content)
        )
        if not embedding:
            await db_session.rollback()
            raise RuntimeError(f"Embedding generation returned None for candidate {candidate_id}")

        candidate.embedding = embedding
        await db_session.commit()

        queue: TaskQueue = ctx["queue"]
        await queue.enqueue("score_candidate", candidate_id, str(candidate.workspace_id))

        return {"status": "completed", "candidate_id": candidate_id}


async def task_batch_generate_embeddings(ctx: dict[str, Any]) -> dict[str, Any]:
    """批量为缺失向量的待审候选生成 embedding。

    刻意不处理记忆（Memory）：记忆的向量必须同时写入 DB 列与
    文件向量索引，只有 ``generate_embedding`` 单条任务（带版本
    守卫 + 文件同步）负责此双写。此处若直接只写 DB，会与该任务
    竞争，可能在 vectors.npz 中留下过期向量。
    """
    logger.info("Batch generating embeddings for pending candidates")

    async with async_session_maker() as db_session:
        # 收集缺向量的候选（同时取 workspace_id，避免后续 N+1 查询）
        candidates_result = await db_session.execute(
            select(
                CandidateMemory.id,
                CandidateMemory.title,
                CandidateMemory.content,
                CandidateMemory.workspace_id,
            ).where(
                CandidateMemory.status == "pending_review",
                CandidateMemory.embedding.is_(None),
            )
        )
        candidate_rows = candidates_result.all()

        if not candidate_rows:
            return {"status": "completed", "processed": 0, "candidates": 0}

        all_texts: list[str] = []
        candidate_ids: list[uuid.UUID] = []
        candidate_workspace_ids: list[uuid.UUID] = []

        for cand_row in candidate_rows:
            all_texts.append(format_memory_for_embedding(cand_row.title, cand_row.content))
            candidate_ids.append(cand_row.id)
            candidate_workspace_ids.append(cand_row.workspace_id)

        embedding_service = _resolve_embedding_service(ctx)
        embeddings = await embedding_service.generate_embeddings_batch(all_texts)

        candidates_updated = 0
        for j, emb in enumerate(embeddings):
            if emb is None:
                continue
            cid = candidate_ids[j]
            await db_session.execute(
                update(CandidateMemory)
                .where(CandidateMemory.id == cid, CandidateMemory.status == "pending_review")
                .values(embedding=emb)
                .execution_options(synchronize_session=False)
            )
            candidates_updated += 1

        await db_session.commit()

        # 为已获得向量的候选入队评分
        if candidates_updated > 0:
            queue: TaskQueue = ctx["queue"]
            for j, emb in enumerate(embeddings):
                if emb is not None:
                    await queue.enqueue(
                        "score_candidate", str(candidate_ids[j]), str(candidate_workspace_ids[j])
                    )

        logger.info("Batch embedding done: %d candidates", candidates_updated)

        return {
            "status": "completed",
            "processed": candidates_updated,
            "candidates": candidates_updated,
        }
