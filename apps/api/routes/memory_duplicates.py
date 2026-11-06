"""记忆库内重复检测：找出高度相似却尚未合并的 active 记忆对。

面向「日常写入累积出近似重复」的场景，与写入时的候选查重互补：
那里是候选对全库，这里是全库记忆两两比较，结果只作建议，不自动合并。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db
from packages.domain.config import API_V1_PREFIX, settings
from packages.domain.models import Memory
from packages.memory.duplicate_detection import (
    batch_detect_duplicates,
    precompute_combined,
)
from packages.retrieval.vector_utils import batch_cosine_similarities

# 独立 router：与 memories 包的共享 router 分开，否则同一 router 被
# include 两次会让 /v1/memories 下所有端点重复注册
router = APIRouter(prefix=f"{API_V1_PREFIX}/memories", tags=["memories"])

# 两两比较是 O(n²)：超过这个规模改用候选查重或按工作区收窄，避免请求超时
MAX_SCAN_MEMORIES = 500


@router.get("/duplicates")
async def find_duplicate_memories(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: uuid.UUID | None = Query(None, description="只扫该工作区，缺省为全部"),
    min_similarity: float = Query(0.6, ge=0.0, le=1.0, description="融合相似度下限"),
    limit: int = Query(20, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """返回相似度达到阈值的记忆对，按相似度降序。

    融合标题/正文/关键词/embedding 四路信号，与写入时的候选查重同口径；
    某条记忆缺向量时该路按 0 计，判定退化为纯文本，分数会偏低。
    """
    stmt = select(Memory.id, Memory.title, Memory.type, Memory.content, Memory.embedding).where(
        Memory.status == "active"
    )
    if workspace_id is not None:
        stmt = stmt.where(Memory.workspace_id == workspace_id)
    rows = (await db.execute(stmt)).all()

    if len(rows) > MAX_SCAN_MEMORIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"active 记忆 {len(rows)} 条，超过两两比较上限 {MAX_SCAN_MEMORIES}；"
                "请用 workspace_id 收窄范围"
            ),
        )

    items = [
        {"id": row.id, "title": row.title, "type": row.type, "content": row.content} for row in rows
    ]
    zero_vector = [0.0] * settings.embedding_dimensions
    embeddings = [row.embedding or zero_vector for row in rows]
    if len(items) < 2:
        return {"scanned": len(items), "threshold": min_similarity, "pairs": []}

    precomputed = precompute_combined(items)
    pairs: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        others = [precomputed[j] for j in range(len(items)) if j != i]
        other_positions = [j for j in range(len(items)) if j != i]
        similarities = batch_cosine_similarities(embeddings[i], embeddings)
        verdicts = batch_detect_duplicates(
            item,
            others,
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
    return {
        "scanned": len(items),
        "threshold": min_similarity,
        "total": len(pairs),
        "pairs": pairs[:limit],
    }
