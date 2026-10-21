"""相似记忆自动整理任务（BM25 预过滤 + 统一相似度验证 + 可选自动合并）。

使用统一相似度计算策略（配置在 config.yaml 的 memory.similarity_strategy）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from packages.domain.config import parasitic_evolution_config, settings
from packages.domain.database import async_session_maker
from packages.domain.models import Memory
from packages.domain.models.memory import (
    MemoryConflict,
    MemoryLifecycleEvent,
    MemoryRelation,
)
from packages.domain.text_utils import format_memory_for_embedding
from packages.memory.service import snapshot_and_advance
from packages.memory.similarity import HybridWeights, compute_similarity

logger = logging.getLogger(__name__)

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
            select(
                Memory.id,
                Memory.title,
                Memory.content,
                Memory.confidence,
                Memory.importance,
                Memory.embedding,
            )
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
        id_to_data: dict[str, dict[str, Any]] = {}
        for m in memories:
            doc_id = str(m.id)
            id_to_mem[doc_id] = m
            id_to_data[doc_id] = {
                "title": m.title,
                "content": m.content,
                "embedding": m.embedding,
            }

        # BM25 预过滤 + 加载额外记忆
        bm25_candidates, extra_ids = _build_bm25_candidates(memories, bm25, id_to_data)
        await _load_extra_memories(db_session, extra_ids, id_to_data)

        # 计算相似度并构建邻接表
        strategy = settings.similarity_strategy
        weights = HybridWeights(**settings.similarity_hybrid_weights)
        adjacency = await _compute_adjacency(memories, bm25_candidates, id_to_data, strategy, weights)

        # 按高相似连通性分组（连通分量）
        consolidation_groups = _find_groups(memories, adjacency, id_to_mem)

        suggestions: list[dict[str, Any]] = []
        for group in consolidation_groups:
            group_data_list = [id_to_data[str(m.id)] for m in group]
            pairwise_sims: list[float] = []
            for a in range(len(group_data_list)):
                for b in range(a + 1, len(group_data_list)):
                    sim = await compute_similarity(
                        group_data_list[a],
                        group_data_list[b],
                        strategy=strategy,
                        weights=weights,
                    )
                    pairwise_sims.append(sim)
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
            "Auto-consolidate found %d groups from %d memories (strategy=%s)",
            len(consolidation_groups),
            len(memories),
            strategy,
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

                # 智能合并：提取共同点，保留差异
                merged_content = await _smart_merge_content(
                    keeper_mem,
                    source_ids,
                    db_session,
                )

                await snapshot_and_advance(
                    db_session,
                    keeper_mem,
                    change_type="merge",
                    changed_by_type="system",
                    reason=f"Auto-merged from {len(source_ids)} memories",
                )
                keeper_mem.content = merged_content
                keeper_mem.embedding = None

                for sid in source_ids:
                    source_row = await db_session.execute(
                        select(Memory).where(Memory.id == sid, Memory.status == "active")
                    )
                    source_mem = source_row.scalar_one_or_none()
                    if source_mem is None:
                        continue

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


async def _smart_merge_content(
    keeper: Memory,
    source_ids: list[uuid.UUID],
    db_session: Any,
) -> str:
    """智能合并内容：提取共同点，保留差异，结构化合并。

    合并策略：
    1. 保留 keeper 的内容作为主体
    2. 源记忆按标题分章节追加，避免重复
    3. 如果内容高度相似（>0.9），只保留 keeper 的版本
    4. 保留所有标签和元数据
    """
    from packages.memory.similarity import compute_similarity

    parts = [keeper.content]
    keeper_data = {
        "title": keeper.title,
        "content": keeper.content,
        "embedding": keeper.embedding,
    }

    for sid in source_ids:
        result = await db_session.execute(
            select(Memory).where(Memory.id == sid, Memory.status == "active")
        )
        source_mem = result.scalar_one_or_none()
        if not source_mem:
            continue

        # 检查内容相似度，避免重复
        source_data = {
            "title": source_mem.title,
            "content": source_mem.content,
            "embedding": source_mem.embedding,
        }
        sim = await compute_similarity(keeper_data, source_data, strategy="hybrid")

        if sim > 0.9:
            # 高度相似，跳过重复内容
            logger.debug(
                "Skipping merge for memory %s (similarity %.2f > 0.9)",
                sid,
                sim,
            )
            continue

        # 如果源记忆有标题且与 keeper 不同，作为子章节保留
        if source_mem.title and source_mem.title != keeper.title:
            parts.append(f"\n\n## {source_mem.title}\n\n{source_mem.content}")
        else:
            parts.append(f"\n\n{source_mem.content}")

    return "\n".join(parts)


def _build_bm25_candidates(
    memories: Any,
    bm25: Any,
    id_to_data: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[str]], set[str]]:
    """BM25 预过滤：为每条记忆找 top-k 邻居，收集需要额外加载的记忆 ID。"""
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
            if oid not in id_to_data:
                extra_ids.add(oid)

    return bm25_candidates, extra_ids


async def _load_extra_memories(
    db_session: Any,
    extra_ids: set[str],
    id_to_data: dict[str, dict[str, Any]],
) -> None:
    """批量加载 BM25 命中但不在初始查询结果中的记忆。"""
    if not extra_ids:
        return

    extra_uuids = [uuid.UUID(mid) for mid in extra_ids]
    detail_stmt = select(
        Memory.id, Memory.title, Memory.content, Memory.embedding
    ).where(Memory.id.in_(extra_uuids))
    detail_result = await db_session.execute(detail_stmt)

    for row in detail_result.all():
        mid = str(row.id)
        if mid not in id_to_data:
            id_to_data[mid] = {
                "title": row.title,
                "content": row.content,
                "embedding": row.embedding,
            }


async def _compute_adjacency(
    memories: Any,
    bm25_candidates: dict[str, list[str]],
    id_to_data: dict[str, dict[str, Any]],
    strategy: str,
    weights: HybridWeights,
) -> dict[str, set[str]]:
    """计算记忆间的相似度，构建邻接表（超阈值的边）。"""
    pair_sims: dict[tuple[str, str], float] = {}
    adjacency: dict[str, set[str]] = {str(m.id): set() for m in memories}

    for m in memories:
        doc_id = str(m.id)
        data_i = id_to_data[doc_id]

        for other_id in bm25_candidates[doc_id]:
            # 规范化对键（排序去重）
            pair_key = (min(doc_id, other_id), max(doc_id, other_id))
            if pair_key in pair_sims:
                continue

            data_j = id_to_data.get(other_id)
            if data_j is None:
                continue

            sim = await compute_similarity(data_i, data_j, strategy=strategy, weights=weights)
            if sim > _CONSOLIDATE_THRESHOLD:
                pair_sims[pair_key] = sim
                adjacency[doc_id].add(other_id)
                adjacency[other_id].add(doc_id)

    return adjacency


def _find_groups(
    memories: Any,
    adjacency: dict[str, set[str]],
    id_to_mem: dict[str, Any],
) -> list[list[Any]]:
    """用 BFS 找连通分量，每个分量是一组待整理的高相似记忆。"""
    processed: set[str] = set()
    consolidation_groups: list[list[Any]] = []

    for m in memories:
        doc_id = str(m.id)
        if doc_id in processed or not adjacency[doc_id]:
            continue

        # BFS 找所有连通节点
        group: list[Any] = []
        queue = [doc_id]
        while queue:
            current = queue.pop(0)
            if current in processed:
                continue
            processed.add(current)
            if current in id_to_mem:
                group.append(id_to_mem[current])
            for neighbor in adjacency[current]:
                if neighbor not in processed:
                    queue.append(neighbor)

        if len(group) >= 2:
            consolidation_groups.append(group)

    return consolidation_groups
