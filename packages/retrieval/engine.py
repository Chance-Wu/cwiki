"""混合检索引擎：完整 0.2 流水线（PRD 第 14-23 节）。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.config import settings
from packages.domain.models import (
    Memory,
    MemoryRelation,
    MemoryUsage,
    RetrievalTrace,
    RetrievalTraceItem,
)
from packages.domain.text_utils import preprocess_query_for_embedding
from packages.memory.utility_aggregation import aggregate_utility_scores
from packages.retrieval.bm25 import BM25Index
from packages.retrieval.context.assembler import ContextResult, assemble_context_with_embedding
from packages.retrieval.context.filters import normalize_mode
from packages.retrieval.embedding import get_embedding_service
from packages.retrieval.query.analyzer import AnalyzedQuery, analyze_query
from packages.retrieval.ranking.diversity import apply_diversity
from packages.retrieval.ranking.reranker import RerankInput, diversity_limit_for_intent, rerank
from packages.retrieval.ranking.temporal import is_stale_item, temporal_score
from packages.retrieval.vector_utils import top_k_indices

logger = logging.getLogger(__name__)

_engine: RetrievalEngine | None = None

# RRF 倒数排名融合常数：k=60 为原论文推荐值，压缩头部名次差距，
# 使各检索路的名次贡献平缓衰减，避免第 1 名过度碾压
RRF_K = 60
# 向量检索侧参与打分的记忆数量上限
_VECTOR_SEARCH_LIMIT = 10_000
# 某一路检索未命中时用于排名兜底的占位名次
_FALLBACK_RANK = 999

# 向量矩阵缓存的生效指纹：DB 内容指纹，使用文件向量索引时再并入其大小。
_VecFingerprint = tuple[int, datetime | None, int] | tuple[int, datetime | None, int, int]

# 内容指纹不变时复用缓存的 BM25 索引。
# SQLite CURRENT_TIMESTAMP 只有秒级精度，同一秒内总长度不变的原地编辑
# 可能逃过指纹检测；TTL 用于限制这类编辑最长的不可见时间。
# 优化：减少缓存条目数，降低内存占用
_INDEX_MAX_AGE_SECONDS = 60.0  # 从 30s 延长到 60s，减少重建频率
_INDEX_CACHE_SIZE = 4  # 从 8 减少到 4
_VEC_CACHE_SIZE = 2  # 从 4 减少到 2

# 指纹缓存：内容未变时避免每次请求都查库。
# 曾设 5s 短 TTL，但该时间窗会让过期指纹掩盖新写入、连带 BM25 索引缓存
# 一起滞后，故已禁用（置 0）；retrieve() 内的单请求复用已足够。
_FINGERPRINT_CACHE_TTL = 0.0


def _ensure_candidate(candidates: dict[str, dict[str, Any]], doc_id: str) -> dict[str, Any]:
    """返回 doc_id 的候选条目；首次出现时创建空条目。"""
    entry = candidates.get(doc_id)
    if entry is None:
        entry = {
            "id": doc_id,
            "bm25_score": 0.0,
            "vector_score": 0.0,
            "bm25_rank": 0,
            "vector_rank": 0,
        }
        candidates[doc_id] = entry
    return entry


class RetrievalEngine:
    """混合检索引擎：BM25 + 向量 → RRF 融合 → 重排 → 多样性 → 上下文。

    流水线（0.2）：
    1. 解析查询（意图、实体）
    2. BM25 关键词检索（top 50）
    3. 向量余弦相似度检索（top 50）
    4. RRF 融合 → 候选池
    5. 取回完整记忆记录
    6. 计算时态 + 新鲜度得分
    7. 多信号加权重排
    8. 多样性过滤（max_per_type）
    9. 按 token 预算组装上下文
    10. 记录检索 trace
    """

    def __init__(self) -> None:
        # (workspace_id, project_id) -> (指纹, 构建时刻, BM25 索引)
        self._index_cache: dict[
            tuple[uuid.UUID | None, uuid.UUID | None],
            tuple[tuple[int, datetime | None, int], float, BM25Index],
        ] = {}
        # (workspace_id, project_id) -> (指纹, 构建时刻, ids, 向量矩阵, 范数)
        self._vec_cache: dict[
            tuple[uuid.UUID | None, uuid.UUID | None],
            tuple[_VecFingerprint, float, list[str], np.ndarray, np.ndarray],
        ] = {}
        # (workspace_id, project_id) -> (指纹, 获取时刻)
        self._fingerprint_cache: dict[
            tuple[uuid.UUID | None, uuid.UUID | None],
            tuple[tuple[int, datetime | None, int], float],
        ] = {}
        # 向量来源覆写：设置后向量取自该提供者（文件版 VectorIndex），
        # 而非遗留的 DB embedding 列。
        self._vector_source: Callable[[], Any] | None = None

    def set_vector_source(self, provider: Callable[[], Any] | None) -> None:
        """注入查询时使用的向量来源（文件版 VectorIndex）。

        由应用 lifespan 在存储组件初始化后调用。未设置时引擎退化为
        读取遗留的 ``Memory.embedding`` 列。切换来源时清空矩阵缓存，
        避免继续命中按旧来源构建的条目。
        """
        self._vector_source = provider
        self._vec_cache.clear()

    async def _ensure_index(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        fingerprint: tuple[int, datetime | None, int] | None = None,
    ) -> BM25Index:
        """返回该范围的 BM25 索引，仅在内容变化时重建。

        指纹（active 数量、最大 updated_at、标题+内容总长度）在数据库侧
        一次性计算；指纹命中即复用缓存索引，避免每次请求重新拉取并分词
        全部记忆。任何写入都会更新 updated_at（onupdate）或改变数量，
        过期索引会在下一次请求时自愈；TTL 只兜底同一秒内的编辑窗口。
        返回的索引在异步交错期间归当前请求独享；并发重建也安全，
        因为缓存条目在完整构建完成后才被整体原子替换。
        """
        key = (workspace_id, project_id)
        if fingerprint is None:
            fingerprint = await self._content_fingerprint(db, workspace_id, project_id)
        cached = self._index_cache.get(key)
        if (
            cached is not None
            and cached[0] == fingerprint
            and time.monotonic() - cached[1] < _INDEX_MAX_AGE_SECONDS
        ):
            return cached[2]

        index = await self._build_index(db, workspace_id, project_id)
        self._index_cache[key] = (fingerprint, time.monotonic(), index)
        if len(self._index_cache) > _INDEX_CACHE_SIZE:
            self._index_cache.pop(next(iter(self._index_cache)))
        return index

    async def _content_fingerprint(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
    ) -> tuple[int, datetime | None, int]:
        """用一次廉价的 DB 聚合查询标识该范围的 active 内容。

        结果按 _FINGERPRINT_CACHE_TTL 秒缓存，内容未变时避免每次请求都查库。
        """
        key = (workspace_id, project_id)
        cached = self._fingerprint_cache.get(key)
        if cached is not None and time.monotonic() - cached[1] < _FINGERPRINT_CACHE_TTL:
            return cached[0]

        stmt = select(
            func.count(),
            func.max(Memory.updated_at),
            func.coalesce(func.sum(func.length(Memory.title) + func.length(Memory.content)), 0),
        ).where(Memory.status == "active")
        if workspace_id:
            stmt = stmt.where(Memory.workspace_id == workspace_id)
        if project_id:
            stmt = stmt.where(Memory.project_id == project_id)
        row = (await db.execute(stmt)).one()
        fingerprint = (row[0], row[1], row[2])
        self._fingerprint_cache[key] = (fingerprint, time.monotonic())
        return fingerprint

    async def _build_index(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
    ) -> BM25Index:
        stmt = select(Memory.id, Memory.title, Memory.content, Memory.metadata_).where(
            Memory.status == "active"
        )
        if workspace_id:
            stmt = stmt.where(Memory.workspace_id == workspace_id)
        if project_id:
            stmt = stmt.where(Memory.project_id == project_id)
        result = await db.execute(stmt)
        memories = result.all()

        index = BM25Index()
        for mem in memories:
            text = mem.content
            if mem.metadata_ and isinstance(mem.metadata_, dict):
                entities = mem.metadata_.get("entities")
                if entities and isinstance(entities, list):
                    text = text + " " + " ".join(str(e) for e in entities)
            index.add(str(mem.id), text, title=mem.title)
        # 无需再调 build()——add() 已增量维护索引有效性
        return index

    async def _episodic_search(
        self,
        query: str,
        workspace_id: uuid.UUID,
        db: AsyncSession,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """对 goal+summary 做 BM25 检索 episode；候选按重要度+时间倒序预排序。"""
        from packages.domain.models.session import Episode

        stmt = (
            select(Episode)
            .where(
                Episode.workspace_id == workspace_id,
                Episode.status == "completed",
            )
            .order_by(Episode.importance.desc(), Episode.ended_at.desc())
            .limit(200)
        )
        result = await db.execute(stmt)
        episodes = result.scalars().all()

        if not episodes:
            return []

        from packages.retrieval.bm25 import BM25Index

        bm25 = BM25Index()
        for ep in episodes:
            text = f"{ep.goal or ''} {ep.summary or ''}"
            bm25.add(str(ep.id), text)

        bm25_results = bm25.search(query, top_k=top_k)
        ep_map = {str(ep.id): ep for ep in episodes}

        results = []
        for doc_id, score in bm25_results:
            episode = ep_map.get(doc_id)
            if episode is None:
                continue
            results.append(
                {
                    "type": "episode",
                    "id": doc_id,
                    "goal": episode.goal,
                    "summary": episode.summary,
                    "started_at": ep.started_at.isoformat() if ep.started_at else None,
                    "ended_at": ep.ended_at.isoformat() if ep.ended_at else None,
                    "lessons": (ep.metadata_ or {}).get("lessons", []),
                    "score": round(score, 4),
                }
            )
        return results[:top_k]

    async def retrieve(
        self,
        query: str | None,
        workspace_id: uuid.UUID,
        db: AsyncSession,
        project_id: uuid.UUID | None = None,
        max_items: int = 10,
        max_tokens: int = 5000,
        session_id: uuid.UUID | None = None,
        mode: str = "semantic",
    ) -> dict[str, Any]:
        start_time = time.time()

        # 纯 episode 模式：完全跳过语义检索流水线
        if mode == "episodic":
            try:
                from packages.domain.config import parasitic_evolution_config as _pec

                if _pec.episodic_retrieval_enabled:
                    episodes = await self._episodic_search(
                        query or "", workspace_id, db, top_k=max_items
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    return {
                        "memories": episodes,
                        "total": len(episodes),
                        "sources": [],
                        "context": "\n".join(
                            f"[Episode] {ep.get('goal', '')}: {ep.get('summary', '')}"
                            for ep in episodes
                        ),
                        "latency_ms": latency_ms,
                    }
            except Exception:
                logger.debug(
                    "Episodic retrieval failed, falling through to semantic", exc_info=True
                )

        # 指纹只计算一次，供 BM25 索引与向量矩阵两路缓存共用
        fingerprint = await self._content_fingerprint(db, workspace_id, project_id)
        index = await self._ensure_index(db, workspace_id, project_id, fingerprint=fingerprint)

        analyzed = analyze_query(query or "")

        candidates: dict[str, dict[str, Any]] = {}

        if query and query.strip():
            search_query = query
            if analyzed.is_short and analyzed.key_terms:
                search_query = " ".join(analyzed.key_terms[:5])

            # 提前算好向量查询串，尽早启动 embedding 生成以便并行
            embedding_svc = get_embedding_service()
            vector_query = preprocess_query_for_embedding(query, analyzed)

            # embedding 生成作为后台任务启动（模型推理较慢，先并行起来）
            embedding_task = asyncio.create_task(embedding_svc.generate_embedding(vector_query))

            # BM25 检索与 embedding 生成并发执行（CPU 密集）
            bm25_results = index.search(search_query, top_k=50)
            for rank, (doc_id, score) in enumerate(bm25_results, 1):
                entry = _ensure_candidate(candidates, doc_id)
                entry["bm25_score"] = score
                entry["bm25_rank"] = rank

            # 短语命中加成：得分 ×1.2、名次 +30——精确短语匹配比散词命中更可信，
            # 只取前 3 个短语，且只在其加成高于原分时替换，避免分数膨胀
            if analyzed.phrases:
                for phrase in analyzed.phrases[:3]:
                    phrase_results = index.search(phrase, top_k=20)
                    for rank, (doc_id, score) in enumerate(phrase_results, 1):
                        entry = _ensure_candidate(candidates, doc_id)
                        boost = score * 1.2
                        if entry["bm25_score"] < boost:
                            entry["bm25_score"] = boost
                            entry["bm25_rank"] = min(
                                entry["bm25_rank"] or _FALLBACK_RANK, rank + 30
                            )

            # 同义词扩展命中打折（×0.7、名次 +50）：扩展词只是语义近似，
            # 相关性弱于原文命中，仅作补充召回，不与原始得分竞争
            if analyzed.expanded_terms:
                expanded_query = query + " " + " ".join(analyzed.expanded_terms[:5])
                expanded_results = index.search(expanded_query, top_k=30)
                for rank, (doc_id, score) in enumerate(expanded_results, 1):
                    entry = _ensure_candidate(candidates, doc_id)
                    boost = score * 0.7
                    if entry["bm25_score"] < boost:
                        entry["bm25_score"] = boost
                        entry["bm25_rank"] = min(entry["bm25_rank"] or _FALLBACK_RANK, rank + 50)

            # 等待与 BM25 并行的 embedding 生成完成
            query_embedding = await embedding_task

            if query_embedding is not None:
                try:
                    vector_results = await self._vector_search(
                        db,
                        query_embedding,
                        workspace_id,
                        top_k=50,
                        project_id=project_id,
                        fingerprint=fingerprint,
                    )
                except Exception:
                    logger.exception("Vector search failed, degrading to BM25-only")
                    vector_results = []
                for rank, (doc_id, score) in enumerate(vector_results, 1):
                    entry = _ensure_candidate(candidates, doc_id)
                    entry["vector_score"] = score
                    entry["vector_rank"] = rank

        if not candidates:
            stmt = select(
                Memory.id,
                Memory.title,
                Memory.content,
                Memory.type,
            ).where(
                Memory.status == "active",
                Memory.workspace_id == workspace_id,
            )
            if project_id:
                stmt = stmt.where(Memory.project_id == project_id)
            result = await db.execute(stmt.order_by(Memory.importance.desc()).limit(max_items))
            rows = result.all()
            mem_dicts = [
                {
                    "id": str(r.id),
                    "title": r.title,
                    "content": r.content,
                    "type": r.type,
                    "score": 1.0,
                }
                for r in rows
            ]
            ctx = await assemble_context_with_embedding(
                mem_dicts, query=query or "", max_tokens=max_tokens
            )
            latency_ms = int((time.time() - start_time) * 1000)

            try:
                await self._record_trace(
                    db=db,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    query=query or "",
                    analyzed=analyzed,
                    candidates=candidates,
                    final_memories=mem_dicts,
                    latency_ms=latency_ms,
                    ctx=ctx,
                )
            except Exception as e:
                logger.warning("Failed to record retrieval trace: %s", e)

            return {
                "memories": mem_dicts,
                "total": len(mem_dicts),
                "sources": [{"memory_id": m["id"], "score": m["score"]} for m in mem_dicts],
                "context": ctx.text,
                "latency_ms": latency_ms,
            }

        # RRF 倒数排名融合：score = Σ 权重/(k+rank)。两路原始分数量纲不可比，
        # 只用名次融合天然公平；bm25/vector 权重来自 config，可调两路偏重
        rrf_scores: dict[str, float] = {}
        bm25_w = settings.bm25_weight
        vec_w = settings.vector_weight
        for doc_id, data in candidates.items():
            bm25_r = data.get("bm25_rank", 0)
            vec_r = data.get("vector_rank", 0)
            rrf = 0.0
            if bm25_r > 0:
                rrf += bm25_w / (RRF_K + bm25_r)
            if vec_r > 0:
                rrf += vec_w / (RRF_K + vec_r)
            rrf_scores[doc_id] = rrf

        sorted_candidates = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        # RRF 融合后截断为 max_items×3 的候选池：给后续重排与多样性过滤
        # 留足余量，同时控制取回完整记录与重排的开销
        top_ids = [doc_id for doc_id, _ in sorted_candidates[: max_items * 3]]

        uuid_ids = []
        for did in top_ids:
            try:
                uuid_ids.append(uuid.UUID(did))
            except ValueError:
                pass

        if not uuid_ids:
            return {"memories": [], "total": 0, "sources": [], "context": "", "latency_ms": 0}

        final_stmt = select(
            Memory.id,
            Memory.title,
            Memory.content,
            Memory.type,
            Memory.confidence,
            Memory.importance,
            Memory.usage_count,
            Memory.valid_from,
            Memory.valid_to,
            Memory.created_at,
            Memory.last_used_at,
            Memory.embedding,
        ).where(
            Memory.id.in_(uuid_ids),
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
        )
        if project_id:
            final_stmt = final_stmt.where(Memory.project_id == project_id)
        hydrated_result = await db.execute(final_stmt)
        mem_map = {str(m.id): m for m in hydrated_result.all()}

        rerank_inputs: list[RerankInput] = []
        for doc_id in top_ids:
            m = mem_map.get(doc_id)
            if not m:
                continue
            data = candidates.get(doc_id, {})
            freshness = temporal_score(
                valid_from=m.valid_from,
                valid_to=m.valid_to,
                created_at=m.created_at,
                last_used_at=m.last_used_at,
            )
            # 使用次数归一化：100 次即满分，抑制超高频记忆的过度优势
            usage_score = min(m.usage_count / 100.0, 1.0) if m.usage_count else 0.0

            rerank_inputs.append(
                RerankInput(
                    memory_id=doc_id,
                    title=m.title,
                    content=m.content,
                    memory_type=m.type,
                    bm25_score=data.get("bm25_score", 0.0),
                    vector_score=data.get("vector_score", 0.0),
                    rrf_score=rrf_scores.get(doc_id, 0.0),
                    confidence=m.confidence,
                    importance=m.importance,
                    freshness=freshness,
                    usage_score=usage_score,
                )
            )

        reranked = rerank(
            rerank_inputs,
            query_intent=analyzed.intent,
            top_k=max_items * 2,
            intent_confidence=analyzed.confidence,
            negations=analyzed.negations,
            key_terms=analyzed.key_terms,
        )

        # 一跳图扩展：沿记忆关系边给邻居加 0.15×关系置信度的分，
        # 让与高置信结果强相关的记忆也能进入最终列表
        try:
            from packages.domain.config import parasitic_evolution_config

            if parasitic_evolution_config.memory_relations_enabled:
                top_ids_for_expansion = [mid for mid, _ in reranked[:5]]
                if top_ids_for_expansion:
                    uuid_top_ids = [uuid.UUID(mid) for mid in top_ids_for_expansion]
                    neighbor_stmt = select(
                        MemoryRelation.target_memory_id,
                        MemoryRelation.confidence,
                    ).where(
                        MemoryRelation.source_memory_id.in_(uuid_top_ids),
                    )
                    neighbor_result = await db.execute(neighbor_stmt)
                    reranked_dict = dict(reranked)
                    for row in neighbor_result.all():
                        neighbor_id = str(row[0])
                        boost = 0.15 * row[1]
                        if neighbor_id in reranked_dict:
                            reranked_dict[neighbor_id] += boost
                        elif neighbor_id in mem_map:
                            reranked_dict[neighbor_id] = boost
                    reranked = sorted(reranked_dict.items(), key=lambda x: x[1], reverse=True)
        except Exception:
            logger.debug("Graph expansion failed, continuing without", exc_info=True)

        # 候选三档过滤（W3-T3）：过期/低置信候选按 config 档位压分或剔除，
        # 挂在 rerank 与多样性之间——被 hard 剔除的候选不再占用多样性名额
        reranked = self._apply_candidate_filters(reranked, mem_map)

        ranked_with_type: list[tuple[str, float, str]] = []
        for mem_id, score in reranked:
            m = mem_map.get(mem_id)
            if m:
                ranked_with_type.append((mem_id, score, m.type))

        max_per_type = diversity_limit_for_intent(analyzed.intent)
        diverse = apply_diversity(ranked_with_type, top_k=max_items, max_per_type=max_per_type)

        # 只对进入最终列表的记忆（≤ max_items 条）批量计算效用分，
        # 供上下文优先级排序在同优先级内综合 score + utility 排序
        utility_map = await self._aggregate_utility_scores(
            db, [mem_id for mem_id, _, _ in diverse], mem_map
        )

        final_memories: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        for rank, (mem_id, final_score, mem_type) in enumerate(diverse, 1):
            m = mem_map.get(mem_id)
            if not m:
                continue
            final_memories.append(
                {
                    "id": mem_id,
                    "title": m.title,
                    "content": m.content,
                    "type": m.type,
                    "score": round(final_score, 4),
                    # 信号分项：显式命名各路分数，与 rrf/utility 一起供
                    # trace metadata 落库与调用方排查"为什么排在这个位置"
                    "bm25_score": round(
                        float(candidates.get(mem_id, {}).get("bm25_score", 0.0)), 6
                    ),
                    "vector_score": round(
                        float(candidates.get(mem_id, {}).get("vector_score", 0.0)), 6
                    ),
                    "rerank_score": round(final_score, 4),
                    "utility_score": utility_map.get(mem_id, 0.0),
                    "rrf_score": round(rrf_scores.get(mem_id, 0), 6),
                    # confidence/valid_to 供组装器入口三档过滤判定
                    # （置信下限与过期判定），API 返回中仅是额外元数据
                    "confidence": m.confidence,
                    "valid_to": m.valid_to,
                    "rank": rank,
                    "embedding": m.embedding,
                }
            )
            sources.append({"memory_id": mem_id, "score": round(final_score, 4)})

        # 混合模式：将 episode 结果并入最终列表
        if mode == "hybrid":
            try:
                from packages.domain.config import parasitic_evolution_config as _pec

                if _pec.episodic_retrieval_enabled:
                    episodes = await self._episodic_search(query or "", workspace_id, db, top_k=3)
                    final_memories.extend(episodes)
            except Exception:
                logger.debug("Hybrid episodic merge failed", exc_info=True)

        ctx = await assemble_context_with_embedding(
            final_memories, query=query or "", max_tokens=max_tokens
        )

        latency_ms = int((time.time() - start_time) * 1000)

        try:
            await self._record_trace(
                db=db,
                workspace_id=workspace_id,
                session_id=session_id,
                query=query or "",
                analyzed=analyzed,
                candidates=candidates,
                final_memories=final_memories,
                latency_ms=latency_ms,
                ctx=ctx,
            )
        except Exception as e:
            logger.warning("Failed to record retrieval trace: %s", e)

        return {
            "memories": final_memories,
            "total": len(final_memories),
            "sources": sources,
            "context": ctx.text,
            "latency_ms": latency_ms,
        }

    def _apply_candidate_filters(
        self,
        reranked: list[tuple[str, float]],
        mem_map: dict[str, Any],
    ) -> list[tuple[str, float]]:
        """候选 hard 档早删（过期/低置信/低相关）。

        demote 与 none 档不在这里处理——组装器入口（apply_entry_filters）
        会统一执行全部档位，这里再降分会让同一候选被连乘两次惩罚因子。
        早删只做 hard 剔除：被删候选不再占用多样性名额、不进 utility 聚合。
        档位值非法按 none 处理并告警，配置错误不阻断检索。
        """
        stale_mode = normalize_mode(settings.stale_filter_mode, "stale_filter_mode")
        conf_mode = normalize_mode(settings.confidence_floor_mode, "confidence_floor_mode")
        rel_mode = normalize_mode(settings.relevance_floor_mode, "relevance_floor_mode")
        conf_floor = settings.confidence_floor
        rel_floor = settings.relevance_floor

        stale_hard = stale_mode == "hard"
        conf_hard = conf_mode == "hard" and conf_floor > 0
        rel_hard = rel_mode == "hard" and rel_floor > 0
        if not (stale_hard or conf_hard or rel_hard):
            return reranked

        result: list[tuple[str, float]] = []
        for mem_id, score in reranked:
            m = mem_map.get(mem_id)
            if m is not None:
                if stale_hard and is_stale_item({"valid_to": m.valid_to}):
                    continue
                if conf_hard and m.confidence < conf_floor:
                    continue
                if rel_hard and score < rel_floor:
                    continue
            result.append((mem_id, score))
        return result

    async def _aggregate_utility_scores(
        self,
        db: AsyncSession,
        mem_ids: list[str],
        mem_map: dict[str, Any],
    ) -> dict[str, float]:
        """批量计算最终候选的 utility_score（PRD 第 31 节）。

        实现（三条 GROUP BY 批量 SQL + 降级策略）已抽到
        packages.memory.utility_aggregation 供列表路由共用，这里只做
        参数形状适配，保证既有调用点与测试签名不变。
        """
        return await aggregate_utility_scores(
            db,
            [m for mem_id in mem_ids if (m := mem_map.get(mem_id)) is not None],
        )

    async def _record_trace(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        session_id: uuid.UUID | None,
        query: str,
        analyzed: AnalyzedQuery,
        candidates: dict[str, dict[str, Any]],
        final_memories: list[dict[str, Any]],
        latency_ms: int,
        ctx: ContextResult | None = None,
    ) -> None:
        trace_id = uuid.uuid4()
        resolved_session_id = uuid.UUID(str(session_id)) if session_id else None

        # 可解释性落库走 explain_enabled 开关：filter_reasons 由组装器在内存中
        # 始终收集（纯函数），但写库有存储成本，关闭时保持 metadata 为空
        metadata: dict[str, Any] | None = None
        if settings.explain_enabled:
            # 全部值先归一为 str/float，保证 JSON 序列化不因 UUID 等类型失败
            signals: dict[str, dict[str, float]] = {}
            for mem in final_memories:
                mem_id = str(mem.get("id", ""))
                if not mem_id:
                    continue
                signals[mem_id] = {
                    "bm25": float(mem.get("bm25_score", 0.0) or 0.0),
                    "vector": float(mem.get("vector_score", 0.0) or 0.0),
                    "rrf": float(mem.get("rrf_score", 0.0) or 0.0),
                    "rerank": float(mem.get("rerank_score", mem.get("score", 0.0)) or 0.0),
                    "utility": float(mem.get("utility_score", 0.0) or 0.0),
                }
            metadata = {
                "signals": signals,
                "filter_reasons": [
                    {
                        "memory_id": str(fr.memory_id),
                        "stage": str(fr.stage),
                        "reason": str(fr.reason),
                    }
                    for fr in (ctx.filter_reasons if ctx else [])
                ],
            }

        trace = RetrievalTrace(
            id=trace_id,
            workspace_id=workspace_id,
            session_id=resolved_session_id,
            keyword=query,
            intent=analyzed.to_dict() if hasattr(analyzed, "to_dict") else None,
            candidate_count=len(candidates),
            returned_count=len(final_memories),
            latency_ms=latency_ms,
            metadata_=metadata,
        )

        # 批量构建最终候选的 trace 项
        final_ids = {m["id"] for m in final_memories}
        trace_items = [
            RetrievalTraceItem(
                trace_id=trace_id,
                memory_id=uuid.UUID(doc_id),
                stage="final",
                rank=rank,
                score=data.get("bm25_score", 0),
                used=True,
            )
            for rank, (doc_id, data) in enumerate(
                sorted(candidates.items(), key=lambda x: x[1].get("bm25_score", 0), reverse=True),
                1,
            )
            if doc_id in final_ids
        ]

        # 批量构建记忆使用记录
        usage_records = [
            MemoryUsage(
                workspace_id=workspace_id,
                memory_id=uuid.UUID(mem["id"]),
                trace_id=trace_id,
                session_id=resolved_session_id,
                position=mem.get("rank", 0),
                stage="retrieved",
            )
            for mem in final_memories
        ]

        # 全部记录一次性批量写入
        db.add(trace)
        if trace_items:
            db.add_all(trace_items)
        if usage_records:
            db.add_all(usage_records)

        await db.flush()

    async def _ensure_embedding_matrix(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        fingerprint: tuple[int, datetime | None, int] | None = None,
    ) -> tuple[list[str], np.ndarray, np.ndarray]:
        """返回 active 向量的 (ids, matrix, norms)，按指纹缓存。

        ``workspace_id=None`` 表示收集所有 workspace 的向量。

        向量优先取自注入的向量来源（文件版 vectors.npz 索引），
        否则回退到遗留的 ``Memory.embedding`` 列。矩阵用 float32、
        范数预先算好，每次查询只需一次矩阵-向量乘 + argpartition——
        无 DB 往返、无 list→array 转换、无范数重算。
        """
        key = (workspace_id, project_id)
        if fingerprint is None:
            fingerprint = await self._content_fingerprint(db, workspace_id, project_id)

        vector_index = self._vector_source() if self._vector_source is not None else None
        effective_fp: _VecFingerprint
        if vector_index is not None:
            # 文件索引可能在不触碰 DB 内容的情况下变化（向量重建、归档裁剪），
            # 因此其大小并入缓存指纹。
            effective_fp = (*fingerprint, vector_index.size())
        else:
            effective_fp = fingerprint

        cached = self._vec_cache.get(key)
        if (
            cached is not None
            and cached[0] == effective_fp
            and time.monotonic() - cached[1] < _INDEX_MAX_AGE_SECONDS
        ):
            return cached[2], cached[3], cached[4]

        if vector_index is not None:
            rows = await self._collect_vectors_from_index(
                db, vector_index, workspace_id, project_id
            )
        else:
            rows = await self._collect_vectors_from_db(db, workspace_id, project_id)

        if not rows:
            empty: tuple[list[str], np.ndarray, np.ndarray] = (
                [],
                np.empty((0, 0), dtype=np.float32),
                np.empty(0, dtype=np.float32),
            )
            self._vec_cache[key] = (
                effective_fp,
                time.monotonic(),
                empty[0],
                empty[1],
                empty[2],
            )
            if len(self._vec_cache) > _VEC_CACHE_SIZE:
                self._vec_cache.pop(next(iter(self._vec_cache)))
            return empty

        ids = [r[0] for r in rows]
        matrix = np.array([r[1] for r in rows], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1)

        self._vec_cache[key] = (effective_fp, time.monotonic(), ids, matrix, norms)
        if len(self._vec_cache) > _VEC_CACHE_SIZE:
            self._vec_cache.pop(next(iter(self._vec_cache)))
        return ids, matrix, norms

    async def _collect_vectors_from_index(
        self,
        db: AsyncSession,
        vector_index: Any,
        workspace_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
    ) -> list[tuple[str, Any]]:
        """返回该范围 active 记忆的 id，并配对文件索引中的向量。"""
        stmt = select(Memory.id).where(Memory.status == "active").limit(_VECTOR_SEARCH_LIMIT)
        if workspace_id:
            stmt = stmt.where(Memory.workspace_id == workspace_id)
        if project_id:
            stmt = stmt.where(Memory.project_id == project_id)
        result = await db.execute(stmt)

        rows: list[tuple[str, Any]] = []
        for (mid,) in result:
            vector = vector_index.get_vector(str(mid))
            if vector is not None:
                rows.append((str(mid), vector))
        return rows

    async def _collect_vectors_from_db(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
    ) -> list[tuple[str, Any]]:
        """遗留路径：从 ``Memory.embedding`` 列读取向量。"""
        stmt = (
            select(Memory.id, Memory.embedding)
            .where(
                Memory.status == "active",
                Memory.embedding.isnot(None),
            )
            .limit(_VECTOR_SEARCH_LIMIT)
        )
        if workspace_id:
            stmt = stmt.where(Memory.workspace_id == workspace_id)
        if project_id:
            stmt = stmt.where(Memory.project_id == project_id)
        result = await db.execute(stmt)

        return [(str(row.id), row.embedding) for row in result if row.embedding]

    async def warm_up(self, db: AsyncSession) -> dict[str, int]:
        """为所有含 active 记忆的 workspace 预构建 BM25 + 向量缓存。

        启动时调用一次，让首个真实查询直接命中热缓存而不必支付
        完整构建成本。返回摘要字典用于日志。
        """
        stmt = select(Memory.workspace_id).where(Memory.status == "active").distinct()
        result = await db.execute(stmt)
        workspace_ids = [row[0] for row in result if row[0]]

        built = 0
        for ws_id in workspace_ids:
            try:
                await self._ensure_index(db, workspace_id=ws_id)
                await self._ensure_embedding_matrix(db, workspace_id=ws_id, project_id=None)
                built += 1
            except Exception:
                logger.warning("Warm-up failed for workspace %s", ws_id, exc_info=True)

        return {"workspaces_found": len(workspace_ids), "caches_built": built}

    async def _vector_search(
        self,
        db: AsyncSession,
        query_embedding: list[float],
        workspace_id: uuid.UUID | None,
        top_k: int = 50,
        project_id: uuid.UUID | None = None,
        fingerprint: tuple[int, datetime | None, int] | None = None,
    ) -> list[tuple[str, float]]:
        ids, matrix, norms = await self._ensure_embedding_matrix(
            db, workspace_id, project_id, fingerprint=fingerprint
        )
        if not ids:
            return []

        q = np.array(query_embedding, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []

        # 余弦相似度 = 点积 / (范数 × 查询范数)；零范数向量记 0 分
        dots = matrix @ q
        valid_mask = norms > 0
        similarities = np.zeros(len(ids), dtype=np.float32)
        similarities[valid_mask] = dots[valid_mask] / (norms[valid_mask] * q_norm)

        return [(ids[i], float(similarities[i])) for i in top_k_indices(similarities, top_k)]

    async def get_bm25_index(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> BM25Index:
        """获取缓存的 BM25 索引（供搜索 API 使用）。"""
        return await self._ensure_index(db, workspace_id, project_id)

    async def vector_search(
        self,
        db: AsyncSession,
        query_embedding: list[float],
        workspace_id: uuid.UUID | None,
        top_k: int = 50,
        project_id: uuid.UUID | None = None,
    ) -> list[tuple[str, float]]:
        """向量检索的公开入口（供搜索 API 使用）。

        ``workspace_id=None`` 表示跨全部 workspace 检索。
        """
        return await self._vector_search(
            db, query_embedding, workspace_id, top_k=top_k, project_id=project_id
        )


def get_retrieval_engine() -> RetrievalEngine:
    global _engine
    if _engine is None:
        _engine = RetrievalEngine()
    return _engine
