"""cwiki 候选记忆去重流水线。

方案「记得准」改造（MQ-302）：
- 移除长度驱动的 UPDATE/MERGE 判定
- 移除否定词驱动的 CONFLICT 判定
- 关系分类保守化：高相似度仅标记为 similar，不自动决定动作
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.config import settings
from packages.domain.models import CandidateMemory, Memory
from packages.domain.text_utils import signal_tokens as _signal_tokens

logger = logging.getLogger(__name__)

# 版本号形态：v1.2.3 / 1.2.3 / 3.11（数字加点分段）
_VERSION_RE = re.compile(r"v?\d+(?:\.\d+)+", re.IGNORECASE)
# 日期形态：2026-10-15 / 2026/10/15 / 2026年10月15日 / 2026.10.15
_DATE_RE = re.compile(r"\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?")


@dataclass
class SimilarityResult:
    """候选与既有记忆的相似度比较结果。"""

    memory_id: uuid.UUID
    title: str
    content: str
    similarity: float
    source: str
    relation: str


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    try:
        from packages.retrieval.vector_utils import batch_cosine_similarities

        return float(batch_cosine_similarities(vec_a, [vec_b])[0])
    except Exception as e:
        logger.error(f"Cosine similarity calculation failed: {e}")
        return 0.0


def _title_similarity(title_a: str, title_b: str) -> float:
    """标题相似度：信号 token 的 Jaccard 重叠率。"""
    tokens_a = _signal_tokens(title_a)
    tokens_b = _signal_tokens(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _classify_high_similarity(
    candidate_content: str,
    existing_content: str,
    candidate_title: str = "",
    existing_title: str = "",
) -> str:
    """高相似段（> merge 阈值）的关系判定。

    MQ-302 改造：移除长度启发式，仅保留版本/日期强信号。
    无强信号时统一返回 similar（需人工判定 UPDATE/MERGE）。
    """
    if not candidate_content or not existing_content:
        return "similar"

    # 强信号：候选含既没有的新版本号 → 可能是版本更新
    cand_versions = set(_VERSION_RE.findall(candidate_content))
    exist_versions = set(_VERSION_RE.findall(existing_content))
    if cand_versions - exist_versions:
        return "update_candidate"

    # 强信号：候选含既没有的新日期 → 可能是时效刷新
    cand_dates = set(_DATE_RE.findall(candidate_content))
    exist_dates = set(_DATE_RE.findall(existing_content))
    if cand_dates - exist_dates:
        return "update_candidate"

    # 无强信号：标记为 similar，由人工或后续语义分类器判定
    return "similar"


def classify_relation(
    candidate_embedding: list[float] | None,
    existing_embedding: list[float] | None,
    candidate_content: str = "",
    existing_content: str = "",
    candidate_title: str = "",
    existing_title: str = "",
) -> str:
    """判定候选与既有记忆的关系类型。

    MQ-302 改造后：
    - 高相似度（> merge 阈值）：返回 update_candidate 或 similar（不再自动 MERGE/UPDATE）
    - 中相似度（update-merge）：返回 similar
    - 中低相似度（conflict-update）：返回 similar（移除否定词 CONFLICT 判定）
    - 低相似度：返回 new

    关系类型不再直接等于处理动作，由下游策略决定。
    """
    if not candidate_embedding or not existing_embedding:
        return "new"

    similarity = _cosine_similarity(candidate_embedding, existing_embedding)

    if similarity > settings.relation_merge_threshold:
        return _classify_high_similarity(
            candidate_content, existing_content, candidate_title, existing_title
        )
    elif similarity > settings.relation_update_threshold:
        return "similar"
    elif similarity > settings.relation_conflict_threshold:
        # MQ-302：移除否定词 CONFLICT 判定，统一返回 similar
        return "similar"
    else:
        return "new"


async def _keyword_search(
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    query_text: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """用 BM25 倒排索引按关键词搜索记忆与候选。

    候选不在 BM25 索引内，回退到定向 SQL 查询。
    """
    results: list[dict[str, Any]] = []

    try:
        from packages.retrieval.engine import get_retrieval_engine

        engine = get_retrieval_engine()
        index = await engine.get_bm25_index(db_session, workspace_id)

        bm25_results = index.search(query_text, top_k=limit)
        if bm25_results:
            matched_ids = [uuid.UUID(doc_id) for doc_id, _ in bm25_results]
            detail_stmt = select(Memory.id, Memory.title, Memory.content, Memory.embedding).where(
                Memory.id.in_(matched_ids)
            )
            detail_result = await db_session.execute(detail_stmt)
            mem_map = {str(m.id): m for m in detail_result.all()}

            for doc_id, score in bm25_results:
                mem = mem_map.get(doc_id)
                if mem:
                    results.append(
                        {
                            "id": mem.id,
                            "title": mem.title,
                            "content": mem.content,
                            "embedding": mem.embedding,
                            "source": "memory",
                        }
                    )

        search_term = f"%{query_text}%"
        candidate_query = (
            select(
                CandidateMemory.id,
                CandidateMemory.title,
                CandidateMemory.content,
                CandidateMemory.embedding,
            )
            .where(
                CandidateMemory.workspace_id == workspace_id,
                CandidateMemory.status == "pending_review",
                (CandidateMemory.title.ilike(search_term))
                | (CandidateMemory.content.ilike(search_term)),
            )
            .limit(limit)
        )
        candidate_result = await db_session.execute(candidate_query)
        for cand in candidate_result.all():
            results.append(
                {
                    "id": cand.id,
                    "title": cand.title,
                    "content": cand.content,
                    "embedding": cand.embedding,
                    "source": "candidate",
                }
            )

    except Exception as e:
        logger.error(f"Keyword search failed: {e}")

    return results


async def _vector_search(
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    query_embedding: list[float],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """用检索引擎的缓存向量索引搜索记忆。"""
    results: list[dict[str, Any]] = []

    if not query_embedding:
        return results

    try:
        from packages.retrieval.engine import get_retrieval_engine

        engine = get_retrieval_engine()
        vector_results = await engine.vector_search(
            db_session, query_embedding, workspace_id, top_k=limit
        )

        if not vector_results:
            return results

        matched_ids = [uuid.UUID(doc_id) for doc_id, _ in vector_results]
        detail_stmt = select(Memory.id, Memory.title, Memory.content, Memory.embedding).where(
            Memory.id.in_(matched_ids)
        )
        detail_result = await db_session.execute(detail_stmt)
        mem_map = {str(m.id): m for m in detail_result.all()}

        for doc_id, sim in vector_results:
            mem = mem_map.get(doc_id)
            if mem:
                results.append(
                    {
                        "id": mem.id,
                        "title": mem.title,
                        "content": mem.content,
                        "embedding": mem.embedding,
                        "source": "memory",
                        "similarity": sim,
                    }
                )

    except Exception as e:
        logger.error(f"Vector search failed: {e}")

    return results


async def find_similar(
    candidate: dict[str, Any],
    db_session: AsyncSession,
    workspace_id: uuid.UUID,
    top_k: int | None = None,
) -> list[SimilarityResult]:
    """用混合检索为候选查找相似记忆。"""
    if top_k is None:
        top_k = settings.dedup_top_k
    title = candidate.get("title", "")
    content = candidate.get("content", "")
    candidate_embedding = candidate.get("embedding")

    keyword_results = await _keyword_search(db_session, workspace_id, title, limit=top_k)
    vector_results = await _vector_search(
        db_session, workspace_id, candidate_embedding or [], limit=top_k
    )

    seen_ids: set[uuid.UUID] = set()
    merged: list[dict[str, Any]] = []

    for result in keyword_results + vector_results:
        result_id = result["id"]
        if result_id in seen_ids:
            continue
        seen_ids.add(result_id)
        merged.append(result)

    similarity_results: list[SimilarityResult] = []

    for result in merged:
        existing_embedding = result.get("embedding")

        if existing_embedding and candidate_embedding:
            similarity = _cosine_similarity(candidate_embedding, existing_embedding)
        else:
            title_overlap = _text_overlap(title, result.get("title", ""))
            content_overlap = _text_overlap(content, result.get("content", ""))
            similarity = 0.6 * content_overlap + 0.4 * title_overlap

        relation = classify_relation(
            candidate_embedding,
            existing_embedding,
            content,
            result.get("content", ""),
            title,
            result.get("title", ""),
        )

        similarity_results.append(
            SimilarityResult(
                memory_id=result["id"],
                title=result.get("title", ""),
                content=result.get("content", ""),
                similarity=similarity,
                source=result.get("source", "unknown"),
                relation=relation,
            )
        )

    similarity_results.sort(key=lambda x: x.similarity, reverse=True)

    return similarity_results[:top_k]


def _text_overlap(text_a: str, text_b: str) -> float:
    """计算两段文本的词重叠率。"""
    if not text_a or not text_b:
        return 0.0

    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b

    return len(intersection) / len(union) if union else 0.0
