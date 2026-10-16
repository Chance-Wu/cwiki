"""上下文组装器——完整上下文流水线：去重、冲突检测、优先级排序、
多样性与 token 预算（spec 第 5 节）。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from packages.domain.config import settings
from packages.domain.text_utils import format_memory_for_embedding
from packages.retrieval.context.compression import (
    DEFAULT_RESERVE_TYPES,
    apply_per_memory_cap,
    degrade_to_fit,
    merge_similar_memories,
    reserve_priority,
)
from packages.retrieval.context.conflict import ConflictReference, detect_conflicts
from packages.retrieval.context.dedup import deduplicate_with_details
from packages.retrieval.context.filters import apply_entry_filters
from packages.retrieval.context.priority import rank_by_priority
from packages.retrieval.context.token_counter import (
    DEFAULT_BUDGET,
    estimate_tokens,
    normalize_budget,
)
from packages.retrieval.embedding import get_embedding_service
from packages.retrieval.ranking.diversity import apply_diversity
from packages.retrieval.vector_utils import batch_cosine_similarities

logger = logging.getLogger(__name__)


@dataclass
class FilterReason:
    """一条记忆被流水线某阶段丢弃的可解释记录。

    reason 尽量携带目标细节（如 ``duplicate_of:<id>``、``merged_into:<id>``、
    ``max_per_type:<type>``、``over_budget``），使排查检索质量问题时
    能直接定位到"谁挤掉了它"，而不必逐阶段复现。
    """

    memory_id: str
    stage: str
    reason: str


@dataclass
class ContextMemory:
    memory_id: str
    content: str
    memory_type: str
    relevance_score: float
    utility_score: float
    priority: float
    evidence_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextResult:
    trace_id: str
    query: str
    memories: list[ContextMemory]
    text: str
    token_count: int
    truncated: bool
    conflicts: list[ConflictReference]
    # 逐条过滤原因始终在内存中收集（纯函数不读配置）；
    # 是否随 trace 落库由 engine 侧 explain_enabled 开关决定
    filter_reasons: list[FilterReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # asdict 会递归转换嵌套的 ContextMemory / ConflictReference / FilterReason。
        return asdict(self)


def _format_memory_text(mem: dict[str, Any], index: int) -> str:
    mem_type = mem.get("type", "fact").upper()
    title = mem.get("title", "Untitled")
    content = mem.get("content", "")
    return f"[{index}] [{mem_type}] {title}\n    {content}"


def _build_conflict_warning(conflicts: list[ConflictReference]) -> str:
    if not conflicts:
        return ""
    lines = ["\u26a0 Conflicting memories detected:"]
    for c in conflicts:
        lines.append(f"  - {c.memory_id_a} (v{c.version_a}) vs {c.memory_id_b} (v{c.version_b})")
    return "\n".join(lines)


def _format_context_result(
    budgeted: list[dict[str, Any]],
    conflicts: list[ConflictReference],
    query: str,
    budget: int,
    truncated: bool,
    filter_reasons: list[FilterReason],
) -> ContextResult:
    """将预算裁剪后的记忆格式化为含头部、正文、汇总行的 ContextResult。"""
    conflict_warning = _build_conflict_warning(conflicts)

    if query:
        header = f"# Memory Context for: {query}\n\n"
        header_tokens = estimate_tokens(header)
    else:
        header = ""
        header_tokens = 0

    summary_placeholder = "\n---\n0 memories provided\n"
    summary_reserved = estimate_tokens(summary_placeholder)
    conflict_reserved = estimate_tokens(conflict_warning) + 1 if conflict_warning else 0
    body_budget = budget - header_tokens - summary_reserved - conflict_reserved

    parts: list[str] = []
    context_memories: list[ContextMemory] = []
    body_tokens = 0

    for i, mem in enumerate(budgeted):
        entry = _format_memory_text(mem, i + 1)
        entry_tokens = estimate_tokens(entry)
        separator_tokens = 2 if parts else 0
        needed = entry_tokens + separator_tokens
        if body_tokens + needed > body_budget:
            truncated = True
            # 从当前条目起全部未渲染：记 truncated 供排查"为什么没出现在
            # 上下文里"，reason 统一为 over_budget（降级后仍放不下）
            for remaining in budgeted[i:]:
                filter_reasons.append(
                    FilterReason(
                        memory_id=str(remaining.get("id", "")),
                        stage="truncated",
                        reason="over_budget",
                    )
                )
            break
        if parts:
            parts.append("")
        parts.append(entry)
        body_tokens += needed

        context_memories.append(
            ContextMemory(
                memory_id=str(mem.get("id", "")),
                content=mem.get("content", ""),
                memory_type=mem.get("type", "fact"),
                relevance_score=mem.get("score", 0),
                utility_score=mem.get("utility_score", 0),
                priority=float(i),
                evidence_count=mem.get("evidence_count", 0),
            )
        )

    if conflict_warning and body_tokens + conflict_reserved <= body_budget:
        if parts:
            parts.append("")
        parts.append(conflict_warning)
        body_tokens += conflict_reserved + (2 if len(parts) > 2 else 0)

    body = "\n\n".join(parts)
    summary_line = f"\n---\n{len(context_memories)} memories provided\n"
    total_tokens = header_tokens + body_tokens + estimate_tokens(summary_line)
    text = header + body + summary_line

    return ContextResult(
        trace_id=str(uuid.uuid4()),
        query=query,
        memories=context_memories,
        text=text,
        token_count=total_tokens,
        truncated=truncated,
        conflicts=conflicts,
        filter_reasons=filter_reasons,
    )


def _dedup_stage(
    memories: list[dict[str, Any]],
    reasons: list[FilterReason],
) -> list[dict[str, Any]]:
    """去重阶段：以保留集差集兜底，能定位判重目标时给 duplicate_of 细节。"""
    deduped, details = deduplicate_with_details(memories)
    detail_map = {removed_id: kept_id for removed_id, kept_id in details}
    kept_ids = {m.get("id", "") for m in deduped}
    for mem in memories:
        mid = mem.get("id", "")
        if mid not in kept_ids:
            # 明细覆盖常规路径；差集兜底防御明细遗漏（如缺 id 键的条目）
            target = detail_map.get(mid)
            reasons.append(
                FilterReason(
                    memory_id=mid,
                    stage="dedup",
                    reason=f"duplicate_of:{target}" if target else "duplicate_removed",
                )
            )
    return deduped


def _diversity_stage(
    ranked: list[dict[str, Any]],
    max_per_type: int,
    reasons: list[FilterReason],
) -> list[dict[str, Any]]:
    """多样性阶段：记录同类型超限被跳过的条目，reason 携带超限的类型。"""
    diversified = apply_diversity(
        [(m.get("id", ""), m.get("score", 0), m.get("type", "fact")) for m in ranked],
        top_k=len(ranked),
        max_per_type=max_per_type,
    )
    diversified_ids = {mid for mid, _, _ in diversified}
    filtered = [m for m in ranked if m.get("id", "") in diversified_ids]
    if len(filtered) < len(ranked):
        for mem in ranked:
            if mem.get("id", "") not in diversified_ids:
                reasons.append(
                    FilterReason(
                        memory_id=mem.get("id", ""),
                        stage="diversity",
                        reason=f"max_per_type:{mem.get('type', 'fact')}",
                    )
                )
    return filtered


def _compress_and_fit(
    filtered: list[dict[str, Any]],
    budget: int,
    per_memory_cap_ratio: float,
    reasons: list[FilterReason],
) -> tuple[list[dict[str, Any]], bool]:
    """L1–L5 共享后段：压缩、合并、降级，并记录 merge/compress/degrade 事件。

    L3 合并会丢条目（记 merge 过滤原因）；L1+L2 与 L4 不丢条目但改内容
    （压缩/降级），条目自带 _compressed / _degraded_level 标记——这些事件
    也记入 filter_reasons，让"正文为什么变短"与丢弃一样可解释，stage 名
    区分了"被移除"（dedup/diversity/merge/truncated）与"被改写"。
    """
    # L1+L2：单条记忆上限 + 内容裁剪
    compressed, _ = apply_per_memory_cap(filtered, budget, per_memory_cap_ratio)
    for mem in compressed:
        if mem.get("_compressed"):
            reasons.append(
                FilterReason(
                    memory_id=str(mem.get("id", "")),
                    stage="compress",
                    reason="content_trimmed",
                )
            )

    # L3：相似合并
    merged, _ = merge_similar_memories(compressed, budget)

    before_ids = {m.get("id", "") for m in compressed}
    after_ids = {m.get("id", "") for m in merged}
    explained: set[str] = set()
    for entry in merged:
        merged_ids = entry.get("_merged_ids") or []
        if len(merged_ids) > 1:
            primary_id = str(entry.get("id", ""))
            for mid in merged_ids:
                if mid != primary_id:
                    explained.add(mid)
                    reasons.append(
                        FilterReason(
                            memory_id=mid,
                            stage="merge",
                            reason=f"merged_into:{primary_id}",
                        )
                    )
    # 差集兜底：防御 _merged_ids 与实际差集不一致的边界（如缺 id 键）
    for mid in before_ids - after_ids:
        if mid not in explained:
            reasons.append(FilterReason(memory_id=mid, stage="merge", reason="merged"))

    # L5：优先保留——降级前先分离 constraint/rule 类型
    reserve_types = DEFAULT_RESERVE_TYPES
    reordered, reserved_tokens = reserve_priority(merged, budget)
    reserved_memories = [m for m in reordered if m.get("type", "") in reserve_types]
    normal_memories = [m for m in reordered if m.get("type", "") not in reserve_types]

    # L4：优雅降级（只作用于非保留类型）
    remaining_budget = max(0, budget - reserved_tokens)
    degraded_normal, _ = degrade_to_fit(normal_memories, remaining_budget)
    for mem in degraded_normal:
        level = mem.get("_degraded_level", 0)
        if level:
            reasons.append(
                FilterReason(
                    memory_id=str(mem.get("id", "")),
                    stage="degrade",
                    reason="degraded_to_summary" if level == 1 else "degraded_to_title",
                )
            )
    budgeted = reserved_memories + degraded_normal
    truncated = len(budgeted) < len(merged)

    return budgeted, truncated


def assemble_context(
    memories: list[dict[str, Any]],
    query: str = "",
    intent: str = "unknown",
    max_tokens: int = DEFAULT_BUDGET,
    max_per_type: int = 3,
    per_memory_cap_ratio: float = 0.25,
) -> ContextResult:
    """对检索结果运行完整上下文流水线。

    流水线：去重 -> 冲突检测 -> 优先级排序 -> 多样性
            -> L1+L2 压缩 -> token 预算 -> 格式化

    Args:
        memories: 原始检索结果（记忆字典列表）。
        query: 原始检索查询。
        intent: 查询分析器给出的意图。
        max_tokens: token 预算（500/1000/2000/4000/8000）。
        max_per_type: 多样性过滤中同类型记忆上限。
        per_memory_cap_ratio: 单条记忆占预算的最大比例（L1）。

    Returns:
        组装完成的 ContextResult。
    """
    budget = normalize_budget(max_tokens)

    if not memories:
        return ContextResult(
            trace_id=str(uuid.uuid4()),
            query=query,
            memories=[],
            text="",
            token_count=0,
            truncated=False,
            conflicts=[],
            filter_reasons=[],
        )

    reasons: list[FilterReason] = []
    entry_passed, entry_events = apply_entry_filters(
        memories,
        stale_mode=settings.stale_filter_mode,
        confidence_mode=settings.confidence_floor_mode,
        confidence_floor=settings.confidence_floor,
        relevance_mode=settings.relevance_floor_mode,
        relevance_floor=settings.relevance_floor,
    )
    for mem_id, stage, reason in entry_events:
        reasons.append(FilterReason(memory_id=mem_id, stage=stage, reason=reason))
    deduped = _dedup_stage(entry_passed, reasons)

    conflicts = detect_conflicts(deduped)

    ranked = rank_by_priority(deduped, intent=intent)

    filtered = _diversity_stage(ranked, max_per_type, reasons)

    budgeted, truncated = _compress_and_fit(filtered, budget, per_memory_cap_ratio, reasons)

    return _format_context_result(budgeted, conflicts, query, budget, truncated, reasons)


async def assemble_context_with_embedding(
    memories: list[dict[str, Any]],
    query: str = "",
    intent: str = "unknown",
    max_tokens: int = DEFAULT_BUDGET,
    max_per_type: int = 3,
    embedding_weight: float = 0.3,
    per_memory_cap_ratio: float = 0.25,
) -> ContextResult:
    """运行完整上下文流水线（带 embedding 增强排序）。

    流水线：去重 -> 冲突检测 -> 优先级排序 -> Embedding 重排
            -> 多样性 -> L1+L2 压缩 -> token 预算 -> 格式化

    Args:
        memories: 原始检索结果（记忆字典列表）。
        query: 原始检索查询。
        intent: 查询分析器给出的意图。
        max_tokens: token 预算（500/1000/2000/4000/8000）。
        max_per_type: 多样性过滤中同类型记忆上限。
        embedding_weight: 重排中 embedding 相似度的权重（0.0 到 1.0）。
        per_memory_cap_ratio: 单条记忆占预算的最大比例（L1）。

    Returns:
        组装完成的 ContextResult。
    """
    budget = normalize_budget(max_tokens)

    if not memories:
        return ContextResult(
            trace_id=str(uuid.uuid4()),
            query=query,
            memories=[],
            text="",
            token_count=0,
            truncated=False,
            conflicts=[],
            filter_reasons=[],
        )

    reasons: list[FilterReason] = []
    entry_passed, entry_events = apply_entry_filters(
        memories,
        stale_mode=settings.stale_filter_mode,
        confidence_mode=settings.confidence_floor_mode,
        confidence_floor=settings.confidence_floor,
        relevance_mode=settings.relevance_floor_mode,
        relevance_floor=settings.relevance_floor,
    )
    for mem_id, stage, reason in entry_events:
        reasons.append(FilterReason(memory_id=mem_id, stage=stage, reason=reason))
    deduped = _dedup_stage(entry_passed, reasons)
    conflicts = detect_conflicts(deduped)
    ranked = rank_by_priority(deduped, intent=intent)

    # 有查询词且权重 > 0 时，用 embedding 相似度重排
    if query and embedding_weight > 0 and len(ranked) > 1:
        logger.debug("Applying embedding re-ranking with weight=%s", embedding_weight)
        ranked = await _rerank_with_embedding(ranked, query, embedding_weight)

    filtered = _diversity_stage(ranked, max_per_type, reasons)

    budgeted, truncated = _compress_and_fit(filtered, budget, per_memory_cap_ratio, reasons)

    return _format_context_result(budgeted, conflicts, query, budget, truncated, reasons)


async def _rerank_with_embedding(
    memories: list[dict[str, Any]],
    query: str,
    embedding_weight: float,
) -> list[dict[str, Any]]:
    """用与查询的 embedding 相似度重排记忆。

    最终得分 = 原始分与 embedding 相似度的线性加权组合；
    优先复用已存储的向量，避免重复生成。
    """
    embedding_service = get_embedding_service()

    query_embedding = await embedding_service.generate_embedding(query)
    if query_embedding is None:
        return memories

    # 区分已存向量与需现算向量的记忆，只对缺失者调模型
    stored_embeddings: list[tuple[int, list[float]]] = []
    needs_generation: list[tuple[int, str]] = []

    for i, mem in enumerate(memories):
        stored_emb = mem.get("embedding")
        if stored_emb:
            stored_embeddings.append((i, stored_emb))
        else:
            text = format_memory_for_embedding(mem.get("title", ""), mem.get("content", ""))
            needs_generation.append((i, text))

    generated_embeddings: dict[int, list[float] | None] = {}
    if needs_generation:
        texts = [text for _, text in needs_generation]
        generated = await embedding_service.generate_embeddings_batch(texts)
        for (idx, _), emb in zip(needs_generation, generated):
            generated_embeddings[idx] = emb

    all_embeddings: list[list[float] | None] = [None] * len(memories)
    for idx, emb in stored_embeddings:
        all_embeddings[idx] = emb
    for idx, emb in generated_embeddings.items():
        all_embeddings[idx] = emb

    valid_embeddings = [e for e in all_embeddings if e is not None]
    if not valid_embeddings:
        return memories

    similarities = batch_cosine_similarities(query_embedding, valid_embeddings)

    sim_iter = iter(similarities)
    reranked_memories = []
    for mem, emb in zip(memories, all_embeddings):
        if emb is not None:
            emb_sim = float(next(sim_iter))
        else:
            emb_sim = 0.0

        # 线性加权：默认 embedding_weight=0.3——语义相似度补足检索分的盲区，
        # 又不至于架空关键词/图信号
        original_score = mem.get("score", 0)
        combined_score = (1 - embedding_weight) * original_score + embedding_weight * emb_sim
        logger.debug(
            "Memory '%s': original=%.4f, embedding=%.4f, combined=%.4f",
            mem.get("title", "")[:30],
            original_score,
            emb_sim,
            combined_score,
        )

        reranked_memories.append({**mem, "score": combined_score, "embedding_score": emb_sim})

    reranked_memories.sort(key=lambda m: m["score"], reverse=True)
    return reranked_memories
