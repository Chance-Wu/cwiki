"""L1–L5 上下文压缩。

借鉴 Claude Code 的五层上下文压缩体系：
- L1: 单条上限 —— 单条记忆 ≤ 预算 × 比例
- L2: 内容裁剪 —— 按段落感知裁剪
- L3: 相似合并 —— 聚类相似记忆并合并为一条
- L4: 优雅降级 —— 全文 → 摘要 → 仅标题 → 丢弃
- L5: 优先保留 —— constraint/rule 类型豁免降级
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

from packages.retrieval.context.token_counter import estimate_tokens

logger = logging.getLogger(__name__)

# 单条记忆最多占预算 25%，防止长记忆挤占名额、牺牲结果多样性
DEFAULT_PER_MEMORY_CAP_RATIO = 0.25
# 余弦相似度 ≥ 0.85 才合并：过高漏合并、过低会误伤语义相近但不同的记忆
DEFAULT_MERGE_SIMILARITY_THRESHOLD = 0.85
# 内容 token 超过预算 60% 才触发 L3 合并，预算宽裕时不做有损合并
DEFAULT_MERGE_TRIGGER_RATIO = 0.6


def per_memory_cap(budget: int, ratio: float = DEFAULT_PER_MEMORY_CAP_RATIO) -> int:
    """计算单条记忆允许的最大 token 数。

    Args:
        budget: 总 token 预算。
        ratio: 单条记忆占预算的比例（默认 0.25）。

    Returns:
        单条记忆的 token 上限。
    """
    return max(50, int(budget * ratio))


def trim_content_to_cap(content: str, cap_tokens: int) -> str:
    """将记忆内容裁剪到 token 上限内。

    策略：
    1. 按段落切分（\\n\\n）。
    2. 始终保留首段（核心结论 / 规则）。
    3. 中间段落在预算内贪心追加。
    4. 始终保留末段（例外 / 补充说明）。
    5. 若首段本身超限，退化为句子级截断。

    Args:
        content: 原始记忆内容。
        cap_tokens: 内容的 token 上限。

    Returns:
        裁剪后的内容。
    """
    if not content or estimate_tokens(content) <= cap_tokens:
        return content

    paragraphs = content.split("\n\n")

    if len(paragraphs) == 1:
        return _truncate_first_paragraph(paragraphs[0], cap_tokens)

    first, last = paragraphs[0], paragraphs[-1]
    middle = paragraphs[1:-1]

    first_tokens = estimate_tokens(first)
    last_tokens = estimate_tokens(last)
    separator_tokens = 3

    if first_tokens + last_tokens + separator_tokens * 2 > cap_tokens:
        return _truncate_first_paragraph(first, cap_tokens)

    result = [first]
    used = first_tokens

    for para in middle:
        para_tokens = estimate_tokens(para)
        needed = para_tokens + separator_tokens
        if used + needed > cap_tokens:
            break
        result.append(para)
        used += needed

    if last not in result:
        if used + last_tokens + separator_tokens <= cap_tokens:
            result.append(last)
        else:
            return _truncate_first_paragraph(first, cap_tokens)

    return "\n\n".join(result) + "\n\n... [已压缩]"


def _truncate_first_paragraph(text: str, cap_tokens: int) -> str:
    """兜底：按句子边界截断单个段落。"""
    for sep in (". ", "。", "！", "!", "？", "?", "；", ";"):
        idx = text.find(sep)
        if idx > 0:
            candidate = text[: idx + len(sep)]
            if estimate_tokens(candidate) <= cap_tokens:
                return candidate.rstrip() + "..."

    for end in range(len(text), 0, -1):
        if estimate_tokens(text[:end]) <= cap_tokens:
            return text[:end].rstrip() + "..."

    return text[: max(20, len(text) // 4)].rstrip() + "..."


def apply_per_memory_cap(
    memories: list[dict[str, Any]],
    budget: int,
    ratio: float = DEFAULT_PER_MEMORY_CAP_RATIO,
) -> tuple[list[dict[str, Any]], int]:
    """对全部记忆应用 L1+L2 压缩。

    Args:
        memories: 记忆字典列表。
        budget: 总 token 预算。
        ratio: 单条记忆上限比例。

    Returns:
        (压缩后记忆, 被裁剪条数) 元组。
    """
    cap = per_memory_cap(budget, ratio)
    result: list[dict[str, Any]] = []
    trimmed = 0

    for mem in memories:
        content = mem.get("content", "")
        if estimate_tokens(content) > cap:
            new_content = trim_content_to_cap(content, cap)
            result.append({**mem, "content": new_content, "_compressed": True})
            trimmed += 1
            logger.debug(
                "Compressed memory '%s': %d → %d tokens (cap=%d)",
                mem.get("title", "")[:30],
                estimate_tokens(content),
                estimate_tokens(new_content),
                cap,
            )
        else:
            result.append(mem)

    if trimmed:
        logger.info(
            "L1+L2 compression: trimmed %d/%d memories (cap=%d tokens)", trimmed, len(memories), cap
        )

    return result, trimmed


# ---------------------------------------------------------------------------
# L3 —— 相似合并
# ---------------------------------------------------------------------------


def _content_hash(text: str) -> str:
    """短内容哈希：无 embedding 时用作分组的兜底键。"""
    return hashlib.md5(text.encode()).hexdigest()[:8]


def _group_by_embedding_similarity(
    memories: list[dict[str, Any]],
    threshold: float,
) -> list[list[int]]:
    """按 embedding 余弦相似度做贪心聚类。

    对每条记忆，与每个已有簇的首成员比较：余弦 ≥ 阈值则加入该簇，
    否则自成一簇。只与簇首（而非簇内全部成员）比较是有意的近似：
    簇首即代表记忆，把比较代价从 O(n²) 降到 O(n×簇数)，
    且保证簇内围绕代表记忆相似。

    无 embedding 的记忆改按内容哈希分组。
    """
    if not memories:
        return []

    raw_embeddings = [m.get("embedding") for m in memories]

    # 预先一次性转为 numpy 数组，避免 _cosine_sim 内反复转换分配
    np_embeddings: list[np.ndarray | None] = []
    for emb in raw_embeddings:
        if emb is None:
            np_embeddings.append(None)
        else:
            np_embeddings.append(np.array(emb, dtype=np.float32))

    emb_clusters: list[list[int]] = []
    no_emb_indices: list[int] = []

    for i, mem in enumerate(memories):
        emb = np_embeddings[i]
        if emb is None:
            no_emb_indices.append(i)
            continue

        placed = False
        for cluster in emb_clusters:
            rep = np_embeddings[cluster[0]]
            if rep is None:
                continue
            sim = _cosine_sim_np(emb, rep)
            if sim >= threshold:
                cluster.append(i)
                placed = True
                break
        if not placed:
            emb_clusters.append([i])

    hash_clusters: dict[str, list[int]] = {}
    for i in no_emb_indices:
        h = _content_hash(memories[i].get("content", ""))
        hash_clusters.setdefault(h, []).append(i)

    all_clusters = emb_clusters + list(hash_clusters.values())
    return all_clusters


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度。"""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _cosine_sim_np(a: np.ndarray, b: np.ndarray) -> float:
    """两个已预转换 numpy 向量的余弦相似度。"""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _merge_memory_group(group_indices: list[int], memories: list[dict[str, Any]]) -> dict[str, Any]:
    """将一组相似记忆合并为单条。

    保留组内得分最高者的标题/类型/正文，
    并追加说明合并了多少条相关记忆。
    """
    sorted_indices = sorted(group_indices, key=lambda i: memories[i].get("score", 0), reverse=True)
    primary = memories[sorted_indices[0]]
    count = len(group_indices)

    if count == 1:
        return primary

    merged_content = primary.get("content", "")
    suffix = f"\n\n〔等 {count} 条相关记忆已合并〕"
    merged_ids = [str(memories[i].get("id", "")) for i in sorted_indices]

    return {
        **primary,
        "content": merged_content + suffix,
        "_merged_count": count,
        "_merged_ids": merged_ids,
    }


def merge_similar_memories(
    memories: list[dict[str, Any]],
    budget: int,
    threshold: float = DEFAULT_MERGE_SIMILARITY_THRESHOLD,
    trigger_ratio: float = DEFAULT_MERGE_TRIGGER_RATIO,
) -> tuple[list[dict[str, Any]], int]:
    """L3：token 占用过高时合并相似记忆。

    仅当内容总 token 超过 trigger_ratio × budget 时才激活。
    按 embedding 余弦相似度 ≥ 阈值分组，每组合并为一条代表条目。

    Args:
        memories: 记忆字典列表（应已完成 L1+L2 压缩）。
        budget: 总 token 预算。
        threshold: 分组的余弦相似度阈值。
        trigger_ratio: 占用超过 ratio × budget 时才触发合并。

    Returns:
        (合并后记忆, 被移除的重复条数) 元组。
    """
    if not memories:
        return memories, 0

    total_tokens = sum(estimate_tokens(m.get("content", "")) for m in memories)
    trigger_threshold = int(budget * trigger_ratio)

    if total_tokens <= trigger_threshold:
        logger.debug(
            "L3 skipped: %d tokens ≤ trigger threshold %d", total_tokens, trigger_threshold
        )
        return memories, 0

    clusters = _group_by_embedding_similarity(memories, threshold)

    merged_count = 0
    assigned: set[int] = set()
    entries: list[tuple[int, dict[str, Any]]] = []

    for cluster in clusters:
        for idx in cluster:
            assigned.add(idx)
        merged = _merge_memory_group(cluster, memories)
        entries.append((min(cluster), merged))
        merged_count += len(cluster) - 1

    for i in range(len(memories)):
        if i not in assigned:
            entries.append((i, memories[i]))

    entries.sort(key=lambda t: t[0])
    result = [e for _, e in entries]

    if merged_count:
        logger.info(
            "L3 compression: merged %d similar memories into %d entries",
            merged_count,
            len(memories) - merged_count,
        )

    return result, merged_count


# ---------------------------------------------------------------------------
# L4 —— 优雅降级
# ---------------------------------------------------------------------------


def _extract_summary(content: str) -> str:
    """提取首句作为摘要。"""
    if not content:
        return ""
    for sep in (". ", "。", "！", "!", "？", "?", "；", ";", "\n"):
        idx = content.find(sep)
        if idx > 0:
            return content[: idx + len(sep)].rstrip()
    return content


def degrade_to_fit(
    memories: list[dict[str, Any]],
    budget: int,
) -> tuple[list[dict[str, Any]], int]:
    """L4：逐步降级记忆以适配预算。

    降级档位（从最低优先级记忆开始）：
    1. 全文（不变）
    2. 摘要 —— 正文首句
    3. 仅标题 —— 正文清空、标题保留
    4. 完全丢弃

    假定列表已按优先级（高在前）排序，
    低优先级记忆先于高优先级被降级。

    Args:
        memories: 按优先级排序的记忆字典列表。
        budget: 正文总 token 预算。

    Returns:
        (降级后记忆, 被降级/丢弃条数) 元组。
    """
    if not memories:
        return memories, 0

    total = sum(estimate_tokens(m.get("content", "")) for m in memories)
    if total <= budget:
        return memories, 0

    result: list[dict[str, Any]] = [dict(m) for m in memories]
    degraded_count = 0

    for i in range(len(result) - 1, -1, -1):
        if total <= budget:
            break

        mem = result[i]
        content = mem.get("content", "")
        content_tokens = estimate_tokens(content)

        if mem.get("_degraded_level", 0) == 0 and content_tokens > 0:
            summary = _extract_summary(content)
            summary_tokens = estimate_tokens(summary)
            saved = content_tokens - summary_tokens
            if saved > 0:
                result[i] = {**mem, "content": summary, "_degraded_level": 1}
                total -= saved
                degraded_count += 1
                continue

        if mem.get("_degraded_level", 0) <= 1 and content_tokens > 0:
            saved = content_tokens
            result[i] = {**mem, "content": "", "_degraded_level": 2}
            total -= saved
            degraded_count += 1
            continue

    if degraded_count:
        logger.info(
            "L4 degradation: degraded/dropped %d memories to fit budget %d",
            degraded_count,
            budget,
        )

    return result, degraded_count


# ---------------------------------------------------------------------------
# L5 —— 优先保留
# ---------------------------------------------------------------------------

DEFAULT_RESERVE_TYPES: frozenset[str] = frozenset({"constraint", "rule"})


def reserve_priority(
    memories: list[dict[str, Any]],
    budget: int,
    reserve_types: frozenset[str] = DEFAULT_RESERVE_TYPES,
) -> tuple[list[dict[str, Any]], int]:
    """L5：为关键类型记忆预留预算。

    类型属于 reserve_types（默认 constraint、rule）的记忆始终以全文保留；
    其 token 开销从预算中扣除，剩余预算留给其他记忆。

    必须在 L4 降级之前调用，使保留型记忆不进入降级池——
    约束/规则被截断可能误导 Agent 行为，宁可挤占其他记忆的空间。

    Args:
        memories: 按优先级排序的记忆字典列表。
        budget: 总 token 预算。
        reserve_types: 始终保留的记忆类型。

    Returns:
        (保留型排前的重排结果, 保留型 token 总数) 元组。
    """
    if not memories:
        return memories, 0

    reserved: list[tuple[int, dict[str, Any]]] = []
    normal: list[tuple[int, dict[str, Any]]] = []

    for i, mem in enumerate(memories):
        if mem.get("type", "") in reserve_types:
            reserved.append((i, mem))
        else:
            normal.append((i, mem))

    if not reserved:
        return memories, 0

    reserved_tokens = sum(estimate_tokens(m.get("content", "")) for _, m in reserved)

    result = [m for _, m in reserved] + [m for _, m in normal]

    if reserved_tokens:
        logger.info(
            "L5 reserve: %d reserved memories (%s) using %d/%d tokens",
            len(reserved),
            ", ".join(reserve_types),
            reserved_tokens,
            budget,
        )

    return result, reserved_tokens
