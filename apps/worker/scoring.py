"""cwiki 候选记忆质量评分。

方案「记得准」改造（MQ-102）：
- novelty 降级为排序信号，不再参与 value_score 计算
- 移除「discard」状态，改为 low_priority / needs_enrichment（可恢复）
- 缺失评分使用 null 语义（不默认 0.5），由调用方显式处理
"""

import logging
from typing import Any

import numpy as np

from packages.domain.config import settings

logger = logging.getLogger(__name__)


def calculate_value_score(candidate: dict[str, Any]) -> float | None:
    """计算候选记忆的综合价值分。

    改造后公式（novelty 降级为排序信号）：
    value_score = 0.25 * reusability + 0.20 * stability
                + 0.20 * confidence + 0.20 * importance + 0.15 * evidence_strength

    缺失维度返回 None 而非 0.5，由调用方决定是否跳过评分。
    """
    reusability = candidate.get("reusability")
    stability = candidate.get("stability")
    confidence = candidate.get("confidence")
    importance = candidate.get("importance")
    evidence_strength = candidate.get("evidence_strength")

    # 关键维度缺失时返回 None，标记为 needs_enrichment
    if any(v is None for v in [reusability, stability, confidence, importance, evidence_strength]):
        return None

    assert reusability is not None
    assert stability is not None
    assert confidence is not None
    assert importance is not None
    assert evidence_strength is not None
    reusability = max(0.0, min(1.0, float(reusability)))
    stability = max(0.0, min(1.0, float(stability)))
    confidence = max(0.0, min(1.0, float(confidence)))
    importance = max(0.0, min(1.0, float(importance)))
    evidence_strength = max(0.0, min(1.0, float(evidence_strength)))

    score = (
        0.25 * reusability
        + 0.20 * stability
        + 0.20 * confidence
        + 0.20 * importance
        + 0.15 * evidence_strength
    )

    return max(0.0, min(1.0, score))


def classify_priority(score: float | None) -> str:
    """按价值分把候选划分到优先级档位。

    改造后（MQ-102）：
    - 移除 discard 状态，改为 needs_enrichment（可恢复）
    - score < 0.35: needs_enrichment（低分但可补全）
    - 0.35 <= score < 0.65: low_priority
    - 0.65 <= score < 0.85: normal
    - score >= 0.85: high_value
    - score is None: needs_enrichment（关键维度缺失）
    """
    if score is None:
        return "needs_enrichment"
    if score < settings.priority_discard_threshold:
        return "needs_enrichment"
    elif score < settings.priority_low_threshold:
        return "low_priority"
    elif score < settings.priority_high_threshold:
        return "normal"
    else:
        return "high_value"


def calculate_novelty(
    candidate_embedding: list[float],
    existing_embeddings: list[list[float]],
) -> tuple[float, int | None]:
    """与既有记忆对比计算新颖度。

    novelty = 1.0 - 与既有记忆的最大余弦相似度；
    无既有记忆时 novelty 为 1.0。

    Args:
        candidate_embedding: 候选的向量。
        existing_embeddings: 已批准记忆的向量列表。

    Returns:
        (0.0-1.0 的新颖度, 最相似向量的下标或 None)。
    """
    if not existing_embeddings:
        return 1.0, None

    if not candidate_embedding:
        return 0.5, None

    try:
        candidate_vec = np.array(candidate_embedding, dtype=np.float32)
        existing_matrix = np.array(existing_embeddings, dtype=np.float32)

        candidate_norm = np.linalg.norm(candidate_vec)
        if candidate_norm == 0:
            return 0.5, None

        existing_norms = np.linalg.norm(existing_matrix, axis=1)
        existing_norms = np.where(existing_norms == 0, 1.0, existing_norms)

        similarities = np.dot(existing_matrix, candidate_vec) / (existing_norms * candidate_norm)
        max_idx = int(np.argmax(similarities))
        max_similarity = float(similarities[max_idx])

        novelty = 1.0 - max_similarity
        return max(0.0, min(1.0, novelty)), max_idx

    except Exception as e:
        # 向量计算失败时给中性分，不阻断候选入库
        logger.error(f"Failed to calculate novelty: {e}")
        return 0.5, None


def score_candidate(
    candidate: dict[str, Any],
    existing_embeddings: list[list[float]] | None = None,
) -> dict[str, Any]:
    """为候选记忆打分并划分优先级。

    改造后（MQ-102）：
    - novelty 仅作为排序信号，不参与 value_score
    - value_score 为 None 时 priority = needs_enrichment
    - 保留 novelty 供下游排序使用
    """
    result = dict(candidate)

    candidate_embedding = candidate.get("embedding")
    similar_index: int | None = None
    if candidate_embedding and existing_embeddings:
        novelty, similar_index = calculate_novelty(candidate_embedding, existing_embeddings)
    else:
        novelty = float(candidate["novelty"]) if candidate.get("novelty") is not None else 0.5

    result["novelty"] = novelty
    result["similar_index"] = similar_index

    value_score = calculate_value_score(result)
    result["value_score"] = value_score
    result["priority"] = classify_priority(value_score)

    logger.info(
        f"Scored candidate '{candidate.get('title', 'unknown')}': "
        f"novelty={novelty:.2f}, "
        f"value_score={value_score}, "
        f"priority={result['priority']}"
    )

    return result
