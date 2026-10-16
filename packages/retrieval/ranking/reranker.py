"""重排器——用多信号对候选池重新打分排序（PRD 第 19 节）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from packages.domain.config import settings

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


# 默认权重和为 1：以相关性（RRF）为主导信号，置信度/重要度/新鲜度等
# 元数据信号作微调；具体值可在 config.yaml 覆盖，for_intent 再按意图缩放。
@dataclass
class RerankerWeights:
    rrf: float = 0.38
    confidence: float = 0.13
    importance: float = 0.16
    freshness: float = 0.13
    usage: float = 0.08
    intent: float = 0.12

    @staticmethod
    def from_settings() -> RerankerWeights:
        return RerankerWeights(
            rrf=settings.reranker_rrf_weight,
            confidence=settings.reranker_confidence_weight,
            importance=settings.reranker_importance_weight,
            freshness=settings.reranker_freshness_weight,
            usage=settings.reranker_usage_weight,
            intent=settings.reranker_intent_weight,
        )

    @staticmethod
    def for_intent(intent: str) -> RerankerWeights:
        base = RerankerWeights.from_settings()
        adjustments = _INTENT_WEIGHT_ADJUSTMENTS.get(intent)
        if not adjustments:
            return base
        w = RerankerWeights(
            rrf=base.rrf * adjustments.get("rrf", 1.0),
            confidence=base.confidence * adjustments.get("confidence", 1.0),
            importance=base.importance * adjustments.get("importance", 1.0),
            freshness=base.freshness * adjustments.get("freshness", 1.0),
            usage=base.usage * adjustments.get("usage", 1.0),
            intent=base.intent * adjustments.get("intent", 1.0),
        )
        # 按意图缩放后重新归一，保证权重和仍为 1，总分口径不变
        total = w.rrf + w.confidence + w.importance + w.freshness + w.usage + w.intent
        if total > 0:
            w.rrf /= total
            w.confidence /= total
            w.importance /= total
            w.freshness /= total
            w.usage /= total
            w.intent /= total
        return w


_INTENT_WEIGHT_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "fact": {
        "rrf": 1.0,
        "confidence": 1.5,
        "importance": 1.2,
        "freshness": 0.8,
        "usage": 1.0,
        "intent": 1.0,
    },
    "procedure": {
        "rrf": 0.9,
        "confidence": 1.0,
        "importance": 1.0,
        "freshness": 1.5,
        "usage": 1.3,
        "intent": 1.2,
    },
    "lesson": {
        "rrf": 1.0,
        "confidence": 1.3,
        "importance": 1.0,
        "freshness": 1.2,
        "usage": 1.2,
        "intent": 1.3,
    },
    "project_rule": {
        "rrf": 1.2,
        "confidence": 1.4,
        "importance": 1.3,
        "freshness": 0.7,
        "usage": 0.8,
        "intent": 1.2,
    },
    "constraint": {
        "rrf": 1.1,
        "confidence": 1.3,
        "importance": 1.2,
        "freshness": 0.8,
        "usage": 0.8,
        "intent": 1.2,
    },
    "decision": {
        "rrf": 1.0,
        "confidence": 1.2,
        "importance": 1.3,
        "freshness": 1.0,
        "usage": 0.9,
        "intent": 1.1,
    },
}


def _normalize_signal(values: list[float]) -> list[float]:
    """将数值列表 min-max 归一化到 [0, 1]；无区分度（极差近 0）时返回全 0。"""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    spread = hi - lo
    if spread < 1e-9:
        return [0.0] * len(values)
    return [(v - lo) / spread for v in values]


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
    # 意图置信度足够高（>0.3）时使用意图专用权重，否则退回全局默认权重
    if weights is None:
        if intent_confidence > 0.3 and query_intent != "unknown":
            w = RerankerWeights.for_intent(query_intent)
        else:
            w = RerankerWeights.from_settings()
    else:
        w = weights

    for name in ("rrf", "confidence", "importance", "freshness", "usage", "intent"):
        val = getattr(w, name)
        if val < 0:
            logger.warning("Negative weight for %s=%s, clamping to 0", name, val)
            setattr(w, name, 0.0)

    if not candidates:
        return []

    raw_rrf = [c.rrf_score for c in candidates]
    raw_conf = [c.confidence for c in candidates]
    raw_imp = [c.importance for c in candidates]
    raw_fresh = [c.freshness for c in candidates]
    raw_usage = [c.usage_score for c in candidates]
    raw_intent = [_intent_bonus(c.memory_type, query_intent) for c in candidates]

    # RRF 名次分是池内相对分（无量纲），必须 min-max 归一才能与其他信号同台加权；
    # confidence/importance/freshness/usage/intent 本身就是 0-1 语义分，绝对值即含义
    # （如 confidence 0.85 就该贡献 0.85×权重），直接用原始值。若对它们也做池内
    # min-max，池内最小值会被强拉到 0（即使绝对值 0.85），而 RRF 头部名次间的
    # 微小差距经归一后被压平，元数据信号反而主导排序，把元数据恰好最小的
    # 相关记忆挤下去——这违背了「RRF 主导、元数据微调」的权重设计。
    norm_rrf = _normalize_signal(raw_rrf)

    scored: list[tuple[str, float]] = []

    for i, c in enumerate(candidates):
        final = (
            w.rrf * norm_rrf[i]
            + w.confidence * raw_conf[i]
            + w.importance * raw_imp[i]
            + w.freshness * raw_fresh[i]
            + w.usage * raw_usage[i]
            + w.intent * raw_intent[i]
        )

        if key_terms or negations:
            text_lc = (c.title + " " + c.content).lower()
            if key_terms:
                key_match_score = _compute_key_term_match(text_lc, key_terms)
                final += settings.reranker_key_term_bonus * key_match_score
            if negations:
                negation_penalty = _compute_negation_penalty(text_lc, negations)
                # 乘法衰减而非减分：保留 20% 底分，防止误判时一票否决
                final *= 1.0 - negation_penalty

        scored.append((c.memory_id, final))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _intent_bonus(memory_type: str, query_intent: str) -> float:
    """意图-类型匹配分：意图未知给中性 0.5，类型完全不匹配给中性 0.5。

    不匹配基线取 0.5 而非更低惩罚值：query_intent 由查询关键词分析得出，
    可靠性有限，重罚（如 0.3）会让一个低置信信号产生高置信影响——意图
    误判时（权重 0.12 × 0.2 分差 = 0.024，且部分匹配 0.6/0.8 与匹配 1.0
    仍保留区分度）不再系统性把正确类型的头部记忆挤下去。
    """
    if query_intent == "unknown":
        return 0.5
    match_map = {
        "project_rule": {"rule": 1.0, "constraint": 0.8},
        "lesson": {"lesson": 1.0, "issue": 0.8, "decision": 0.6},
        "fact": {"fact": 1.0},
        "procedure": {"procedure": 1.0, "project_rule": 0.5},
        "constraint": {"constraint": 1.0, "project_rule": 0.8},
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
