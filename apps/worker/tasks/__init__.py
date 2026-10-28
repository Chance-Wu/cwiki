"""cwiki 后台任务实现。

按任务域拆分：
- ``episode``          会话 episode 构建与 lesson 候选生成
- ``candidate_review`` 候选评分与自动生效
- ``embedding``        记忆/候选向量生成
- ``dedup_check``      候选去重检查
- ``consolidate``      相似记忆自动整理
- ``maintenance``      复习提醒与定期 meta 导出

公开名从此包根重导出，``from apps.worker.tasks import X`` 兼容旧引用。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from apps.worker.tasks._shared import _resolve_embedding_service
from apps.worker.tasks.candidate_review import (
    _auto_approve_reason,
    _maybe_auto_approve,
    task_score_candidate,
)
from apps.worker.tasks.consolidate import task_auto_consolidate_similar
from apps.worker.tasks.dedup_check import task_dedup_check
from apps.worker.tasks.embedding import (
    task_batch_generate_embeddings,
    task_generate_candidate_embedding,
    task_generate_embedding,
)
from apps.worker.tasks.episode import (
    _backfill_episode_candidates,
    _build_episode_lesson_candidate,
    _describe_problem,
    _describe_solution,
    _generate_episode_candidate,
    task_finalize_episode,
)
from apps.worker.tasks.maintenance import (
    task_auto_discover_relations,
    task_check_review_reminders,
    task_periodic_meta_export,
)
from packages.domain.models import CandidateMemory, Memory
from packages.domain.task_queue import TaskQueue

logger = logging.getLogger(__name__)

__all__ = [
    "_auto_approve_reason",
    "_backfill_episode_candidates",
    "_build_episode_lesson_candidate",
    "_describe_problem",
    "_describe_solution",
    "_generate_episode_candidate",
    "_maybe_auto_approve",
    "_resolve_embedding_service",
    "recover_orphaned_candidates",
    "register_tasks",
    "task_auto_consolidate_similar",
    "task_auto_discover_relations",
    "task_batch_generate_embeddings",
    "task_check_review_reminders",
    "task_dedup_check",
    "task_finalize_episode",
    "task_generate_candidate_embedding",
    "task_generate_embedding",
    "task_periodic_meta_export",
    "task_score_candidate",
]


def register_tasks(queue: TaskQueue) -> None:
    """向队列注册全部任务函数。"""
    queue.register("finalize_episode", task_finalize_episode)
    queue.register("score_candidate", task_score_candidate)
    queue.register("generate_embedding", task_generate_embedding)
    queue.register("generate_candidate_embedding", task_generate_candidate_embedding)
    queue.register("batch_generate_embeddings", task_batch_generate_embeddings)
    queue.register("dedup_check", task_dedup_check)
    queue.register("auto_consolidate_similar", task_auto_consolidate_similar)
    queue.register("check_review_reminders", task_check_review_reminders)
    queue.register("periodic_meta_export", task_periodic_meta_export)
    queue.register("auto_discover_relations", task_auto_discover_relations)


async def recover_orphaned_candidates(queue: TaskQueue) -> None:
    """服务崩溃后从持久化 DB 行恢复被中断的派生任务。

    候选需要向量/评分；缺向量的 active 记忆需要同时补齐 DB 列
    与文件向量索引——该双写由 ``generate_embedding`` 单条任务
    独占。存储在队列启动后才初始化，同步错误走队列重试。

    async_session_maker 经 embedding 子模块的模块属性在运行时
    解析：恢复与补齐是同一链路，测试/运行时 patch
    ``apps.worker.tasks.embedding.async_session_maker`` 一处即全覆盖。
    """
    from apps.worker.tasks import embedding as _embedding

    async with _embedding.async_session_maker() as db_session:
        try:
            no_embedding_stmt = select(CandidateMemory.id, CandidateMemory.workspace_id).where(
                CandidateMemory.status == "pending_review",
                CandidateMemory.embedding.is_(None),
            )
            no_embedding_result = await db_session.execute(no_embedding_stmt)
            orphans_no_emb = no_embedding_result.all()

            not_scored_stmt = select(CandidateMemory.id, CandidateMemory.workspace_id).where(
                CandidateMemory.status == "pending_review",
                CandidateMemory.embedding.isnot(None),
                CandidateMemory.value_score.is_(None),
            )
            not_scored_result = await db_session.execute(not_scored_stmt)
            orphans_not_scored = not_scored_result.all()

            # 缺向量的候选统一走一个批量任务
            if orphans_no_emb:
                await queue.enqueue("batch_generate_embeddings")
                logger.info(
                    "Enqueued batch embedding task for %d orphaned candidates", len(orphans_no_emb)
                )

            # 缺向量的记忆走逐条任务，保证 DB 列与 vectors.npz 在版本
            # 守卫下同时写入。
            missing_memory_stmt = select(Memory.id).where(
                Memory.status == "active",
                Memory.embedding.is_(None),
            )
            missing_memory_result = await db_session.execute(missing_memory_stmt)
            missing_memory_ids = missing_memory_result.scalars().all()

            if missing_memory_ids:
                for mem_id in missing_memory_ids:
                    await queue.enqueue("generate_embedding", str(mem_id))
                logger.info("Enqueued embedding recovery for %d memories", len(missing_memory_ids))

            if not orphans_not_scored:
                return

            logger.info("Recovering %d orphaned candidates for scoring", len(orphans_not_scored))

            for cand_id, cand_ws_id in orphans_not_scored:
                await queue.enqueue("score_candidate", str(cand_id), str(cand_ws_id))

            logger.info(
                "Re-enqueued %d orphaned candidates for scoring",
                len(orphans_not_scored),
            )
        except Exception:
            logger.exception("Failed to recover orphaned candidates")
            raise
