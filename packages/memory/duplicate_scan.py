"""库内记忆两两查重（供 API 端点与周报复用）。

与写入时的候选查重互补：那里是「候选 × 全库」，这里是「全库 × 全库」，
用于发现日常写入逐渐累积出的近似重复。只产出判定，不改动任何记忆。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.config import settings
from packages.domain.models import Memory
from packages.memory.duplicate_detection import (
    batch_detect_duplicates,
    precompute_combined,
)
from packages.retrieval.vector_utils import batch_cosine_similarities

# 两两比较是 O(n²)：超过这个规模就截断（按 updated_at 取最新的），
# 由调用方决定是全量拒绝还是接受截断结果
DEFAULT_MAX_SCAN = 500


async def find_duplicate_pairs(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID | None = None,
    min_similarity: float = 0.6,
    limit: int = 20,
    max_scan: int = DEFAULT_MAX_SCAN,
) -> dict[str, Any]:
    """扫描 active 记忆，返回相似度 ≥ ``min_similarity`` 的记忆对。

    融合标题/正文/关键词/embedding 四路信号，与写入时判定同口径；
    缺向量的记忆该路按 0 计，分数退化为纯文本。``truncated=True`` 表示
    候选超出 ``max_scan`` 被截断（只扫最近更新的那批）。
    """
    stmt = (
        select(Memory.id, Memory.title, Memory.type, Memory.content, Memory.embedding)
        .where(Memory.status == "active")
        .order_by(Memory.updated_at.desc(), Memory.id.asc())
        .limit(max_scan + 1)
    )
    if workspace_id is not None:
        stmt = stmt.where(Memory.workspace_id == workspace_id)
    rows = (await db.execute(stmt)).all()
    truncated = len(rows) > max_scan
    rows = rows[:max_scan]

    result: dict[str, Any] = {
        "scanned": len(rows),
        "truncated": truncated,
        "threshold": min_similarity,
        "total": 0,
        "pairs": [],
    }
    if len(rows) < 2:
        return result

    items = [
        {"id": row.id, "title": row.title, "type": row.type, "content": row.content} for row in rows
    ]
    zero_vector = [0.0] * settings.embedding_dimensions
    embeddings = [row.embedding or zero_vector for row in rows]
    precomputed = precompute_combined(items)

    pairs: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        other_positions = [j for j in range(len(items)) if j != i]
        similarities = batch_cosine_similarities(embeddings[i], embeddings)
        verdicts = batch_detect_duplicates(
            item,
            [precomputed[j] for j in other_positions],
            embedding_similarities=[float(similarities[j]) for j in other_positions],
        )
        for verdict, j in zip(verdicts, other_positions, strict=True):
            # 上三角：每对只记一次
            if j <= i or verdict.combined_score < min_similarity:
                continue
            pairs.append(
                {
                    "left": {"id": str(item["id"]), "title": item["title"], "type": item["type"]},
                    "right": {
                        "id": str(items[j]["id"]),
                        "title": items[j]["title"],
                        "type": items[j]["type"],
                    },
                    "similarity": round(verdict.combined_score, 4),
                    "classification": verdict.classification,
                    "title_similarity": round(verdict.title_similarity, 4),
                    "content_similarity": round(verdict.content_similarity, 4),
                    "embedding_similarity": round(verdict.embedding_similarity, 4),
                }
            )

    pairs.sort(key=lambda pair: (-pair["similarity"], pair["left"]["id"], pair["right"]["id"]))
    result["total"] = len(pairs)
    result["pairs"] = pairs[:limit]
    return result
