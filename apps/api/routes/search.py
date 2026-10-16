"""检索 API 端点——关键词 + 向量融合的混合检索。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX, settings
from packages.domain.models import Memory
from packages.domain.schemas import SearchRequest, SearchResponse, SearchResult
from packages.domain.text_utils import preprocess_query_for_embedding
from packages.retrieval.embedding import get_embedding_service
from packages.retrieval.engine import RRF_K, get_retrieval_engine
from packages.retrieval.query.analyzer import analyze_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix=API_V1_PREFIX, tags=["search"])

_SEARCH_CACHE_TTL = 30.0
_SEARCH_CACHE_MAX = 128
_search_cache: OrderedDict[tuple[Any, ...], tuple[float, SearchResponse]] = OrderedDict()


def invalidate_search_cache() -> None:
    """清空全部搜索结果缓存（记忆写入后调用）。"""
    _search_cache.clear()


def _evict_search_cache() -> None:
    while len(_search_cache) > _SEARCH_CACHE_MAX:
        _search_cache.popitem(last=False)


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> SearchResponse:
    """混合检索：关键词匹配 + 向量相似度。

    用倒数排名融合（RRF）合并两路结果；BM25 与向量索引
    均由检索引擎的共享缓存提供。
    """
    if not body.keyword or not body.keyword.strip():
        raise HTTPException(400, detail="Search keyword cannot be empty")

    resolved_ws_id = await resolve_workspace(body.workspace_id, db) if body.workspace_id else None

    # 解析有效过滤条件：显式字段优先于 filters dict
    filter_type = body.memory_type
    filter_min_confidence = body.min_confidence
    if body.filters:
        if not filter_type:
            filter_type = body.filters.get("type")
        if filter_min_confidence is None:
            filter_min_confidence = body.filters.get("min_confidence")

    cache_key = (
        body.keyword.strip(),
        str(resolved_ws_id) if resolved_ws_id else "",
        str(body.project_id) if body.project_id else "",
        body.memory_type or "",
        str(body.min_confidence) if body.min_confidence is not None else "",
        str(body.offset),
        str(body.limit),
        str(sorted(body.filters.items())) if body.filters else "",
    )
    cached = _search_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL:
        _search_cache.move_to_end(cache_key)
        return cached[1]

    base_filters: list[Any] = [Memory.status == "active"]
    if resolved_ws_id is not None:
        base_filters.append(Memory.workspace_id == resolved_ws_id)
    if body.memory_type:
        base_filters.append(Memory.type == body.memory_type)
    if body.project_id:
        base_filters.append(Memory.project_id == body.project_id)
    if body.min_confidence is not None:
        base_filters.append(Memory.confidence >= body.min_confidence)

    engine = get_retrieval_engine()

    async def _do_keyword_search() -> list[tuple[str, float]]:
        index = await engine.get_bm25_index(db, resolved_ws_id, body.project_id)
        return index.search(body.keyword, top_k=50)

    async def _do_vector_search() -> list[tuple[str, float]]:
        # 尽力而为：向量检索失败不影响关键词检索
        try:
            embedding_svc = get_embedding_service()
            analyzed = analyze_query(body.keyword)
            vector_query = preprocess_query_for_embedding(body.keyword, analyzed)
            query_embedding = await embedding_svc.generate_embedding(vector_query)
            if not query_embedding:
                return []
            return await engine.vector_search(
                db, query_embedding, resolved_ws_id, top_k=50, project_id=body.project_id
            )
        except Exception:
            logger.warning("Vector search failed in search endpoint", exc_info=True)
            return []

    keyword_results, vector_results = await asyncio.gather(
        _do_keyword_search(), _do_vector_search()
    )

    candidates: dict[str, dict[str, Any]] = {}
    for rank, (mem_id, _score) in enumerate(keyword_results, 1):
        candidates[mem_id] = {"memory": None, "keyword_rank": rank, "vector_rank": 0}
    for rank, (mem_id, _score) in enumerate(vector_results, 1):
        if mem_id in candidates:
            candidates[mem_id]["vector_rank"] = rank
        else:
            candidates[mem_id] = {"memory": None, "keyword_rank": 0, "vector_rank": rank}

    all_ids = [uuid.UUID(mid) for mid in candidates]
    if all_ids:
        result = await db.execute(
            select(Memory).options(defer(Memory.embedding)).where(Memory.id.in_(all_ids))
        )
        mem_map = {str(m.id): m for m in result.scalars().all()}
        for mid, data in candidates.items():
            if mid in mem_map:
                data["memory"] = mem_map[mid]

    scored: list[tuple[str, float, Memory]] = []
    bm25_w = settings.bm25_weight
    vec_w = settings.vector_weight
    for mem_id, data in candidates.items():
        mem = data["memory"]
        if mem is None:
            continue
        # 应用过滤条件
        if filter_type and mem.type != filter_type:
            continue
        if filter_min_confidence is not None and (mem.confidence or 0) < filter_min_confidence:
            continue
        kw_rank = data["keyword_rank"]
        vec_rank = data["vector_rank"]
        rrf_score = 0.0
        if kw_rank > 0:
            rrf_score += bm25_w / (RRF_K + kw_rank)
        if vec_rank > 0:
            rrf_score += vec_w / (RRF_K + vec_rank)
        scored.append((mem_id, rrf_score, mem))

    scored.sort(key=lambda x: x[1], reverse=True)
    paginated = scored[body.offset : body.offset + body.limit]

    results = [
        SearchResult(
            id=mem.id,
            title=mem.title,
            content=mem.content,
            type=mem.type,
            version=mem.version,
            score=round(rrf_score, 6),
        )
        for _, rrf_score, mem in paginated
    ]

    response = SearchResponse(results=results, total=len(scored), keyword=body.keyword)
    _search_cache[cache_key] = (time.monotonic(), response)
    _evict_search_cache()
    return response
