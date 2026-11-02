"""候选评分与自动生效任务。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from apps.worker.scoring import score_candidate
from apps.worker.tasks._shared import _resolve_embedding_service
from packages.domain.config import parasitic_evolution_config, settings
from packages.domain.database import async_session_maker
from packages.domain.models import CandidateMemory, Memory
from packages.domain.models.memory import MemoryConflict, Review
from packages.domain.task_queue import TaskQueue
from packages.memory.conflict_detection import detect_write_time_conflicts
from packages.memory.service import (
    CandidateStateError,
    DuplicateMemoryError,
    approve_candidate,
    find_duplicate_for_approval,
)

logger = logging.getLogger(__name__)


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

        decision_review = candidate.decision_action == "review"

        if candidate.policy_action == "auto" and not decision_review:
            # 写入策略显式指定自动生效：优先于 needs_enrichment 与全局阈值。
            # 被冲突或高重复拦截时保留 pending_review，交给人工而不是降级留存。
            auto_result = await _maybe_auto_approve(db_session, ctx, candidate, force=True)
            if auto_result is not None:
                return auto_result
            await db_session.commit()
            return {
                "status": "policy_auto_blocked",
                "value_score": scored["value_score"],
                "priority": scored["priority"],
                "policy_rule": candidate.policy_rule_id,
            }

        if scored["priority"] == "needs_enrichment" and not decision_review:
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

        # 三档审核：高分候选自动生效（默认关）；策略/决策命中 review 时强制人工审核
        if (
            settings.auto_approve_enabled
            and candidate.policy_action != "review"
            and not decision_review
        ):
            auto_result = await _maybe_auto_approve(db_session, ctx, candidate)
            if auto_result is not None:
                return auto_result

        await db_session.commit()

        return {
            "status": "completed",
            "value_score": scored["value_score"],
            "novelty": scored["novelty"],
            "priority": scored["priority"],
            "decision_action": candidate.decision_action,
        }


def _auto_approve_reason(
    candidate: CandidateMemory,
    thresholds: dict[str, float],
    memory_id: str,
    memory_version: int,
    *,
    forced: bool = False,
) -> str:
    """构造自动生效 Review 的决策明细 JSON（各分项 + 阈值 + 生成记忆 ID）。"""
    payload = {
        "memory_id": memory_id,
        "memory_version": memory_version,
        "value_score": candidate.value_score,
        "confidence": candidate.confidence,
        "quality_gate_score": candidate.quality_gate_score,
        "duplicate_probability": candidate.duplicate_probability,
        "thresholds": thresholds,
    }
    if candidate.policy_rule_id:
        payload["policy_rule"] = candidate.policy_rule_id
        payload["policy_action"] = candidate.policy_action
    if candidate.decision_rule_id:
        payload["decision_rule"] = candidate.decision_rule_id
        payload["decision_action"] = candidate.decision_action
    if forced:
        payload["forced"] = True
    return json.dumps(payload, ensure_ascii=False)


async def _maybe_auto_approve(
    db_session: AsyncSession,
    ctx: dict[str, Any],
    candidate: CandidateMemory,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """满足全部保守条件的候选自动生效为正式记忆，否则返回 None 留待人工审核。

    ``force=True`` 用于写入策略的 ``auto`` 规则：跳过价值分/置信度/质量门阈值，
    但仍要求无 open 冲突，且已知重复概率不得达到合并阈值（>=0.95），
    避免策略规则把明显重复的内容直接转正。
    """
    thresholds = {
        "value": settings.auto_approve_value_threshold,
        "confidence": settings.auto_approve_confidence_threshold,
        "gate": settings.auto_approve_gate_threshold,
        "duplicate": settings.auto_approve_duplicate_threshold,
    }
    if not force and (
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

    if (
        force
        and candidate.duplicate_probability is not None
        and candidate.duplicate_probability >= settings.relation_merge_threshold
    ):
        logger.info(
            "Policy auto-approve blocked for candidate %s: duplicate_probability %.2f",
            candidate.id,
            candidate.duplicate_probability,
        )
        return None

    # 审批前重新查重：重复候选留在人工审核，并把目标写回候选供 UI 展示
    candidate_embedding = list(candidate.embedding) if candidate.embedding else None
    duplicate = await find_duplicate_for_approval(
        db_session,
        candidate.workspace_id,
        candidate.title,
        candidate.content,
        embedding=candidate_embedding,
    )
    if duplicate is not None:
        candidate.duplicate_probability = duplicate.similarity
        candidate.similar_memory_id = duplicate.id
        candidate.similar_memory_source = duplicate.source
        logger.info(
            "Auto-approve skipped for candidate %s: duplicate of %s",
            candidate.id,
            duplicate.id,
        )
        return None

    # 审批前用候选向量预检冲突；检测失败时保守留在人工审核，避免冲突守卫被绕过。
    if parasitic_evolution_config.write_time_conflict_enabled:
        if candidate_embedding is None:
            logger.info(
                "Auto-approve skipped for candidate %s: no embedding for conflict check",
                candidate.id,
            )
            return None
        try:
            await detect_write_time_conflicts(
                db_session,
                workspace_id=candidate.workspace_id,
                content=candidate.content,
                embedding=candidate_embedding,
                candidate_id=candidate.id,
            )
        except Exception:
            logger.warning(
                "Auto-approve conflict pre-check failed; keeping candidate pending",
                exc_info=True,
            )
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

    await db_session.flush()
    try:
        # savepoint 隔离审批：重复/状态竞态只回滚本次转正，保留已算出的评分
        async with db_session.begin_nested():
            memory = await approve_candidate(
                db_session,
                candidate,
                embedding=candidate_embedding,
                duplicate_checked=True,
            )
    except DuplicateMemoryError as exc:
        candidate.duplicate_probability = exc.similarity
        candidate.similar_memory_id = exc.similar.id
        candidate.similar_memory_source = exc.source
        set_committed_value(candidate, "status", "pending_review")
        logger.info("Auto-approve blocked for candidate %s: duplicate", candidate.id)
        return None
    except CandidateStateError:
        set_committed_value(candidate, "status", "pending_review")
        logger.info("Auto-approve skipped for candidate %s: state changed", candidate.id)
        return None
    await db_session.flush()

    review = Review(
        candidate_id=candidate.id,
        reviewer_type="system",
        reviewer_id="write_policy" if force else "auto_tier_v1",
        action="auto_approve",
        reason=_auto_approve_reason(
            candidate, thresholds, str(memory.id), memory.version, forced=force
        ),
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
    result = {
        "status": "auto_approved",
        "value_score": candidate.value_score,
        "memory_id": str(memory.id),
    }
    if candidate.policy_rule_id:
        result["policy_rule"] = candidate.policy_rule_id
    return result
