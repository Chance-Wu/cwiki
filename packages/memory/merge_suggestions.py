"""记忆合并建议——自动发现相似记忆对。

扫描 active 记忆，找出相似度较高、可能适合合并的记忆对。
支持多种相似度策略：jaccard（词面）、embedding（语义）、hybrid（加权融合）。

性能：token 与向量只预计算一次，成对比较复用预计算结果，
避免 O(N²) 对每对重新分词。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.config import settings
from packages.domain.models import Memory
from packages.memory.duplicate_detection import (
    batch_detect_duplicates,
    precompute_combined,
)
from packages.memory.similarity import (
    HybridWeights,
    jaccard_from_sets,
    tokenize,
)
from packages.retrieval.vector_utils import batch_cosine_similarities

logger = logging.getLogger(__name__)

# 默认阈值：建议最终由人工裁决，阈值取高以压低误报（可由配置覆盖）
DEFAULT_SIMILARITY_THRESHOLD = 0.85


def _state_path() -> Path:
    root = Path(os.environ.get("CWIKI_STATE_DIR", "~/.cwiki/state")).expanduser()
    return root / "consolidation_dismissed.json"


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted((str(a), str(b))))


def load_dismissed(workspace_id: str) -> set[str]:
    """读取该工作区被忽略的合并建议对（无序对键）。"""
    path = _state_path()
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    pairs = workspaces.get(workspace_id) if isinstance(workspaces, dict) else None
    return {str(key) for key in pairs} if isinstance(pairs, list) else set()


def dismiss_pair(workspace_id: str, source_id: str, target_id: str) -> None:
    """记录一条被忽略的合并建议；只增不删，避免重复提示。"""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
    workspaces = data.setdefault("workspaces", {})
    pairs = workspaces.setdefault(workspace_id, [])
    key = _pair_key(source_id, target_id)
    if key not in pairs:
        pairs.append(key)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass
class MergeSuggestion:
    memory_id_a: str
    memory_id_b: str
    title_a: str
    title_b: str
    similarity: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id_a": self.memory_id_a,
            "memory_id_b": self.memory_id_b,
            "title_a": self.title_a,
            "title_b": self.title_b,
            "similarity": round(self.similarity, 4),
            "reason": self.reason,
        }


def _embedding_scores(items: list[dict[str, Any]], i: int) -> list[float]:
    """返回 items[i] 与 i 之后各项的 embedding 余弦相似度（缺失向量记 0）。"""
    base = items[i].get("embedding")
    others = [item.get("embedding") for item in items[i + 1 :]]
    scores = [0.0] * len(others)
    if not base:
        return scores
    valid = [(idx, emb) for idx, emb in enumerate(others) if emb]
    if not valid:
        return scores
    sims = batch_cosine_similarities(base, [emb for _, emb in valid])
    for (idx, _), sim in zip(valid, sims):
        scores[idx] = float(sim)
    return scores


async def find_merge_candidates(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    similarity_threshold: float | None = None,
    limit: int = 20,
    strategy: str | None = None,
) -> list[MergeSuggestion]:
    """找出相似度较高的 active 记忆对。

    使用统一相似度计算策略（默认取 memory.similarity_strategy）。
    为控制开销，只扫描最近更新的 500 条记忆。

    Args:
        db: 数据库会话
        workspace_id: 要扫描的 workspace
        similarity_threshold: 最小相似度；省略时用 performance.merge_suggestions_threshold
        limit: 返回建议的最大数量
        strategy: jaccard/embedding/hybrid；省略时取配置

    Returns:
        MergeSuggestion 列表，按相似度降序排列
    """
    # 只扫最近更新的 500 条，控制两两比较的开销
    stmt = (
        select(
            Memory.id,
            Memory.title,
            Memory.content,
            Memory.embedding,
        )
        .where(
            Memory.workspace_id == workspace_id,
            Memory.status == "active",
        )
        .order_by(Memory.updated_at.desc())
        .limit(500)
    )
    result = await db.execute(stmt)
    memories = result.all()

    if len(memories) < 2:
        return []

    threshold = (
        settings.merge_suggestions_threshold
        if similarity_threshold is None
        else similarity_threshold
    )
    resolved_strategy = strategy or settings.similarity_strategy
    weights = HybridWeights(**settings.similarity_hybrid_weights)
    dismissed = load_dismissed(str(workspace_id))
    memory_items = [
        {"id": str(mem_id), "title": title, "content": content, "embedding": emb}
        for mem_id, title, content, emb in memories
    ]

    # 一次性预计算：hybrid 用 n-gram/token 集合，jaccard 用统一分词
    precomputed = precompute_combined(memory_items)
    jaccard_sets = (
        [tokenize(f"{item['title']} {item['content']}") for item in memory_items]
        if resolved_strategy == "jaccard"
        else []
    )

    suggestions: list[MergeSuggestion] = []
    n = len(memory_items)
    for i in range(n - 1):
        if resolved_strategy == "jaccard":
            scores = [jaccard_from_sets(jaccard_sets[i], jaccard_sets[j]) for j in range(i + 1, n)]
        elif resolved_strategy == "embedding":
            scores = _embedding_scores(memory_items, i)
        else:
            verdicts = batch_detect_duplicates(
                memory_items[i],
                precomputed[i + 1 :],
                embedding_similarities=_embedding_scores(memory_items, i),
                weights=weights,
            )
            scores = [verdict.combined_score for verdict in verdicts]

        for offset, score in enumerate(scores):
            if score < threshold:
                continue
            j = i + 1 + offset
            if _pair_key(memory_items[i]["id"], memory_items[j]["id"]) in dismissed:
                continue
            suggestions.append(
                MergeSuggestion(
                    memory_id_a=memory_items[i]["id"],
                    memory_id_b=memory_items[j]["id"],
                    title_a=memory_items[i]["title"],
                    title_b=memory_items[j]["title"],
                    similarity=float(score),
                    reason=f"Similarity ({score:.2%}, strategy={resolved_strategy})",
                )
            )

    suggestions.sort(key=lambda s: s.similarity, reverse=True)
    return suggestions[:limit]


async def generate_merge_suggestions(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """为 workspace 生成合并建议。

    find_merge_candidates 的便捷封装，返回字典形式。
    """
    suggestions = await find_merge_candidates(
        db, workspace_id, similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD, limit=limit
    )
    return [s.to_dict() for s in suggestions]
