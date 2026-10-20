"""记忆状态与健康端点（PRD 第 39-42 节）。"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from apps.api.auth import AgentIdentity
from apps.api.deps import (
    get_current_agent,
    get_db,
    get_memory_indexer,
    resolve_workspace,
)
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import (
    AgentSession,
    CandidateMemory,
    Memory,
    MemoryConflict,
    MemoryFeedback,
    MemoryUsage,
    RetrievalTrace,
    ReviewSchedule,
    SessionNote,
)
from packages.memory.evolution_metrics import compute_evolution_metrics
from packages.memory.health import compute_health
from packages.memory.utility_score import compute_utility_score
from packages.retrieval.embedding import get_embedding_metrics

logger = logging.getLogger(__name__)

router = APIRouter(prefix=API_V1_PREFIX, tags=["memory-status"])

_EMPTY_HEALTH_RESPONSE: dict[str, Any] = {
    "utility": {
        "utility": 0.0,
        "retrieval_success": 0.0,
        "agent_usage": 0.0,
        "human_feedback": 0.0,
        "freshness": 0.0,
        "evidence_strength": 0.0,
    },
    "health": {"score": 0.0, "status": "unknown", "reasons": []},
}


def _calculate_evidence_count(content: str | None) -> int:
    """从内容特征推断证据强度。

    证据包括：代码块、示例、结构化小节、参考链接。
    返回 0-5 的计数，用于效用分计算。
    """
    if not content:
        return 0

    evidence = 0

    # 代码块（``` 围栏或缩进代码）
    if "```" in content:
        evidence += 1
    if content.count("    ") > 3 or content.count("\t") > 3:
        evidence += 1

    # 示例/反例关键词
    if any(kw in content for kw in ["例如", "比如", "example", "反例", "反例"]):
        evidence += 1

    # 结构化小节（## 标题）
    section_count = content.count("\n## ")
    if section_count >= 2:
        evidence += 1
    if section_count >= 4:
        evidence += 1

    # 参考链接
    if "http" in content or "参考" in content or "reference" in content.lower():
        evidence += 1

    return min(evidence, 5)


# 仪表盘统计的简单 TTL 缓存（避免高频轮询重复执行 SQL）
class _StatsCache:
    __slots__ = ("_expires_at", "_ttl", "_value")

    def __init__(self, ttl: float = 30.0) -> None:
        self._value: dict[str, Any] | None = None
        self._expires_at: float = 0.0
        self._ttl = ttl

    def get(self) -> dict[str, Any] | None:
        if self._value is not None and time.monotonic() < self._expires_at:
            return self._value
        return None

    def set(self, value: dict[str, Any]) -> None:
        self._value = value
        self._expires_at = time.monotonic() + self._ttl

    def invalidate(self) -> None:
        self._value = None
        self._expires_at = 0.0


_dashboard_cache = _StatsCache(ttl=30.0)
_metrics_cache = _StatsCache(ttl=30.0)
_health_summary_cache = _StatsCache(ttl=60.0)

# 单条记忆健康度缓存（以 memory_id 为键）
_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_TTL = 30.0


def invalidate_memory_status_caches(memory_id: str | None = None) -> None:
    """记忆写入后使记忆状态相关缓存失效。

    始终失效仪表盘、指标与健康汇总缓存；传入 *memory_id* 时
    同时失效该记忆的健康度缓存。
    """
    _dashboard_cache.invalidate()
    _metrics_cache.invalidate()
    _health_summary_cache.invalidate()
    if memory_id is not None:
        _health_cache.pop(memory_id, None)


@router.get("/dashboard-stats")
async def get_dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回仪表盘统计卡片的全局计数。"""
    cached = _dashboard_cache.get()
    if cached is not None:
        return cached

    # 各表分表计数，避免跨表笛卡尔积
    candidate_count = await db.scalar(
        select(func.count(CandidateMemory.id)).filter(CandidateMemory.status == "pending_review")
    )
    conflict_count = await db.scalar(
        select(func.count(MemoryConflict.id)).filter(MemoryConflict.status == "open")
    )
    memory_stats = await db.execute(
        select(
            func.count(Memory.id).filter(Memory.status == "active").label("approved"),
            func.count(Memory.id)
            .filter(Memory.status == "active", Memory.importance >= 0.8)
            .label("high_value"),
        )
    )
    mem_row = memory_stats.one()
    pending_notes = await db.scalar(
        select(func.count(SessionNote.id)).filter(SessionNote.formalized.is_(False))
    )

    result = {
        "candidates": candidate_count or 0,
        "high_value": mem_row.high_value or 0,
        "conflicts": conflict_count or 0,
        "approved": mem_row.approved or 0,
        "pending_notes": pending_notes or 0,
    }
    _dashboard_cache.set(result)
    return result


@router.get("/memory-status")
async def get_memory_status(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    resolved_ws_id = await resolve_workspace(workspace_id, db)

    # 用标量子查询单条 SQL 批量取各计数
    counts = await _batch_counts(db, resolved_ws_id)

    candidate_count_val = counts["candidates"]
    insights = await _compute_insights(db, resolved_ws_id, candidate_count=candidate_count_val)
    evolution = await compute_evolution_metrics(db, resolved_ws_id, days=7)

    return {
        "workspace_id": str(resolved_ws_id),
        "version": "0.2.0",
        "memories": {
            "total": counts["mem_total"],
            "active": counts["mem_active"],
        },
        "candidates": {
            "pending_review": candidate_count_val,
        },
        "conflicts": {
            "open": counts["conflicts"],
        },
        "retrieval": {
            "traces": counts["traces"],
        },
        "insights": insights,
        "evolution_metrics": evolution,
    }


async def _batch_counts(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, int]:
    """单次 SQL 往返完成 memory-status 所需的全部计数。

    通过标量子查询合并为一条 SQL：既遵守 aiosqlite 单连接约束，
    又省掉 3 次多余往返。
    """
    mem_total_sq = (
        select(func.count(Memory.id)).where(Memory.workspace_id == workspace_id).scalar_subquery()
    )
    mem_active_sq = (
        select(func.count(Memory.id))
        .where(Memory.workspace_id == workspace_id, Memory.status == "active")
        .scalar_subquery()
    )
    candidate_sq = (
        select(func.count(CandidateMemory.id))
        .where(
            CandidateMemory.workspace_id == workspace_id,
            CandidateMemory.status == "pending_review",
        )
        .scalar_subquery()
    )
    conflict_sq = (
        select(func.count(MemoryConflict.id))
        .where(
            MemoryConflict.workspace_id == workspace_id,
            MemoryConflict.status == "open",
        )
        .scalar_subquery()
    )
    trace_sq = (
        select(func.count(RetrievalTrace.id))
        .where(RetrievalTrace.workspace_id == workspace_id)
        .scalar_subquery()
    )

    row = await db.execute(select(mem_total_sq, mem_active_sq, candidate_sq, conflict_sq, trace_sq))
    vals = row.one()
    return {
        "mem_total": vals[0] or 0,
        "mem_active": vals[1] or 0,
        "candidates": vals[2] or 0,
        "conflicts": vals[3] or 0,
        "traces": vals[4] or 0,
    }


async def _compute_insights(
    db: AsyncSession, workspace_id: uuid.UUID, candidate_count: int = 0
) -> dict[str, Any]:
    """为 memory_status 计算趋势分析与洞察。"""
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    submission_stats = await db.execute(
        select(
            func.count(case((CandidateMemory.created_at >= seven_days_ago, CandidateMemory.id))),
            func.count(
                case(
                    (
                        (CandidateMemory.created_at >= fourteen_days_ago)
                        & (CandidateMemory.created_at < seven_days_ago),
                        CandidateMemory.id,
                    )
                )
            ),
        ).where(CandidateMemory.workspace_id == workspace_id)
    )
    active_dist_result = await db.execute(
        select(
            Memory.type,
            func.count(Memory.id),
            func.count(case((Memory.confidence < 0.5, Memory.id))),
        )
        .where(Memory.workspace_id == workspace_id, Memory.status == "active")
        .group_by(Memory.type)
    )
    candidate_dist_result = await db.execute(
        select(CandidateMemory.type, func.count(CandidateMemory.id))
        .where(CandidateMemory.workspace_id == workspace_id)
        .group_by(CandidateMemory.type)
    )

    row = submission_stats.one_or_none()
    recent_count, previous_count = (row[0], row[1]) if row else (0, 0)

    if previous_count == 0:
        trend = "new" if recent_count > 0 else "stable"
    elif recent_count > previous_count * 1.2:
        trend = "rising"
    elif recent_count < previous_count * 0.8:
        trend = "declining"
    else:
        trend = "stable"

    type_distribution: dict[str, int] = {}
    low_confidence_count = 0
    for active_row in active_dist_result.all():
        # 行结构：(类型, 数量, 低置信度数量)
        type_distribution[str(active_row[0])] = int(active_row[1])
        low_confidence_count += int(active_row[2] or 0)
    for cand_row in candidate_dist_result.all():
        cand_type = str(cand_row[0])
        type_distribution[cand_type] = type_distribution.get(cand_type, 0) + int(cand_row[1])

    suggestions = []
    if low_confidence_count > 0:
        suggestions.append(f"发现 {low_confidence_count} 条低置信度记忆，建议审核")
    if candidate_count > 10:
        suggestions.append(f"有 {candidate_count} 条候选记忆待审核")

    return {
        "submission_trend": trend,
        "recent_submissions_7d": recent_count,
        "type_distribution": type_distribution,
        "low_confidence_count": low_confidence_count,
        "suggestions": suggestions,
    }


@router.get("/memory-health/{memory_id}")
async def get_memory_health(
    memory_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    # 检查单条记忆健康度缓存
    now = time.monotonic()
    if memory_id in _health_cache:
        cached_time, cached_data = _health_cache[memory_id]
        if now - cached_time < _HEALTH_CACHE_TTL:
            return cached_data
        del _health_cache[memory_id]

    try:
        uid = uuid.UUID(memory_id)
    except ValueError:
        return {"memory_id": memory_id, **_EMPTY_HEALTH_RESPONSE}

    memory = await db.get(Memory, uid, options=(defer(Memory.embedding),))
    if memory is None:
        return {"memory_id": memory_id, **_EMPTY_HEALTH_RESPONSE}

    feedback_result = await db.execute(
        select(MemoryFeedback.feedback_type, func.count(MemoryFeedback.id))
        .where(MemoryFeedback.memory_id == uid)
        .group_by(MemoryFeedback.feedback_type)
    )
    usage_stats = await db.execute(
        select(
            func.count(MemoryUsage.id),
            func.count(case((MemoryUsage.stage.in_(["used", "cited"]), MemoryUsage.id))),
        ).where(MemoryUsage.memory_id == uid)
    )
    conflict_result = await db.execute(
        select(func.count(MemoryConflict.id)).where(
            MemoryConflict.memory_id == uid,
            MemoryConflict.status == "open",
        )
    )

    ease_factor_row = await db.execute(
        select(ReviewSchedule.ease_factor).where(ReviewSchedule.memory_id == uid)
    )
    ease_factor = ease_factor_row.scalar() or 2.5

    feedback_counts = {row[0]: row[1] for row in feedback_result.all()}
    row = usage_stats.first()
    retrieval_count, used_count = (row[0], row[1]) if row else (0, 0)
    conflict_count = conflict_result.scalar() or 0

    # 从内容特征计算 evidence_count
    evidence_count = _calculate_evidence_count(memory.content)

    utility = compute_utility_score(
        retrieval_count=retrieval_count,
        used_count=used_count,
        cited_count=0,
        useful_votes=feedback_counts.get("useful", 0),
        not_useful_votes=feedback_counts.get("not_useful", 0),
        last_used_at=memory.last_used_at,
        evidence_count=evidence_count,
        ease_factor=ease_factor,
    )

    health = compute_health(
        memory_status=memory.status,
        utility_score=utility.utility,
        conflict_count=conflict_count,
        feedback_useful=feedback_counts.get("useful", 0),
        feedback_not_useful=feedback_counts.get("not_useful", 0),
        last_used_at=memory.last_used_at,
        created_at=memory.created_at,
        usage_count=memory.usage_count,
        confidence=memory.confidence,
        importance=memory.importance,
        is_permanent=memory.is_permanent,
        ease_factor=ease_factor,
    )

    result = {
        "memory_id": str(memory_id),
        "utility": utility.to_dict(),
        "health": health.to_dict(),
    }

    # 写入缓存
    _health_cache[memory_id] = (time.monotonic(), result)

    return result


@router.get("/health-summary")
async def get_health_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回全部 active 记忆的聚合健康统计。"""
    cached = _health_summary_cache.get()
    if cached is not None:
        return cached

    result = await db.execute(
        select(Memory).where(Memory.status == "active").options(defer(Memory.embedding))
    )
    memories = result.scalars().all()

    if not memories:
        empty = {
            "total": 0,
            "avg_score": 0.0,
            "distribution": {"healthy": 0, "needs_review": 0, "suspicious": 0},
        }
        _health_summary_cache.set(empty)
        return empty

    ease_factor_result = await db.execute(
        select(ReviewSchedule.memory_id, ReviewSchedule.ease_factor)
    )
    ease_factor_map: dict[Any, float] = {row[0]: row[1] for row in ease_factor_result.all()}

    memory_ids = [mem.id for mem in memories]

    # 批量反馈计数：memory_id -> {反馈类型: 数量}
    feedback_batch: dict[Any, dict[str, int]] = {}
    if memory_ids:
        feedback_result = await db.execute(
            select(
                MemoryFeedback.memory_id,
                MemoryFeedback.feedback_type,
                func.count(MemoryFeedback.id),
            )
            .where(MemoryFeedback.memory_id.in_(memory_ids))
            .group_by(MemoryFeedback.memory_id, MemoryFeedback.feedback_type)
        )
        for mid, ftype, cnt in feedback_result.all():
            feedback_batch.setdefault(mid, {})[ftype] = cnt

    # 批量使用统计：memory_id -> (检索次数, 实际使用次数)
    usage_batch: dict[Any, tuple[int, int]] = {}
    if memory_ids:
        usage_result = await db.execute(
            select(
                MemoryUsage.memory_id,
                func.count(MemoryUsage.id),
                func.count(case((MemoryUsage.stage.in_(["used", "cited"]), MemoryUsage.id))),
            )
            .where(MemoryUsage.memory_id.in_(memory_ids))
            .group_by(MemoryUsage.memory_id)
        )
        for mid, total, used in usage_result.all():
            usage_batch[mid] = (total, used)

    # 批量冲突计数：memory_id -> 数量
    conflict_batch: dict[Any, int] = {}
    if memory_ids:
        conflict_result = await db.execute(
            select(MemoryConflict.memory_id, func.count(MemoryConflict.id))
            .where(
                MemoryConflict.memory_id.in_(memory_ids),
                MemoryConflict.status == "open",
            )
            .group_by(MemoryConflict.memory_id)
        )
        for mid, cnt in conflict_result.all():
            conflict_batch[mid] = cnt

    scores: list[float] = []
    distribution = {"healthy": 0, "needs_review": 0, "suspicious": 0}

    for mem in memories:
        ef = ease_factor_map.get(mem.id, 2.5)
        feedback_counts = feedback_batch.get(mem.id, {})
        retrieval_count, used_count = usage_batch.get(mem.id, (0, 0))
        conflict_count = conflict_batch.get(mem.id, 0)

        evidence_count = _calculate_evidence_count(mem.content)

        utility = compute_utility_score(
            retrieval_count=retrieval_count,
            used_count=used_count,
            cited_count=0,
            useful_votes=feedback_counts.get("useful", 0),
            not_useful_votes=feedback_counts.get("not_useful", 0),
            last_used_at=mem.last_used_at,
            evidence_count=evidence_count,
            ease_factor=ef,
        )

        health = compute_health(
            memory_status=mem.status,
            utility_score=utility.utility,
            conflict_count=conflict_count,
            feedback_useful=feedback_counts.get("useful", 0),
            feedback_not_useful=feedback_counts.get("not_useful", 0),
            last_used_at=mem.last_used_at,
            created_at=mem.created_at,
            usage_count=mem.usage_count,
            confidence=mem.confidence,
            importance=mem.importance,
            is_permanent=mem.is_permanent,
            ease_factor=ef,
        )

        scores.append(health.score)
        status = health.status
        if status in distribution:
            distribution[status] += 1

    avg_score = sum(scores) / len(scores) if scores else 0.0

    result_data = {
        "total": len(memories),
        "avg_score": round(avg_score, 3),
        "distribution": distribution,
    }

    _health_summary_cache.set(result_data)
    return result_data


@router.get("/candidate-quality")
async def get_candidate_quality(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回待审候选的质量分布。"""
    result = await db.execute(
        select(
            CandidateMemory.quality_gate_score,
            CandidateMemory.value_score,
            CandidateMemory.quality_score,
        ).where(CandidateMemory.status == "pending_review")
    )
    rows = result.all()

    # 优先级：quality_gate_score > value_score > quality_score
    scores = []
    for row in rows:
        score = row[0] if row[0] is not None else (row[1] if row[1] is not None else row[2])
        if score is not None:
            scores.append(score)

    if not scores:
        return {"total": 0, "avg_score": 0.0, "distribution": {"high": 0, "medium": 0, "low": 0}}

    high = sum(1 for s in scores if s >= 0.7)
    low = sum(1 for s in scores if s < 0.4)
    medium = len(scores) - high - low

    return {
        "total": len(scores),
        "avg_score": round(sum(scores) / len(scores), 3),
        "distribution": {"high": high, "medium": medium, "low": low},
    }


@router.get("/metrics")
async def get_metrics(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回仪表盘聚合监控指标。"""
    # embedding 状态绕过统计缓存，保证 provider/加载状态实时
    cached = _metrics_cache.get()
    if cached is not None:
        return {**cached, "embedding": get_embedding_metrics()}

    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)

    trace_stats = await db.execute(
        select(
            func.avg(RetrievalTrace.latency_ms),
            func.count(RetrievalTrace.id),
            func.count(case((RetrievalTrace.created_at >= day_ago, RetrievalTrace.id))),
            func.count(case((RetrievalTrace.returned_count > 0, RetrievalTrace.id))),
        )
    )
    feedback_result = await db.execute(
        select(MemoryFeedback.feedback_type, func.count(MemoryFeedback.id)).group_by(
            MemoryFeedback.feedback_type
        )
    )
    session_stats = await db.execute(
        select(
            func.count(case((AgentSession.ended_at.is_(None), AgentSession.id))),
            func.count(AgentSession.id),
            func.count(case((AgentSession.outcome == "success", AgentSession.id))),
        )
    )

    row = trace_stats.first()
    avg_latency_val, total_traces_val, traces_24h_val, successful_val = (
        (row[0], row[1], row[2], row[3]) if row else (None, 0, 0, 0)
    )

    feedback_counts = {row[0]: row[1] for row in feedback_result.all()}
    row = session_stats.first()
    active_sessions_val, total_sessions_val, success_sessions_val = (
        (row[0], row[1], row[2]) if row else (0, 0, 0)
    )

    # 尽力而为：向量数量属补充监控数据
    vector_count = 0
    try:
        indexer = get_memory_indexer()
        vector_count = indexer.vector_index.size()
    except Exception:
        logger.warning("Failed to get vector index size", exc_info=True)

    result = {
        "retrieval": {
            "avg_latency_ms": round(avg_latency_val or 0, 1),
            "queries_24h": traces_24h_val or 0,
            "success_rate": round(successful_val / total_traces_val, 2)
            if total_traces_val > 0
            else 0,
            "total_queries": total_traces_val or 0,
        },
        "feedback": {
            "useful": feedback_counts.get("useful", 0),
            "not_useful": feedback_counts.get("not_useful", 0),
        },
        "sessions": {
            "active": active_sessions_val,
            "total": total_sessions_val,
            "success_rate": round(success_sessions_val / total_sessions_val, 2)
            if total_sessions_val > 0
            else 0,
        },
        "storage": {
            "vector_count": vector_count,
        },
    }
    _metrics_cache.set(result)
    return {**result, "embedding": get_embedding_metrics()}


@router.get("/evolution-metrics")
async def get_evolution_metrics(
    workspace_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回寄生演化系统的演化指标。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    return await compute_evolution_metrics(db, resolved_ws_id, days=days)
