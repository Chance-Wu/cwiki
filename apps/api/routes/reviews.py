"""候选记忆审核工作流端点。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    apply_optional_filters,
    execute_paginated,
    get_current_agent,
    get_db,
    get_or_404,
    require_scope,
)
from apps.api.file_sync import sync_memory_to_file
from apps.api.routes.context import invalidate_context_cache
from apps.api.routes.memory_status import invalidate_memory_status_caches
from apps.api.routes.search import invalidate_search_cache
from packages.domain.config import API_V1_PREFIX, parasitic_evolution_config
from packages.domain.models import CandidateMemory, Memory, MemoryRelation, Review
from packages.domain.schemas import (
    PaginatedResponse,
    ReviewCreate,
    ReviewRead,
)
from packages.domain.task_queue import queue as task_queue
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.service import (
    approve_candidate,
    merge_candidate,
    update_candidate_into,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix=f"{API_V1_PREFIX}/reviews", tags=["reviews"])


_JACCARD_WEIGHT = 0.4
_COSINE_WEIGHT = 0.6
_RELATED_THRESHOLD = 0.5
_SUPERSEDES_THRESHOLD = 0.75
_SUPPORTS_THRESHOLD = 0.85


async def _prepare_review_embedding(memory: Memory) -> list[float] | None:
    """为刚批准的记忆生成一次向量，供本次请求内的审核检查使用。

    关系检测与写时冲突检测共用这一份向量，每次批准只生成一次。
    尽力而为：失败时异步 generate_embedding 任务仍会补齐并索引。
    """
    try:
        from packages.retrieval.embedding import get_embedding_service

        text = format_memory_for_embedding(memory.title, memory.content)
        embedding = await get_embedding_service().generate_embedding(text)
        return list(embedding) if embedding else None
    except Exception:
        logger.warning("Failed to embed memory %s for review checks", memory.id, exc_info=True)
        return None


async def _auto_detect_relations(
    memory: Memory,
    db: AsyncSession,
    existing_memories: list[Any] | None = None,
    precomputed_tokens: dict[str, tuple[str, set[str], set[str]]] | None = None,
    new_embedding: list[float] | None = None,
) -> None:
    """用 Jaccard + embedding 余弦融合自动检测记忆关系。

    两种信号齐备时 final_score = 0.4 * jaccard + 0.6 * cosine；
    缺向量时退回单信号。``new_embedding`` 复用审核流程已生成的
    向量；未提供时在此尽力生成。
    """
    if not parasitic_evolution_config.memory_relations_enabled:
        return

    try:
        from packages.memory.similarity import jaccard_from_sets, tokenize
        from packages.retrieval.vector_utils import batch_cosine_similarities

        new_text = format_memory_for_embedding(memory.title, memory.content)
        new_tokens = tokenize(new_text)
        if not new_tokens:
            return

        if new_embedding is None:
            # 尽力而为：缺向量时关系检测优雅降级
            try:
                from packages.retrieval.embedding import get_embedding_service

                emb = await get_embedding_service().generate_embedding(new_text)
                if emb:
                    new_embedding = emb
            except Exception:
                logger.warning("Failed to generate embedding for relation detection", exc_info=True)

        if existing_memories is None:
            stmt = (
                select(Memory.id, Memory.title, Memory.content, Memory.embedding)
                .where(
                    Memory.workspace_id == memory.workspace_id,
                    Memory.id != memory.id,
                    Memory.status == "active",
                )
                .order_by(Memory.updated_at.desc())
                .limit(100)
            )
            result = await db.execute(stmt)
            existing_memories = list(result.all())

        # 双向查重：入边与出边都算已关联，避免批准时再造一条反向重复边
        existing_rel_stmt = select(
            MemoryRelation.source_memory_id, MemoryRelation.target_memory_id
        ).where(
            or_(
                MemoryRelation.source_memory_id == memory.id,
                MemoryRelation.target_memory_id == memory.id,
            )
        )
        existing_rel_result = await db.execute(existing_rel_stmt)
        linked_ids: set[Any] = set()
        for src_id, tgt_id in existing_rel_result.all():
            linked_ids.add(tgt_id if src_id == memory.id else src_id)

        new_bigrams = (
            {new_text[i : i + 2] for i in range(len(new_text) - 1)} if len(new_text) >= 2 else set()
        )

        candidates: list[tuple[Any, float, Any]] = []

        for row in existing_memories:
            other_id, other_title, other_content = row[0], row[1], row[2]
            other_embedding = row[3] if len(row) > 3 else None

            if other_id in linked_ids:
                continue

            other_id_str = str(other_id)

            if precomputed_tokens and other_id_str in precomputed_tokens:
                _, other_tokens, other_bigrams = precomputed_tokens[other_id_str]
            else:
                other_text = format_memory_for_embedding(other_title, other_content)
                other_tokens = tokenize(other_text)
                other_bigrams = (
                    {other_text[i : i + 2] for i in range(len(other_text) - 1)}
                    if len(other_text) >= 2
                    else set()
                )

            if not other_tokens:
                continue

            if new_bigrams and other_bigrams and not (new_bigrams & other_bigrams):
                continue

            jaccard_sim = jaccard_from_sets(new_tokens, other_tokens)
            candidates.append((other_id, jaccard_sim, other_embedding))

        if not candidates:
            return

        cosine_map: dict[Any, float] = {}
        if new_embedding is not None:
            emb_indices = [i for i, (_, _, emb) in enumerate(candidates) if emb is not None]
            if emb_indices:
                emb_list = [candidates[i][2] for i in emb_indices]
                # 尽力而为：余弦计算失败时退回仅用 Jaccard 打分
                try:
                    cosine_scores = batch_cosine_similarities(new_embedding, emb_list)
                    for idx, score in zip(emb_indices, cosine_scores):
                        cosine_map[candidates[idx][0]] = float(score)
                except Exception:
                    logger.warning("Failed to compute cosine similarities", exc_info=True)

        relations_to_add: list[MemoryRelation] = []
        for other_id, jaccard_sim, _ in candidates:
            cosine_sim = cosine_map.get(other_id)

            if new_embedding is not None and cosine_sim is not None:
                final_score = _JACCARD_WEIGHT * jaccard_sim + _COSINE_WEIGHT * cosine_sim
            elif cosine_sim is not None:
                final_score = cosine_sim
            else:
                final_score = jaccard_sim

            if final_score > _RELATED_THRESHOLD:
                other_text = ""
                for row in existing_memories:
                    if row[0] == other_id:
                        other_text = format_memory_for_embedding(row[1], row[2])
                        break

                # 尽力而为：矛盾检测失败默认视为不矛盾
                has_contradiction = False
                try:
                    from packages.retrieval.context.conflict import _has_contradiction

                    has_contradiction = _has_contradiction(new_text, other_text)
                except Exception:
                    logger.warning("Contradiction check failed", exc_info=True)

                if has_contradiction and final_score > _RELATED_THRESHOLD:
                    relation_type = "contradicts"
                elif final_score > _SUPPORTS_THRESHOLD:
                    relation_type = "supports"
                elif final_score > _SUPERSEDES_THRESHOLD:
                    relation_type = "supersedes"
                elif final_score > _RELATED_THRESHOLD + 0.1:
                    relation_type = "refines"
                else:
                    relation_type = "related"

                rel = MemoryRelation(
                    id=uuid.uuid4(),
                    source_memory_id=memory.id,
                    target_memory_id=other_id,
                    relation_type=relation_type,
                    confidence=round(final_score, 3),
                    created_by="review",
                )
                relations_to_add.append(rel)

        if relations_to_add:
            db.add_all(relations_to_add)

    # 尽力而为：关系检测属补充信息，失败不得阻断审核流程
    except Exception:
        logger.warning(
            "Failed to auto-detect relations for memory %s",
            memory.id,
            exc_info=True,
        )


def _batch_failure(candidate_id: str, action: str, error: str) -> dict[str, str | bool]:
    """批量审核结果的统一失败条目。"""
    return {
        "candidate_id": candidate_id,
        "success": False,
        "action": action,
        "error": error,
    }


async def _apply_simple_review_action(
    db: AsyncSession, candidate: CandidateMemory, action: str
) -> Memory | None:
    """执行单审与批审共享的简单审核动作。

    "approve" 返回生成的已验证记忆，其余返回 None；
    "reject" 标记 rejected 隔离留存（行不删除，可恢复）；
    动作不是 approve/reject/later 时抛 ValueError。
    """
    if action == "approve":
        return await approve_candidate(db, candidate)
    if action == "reject":
        candidate.status = "rejected"
        return None
    if action == "later":
        candidate.status = "deferred"
        return None
    raise ValueError(f"Unsupported simple action: {action}")


async def _check_write_time_conflicts(
    memory: Memory, db: AsyncSession, embedding: list[float] | None = None
) -> None:
    """检查新批准记忆与高相似已有记忆是否矛盾。

    ``embedding`` 复用审核流程生成的向量（批准时 DB 列尚为
    NULL）；其他调用方可省略，回退到 ``memory.embedding``。
    """
    try:
        from packages.domain.models.memory import MemoryConflict
        from packages.retrieval.context.conflict import has_contradiction_text

        effective_embedding = embedding if embedding is not None else memory.embedding
        if effective_embedding is None:
            return

        import numpy as np

        stmt = select(Memory.id, Memory.title, Memory.content, Memory.embedding).where(
            Memory.workspace_id == memory.workspace_id,
            Memory.id != memory.id,
            Memory.status == "active",
            Memory.embedding.isnot(None),
        )
        result = await db.execute(stmt)
        rows = result.all()

        new_emb = np.array(list(effective_embedding), dtype=np.float32)
        new_norm = np.linalg.norm(new_emb)
        if new_norm == 0:
            return

        for row in rows:
            existing_emb = np.array(list(row.embedding), dtype=np.float32)
            existing_norm = np.linalg.norm(existing_emb)
            if existing_norm == 0:
                continue
            cosine = float(np.dot(new_emb, existing_emb) / (new_norm * existing_norm))
            if cosine > 0.7 and has_contradiction_text(memory.content, row.content):
                existing_conflict = await db.execute(
                    select(MemoryConflict).where(
                        MemoryConflict.memory_id == row.id,
                        MemoryConflict.status == "open",
                    )
                )
                if existing_conflict.scalar_one_or_none() is None:
                    conflict = MemoryConflict(
                        workspace_id=memory.workspace_id,
                        memory_id=row.id,
                        conflict_type="contradiction",
                        evidence={"similarity": cosine, "new_memory_id": str(memory.id)},
                    )
                    db.add(conflict)
    # 尽力而为：冲突检测属补充信息，失败不得阻断审核流程
    except Exception:
        logger.warning("Write-time conflict check failed", exc_info=True)


@router.get("", response_model=PaginatedResponse[ReviewRead])
async def list_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    candidate_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PaginatedResponse[ReviewRead]:
    """列出审核记录。"""
    stmt = select(Review)
    count_stmt = select(func.count(Review.id))

    conditions = []
    if candidate_id:
        conditions.append(Review.candidate_id == candidate_id)
    stmt, count_stmt = apply_optional_filters(stmt, count_stmt, conditions)

    total, reviews = await execute_paginated(
        db, stmt, count_stmt, Review.created_at.desc(), offset, limit
    )

    return PaginatedResponse(
        items=[ReviewRead.model_validate(r) for r in reviews],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_review(
    body: ReviewCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> ReviewRead:
    """提交候选记忆的审核动作。

    动作：approve、edit、reject、merge、update、later。
    - approve: 由候选创建新已验证记忆
    - edit: 以编辑后的内容创建新已验证记忆
    - reject: 拒绝候选
    - merge: 把候选内容并入已有记忆
    - update: 用候选内容替换已有记忆
    - later: 暂缓审核
    """
    candidate = await get_or_404(db, CandidateMemory, body.candidate_id)

    if candidate.status != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Candidate is already in '{candidate.status}' status and cannot be reviewed",
        )

    action = body.action
    memory: Memory | None = None

    try:
        if action in ("approve", "reject", "later"):
            memory = await _apply_simple_review_action(db, candidate, action)
        elif action == "edit":
            if body.edited_content is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="edited_content is required for edit action",
                )
            title = body.edited_title or candidate.title
            if "project_id" in body.model_fields_set:
                project_id = body.project_id
            else:
                project_id = candidate.project_id
            memory = await approve_candidate(
                db, candidate, title=title, content=body.edited_content, project_id=project_id
            )
        elif action == "merge":
            if body.merged_content is None or body.merge_target_memory_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="merged_content and merge_target_memory_id are required for merge action",
                )
            # 先按已验证记忆找合并目标，找不到再查候选（自动批准为合并目标）
            target_result = await db.execute(
                select(Memory).where(Memory.id == body.merge_target_memory_id)
            )
            target_memory = target_result.scalar_one_or_none()
            if target_memory is None:
                target_candidate = await get_or_404(
                    db,
                    CandidateMemory,
                    body.merge_target_memory_id,
                    detail=f"Target memory {body.merge_target_memory_id} not found",
                )
                # 自动批准目标候选，使其成为有效合并目标
                target_memory = await approve_candidate(db, target_candidate)
            memory = await merge_candidate(db, candidate, target_memory, body.merged_content)
        elif action == "update":
            if body.merge_target_memory_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="merge_target_memory_id is required for update action",
                )
            target_memory = await get_or_404(
                db,
                Memory,
                body.merge_target_memory_id,
                detail=f"Target memory {body.merge_target_memory_id} not found",
            )
            memory = await update_candidate_into(db, candidate, target_memory)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown action: {action}",
            )

        # 一份向量同时服务关系与冲突检测：此时 DB 列仍为 NULL，
        # 检测逻辑不能依赖它
        review_embedding: list[float] | None = None
        if memory is not None and (
            parasitic_evolution_config.memory_relations_enabled
            or parasitic_evolution_config.write_time_conflict_enabled
        ):
            review_embedding = await _prepare_review_embedding(memory)

        if memory is not None:
            await _auto_detect_relations(memory, db, new_embedding=review_embedding)

        if memory is not None and parasitic_evolution_config.write_time_conflict_enabled:
            await _check_write_time_conflicts(memory, db, embedding=review_embedding)

        # reject 现为隔离留存（状态标记），与其他动作一样创建 Review 留痕
        review = Review(
            candidate_id=body.candidate_id,
            reviewer_type=body.reviewer_type,
            reviewer_id=body.reviewer_id,
            action=action,
            before_content=body.before_content,
            after_content=body.after_content,
            reason=body.reason,
        )
        db.add(review)
        await db.commit()
        await db.refresh(review)

        # 候选状态已变化，失效相关缓存
        invalidate_memory_status_caches()

        if memory is not None:
            await db.refresh(memory)
            await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)
            await task_queue.enqueue("generate_embedding", str(memory.id))
            invalidate_search_cache()
            invalidate_context_cache()
    except Exception:
        # 主事务处理器：回滚并向上传播错误
        await db.rollback()
        raise

    return ReviewRead.model_validate(review)


class BatchReviewItem(BaseModel):
    candidate_id: uuid.UUID
    action: str = Field(..., max_length=32)
    reason: str | None = None


class BatchReviewRequest(BaseModel):
    items: list[BatchReviewItem] = Field(..., max_length=100)
    reviewer_type: str = Field(..., max_length=32)
    reviewer_id: str | None = Field(default=None, max_length=128)


@router.post("/batch")
async def batch_review(
    body: BatchReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(require_scope("reviews:write"))] = None,
) -> dict[str, Any]:
    """批量批准/拒绝候选。"""
    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    memories_for_side_effects: list[Memory] = []

    candidate_ids = [item.candidate_id for item in body.items]
    candidate_map: dict[str, CandidateMemory] = {}
    if candidate_ids:
        cand_stmt = select(CandidateMemory).where(CandidateMemory.id.in_(candidate_ids))
        cand_result = await db.execute(cand_stmt)
        candidate_map = {str(c.id): c for c in cand_result.scalars().all()}

    has_approve = any(item.action == "approve" for item in body.items)
    preloaded_memories: list[Any] | None = None
    precomputed_tokens: dict[str, tuple[str, set[str], set[str]]] = {}
    if has_approve and parasitic_evolution_config.memory_relations_enabled:
        ws_ids = (
            {
                str(candidate_map[str(it.candidate_id)].workspace_id)
                for it in body.items
                if str(it.candidate_id) in candidate_map
            }
            if candidate_map
            else set()
        )
        if ws_ids:
            from packages.domain.models import Memory

            mem_stmt = (
                select(Memory.id, Memory.title, Memory.content, Memory.embedding)
                .where(Memory.workspace_id.in_(ws_ids), Memory.status == "active")
                .limit(200)
            )
            mem_result = await db.execute(mem_stmt)
            preloaded_memories = list(mem_result.all())

            # 为全部已有记忆预计算一次 token，各批准项复用，避免重复分词
            precomputed_tokens = {}
            # 尽力而为：预计算只影响批量速度，失败即跳过
            try:
                from packages.memory.similarity import tokenize

                for oid, otitle, ocontent, _oemb in preloaded_memories:
                    otext = format_memory_for_embedding(otitle, ocontent)
                    otokens = tokenize(otext)
                    obigrams = (
                        {otext[i : i + 2] for i in range(len(otext) - 1)}
                        if len(otext) >= 2
                        else set()
                    )
                    precomputed_tokens[str(oid)] = (otext, otokens, obigrams)
            except Exception:
                logger.warning("Precomputed tokens batch failed", exc_info=True)
                precomputed_tokens = {}

    for item in body.items:
        try:
            async with db.begin_nested():
                candidate = candidate_map.get(str(item.candidate_id))
                if candidate is None:
                    results.append(
                        _batch_failure(
                            str(item.candidate_id),
                            item.action,
                            f"Candidate {item.candidate_id} not found",
                        )
                    )
                    failed += 1
                    continue

                if candidate.status != "pending_review":
                    results.append(
                        _batch_failure(
                            str(item.candidate_id),
                            item.action,
                            f"Candidate is already in '{candidate.status}' status",
                        )
                    )
                    failed += 1
                    continue

                memory: Memory | None = None
                action = item.action

                if action in ("approve", "reject", "later"):
                    memory = await _apply_simple_review_action(db, candidate, action)
                else:
                    results.append(
                        _batch_failure(
                            str(item.candidate_id),
                            action,
                            f"Batch mode only supports approve/reject/later, got: {action}",
                        )
                    )
                    failed += 1
                    continue

                if memory is not None:
                    review_embedding: list[float] | None = None
                    if (
                        parasitic_evolution_config.memory_relations_enabled
                        or parasitic_evolution_config.write_time_conflict_enabled
                    ):
                        review_embedding = await _prepare_review_embedding(memory)
                    filtered = (
                        [row for row in preloaded_memories if row[0] != memory.id]
                        if preloaded_memories is not None
                        else None
                    )
                    await _auto_detect_relations(
                        memory,
                        db,
                        existing_memories=filtered,
                        precomputed_tokens=precomputed_tokens,
                        new_embedding=review_embedding,
                    )
                    if parasitic_evolution_config.write_time_conflict_enabled:
                        await _check_write_time_conflicts(memory, db, embedding=review_embedding)
                    memories_for_side_effects.append(memory)

                review = Review(
                    candidate_id=item.candidate_id,
                    reviewer_type=body.reviewer_type,
                    reviewer_id=body.reviewer_id,
                    action=action,
                    reason=item.reason,
                )
                db.add(review)

            result_entry: dict[str, Any] = {
                "candidate_id": str(item.candidate_id),
                "success": True,
                "action": action,
            }
            if action != "reject":
                result_entry["review_id"] = str(review.id)
            results.append(result_entry)
            succeeded += 1

        except Exception as exc:
            # 单条失败只记录，继续处理剩余条目
            results.append(_batch_failure(str(item.candidate_id), item.action, str(exc)))
            failed += 1

    await db.commit()

    # 候选状态已批量变化，失效相关缓存
    if succeeded > 0:
        invalidate_memory_status_caches()

    # 尽力而为：文件同步与向量化失败可在下次启动时恢复
    for memory in memories_for_side_effects:
        try:
            await sync_memory_to_file(memory, db, skip_vector_index=True, save_index=True)
            await task_queue.enqueue("generate_embedding", str(memory.id))
        except Exception:
            logger.warning("Post-commit side effect failed for memory %s", memory.id)

    if memories_for_side_effects:
        invalidate_search_cache()
        invalidate_context_cache()

    return {
        "results": results,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
    }
