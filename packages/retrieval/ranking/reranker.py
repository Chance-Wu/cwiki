"""重排器——相关性主导，元数据只在带内微调（PRD 第 19 节）。

排序模型分两组：

- 相关性组：RRF 名次（按理论满分锚定）、向量余弦、BM25 池内相对分、
  意图-类型匹配（以中性 0.5 为中心）与关键词命中。组内按权重归一。
- 元数据组：置信度、重要度、新鲜度、使用频率。组内按权重归一后，
  只以 ``band`` 为上限参与最终分，不能跨带压过相关性。

最终分 = (1 - band) × relevance + band × metadata。
band 默认 0.05：元数据最多翻转相关性差 ≤band 的候选，相关性主导排序。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from packages.domain.config import settings
from packages.retrieval.ranking.constants import RRF_K

logger = logging.getLogger(__name__)


@dataclass
class RerankInput:
    memory_id: str
    title: str
    content: str
    memory_type: str
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    confidence: float = 0.5
    importance: float = 0.5
    freshness: float = 0.5
    usage_score: float = 0.0


# 相关性组：rrf / semantic / bm25 / intent；元数据组：confidence / importance /
# freshness / usage。两组各自归一，key_term_bonus 为相关性组内的加性奖励，
# band 为元数据组的总影响力上限。默认值可在 config.yaml 覆盖。
@dataclass
class RerankerWeights:
    rrf: float = 0.40
    semantic: float = 0.30
    confidence: float = 0.35
    importance: float = 0.30
    freshness: float = 0.20
    usage: float = 0.15
    intent: float = 0.15
    bm25: float = 0.30
    band: float = 0.05
    key_term_bonus: float = 0.08

    @staticmethod
    def from_settings() -> RerankerWeights:
        return RerankerWeights(
            rrf=settings.reranker_rrf_weight,
            semantic=settings.reranker_semantic_weight,
            confidence=settings.reranker_confidence_weight,
            importance=settings.reranker_importance_weight,
            freshness=settings.reranker_freshness_weight,
            usage=settings.reranker_usage_weight,
            intent=settings.reranker_intent_weight,
            bm25=settings.reranker_bm25_weight,
            band=settings.reranker_relevance_band,
            key_term_bonus=settings.reranker_key_term_bonus,
        )

    @staticmethod
    def for_intent(intent: str) -> RerankerWeights:
        """按意图缩放元数据组并组内归一；相关性组不受意图影响。"""
        base = RerankerWeights.from_settings()
        adjustments = _INTENT_META_ADJUSTMENTS.get(intent)
        if not adjustments:
            return base
        w = replace(
            base,
            confidence=base.confidence * adjustments.get("confidence", 1.0),
            importance=base.importance * adjustments.get("importance", 1.0),
            freshness=base.freshness * adjustments.get("freshness", 1.0),
            usage=base.usage * adjustments.get("usage", 1.0),
        )
        total = w.confidence + w.importance + w.freshness + w.usage
        if total > 0:
            w.confidence /= total
            w.importance /= total
            w.freshness /= total
            w.usage /= total
        return w


_INTENT_META_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "fact": {"confidence": 1.5, "importance": 1.2, "freshness": 0.8, "usage": 1.0},
    "procedure": {"confidence": 1.0, "importance": 1.0, "freshness": 1.5, "usage": 1.3},
    "lesson": {"confidence": 1.3, "importance": 1.0, "freshness": 1.2, "usage": 1.2},
    "project_rule": {"confidence": 1.4, "importance": 1.3, "freshness": 0.7, "usage": 0.8},
    "constraint": {"confidence": 1.3, "importance": 1.2, "freshness": 0.8, "usage": 0.8},
    "decision": {"confidence": 1.2, "importance": 1.3, "freshness": 1.0, "usage": 0.9},
}

_RELEVANCE_FIELDS = ("rrf", "semantic", "bm25", "intent")
_META_FIELDS = ("confidence", "importance", "freshness", "usage")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def rerank(
    candidates: list[RerankInput],
    query_intent: str = "unknown",
    top_k: int = 20,
    weights: RerankerWeights | None = None,
    intent_confidence: float = 0.0,
    negations: list[str] | None = None,
    key_terms: list[str] | None = None,
) -> list[tuple[str, float]]:
    top_k = max(1, top_k)
    # 意图置信度足够高（>0.3）时使用意图专用元数据权重，否则退回全局默认
    if weights is None:
        if intent_confidence > 0.3 and query_intent != "unknown":
            w = RerankerWeights.for_intent(query_intent)
        else:
            w = RerankerWeights.from_settings()
    else:
        w = weights

    for name in (*_RELEVANCE_FIELDS, *_META_FIELDS, "band", "key_term_bonus"):
        val = getattr(w, name)
        if val < 0:
            logger.warning("Negative weight for %s=%s, clamping to 0", name, val)
            setattr(w, name, 0.0)
    if w.band > 1.0:
        logger.warning("reranker band=%s out of [0,1], clamping to 1", w.band)
        w = replace(w, band=1.0)

    if not candidates:
        return []

    relevance_total = sum(getattr(w, name) for name in _RELEVANCE_FIELDS if name != "intent")
    meta_total = sum(getattr(w, name) for name in _META_FIELDS)
    # RRF 按理论满分锚定，而不是池内 min-max：候选池大小变化（2 条 vs 60 条）
    # 不改变同名词次的相关性分，避免小池归一化把头部差距压平。
    rrf_ceiling = (max(0.0, settings.bm25_weight) + max(0.0, settings.vector_weight)) / (RRF_K + 1)
    bm25_max = max((c.bm25_score for c in candidates), default=0.0)

    scored: list[tuple[str, float, float]] = []
    for c in candidates:
        if relevance_total > 0:
            relevance = (
                w.rrf * _clamp01(c.rrf_score / rrf_ceiling if rrf_ceiling > 0 else 0.0)
                + w.semantic * _clamp01(c.vector_score)
                + w.bm25 * _clamp01(c.bm25_score / bm25_max if bm25_max > 1e-9 else 0.0)
            ) / relevance_total
        else:
            relevance = 0.0

        # 意图匹配以中性 0.5 为中心：unknown 或类型不匹配不改变相关性，
        # 匹配类型最多加 w.intent×0.5，避免给所有候选加同一个常数。
        relevance += w.intent * (_intent_bonus(c.memory_type, query_intent) - 0.5)

        text_lc = (c.title + " " + c.content).lower()
        if key_terms:
            relevance += w.key_term_bonus * _compute_key_term_match(text_lc, key_terms)

        relevance = _clamp01(relevance)
        if negations:
            relevance *= 1.0 - _compute_negation_penalty(text_lc, negations)

        if meta_total > 0:
            metadata = (
                w.confidence * _clamp01(c.confidence)
                + w.importance * _clamp01(c.importance)
                + w.freshness * _clamp01(c.freshness)
                + w.usage * _clamp01(c.usage_score)
            ) / meta_total
        else:
            metadata = 0.0

        final = (1.0 - w.band) * relevance + w.band * _clamp01(metadata)
        scored.append((c.memory_id, final, relevance))

    # 同分时先看相关性，再按 id 保证确定性
    scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
    return [(memory_id, score) for memory_id, score, _ in scored[:top_k]]


def _intent_bonus(memory_type: str, query_intent: str) -> float:
    """意图-类型匹配分：意图未知给中性 0.5，类型完全不匹配给中性 0.5。"""
    if query_intent == "unknown":
        return 0.5
    match_map = {
        "project_rule": {"rule": 1.0, "constraint": 0.8},
        "lesson": {"lesson": 1.0, "issue": 0.8, "decision": 0.6},
        "fact": {"fact": 1.0},
        "procedure": {"procedure": 1.0, "rule": 0.5},
        "constraint": {"constraint": 1.0, "rule": 0.8},
        "decision": {"decision": 1.0, "lesson": 0.5},
    }
    return match_map.get(query_intent, {}).get(memory_type, 0.5)


def _compute_key_term_match(text_lc: str, key_terms: list[str]) -> float:
    if not key_terms:
        return 0.0
    matches = sum(1 for term in key_terms if term.lower() in text_lc)
    return matches / len(key_terms)


def _compute_negation_penalty(text_lc: str, negations: list[str]) -> float:
    """每个否定词命中记 0.3 罚分，上限 0.8（对应乘法衰减保底 20%）。"""
    if not negations:
        return 0.0
    matches = sum(1 for neg in negations if neg.lower() in text_lc)
    return min(matches * 0.3, 0.8)


def diversity_limit_for_intent(intent: str) -> int:
    return _INTENT_DIVERSITY.get(intent, 3)


# 各意图下同类型记忆的保留上限：fact 类信息互补可多留，
# 规则/约束类重复价值低，留 2 条即可
_INTENT_DIVERSITY: dict[str, int] = {
    "fact": 4,
    "procedure": 3,
    "lesson": 3,
    "project_rule": 2,
    "constraint": 2,
    "decision": 3,
    "unknown": 3,
}
