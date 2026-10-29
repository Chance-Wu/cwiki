"""检索 API 端点——复用检索引擎完整管线的混合检索。"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.schemas import SearchRequest, SearchResponse, SearchResult
from packages.retrieval.engine import get_retrieval_engine

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


def _is_stale(valid_to: Any) -> bool:
    """判断记忆是否已过期。"""
    if not valid_to:
        return False
    try:
        if isinstance(valid_to, str):
            parsed = datetime.fromisoformat(valid_to)
        else:
            parsed = valid_to
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return datetime.now(UTC) > parsed
    except (ValueError, TypeError):
        return False


@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> SearchResponse:
    """混合检索：与 /v1/context 共用检索引擎完整排序管线。

    双路召回 → RRF 融合 → 多信号重排（时态/意图/否定等）→ 多样性过滤，
    排序行为与 /v1/context 一致。无相关性候选时返回按重要度排序的
    兜底列表并以 insufficient=True 显式标记（score 恒为 0）。
    """
    if not body.keyword or not body.keyword.strip():
        raise HTTPException(400, detail="Search keyword cannot be empty")

    resolved_ws_id = await resolve_workspace(body.workspace_id, db) if body.workspace_id else None

    # 解析有效过滤条件：显式字段优先于 filters dict
    filter_type = body.memory_type
    filter_min_confidence = body.min_confidence
    filter_threshold = body.threshold
    if body.filters:
        if not filter_type:
            filter_type = body.filters.get("type")
        if filter_min_confidence is None:
            filter_min_confidence = body.filters.get("min_confidence")
        if filter_threshold is None:
            filter_threshold = body.filters.get("threshold")

    cache_key = (
        body.keyword.strip(),
        str(resolved_ws_id) if resolved_ws_id else "",
        str(body.project_id) if body.project_id else "",
        body.memory_type or "",
        str(body.min_confidence) if body.min_confidence is not None else "",
        str(body.threshold) if body.threshold is not None else "",
        str(body.offset),
        str(body.limit),
        str(sorted(body.filters.items())) if body.filters else "",
        str(body.session_id) if body.session_id else "",
        "trace" if body.record_trace else "no-trace",
        body.mode,
    )
    cached = _search_cache.get(cache_key)
    if cached is not None and time.monotonic() - cached[0] < _SEARCH_CACHE_TTL:
        _search_cache.move_to_end(cache_key)
        return cached[1]

    engine = get_retrieval_engine()
    ranked = await engine.search_ranked(
        db,
        body.keyword.strip(),
        resolved_ws_id,
        project_id=body.project_id,
        # top_k 决定候选池与重排规模，取 offset+limit 保证分页切片后有足够条目
        top_k=body.offset + body.limit,
        memory_type=filter_type,
        min_confidence=filter_min_confidence,
        min_similarity=filter_threshold,
        session_id=body.session_id,
        record_trace=body.record_trace,
        tags=body.tags,
        mode=body.mode,
    )

    page = ranked["memories"][body.offset : body.offset + body.limit]
    results = [
        SearchResult(
            id=uuid.UUID(m["id"]),
            title=m["title"],
            content=m["content"],
            type=m["type"],
            tags=m.get("tags", []),
            version=m["version"],
            score=m["score"],
            confidence=m.get("confidence"),
            valid_to=str(m["valid_to"]) if m.get("valid_to") else None,
            is_stale=_is_stale(m.get("valid_to")),
        )
        for m in page
    ]

    response = SearchResponse(
        results=results,
        total=ranked["total"],
        keyword=body.keyword,
        insufficient=ranked["fallback"],
        insufficient_reason=(
            "无相关性候选，以下为按重要度排序的兜底结果" if ranked["fallback"] else None
        ),
        degraded=ranked.get("degraded", []),
    )
    _search_cache[cache_key] = (time.monotonic(), response)
    _evict_search_cache()
    return response
