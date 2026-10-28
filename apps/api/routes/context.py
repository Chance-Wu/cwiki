"""上下文检索端点——核心检索 API。"""

from __future__ import annotations

import json
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX, parasitic_evolution_config, settings
from packages.domain.models import AgentProfile, MemoryUsage
from packages.domain.schemas import (
    ContextItem,
    ContextRequest,
    ContextResponse,
    ProactivePushItem,
    ProactivePushRequest,
    ProactivePushResponse,
)
from packages.memory.similarity import jaccard_similarity
from packages.retrieval.engine import get_retrieval_engine

router = APIRouter(prefix=API_V1_PREFIX, tags=["context"])

_context_cache: OrderedDict[str, tuple[float, ContextResponse]] = OrderedDict()


def _evict_context_cache() -> None:
    """清理过期条目，并用 OrderedDict 的 LRU 顺序控制最大容量。

    优化点：只在插入时检查容量，TTL 在访问时惰性判断；
    仅当缓存超过上限才做全量清理。
    """
    while len(_context_cache) > settings.context_cache_max_size:
        _context_cache.popitem(last=False)


def _cache_key(body: ContextRequest) -> str:
    # 所有影响结果的请求字段都进键：不同 project/session/过滤条件不能串味
    return "|".join(
        [
            body.workspace_id,
            str(body.agent_id),
            str(body.session_id),
            str(body.project_id) if body.project_id else "",
            body.keyword or "",
            str(body.max_items),
            str(body.max_tokens),
            body.mode,
            ",".join(body.event_types or []),
            str(body.limit),
            str(body.include_memories),
            str(body.include_entities),
        ]
    )


def invalidate_context_cache() -> None:
    """清空上下文响应缓存（记忆写入后调用）。"""
    _context_cache.clear()


async def compute_freshness(
    memory_id: uuid.UUID,
    db: AsyncSession,
    memory_type: str | None = None,
) -> dict[str, Any]:
    """按最近使用时间计算记忆新鲜度。

    返回 dict，days_unused 为 None 表示永久记忆或无使用记录。
    """
    from packages.domain.models import Memory

    mem_stmt = select(Memory.is_permanent, Memory.permanent_reason).where(Memory.id == memory_id)
    mem_result = await db.execute(mem_stmt)
    mem_row = mem_result.one_or_none()

    if mem_row and mem_row[0]:
        return {
            "status": "permanent",
            "reason": mem_row[1],
            "days_unused": None,
        }

    stmt = (
        select(MemoryUsage.created_at)
        .where(MemoryUsage.memory_id == memory_id)
        .order_by(MemoryUsage.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    last_used = result.scalar_one_or_none()

    if not last_used:
        return {"days_unused": None}

    _last_used_aware = last_used if last_used.tzinfo else last_used.replace(tzinfo=UTC)
    days_unused = (datetime.now(UTC) - _last_used_aware).days
    return {"days_unused": days_unused}


async def batch_compute_freshness(
    memory_ids: list[uuid.UUID],
    db: AsyncSession,
) -> tuple[dict[uuid.UUID, dict[str, Any]], dict[uuid.UUID, str], dict[uuid.UUID, int]]:
    """用 2 条 SQL 批量计算多条记忆的新鲜度。

    返回 (freshness_map, type_map, usage_counts)。
    """
    if not memory_ids:
        return {}, {}, {}

    from packages.domain.models import Memory

    now = datetime.now(UTC)

    stmt = select(
        Memory.id, Memory.is_permanent, Memory.permanent_reason, Memory.type, Memory.usage_count
    ).where(Memory.id.in_(memory_ids))
    result = await db.execute(stmt)
    permanent_map: dict[uuid.UUID, tuple[bool, str | None]] = {}
    auto_type_map: dict[uuid.UUID, str] = {}
    usage_counts: dict[uuid.UUID, int] = {}
    for row in result.all():
        permanent_map[row[0]] = (row[1], row[2])
        auto_type_map[row[0]] = row[3]
        usage_counts[row[0]] = row[4]

    last_used_stmt = (
        select(MemoryUsage.memory_id, func.max(MemoryUsage.created_at))
        .where(MemoryUsage.memory_id.in_(memory_ids))
        .group_by(MemoryUsage.memory_id)
    )
    usage_result = await db.execute(last_used_stmt)
    last_used_map: dict[uuid.UUID, datetime | None] = {}
    for usage_row in usage_result.all():
        mem_id: uuid.UUID = usage_row[0]
        last_used_dt: datetime | None = usage_row[1]
        last_used_map[mem_id] = last_used_dt
    freshness_map: dict[uuid.UUID, dict[str, Any]] = {}
    for mid in memory_ids:
        perm_info = permanent_map.get(mid)
        if perm_info and perm_info[0]:
            freshness_map[mid] = {
                "status": "permanent",
                "reason": perm_info[1],
                "days_unused": None,
            }
            continue

        last_used = last_used_map.get(mid)
        if not last_used:
            freshness_map[mid] = {"days_unused": None}
            continue

        _lu_aware = last_used if last_used.tzinfo else last_used.replace(tzinfo=UTC)
        days_unused = (now - _lu_aware).days
        freshness_map[mid] = {"days_unused": days_unused}

    return freshness_map, auto_type_map, usage_counts


async def rerank_context_results(
    items: list[ContextItem],
    workspace_id: uuid.UUID,
    db: AsyncSession,
    freshness_map: dict[uuid.UUID, dict[str, Any]] | None = None,
    type_map: dict[uuid.UUID, str] | None = None,
    usage_counts: dict[uuid.UUID, int] | None = None,
) -> list[ContextItem]:
    """多信号重排：使用频次、新鲜度、类型通过率。"""
    if not items:
        return items

    from packages.domain.models import CandidateMemory, Review

    memory_ids = [item.memory_id for item in items if item.memory_id is not None]

    # 缺省数据一次性批量补齐，避免逐条查询
    if freshness_map is None or type_map is None or usage_counts is None:
        _freshness, _type_map, _usage_counts = await batch_compute_freshness(memory_ids, db)
        if freshness_map is None:
            freshness_map = _freshness
        if type_map is None:
            type_map = _type_map
        if usage_counts is None:
            usage_counts = _usage_counts

    approval_rates: dict[str, float] = {}
    stmt = (
        select(
            CandidateMemory.type,
            func.count(Review.id),
            func.sum(case((Review.action == "approved", 1), else_=0)),
        )
        .join(Review, Review.candidate_id == CandidateMemory.id)
        .where(CandidateMemory.workspace_id == workspace_id)
        .group_by(CandidateMemory.type)
    )
    result = await db.execute(stmt)
    for row in result.all():
        mem_type, total, approved = row[0], row[1], row[2] or 0
        approval_rates[mem_type] = approved / total if total > 0 else 0.5

    for item in items:
        sim_score = item.score if item.score is not None else 0.0

        usage_count = usage_counts.get(item.memory_id, 0) if item.memory_id is not None else 0
        usage_boost = min(0.15, usage_count * 0.02)

        freshness = freshness_map.get(item.memory_id, {}) if item.memory_id is not None else {}
        days_unused = freshness.get("days_unused")
        if freshness.get("status") == "permanent":
            freshness_boost = 0.05
        elif days_unused is None:
            freshness_boost = 0.0
        elif days_unused > 180:
            freshness_boost = -0.15
        elif days_unused > 90:
            freshness_boost = 0.0
        else:
            freshness_boost = 0.1

        mem_type = (
            type_map.get(item.memory_id, item.type) if item.memory_id is not None else item.type
        )
        approval_rate = approval_rates.get(mem_type, 0.5)
        approval_boost = (approval_rate - 0.5) * 0.1

        item.score = sim_score + usage_boost + freshness_boost + approval_boost

    return sorted(items, key=lambda x: x.score if x.score is not None else 0.0, reverse=True)


async def fit_to_token_budget(
    items: list[ContextItem],
    budget: int | None = None,
) -> list[ContextItem]:
    """贪心策略在 token 预算内选取条目。"""
    if budget is None:
        budget = settings.context_token_budget
    for item in items:
        item.metadata = item.metadata or {}
        item.metadata["estimated_tokens"] = len(item.content) // 4

    selected = []
    remaining = budget
    for item in items:
        tokens = item.metadata["estimated_tokens"] if item.metadata else 0
        if tokens <= remaining:
            selected.append(item)
            remaining -= tokens

    return selected


async def deduplicate_results(
    items: list[ContextItem],
    similarity_threshold: float = 0.8,
) -> list[ContextItem]:
    """移除高相似重复项，保留得分更高的一条。"""
    if len(items) <= 1:
        return items

    deduplicated: list[ContextItem] = []
    for item in items:
        is_duplicate = False
        for i, existing in enumerate(deduplicated):
            sim = jaccard_similarity(item.content, existing.content)
            if sim >= similarity_threshold:
                item_score = item.score if item.score is not None else 0.0
                existing_score = existing.score if existing.score is not None else 0.0
                if item_score > existing_score:
                    deduplicated[i] = item
                is_duplicate = True
                break
        if not is_duplicate:
            deduplicated.append(item)

    return deduplicated


async def _get_agent_profile_hints(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> dict[str, Any] | None:
    """加载 Agent Profile，返回用于上下文组装的个性化提示。"""
    if not parasitic_evolution_config.agent_profile_enabled:
        return None

    result = await db.execute(
        select(AgentProfile).where(
            AgentProfile.workspace_id == str(workspace_id),
            AgentProfile.agent_id == str(agent_id),
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        return None

    hints: dict[str, Any] = {}
    if profile.preferred_memory_types:
        hints["preferred_types"] = json.loads(profile.preferred_memory_types)
    if profile.nudge_response_rate < 0.3:
        hints["reduce_hints"] = True
    if profile.preferred_nudge_types:
        hints["preferred_nudge_types"] = json.loads(profile.preferred_nudge_types)
    return hints


async def proactive_memory_push(
    conversation_keywords: list[str],
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    db: AsyncSession,
    max_items: int = 3,
    min_score: float = 0.5,
) -> list[ProactivePushItem]:
    """根据对话关键词主动推送相关记忆。

    检索匹配关键词的记忆，过滤本会话已推送过的条目，
    并记录新推送以便后续去重。
    """
    if not conversation_keywords:
        return []

    from packages.domain.models import ProactivePushRecord

    already_pushed_stmt = select(ProactivePushRecord.memory_id).where(
        ProactivePushRecord.session_id == session_id,
    )
    result = await db.execute(already_pushed_stmt)
    already_pushed = {row[0] for row in result.all()}

    query = " ".join(conversation_keywords[:5])
    engine = get_retrieval_engine()
    search_result = await engine.retrieve(
        query=query,
        workspace_id=workspace_id,
        db=db,
        max_items=max_items + len(already_pushed),
    )

    pushed: list[ProactivePushItem] = []
    records_to_add: list[ProactivePushRecord] = []
    keywords_str = ", ".join(conversation_keywords[:3])

    for mem in search_result.get("memories", []):
        if len(pushed) >= max_items:
            break

        score = float(mem.get("score", mem.get("combined_score", 0.0)))
        if score < min_score:
            continue

        mem_id = uuid.UUID(mem["id"]) if isinstance(mem["id"], str) else mem["id"]
        if mem_id in already_pushed:
            continue

        records_to_add.append(
            ProactivePushRecord(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                session_id=session_id,
                memory_id=mem_id,
                relevance_score=score,
                keywords=keywords_str,
            )
        )

        pushed.append(
            ProactivePushItem(
                memory_id=mem_id,
                title=mem["title"],
                snippet=mem["content"][:200],
                relevance=score,
                push_reason=f"与当前对话主题相关（关键词：{keywords_str}）",
            )
        )

    if records_to_add:
        db.add_all(records_to_add)

    return pushed


@router.post("/context/proactive", response_model=ProactivePushResponse)
async def proactive_push(
    body: ProactivePushRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> ProactivePushResponse:
    """根据对话关键词主动推送相关记忆。"""
    if not parasitic_evolution_config.proactive_push_enabled:
        return ProactivePushResponse(items=[], total=0)

    resolved_ws_id = await resolve_workspace(body.workspace_id, db)

    items = await proactive_memory_push(
        conversation_keywords=body.keywords,
        workspace_id=resolved_ws_id,
        session_id=body.session_id,
        db=db,
        max_items=body.max_items,
    )
    await db.commit()
    return ProactivePushResponse(items=items, total=len(items))


@router.post("/context", response_model=ContextResponse)
async def get_context(
    body: ContextRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> ContextResponse:
    """主检索端点。

    从已验证记忆中为查询组装相关上下文。底层由 RetrievalEngine
    融合 BM25 关键词检索、向量语义检索、元数据过滤与重排。
    """
    resolved_ws_id = await resolve_workspace(body.workspace_id, db)

    key = _cache_key(body)
    _evict_context_cache()
    now = time.monotonic()
    cached = _context_cache.get(key)
    if cached and now - cached[0] < settings.context_cache_ttl:
        _context_cache.move_to_end(key)
        return cached[1]

    engine = get_retrieval_engine()

    profile_hints = await _get_agent_profile_hints(resolved_ws_id, body.agent_id, db)

    result = await engine.retrieve(
        query=body.keyword or "",
        workspace_id=resolved_ws_id,
        db=db,
        project_id=body.project_id,
        max_items=body.max_items,
        max_tokens=body.max_tokens,
        session_id=body.session_id,
        mode=body.mode,
    )

    preferred_types = profile_hints.get("preferred_types") if profile_hints else None

    valid_memories: list[tuple[uuid.UUID, str, dict[str, Any], int]] = []
    for position, mem in enumerate(result.get("memories", [])):
        confidence = float(mem.get("confidence", 0.5))
        if confidence < 0.3:
            continue
        mem_id = uuid.UUID(mem["id"]) if isinstance(mem["id"], str) else mem["id"]
        mem_type = mem.get("type", "fact")
        valid_memories.append((mem_id, mem_type, mem, position))

    if valid_memories:
        batch_ids = [v[0] for v in valid_memories]
        freshness_map, auto_type_map, usage_counts = await batch_compute_freshness(batch_ids, db)
    else:
        freshness_map = {}
        auto_type_map = {}
        usage_counts = {}

    items = []
    usage_records: list[MemoryUsage] = []
    for mem_id, mem_type, mem, position in valid_memories:
        freshness = freshness_map.get(mem_id, {"days_unused": None})
        # curated 上下文是 Agent 主动拉取并实际消费的内容 → 记 used；
        # 检索（/v1/search）命中的记 retrieved，两者构成 utility 的成功率信号
        usage_records.append(
            MemoryUsage(
                workspace_id=resolved_ws_id,
                memory_id=mem_id,
                session_id=body.session_id,
                position=position,
                stage="used",
            )
        )

        items.append(
            ContextItem(
                memory_id=mem_id,
                id=mem_id,
                title=mem["title"],
                content=mem["content"],
                type=mem_type,
                version=mem.get("version"),
                score=float(mem.get("score", mem.get("combined_score", 0.5))),
                source="memory",
                metadata={"freshness": freshness},
            )
        )

    if preferred_types:
        for item in items:
            if item.type in preferred_types:
                item.score = (item.score if item.score is not None else 0.0) + 0.05

    if usage_records:
        db.add_all(usage_records)

    items = await rerank_context_results(
        items,
        resolved_ws_id,
        db,
        freshness_map=freshness_map,
        type_map=auto_type_map,
        usage_counts=usage_counts,
    )
    items = await deduplicate_results(items)
    items = await fit_to_token_budget(
        items, budget=body.max_tokens or settings.context_token_budget
    )

    await db.commit()

    sources = [f"memory:{s['memory_id']}" for s in result.get("sources", [])]

    response = ContextResponse(
        context=result.get("context", ""),
        items=items,
        sources=sources,
        total=result.get("total", len(items)),
        keyword=body.keyword,
        latency_ms=int(result.get("latency_ms", 0)),
        degraded=result.get("degraded", []),
    )
    _context_cache[key] = (time.monotonic(), response)
    _context_cache.move_to_end(key)
    return response


@router.get("/context/suggestions")
async def get_learning_suggestions(
    workspace_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回学习建议：陈旧记忆、低置信度、记忆缺口。"""
    from sqlalchemy import func as sa_func

    from packages.domain.models import Memory

    # 低置信度：过滤与 limit 下推到 SQL 完成
    low_conf_stmt = (
        select(
            Memory.id,
            Memory.title,
            Memory.type,
            Memory.confidence,
            Memory.importance,
            Memory.last_used_at,
        )
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
            Memory.confidence < 0.5,
        )
        .order_by(Memory.confidence.asc())
        .limit(10)
    )
    low_conf_result = await db.execute(low_conf_stmt)
    low_confidence = [
        {
            "memory_id": str(row[0]),
            "title": row[1],
            "type": row[2],
            "confidence": row[3],
            "importance": row[4],
            "last_used_at": row[5].isoformat() if row[5] else None,
            "reason": f"置信度 {row[3]:.2f} 低于 0.5 阈值",
        }
        for row in low_conf_result.all()
    ]

    # 类型计数：SQL 内 GROUP BY，避免加载全部行
    type_counts_stmt = (
        select(
            Memory.type,
            sa_func.count(Memory.id).label("count"),
        )
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
        )
        .group_by(Memory.type)
    )
    type_counts_result = await db.execute(type_counts_stmt)
    type_counts = {row[0]: row[1] for row in type_counts_result}

    total = sum(type_counts.values()) or 1
    from packages.domain.types import ALL_TYPES

    expected_types = ALL_TYPES
    expected_ratio = 1.0 / len(expected_types)

    memory_gaps: list[dict[str, Any]] = []
    for t in expected_types:
        count = type_counts.get(t, 0)
        actual_ratio = count / total
        if actual_ratio < expected_ratio * 0.5:
            memory_gaps.append(
                {
                    "type": t,
                    "count": count,
                    "expected_ratio": round(expected_ratio, 3),
                    "actual_ratio": round(actual_ratio, 3),
                }
            )

    return {
        "low_confidence": low_confidence,
        "memory_gaps": memory_gaps,
        "total_suggestions": len(low_confidence) + len(memory_gaps),
    }
