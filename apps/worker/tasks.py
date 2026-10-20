"""cwiki 后台任务实现。"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.worker.dedup import find_similar
from apps.worker.episode_builder import EpisodeData, build_episode
from apps.worker.scoring import score_candidate
from packages.domain.config import parasitic_evolution_config, settings
from packages.domain.database import async_session_maker
from packages.domain.models import (
    CandidateMemory,
    Episode,
    Event,
    Memory,
)
from packages.domain.models.memory import (
    MemoryConflict,
    MemoryLifecycleEvent,
    MemoryRelation,
    Review,
    ReviewSchedule,
)
from packages.domain.task_queue import TaskQueue
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.service import (
    ContentFormatError,
    create_candidate,
    snapshot_and_advance,
)
from packages.memory.similarity import jaccard_from_sets, tokenize

logger = logging.getLogger(__name__)


def _resolve_embedding_service(ctx: dict[str, Any]) -> Any:
    """从上下文取 embedding 服务，缺失时回退创建单例。"""
    svc = ctx.get("embedding_service")
    if not svc:
        from packages.retrieval.embedding import get_embedding_service

        logger.warning("embedding_service not in context, using fallback singleton")
        svc = get_embedding_service()
    return svc


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


async def task_finalize_episode(
    ctx: dict[str, Any], session_id: str, workspace_id: str
) -> dict[str, Any]:
    """从事件构建 episode 并提取记忆。"""
    logger.info("Finalizing episode for session %s", session_id)

    async with async_session_maker() as db_session:
        sid = uuid.UUID(session_id)
        wid = uuid.UUID(workspace_id)

        # 幂等守卫：队列是 at-least-once，finalize 重放/重复入队不得重建
        # episode（否则时间窗回填与规则候选生成会重复执行）
        existing_episode = (
            await db_session.execute(
                select(Episode.id).where(
                    Episode.session_id == sid,
                    Episode.workspace_id == wid,
                )
            )
        ).scalar_one_or_none()
        if existing_episode is not None:
            logger.info(
                "Episode %s already exists for session %s, skipping finalize",
                existing_episode,
                session_id,
            )
            return {"episode_id": str(existing_episode), "status": "already_finalized"}

        events_query = select(Event).where(Event.session_id == sid).order_by(Event.sequence)
        events_result = await db_session.execute(events_query)
        events = []
        for event in events_result.scalars().all():
            events.append(
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "sequence": event.sequence,
                    "payload": event.payload,
                    "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                }
            )

        if not events:
            logger.warning("No events found for session %s", session_id)
            return {"episode_id": None, "status": "no_events"}

        episode_data = build_episode(session_id, events)

        episode = Episode(
            workspace_id=wid,
            session_id=sid,
            goal=episode_data.goal,
            summary=episode_data.summary,
            status="completed",
            importance=sum(1 for _ in episode_data.actions) * 0.05,
            started_at=(
                datetime.fromisoformat(str(events[0]["occurred_at"]))
                if events[0].get("occurred_at")
                else datetime.now(UTC)
            ),
            ended_at=(
                datetime.fromisoformat(str(events[-1]["occurred_at"]))
                if events[-1].get("occurred_at")
                else datetime.now(UTC)
            ),
            event_count=len(events),
            metadata_={"lessons": episode_data.lessons},
        )

        db_session.add(episode)
        await db_session.commit()
        await db_session.refresh(episode)

        # 为 episode 生成向量以支持情节化检索
        try:
            from packages.domain.config import parasitic_evolution_config as _pec

            if _pec.episodic_retrieval_enabled:
                from packages.retrieval.embedding import get_embedding_service

                emb_text = f"{episode_data.goal or ''} {episode_data.summary or ''}".strip()
                if emb_text:
                    emb_svc = get_embedding_service()
                    vec = await emb_svc.generate_embedding(emb_text)
                    if vec is not None:
                        episode.embedding = vec
                        await db_session.flush()
        except Exception:
            logger.debug("Episode embedding generation failed", exc_info=True)

        # 回填：把 episode 时间窗内尚未关联的 pending 候选挂到该 episode 上
        # （候选表无 session 外键，这是候选与 episode 建立关联的唯一途径）
        candidates_linked = 0
        try:
            # 独立 commit：同时把上方 flush 的 episode 向量一并落库；
            # 回填失败不应让整个任务失败（episode 本身已落库成功）
            candidates_linked = await _backfill_episode_candidates(db_session, episode)
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            logger.warning(
                "Backfilling episode_id for episode %s failed", episode.id, exc_info=True
            )

        # 规则候选生成：仅当「失败→修复」信号齐备（保守触发，默认关）
        candidate_generated = False
        if (
            parasitic_evolution_config.episode_candidate_extraction_enabled
            and episode_data.problems
            and episode_data.solutions
        ):
            candidate_generated = await _generate_episode_candidate(
                db_session, ctx, episode, episode_data
            )

        logger.info("Episode %s created for session %s", episode.id, session_id)

        return {
            "episode_id": str(episode.id),
            "status": "completed",
            "event_count": len(events),
            "goal": episode_data.goal,
            "candidates_linked": candidates_linked,
            "candidate_generated": candidate_generated,
        }


# 回填时间窗的余量：单事件 episode 的 started_at == ended_at，
# 过窄的窗口会漏掉几乎同时产生的候选，前后各放宽数秒兜底
_EPISODE_BACKFILL_MARGIN = timedelta(seconds=5)


async def _backfill_episode_candidates(db_session: AsyncSession, episode: Episode) -> int:
    """把 episode 时间窗内符合条件的 pending 候选批量回填 episode_id。

    候选表没有 session 外键，只能按 workspace + 创建时间窗近似关联；
    episode_id IS NULL 条件保证重复 finalize 不会改写既有关联。
    返回回填行数。
    """
    if episode.started_at is None or episode.ended_at is None:
        return 0
    result = await db_session.execute(
        update(CandidateMemory)
        .where(
            CandidateMemory.workspace_id == episode.workspace_id,
            CandidateMemory.status == "pending_review",
            CandidateMemory.episode_id.is_(None),
            CandidateMemory.created_at >= episode.started_at - _EPISODE_BACKFILL_MARGIN,
            CandidateMemory.created_at <= episode.ended_at + _EPISODE_BACKFILL_MARGIN,
        )
        .values(episode_id=episode.id)
        .execution_options(synchronize_session=False)
    )
    # UPDATE 返回 CursorResult，rowcount 仅在其上可用
    linked = cast("CursorResult[Any]", result).rowcount
    if linked > 0:
        logger.info("Backfilled %d candidate(s) to episode %s", linked, episode.id)
    return linked


def _describe_problem(problem: dict[str, Any]) -> str | None:
    """把单条 problem 信号转成一行描述；关键字段缺失时返回 None（不编造内容）。"""
    if problem.get("type") == "tool_failure":
        tool_name = problem.get("tool_name")
        if not tool_name:
            return None
        line = f"工具 {tool_name} 调用失败"
        error = problem.get("error")
        if error:
            line += f"：{error}"
        return line
    if problem.get("type") == "test_failure":
        test_name = problem.get("test_name")
        if not test_name:
            return None
        line = f"测试 {test_name} 失败"
        error = problem.get("error")
        if error:
            line += f"：{error}"
        return line
    return None


def _describe_solution(solution: dict[str, Any]) -> str | None:
    """把单条 solution 信号转成一行描述；关键字段缺失时返回 None（不编造内容）。"""
    if solution.get("type") == "fix_applied":
        tool_name = solution.get("tool_name")
        if not tool_name:
            return None
        line = f"应用修复（{tool_name}）"
        input_summary = solution.get("input_summary")
        if input_summary:
            line += f"：{input_summary}"
        return line
    if solution.get("type") == "test_fixed":
        test_name = solution.get("test_name")
        if not test_name:
            return None
        return f"测试 {test_name} 通过"
    return None


def _build_episode_lesson_candidate(episode_data: EpisodeData) -> tuple[str, str] | None:
    """从 episode 信号构造 (标题, 正文)。

    正文组织「目标 / 遇到的问题 / 应用的解决 / 经验教训」几段，
    全部使用 problems/solutions/lessons 里的真实字段值；
    过滤后无有效问题或解决行时返回 None。
    """
    problem_lines = [line for line in (_describe_problem(p) for p in episode_data.problems) if line]
    solution_lines = [
        line for line in (_describe_solution(s) for s in episode_data.solutions) if line
    ]
    if not problem_lines or not solution_lines:
        return None

    goal = (episode_data.goal or "").strip()
    # 标题从 goal 或会话摘要截断生成，保证不超过配置上限
    title_base = goal or (episode_data.summary or "").strip() or "会话调试记录"
    title = f"调试解决：{title_base}"[: settings.memory_title_max_length]

    parts: list[str] = []
    if goal:
        parts.append(f"## 目标\n{goal}")
    parts.append("## 遇到的问题\n" + "\n".join(f"- {line}" for line in problem_lines))
    parts.append("## 应用的解决\n" + "\n".join(f"- {line}" for line in solution_lines))
    if episode_data.lessons:
        parts.append("## 经验教训\n" + "\n".join(f"- {lesson}" for lesson in episode_data.lessons))
    return title, "\n\n".join(parts) + "\n"


async def _generate_episode_candidate(
    db_session: AsyncSession,
    ctx: dict[str, Any],
    episode: Episode,
    episode_data: EpisodeData,
) -> bool:
    """按规则从 episode 的「失败→修复」信号生成一条 lesson 候选。

    幂等：client_write_id 固定为 "episode-{episode.id}"，同一 episode
    重复执行不会重复生成。校验拒绝（ContentFormatError 等）时记
    warning 并跳过，绝不中断任务。返回是否新建。
    """
    built = _build_episode_lesson_candidate(episode_data)
    if built is None:
        return False
    title, content = built

    try:
        candidate, _similar, created = await create_candidate(
            db_session,
            workspace_id=episode.workspace_id,
            title=title,
            content=content,
            type="lesson",
            source="episode",
            confidence=0.5,
            importance=0.5,
            client_write_id=f"episode-{episode.id}",
        )
        if created:
            # 生成的候选天然来源于该 episode，显式挂上关联
            candidate.episode_id = episode.id
        await db_session.commit()
    except ContentFormatError as exc:
        await db_session.rollback()
        logger.warning("Episode %s lesson candidate rejected: %s", episode.id, exc)
        return False
    except Exception:
        await db_session.rollback()
        logger.warning("Episode %s lesson candidate generation failed", episode.id, exc_info=True)
        return False

    if created:
        queue: TaskQueue | None = ctx.get("queue")
        if queue is not None:
            await queue.enqueue("generate_candidate_embedding", str(candidate.id))
        logger.info("Generated lesson candidate from episode %s", episode.id)
    return created


async def task_score_candidate(
    ctx: dict[str, Any], candidate_id: str, workspace_id: str
) -> dict[str, Any]:
    """为候选记忆评分。"""
    logger.info("Scoring candidate %s", candidate_id)

    async with async_session_maker() as db_session:
        cid = uuid.UUID(candidate_id)
        wid = uuid.UUID(workspace_id)

        candidate_query = select(CandidateMemory).where(
            CandidateMemory.id == cid,
            CandidateMemory.workspace_id == wid,
        )
        candidate_result = await db_session.execute(candidate_query)
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            return {"status": "not_found"}

        if candidate.status != "pending_review":
            # at-least-once 重放守卫：已评分/已生效/已合并的候选不再重评，
            # 否则 auto-approve 会对同一候选重复创建正式记忆
            logger.info(
                "Skipping score for candidate %s in status %r (not pending_review)",
                candidate_id,
                candidate.status,
            )
            return {"status": "skipped", "reason": f"candidate status is {candidate.status}"}

        embedding_service = _resolve_embedding_service(ctx)

        use_vector_novelty = not embedding_service.is_fallback and candidate.embedding is not None

        # 只有向量与候选齐备才用向量新颖度；否则保留提交时给的中性默认值

        existing_embeddings: list[list[float]] = []
        memory_ids: list[uuid.UUID] = []

        if use_vector_novelty:
            memories_query = (
                select(Memory.id, Memory.embedding)
                .where(
                    Memory.workspace_id == wid,
                    Memory.status == "active",
                    Memory.embedding.isnot(None),
                )
                .limit(500)
            )
            memories_result = await db_session.execute(memories_query)
            for mem_id, mem_embedding in memories_result.all():
                if mem_embedding:
                    existing_embeddings.append(list(mem_embedding))
                    memory_ids.append(mem_id)

        scored = score_candidate(
            {
                "title": candidate.title,
                "content": candidate.content,
                "reusability": candidate.reusability or 0.5,
                "stability": candidate.stability or 0.5,
                "confidence": candidate.confidence or 0.5,
                "importance": candidate.importance or 0.5,
                "evidence_strength": candidate.evidence_strength or 0.5,
                "embedding": list(candidate.embedding) if candidate.embedding else None,
                "novelty": candidate.novelty,
            },
            existing_embeddings=existing_embeddings,
        )

        candidate.value_score = scored["value_score"]
        candidate.novelty = scored["novelty"]

        if use_vector_novelty and existing_embeddings:
            candidate.duplicate_probability = 1.0 - scored["novelty"]

        similar_index = scored.get("similar_index")
        if similar_index is not None and similar_index < len(memory_ids):
            candidate.similar_memory_id = memory_ids[similar_index]
            candidate.similar_memory_source = "memory"

        if scored["priority"] == "needs_enrichment":
            # MQ-102 改造：低分/缺失维度候选标记为 needs_enrichment（可恢复），不再隔离丢弃
            logger.info(
                "Marking candidate %s as needs_enrichment (score=%s)",
                candidate_id,
                scored["value_score"],
            )
            candidate.status = "needs_enrichment"
            await db_session.commit()
            return {
                "status": "needs_enrichment",
                "value_score": scored["value_score"],
                "priority": scored["priority"],
            }

        # 三档审核：高分候选自动生效（默认关）；其余留在人工审核队列
        if settings.auto_approve_enabled:
            auto_result = await _maybe_auto_approve(db_session, ctx, candidate)
            if auto_result is not None:
                return auto_result

        await db_session.commit()

        return {
            "status": "completed",
            "value_score": scored["value_score"],
            "novelty": scored["novelty"],
            "priority": scored["priority"],
        }


def _auto_approve_reason(
    candidate: CandidateMemory,
    thresholds: dict[str, float],
    memory_id: str,
) -> str:
    """构造自动生效 Review 的决策明细 JSON（各分项 + 阈值 + 生成记忆 ID）。"""
    return json.dumps(
        {
            "memory_id": memory_id,
            "value_score": candidate.value_score,
            "confidence": candidate.confidence,
            "quality_gate_score": candidate.quality_gate_score,
            "duplicate_probability": candidate.duplicate_probability,
            "thresholds": thresholds,
        },
        ensure_ascii=False,
    )


async def _maybe_auto_approve(
    db_session: AsyncSession, ctx: dict[str, Any], candidate: CandidateMemory
) -> dict[str, Any] | None:
    """满足全部保守条件的候选自动生效为正式记忆，否则返回 None 留待人工审核。

    条件（须全部满足）：价值分、置信度、质量闸门分达阈值，
    重复概率低于阈值（须已知——embedding 缺失时不自动生效），
    且无指向该候选的 open 冲突。
    """
    thresholds = {
        "value": settings.auto_approve_value_threshold,
        "confidence": settings.auto_approve_confidence_threshold,
        "gate": settings.auto_approve_gate_threshold,
        "duplicate": settings.auto_approve_duplicate_threshold,
    }
    if (
        candidate.value_score is None
        or candidate.value_score < thresholds["value"]
        or candidate.confidence is None
        or candidate.confidence < thresholds["confidence"]
        or candidate.quality_gate_score is None
        or candidate.quality_gate_score < thresholds["gate"]
        or candidate.duplicate_probability is None
        or candidate.duplicate_probability >= thresholds["duplicate"]
    ):
        return None

    conflict_stmt = select(func.count(MemoryConflict.id)).where(
        MemoryConflict.candidate_id == candidate.id,
        MemoryConflict.status == "open",
    )
    open_conflicts = (await db_session.execute(conflict_stmt)).scalar_one()
    if open_conflicts > 0:
        logger.info(
            "Auto-approve skipped for candidate %s: %d open conflicts",
            candidate.id,
            open_conflicts,
        )
        return None

    from packages.memory.service import approve_candidate

    memory = await approve_candidate(db_session, candidate)
    await db_session.flush()

    review = Review(
        candidate_id=candidate.id,
        reviewer_type="system",
        reviewer_id="auto_tier_v1",
        action="auto_approve",
        reason=_auto_approve_reason(candidate, thresholds, str(memory.id)),
    )
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(memory)

    # 与 reviews.py 批准路径等价的后置：先落 MD 文件（无向量），
    # 向量与索引由 generate_embedding 任务补齐
    from apps.api.file_sync import sync_memory_to_file

    await sync_memory_to_file(memory, db_session, skip_vector_index=True, save_index=True)
    queue: TaskQueue = ctx["queue"]
    await queue.enqueue("generate_embedding", str(memory.id))

    logger.info(
        "Auto-approved candidate %s -> memory %s (value=%.2f)",
        candidate.id,
        memory.id,
        candidate.value_score or 0.0,
    )
    return {
        "status": "auto_approved",
        "value_score": candidate.value_score,
        "memory_id": str(memory.id),
    }


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


async def task_dedup_check(
    ctx: dict[str, Any], candidate_id: str, workspace_id: str
) -> dict[str, Any]:
    """检查重复或相似的既有记忆。"""
    logger.info("Running dedup check for candidate %s", candidate_id)

    async with async_session_maker() as db_session:
        cid = uuid.UUID(candidate_id)
        wid = uuid.UUID(workspace_id)

        candidate_query = select(CandidateMemory).where(
            CandidateMemory.id == cid,
            CandidateMemory.workspace_id == wid,
        )
        candidate_result = await db_session.execute(candidate_query)
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            return {"status": "not_found"}

        candidate_dict = {
            "title": candidate.title,
            "content": candidate.content,
            "embedding": list(candidate.embedding) if candidate.embedding else None,
        }

        similar_results = await find_similar(candidate_dict, db_session, wid)

        similar_dicts = []
        for sr in similar_results:
            similar_dicts.append(
                {
                    "memory_id": str(sr.memory_id),
                    "title": sr.title,
                    "similarity": sr.similarity,
                    "relation": sr.relation,
                    "source": sr.source,
                }
            )

        recommended_action = "approve"
        top_relation = "NEW"
        for sr in similar_results:
            if sr.relation == "MERGE":
                recommended_action = "merge"
                top_relation = sr.relation
                break
            elif sr.relation == "CONFLICT":
                recommended_action = "review_conflict"
                top_relation = sr.relation
                break
            elif sr.relation == "UPDATE":
                recommended_action = "review_update"
                top_relation = sr.relation

        candidate.dedup_relation_type = top_relation
        await db_session.flush()

        if top_relation == "CONFLICT" and similar_results:
            from packages.domain.config import parasitic_evolution_config as _pec

            if _pec.write_time_conflict_enabled:
                for sr in similar_results:
                    if sr.relation == "CONFLICT":
                        conflict = MemoryConflict(
                            workspace_id=wid,
                            memory_id=sr.memory_id,
                            candidate_id=cid,
                            conflict_type="contradiction",
                            evidence={
                                "similarity": sr.similarity,
                                "source": sr.source,
                            },
                        )
                        db_session.add(conflict)
                await db_session.flush()

        return {
            "status": "completed",
            "candidate_id": candidate_id,
            "similar_count": len(similar_dicts),
            "similar_memories": similar_dicts,
            "recommended_action": recommended_action,
        }


async def recover_orphaned_candidates(queue: TaskQueue) -> None:
    """服务崩溃后从持久化 DB 行恢复被中断的派生任务。

    候选需要向量/评分；缺向量的 active 记忆需要同时补齐 DB 列
    与文件向量索引——该双写由 ``generate_embedding`` 单条任务
    独占。存储在队列启动后才初始化，同步错误走队列重试。
    """
    async with async_session_maker() as db_session:
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


_CONSOLIDATE_THRESHOLD = settings.consolidate_threshold

# 脏标记：自上次运行以来无记忆变化则跳过昂贵的整理分析
_consolidate_last_snapshot: tuple[int, str | None] | None = None


async def task_auto_consolidate_similar(ctx: dict[str, Any]) -> dict[str, Any]:
    """发现高相似记忆分组并生成整理建议。

    用 BM25 索引预过滤，避免 O(n²) 全量两两比较：每条记忆只与
    自己的 BM25 top-k 邻居比较，复杂度从 O(n²) 降到 O(n * k)。
    受 auto_consolidate_enabled 特性开关控制。
    """
    global _consolidate_last_snapshot

    if not parasitic_evolution_config.auto_consolidate_enabled:
        return {"status": "disabled"}

    async with async_session_maker() as db_session:
        # 快速脏检查：上次运行后有无任何变化？
        snapshot_stmt = select(func.count(Memory.id), func.max(Memory.updated_at)).where(
            Memory.status == "active"
        )
        snapshot_result = await db_session.execute(snapshot_stmt)
        snapshot_row = snapshot_result.one()
        current_snapshot = (snapshot_row[0], str(snapshot_row[1]) if snapshot_row[1] else None)

        if (
            _consolidate_last_snapshot is not None
            and current_snapshot == _consolidate_last_snapshot
        ):
            return {
                "status": "skipped",
                "reason": "no_changes",
                "groups_found": 0,
                "suggestions": [],
            }

        query = (
            select(Memory.id, Memory.title, Memory.content, Memory.confidence, Memory.importance)
            .where(Memory.status == "active")
            .limit(settings.auto_consolidate_limit)
        )
        result = await db_session.execute(query)
        memories = result.all()

        if len(memories) < 2:
            return {"status": "completed", "groups_found": 0, "suggestions": []}

        # 复用检索引擎的 BM25 缓存索引，避免现场重建
        from packages.retrieval.engine import get_retrieval_engine

        engine = get_retrieval_engine()
        bm25 = await engine.get_bm25_index(db_session)

        id_to_mem: dict[str, Any] = {}
        id_to_tokens: dict[str, set[str]] = {}
        for m in memories:
            doc_id = str(m.id)
            id_to_mem[doc_id] = m
            id_to_tokens[doc_id] = tokenize(m.content)

        # 第一趟：BM25 预过滤，收集需要分词的命中 ID
        bm25_candidates: dict[str, list[str]] = {}
        extra_ids: set[str] = set()
        for m in memories:
            doc_id = str(m.id)
            candidates = bm25.search(
                format_memory_for_embedding(m.title, m.content),
                top_k=settings.auto_consolidate_top_k,
            )
            valid = [oid for oid, _ in candidates if oid != doc_id]
            bm25_candidates[doc_id] = valid
            for oid in valid:
                if oid not in id_to_tokens:
                    extra_ids.add(oid)

        # 批量加载并分词限定集之外的 BM25 命中
        if extra_ids:
            extra_uuids = [uuid.UUID(mid) for mid in extra_ids]
            detail_stmt = select(Memory.id, Memory.content).where(Memory.id.in_(extra_uuids))
            detail_result = await db_session.execute(detail_stmt)
            for row in detail_result.all():
                mid = str(row.id)
                if mid not in id_to_tokens:
                    id_to_tokens[mid] = tokenize(row.content)

        # 对每条记忆用 BM25 预过滤 + Jaccard 验证找相似记忆；
        # 用规范化键记录超阈值对（避免重复比较）
        pair_sims: dict[tuple[str, str], float] = {}
        adjacency: dict[str, set[str]] = {str(m.id): set() for m in memories}

        for m in memories:
            doc_id = str(m.id)
            tokens_i = id_to_tokens[doc_id]
            for other_id in bm25_candidates[doc_id]:
                # 规范化对键（排序去重）
                pair_key = (min(doc_id, other_id), max(doc_id, other_id))
                if pair_key in pair_sims:
                    continue
                other_tokens = id_to_tokens.get(other_id)
                if other_tokens is None:
                    continue
                sim = jaccard_from_sets(tokens_i, other_tokens)
                if sim > _CONSOLIDATE_THRESHOLD:
                    pair_sims[pair_key] = sim
                    adjacency[doc_id].add(other_id)
                    adjacency[other_id].add(doc_id)

        # 按高相似连通性分组（连通分量）
        processed: set[str] = set()
        consolidation_groups: list[list[Any]] = []

        for m in memories:
            doc_id = str(m.id)
            if doc_id in processed or not adjacency[doc_id]:
                continue
            # BFS 求连通分量
            group_ids: list[str] = []
            queue_bfs: list[str] = [doc_id]
            while queue_bfs:
                current = queue_bfs.pop(0)
                if current in processed:
                    continue
                processed.add(current)
                group_ids.append(current)
                for neighbor in adjacency[current]:
                    if neighbor not in processed:
                        queue_bfs.append(neighbor)

            if len(group_ids) >= 2:
                group = [id_to_mem[did] for did in group_ids]
                consolidation_groups.append(group)

        suggestions: list[dict[str, Any]] = []
        for group in consolidation_groups:
            group_tokens_list = [id_to_tokens[str(m.id)] for m in group]
            pairwise_sims: list[float] = []
            for a in range(len(group)):
                for b in range(a + 1, len(group)):
                    pairwise_sims.append(
                        jaccard_from_sets(group_tokens_list[a], group_tokens_list[b])
                    )
            avg_sim = sum(pairwise_sims) / len(pairwise_sims) if pairwise_sims else 0.0

            best = max(group, key=lambda m: m.confidence * 0.6 + m.importance * 0.4)

            suggestions.append(
                {
                    "memory_ids": [str(m.id) for m in group],
                    "titles": [m.title for m in group],
                    "avg_similarity": round(avg_sim, 3),
                    "recommended_keeper": str(best.id),
                    "suggestion": f"发现 {len(group)} 条高度相似记忆，建议合并为一条",
                }
            )

        logger.info(
            "Auto-consolidate found %d groups from %d memories",
            len(consolidation_groups),
            len(memories),
        )

        if suggestions:
            suggestions_path = Path.home() / ".cwiki" / "state" / "consolidation_suggestions.json"
            suggestions_path.parent.mkdir(parents=True, exist_ok=True)
            suggestions_data = {
                "generated_at": datetime.now(UTC).isoformat(),
                "suggestions": suggestions,
            }
            await asyncio.to_thread(
                suggestions_path.write_text,
                json.dumps(suggestions_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # 自动合并高相似分组
        auto_merged_count = 0
        archived_sources: list[Memory] = []
        modified_keepers: dict[uuid.UUID, Memory] = {}
        if parasitic_evolution_config.auto_merge_enabled and suggestions:
            auto_merge_threshold = parasitic_evolution_config.auto_merge_threshold
            for suggestion in suggestions:
                if suggestion["avg_similarity"] < auto_merge_threshold:
                    continue
                keeper_id = uuid.UUID(suggestion["recommended_keeper"])
                source_ids = [
                    uuid.UUID(mid)
                    for mid in suggestion["memory_ids"]
                    if mid != suggestion["recommended_keeper"]
                ]

                # 确认 keeper 无未决冲突
                conflict_check = await db_session.execute(
                    select(MemoryConflict).where(
                        MemoryConflict.memory_id == keeper_id,
                        MemoryConflict.status == "open",
                    )
                )
                if conflict_check.scalar_one_or_none() is not None:
                    continue

                keeper_row = await db_session.execute(
                    select(Memory).where(Memory.id == keeper_id, Memory.status == "active")
                )
                keeper_mem = keeper_row.scalar_one_or_none()
                if keeper_mem is None:
                    continue

                merged_parts = [keeper_mem.content]
                for sid in source_ids:
                    source_row = await db_session.execute(
                        select(Memory).where(Memory.id == sid, Memory.status == "active")
                    )
                    source_mem = source_row.scalar_one_or_none()
                    if source_mem is None:
                        continue
                    merged_parts.append(source_mem.content)

                    await snapshot_and_advance(
                        db_session,
                        keeper_mem,
                        change_type="merge",
                        changed_by_type="system",
                        reason=f"Auto-merged from memory {sid}",
                    )
                    keeper_mem.content = "\n\n".join(merged_parts)
                    keeper_mem.embedding = None

                    source_mem.status = "archived"
                    archived_sources.append(source_mem)
                    modified_keepers[keeper_id] = keeper_mem
                    relation = MemoryRelation(
                        source_memory_id=keeper_id,
                        target_memory_id=sid,
                        relation_type="supersedes",
                        confidence=suggestion["avg_similarity"],
                    )
                    db_session.add(relation)

                    lifecycle_event = MemoryLifecycleEvent(
                        id=uuid.uuid4(),
                        memory_id=keeper_id,
                        event_type="auto_merged",
                    )
                    db_session.add(lifecycle_event)

                    auto_merged_count += 1

                await db_session.flush()

        if auto_merged_count:
            # 副作用前先提交合并：镜像与向量必须跟随已提交状态；
            # 不提交的话，会话关闭时上面的 flush 会被回滚。
            await db_session.commit()

            from apps.api.file_sync import sync_memory_to_file

            queue = ctx.get("queue")
            for mem in [*modified_keepers.values(), *archived_sources]:
                try:
                    # 上面的版本 UPDATE 在 flush 后部分列未加载；
                    # 先 reload 让同步读到最新的 updated_at/status。
                    await db_session.refresh(mem)
                    # 先做持久的逐条收敛（失败由队列重试）；
                    # 归档的源记忆在此次同步中移除向量。
                    if queue is not None:
                        await queue.enqueue("generate_embedding", str(mem.id))
                    await sync_memory_to_file(
                        mem, db_session, skip_vector_index=True, save_index=True
                    )
                except Exception:
                    logger.warning(
                        "Post-commit side effect failed for memory %s", mem.id, exc_info=True
                    )

        # 更新快照，内容无变化时下次运行直接跳过
        _consolidate_last_snapshot = current_snapshot

        return {
            "status": "completed",
            "groups_found": len(consolidation_groups),
            "total_memories": len(memories),
            "suggestions": suggestions,
            "auto_merged_count": auto_merged_count,
        }


async def task_check_review_reminders(ctx: dict[str, Any]) -> dict[str, Any]:
    """检查逾期待审项并生成提醒记录。

    扫描全部工作区中 next_review 已过期的 ReviewSchedule，
    把提醒摘要写入 state 文件供主动推送机制使用。
    受 review_reminders_enabled 特性开关控制。
    """
    if not parasitic_evolution_config.review_reminders_enabled:
        return {"status": "disabled"}

    async with async_session_maker() as db_session:
        now = datetime.now(UTC).replace(tzinfo=None)

        query = (
            select(
                ReviewSchedule.workspace_id,
                ReviewSchedule.memory_id,
                ReviewSchedule.next_review,
                Memory.title,
            )
            .join(Memory, ReviewSchedule.memory_id == Memory.id)
            .where(ReviewSchedule.next_review <= now)
            .order_by(ReviewSchedule.next_review.asc())
            .limit(200)
        )
        result = await db_session.execute(query)
        due_items = result.all()

        if not due_items:
            return {"status": "completed", "due_count": 0, "reminders": []}

        # 按 workspace 分组
        by_workspace: dict[str, list[dict[str, Any]]] = {}
        for ws_id, mem_id, next_review, title in due_items:
            ws_key = str(ws_id)
            if ws_key not in by_workspace:
                by_workspace[ws_key] = []
            days_overdue = (now - next_review).days if next_review else 0
            by_workspace[ws_key].append(
                {
                    "memory_id": str(mem_id),
                    "title": title,
                    "days_overdue": days_overdue,
                }
            )

        reminders = []
        for ws_key, items in by_workspace.items():
            reminders.append(
                {
                    "workspace_id": ws_key,
                    "due_count": len(items),
                    "top_items": items[:5],  # 逾期最久的前 5 条
                }
            )

        # 写入 state 文件供推送机制使用（内容未变则跳过写盘）
        reminders_path = Path.home() / ".cwiki" / "state" / "review_reminders.json"
        reminders_path.parent.mkdir(parents=True, exist_ok=True)
        reminders_data = {
            "total_due": len(due_items),
            "reminders": reminders,
        }
        new_content = json.dumps(reminders_data, ensure_ascii=False, indent=2, sort_keys=True)

        # 与现有文件比较，避免冗余写入
        should_write = True
        try:
            existing_content = await asyncio.to_thread(reminders_path.read_text, encoding="utf-8")
            if existing_content == new_content:
                should_write = False
        except FileNotFoundError:
            pass

        if should_write:
            reminders_data["generated_at"] = datetime.now(UTC).isoformat()
            await asyncio.to_thread(
                reminders_path.write_text,
                json.dumps(reminders_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        logger.info(
            "Review reminders: %d items due across %d workspaces",
            len(due_items),
            len(by_workspace),
        )

        return {
            "status": "completed",
            "due_count": len(due_items),
            "workspace_count": len(by_workspace),
            "reminders": reminders,
        }


async def task_periodic_meta_export(ctx: dict[str, Any]) -> dict[str, Any]:
    """定期将 DB 侧车数据导出到 _meta/*.json，防止重建时回退。

    由周期调度器按 scheduler.meta_export_interval_hours 间隔触发。
    复用 scripts/migrate_to_git.py 的 export_all 逻辑。
    """
    from packages.domain.settings import get_settings
    from packages.storage import config as storage_config
    from scripts.migrate_to_git import export_all

    db_url = get_settings().database_url
    data_dir = str(storage_config.memory_dir)

    try:
        stats = await export_all(db_url, data_dir)
        logger.info(
            "Periodic meta export: %d memories, %d meta, %d workspaces",
            stats.get("memory_count", 0),
            stats.get("meta_count", 0),
            stats.get("workspace_count", 0),
        )
        return {"status": "completed", **stats}
    except Exception:
        logger.exception("Periodic meta export failed")
        return {"status": "error"}
