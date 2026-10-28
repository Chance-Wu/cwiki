"""增强版重复检测 3.0。

组合多种文本相似度算法以提升中文匹配效果：
- 字符 n-gram 重叠（适合中文）
- 标题相似度（权重更高）
- BM25 风格关键词得分
- 结构化小节匹配
- embedding 余弦相似度（语义相似）

将记忆对分类为：exact_duplicate、possible_duplicate、distinct。
不自动合并，判定结果交由人工复核。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from packages.domain.config import settings
from packages.domain.text_utils import format_memory_for_embedding
from packages.retrieval.embedding import get_embedding_service
from packages.retrieval.vector_utils import batch_cosine_similarities

if TYPE_CHECKING:
    from packages.memory.similarity import HybridWeights


@dataclass
class DuplicateVerdict:
    classification: str
    jaccard_score: float
    normalized_score: float
    combined_score: float
    detail: str = ""
    title_similarity: float = 0.0
    content_similarity: float = 0.0
    embedding_similarity: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}


@dataclass
class _Tokens:
    """单个文本的预计算 token 集合（避免批量比较时重复分词）。"""

    bigrams: set[str] = field(default_factory=set)
    trigrams: set[str] = field(default_factory=set)
    ngrams: set[str] = field(default_factory=set)
    token_set: set[str] = field(default_factory=set)
    token_list: list[str] = field(default_factory=list)


# 分类阈值由 config.yaml 的 memory.duplicate_*_threshold 提供（运行时读取）。
# 判定规则：combined_score ≥ exact 为完全重复，≥ possible 为可能重复。
# 标题/正文/关键词/embedding 四路相似度的默认融合权重：
# 正文与语义（embedding）承载主要判断，标题短而信息密度高，关键词兜底
WEIGHT_TITLE = 0.20
WEIGHT_CONTENT = 0.35
WEIGHT_KEYWORD = 0.15
WEIGHT_EMBEDDING = 0.30

# n-gram 相似度与 token 集合相似度的内部融合权重
WEIGHT_NGRAM = 0.6
WEIGHT_TOKEN_SET = 0.4


def _precompute_text_tokens(text: str) -> _Tokens:
    """为单个文本预计算全部 token 表示。"""
    if not text:
        return _Tokens()
    bigrams = _char_ngrams(text, 2)
    trigrams = _char_ngrams(text, 3)
    token_list = _tokenize(text)
    return _Tokens(
        bigrams=bigrams,
        trigrams=trigrams,
        ngrams=bigrams | trigrams,
        token_set=set(token_list),
        token_list=token_list,
    )


def _classify(combined: float) -> tuple[str, str]:
    # 运行时读取，配置修改无需重启进程之外的操作
    if combined >= settings.duplicate_exact_threshold:
        return "exact_duplicate", "Very high similarity — likely the same memory"
    if combined >= settings.duplicate_possible_threshold:
        return "possible_duplicate", "Moderate similarity — may overlap with existing memory"
    return "distinct", "Low similarity — appears to be distinct memory"


def _tversky(set_a: set[str], set_b: set[str], alpha: float = 0.5) -> float:
    """Tversky 相似度：交集除以两集合大小的加权和。

    alpha=0.5 时退化为 Dice 系数，对长度不等的文本比 Jaccard 更宽容。
    """
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    if not intersection:
        return 0.0
    return len(intersection) / (alpha * len(set_a) + (1 - alpha) * len(set_b))


def _build_verdict(
    cand_title_t: _Tokens,
    exist_title_t: _Tokens,
    cand_content_t: _Tokens,
    exist_content_t: _Tokens,
    cand_combined_ts: set[str],
    exist_combined_ts: set[str],
    cand_combined_tokens: list[str],
    exist_combined_tokens: list[str],
    embedding_similarity: float = 0.0,
    weights: HybridWeights | None = None,
) -> DuplicateVerdict:
    """基于预计算 token 的核心比较逻辑。

    Args:
        embedding_similarity: 标题+正文 embedding 的余弦相似度（0.0-1.0）
        weights: 融合权重；None 用模块默认值。传入时按总和归一化。
    """
    title_sim = 0.0
    if cand_title_t.ngrams and exist_title_t.ngrams:
        ngram_sim = _tversky(cand_title_t.ngrams, exist_title_t.ngrams)
        token_sim = _tversky(cand_title_t.token_set, exist_title_t.token_set)
        title_sim = WEIGHT_NGRAM * ngram_sim + WEIGHT_TOKEN_SET * token_sim

    content_sim = 0.0
    if cand_content_t.ngrams and exist_content_t.ngrams:
        ngram_sim = _tversky(cand_content_t.ngrams, exist_content_t.ngrams)
        token_sim = _tversky(cand_content_t.token_set, exist_content_t.token_set)
        content_sim = WEIGHT_NGRAM * ngram_sim + WEIGHT_TOKEN_SET * token_sim

    keyword_sim = 0.0
    if cand_combined_tokens and exist_combined_tokens:
        common = cand_combined_ts & exist_combined_ts
        if common:
            # 按 token 长度加权（长 token 信息量更大），BM25 风格的加权重叠
            total_weight = 0.0
            matched_weight = 0.0
            for token in cand_combined_ts | exist_combined_ts:
                weight = len(token)
                total_weight += weight
                if token in common:
                    matched_weight += weight
            keyword_sim = matched_weight / total_weight if total_weight > 0 else 0.0

    if weights is None:
        w_title, w_content, w_keyword, w_embedding = (
            WEIGHT_TITLE,
            WEIGHT_CONTENT,
            WEIGHT_KEYWORD,
            WEIGHT_EMBEDDING,
        )
    else:
        total_weight = weights.title + weights.content + weights.keyword + weights.embedding
        if total_weight > 0:
            w_title = weights.title / total_weight
            w_content = weights.content / total_weight
            w_keyword = weights.keyword / total_weight
            w_embedding = weights.embedding / total_weight
        else:
            w_title, w_content, w_keyword, w_embedding = (
                WEIGHT_TITLE,
                WEIGHT_CONTENT,
                WEIGHT_KEYWORD,
                WEIGHT_EMBEDDING,
            )

    combined = (
        w_title * title_sim
        + w_content * content_sim
        + w_keyword * keyword_sim
        + w_embedding * embedding_similarity
    )
    classification, detail = _classify(combined)

    jaccard = 0.0
    if cand_combined_ts and exist_combined_ts:
        intersection = cand_combined_ts & exist_combined_ts
        if intersection:
            jaccard = len(intersection) / len(cand_combined_ts | exist_combined_ts)

    normalized = 0.0
    if cand_combined_ts and exist_combined_ts:
        intersection = cand_combined_ts & exist_combined_ts
        if intersection:
            normalized = len(intersection) / min(len(cand_combined_ts), len(exist_combined_ts))

    return DuplicateVerdict(
        classification=classification,
        jaccard_score=jaccard,
        normalized_score=normalized,
        combined_score=combined,
        detail=detail,
        title_similarity=title_sim,
        content_similarity=content_sim,
        embedding_similarity=embedding_similarity,
    )


def detect_duplicate(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    *,
    embedding_similarity: float = 0.0,
) -> DuplicateVerdict:
    """将候选记忆与一条已有记忆比较（同步、无 embedding 计算）。

    加权组合标题、正文 n-gram、BM25 风格关键词重叠与传入的
    *embedding_similarity*。生产写入路径用
    :func:`batch_detect_duplicates_with_embedding` 自动计算语义相似度；
    本函数供不需要异步/模型的调用方使用，不传 embedding 时仅词面打分
    （理论上限约 0.70，达不到 exact 阈值）。
    """
    cand_title_t = _precompute_text_tokens(_normalize_text(candidate.get("title", "")))
    exist_title_t = _precompute_text_tokens(_normalize_text(existing.get("title", "")))
    cand_content_t = _precompute_text_tokens(_normalize_text(candidate.get("content", "")))
    exist_content_t = _precompute_text_tokens(_normalize_text(existing.get("content", "")))

    cand_combined = cand_title_t.token_list + cand_content_t.token_list
    exist_combined = exist_title_t.token_list + exist_content_t.token_list
    cand_combined_ts = cand_title_t.token_set | cand_content_t.token_set
    exist_combined_ts = exist_title_t.token_set | exist_content_t.token_set

    return _build_verdict(
        cand_title_t,
        exist_title_t,
        cand_content_t,
        exist_content_t,
        cand_combined_ts,
        exist_combined_ts,
        cand_combined,
        exist_combined,
        embedding_similarity=embedding_similarity,
    )


@dataclass
class _CombinedTokens:
    """批量比较用的标题+正文预计算 token。"""

    title_tokens: _Tokens
    content_tokens: _Tokens
    combined_set: set[str]
    combined_list: list[str]


def precompute_combined(texts: list[dict[str, Any]]) -> list[_CombinedTokens]:
    """为 {title, content} 字典列表预计算合并 token。"""
    result: list[_CombinedTokens] = []
    for item in texts:
        title_t = _precompute_text_tokens(_normalize_text(item.get("title", "")))
        content_t = _precompute_text_tokens(_normalize_text(item.get("content", "")))
        result.append(
            _CombinedTokens(
                title_tokens=title_t,
                content_tokens=content_t,
                combined_set=title_t.token_set | content_t.token_set,
                combined_list=title_t.token_list + content_t.token_list,
            )
        )
    return result


def batch_detect_duplicates(
    candidate: dict[str, Any],
    precomputed_existing: list[_CombinedTokens],
    *,
    embedding_similarities: list[float] | None = None,
    weights: HybridWeights | None = None,
) -> list[DuplicateVerdict]:
    """将候选与多条已预分词的已有项比较。

    候选只分词一次；已有项直接复用预计算结果，消除重复分词开销。
    *embedding_similarities* 与 *precomputed_existing* 等长，缺省为 0。
    """
    cand_title_t = _precompute_text_tokens(_normalize_text(candidate.get("title", "")))
    cand_content_t = _precompute_text_tokens(_normalize_text(candidate.get("content", "")))
    cand_combined_ts = cand_title_t.token_set | cand_content_t.token_set
    cand_combined_list = cand_title_t.token_list + cand_content_t.token_list

    embedding_scores = embedding_similarities or [0.0] * len(precomputed_existing)
    return [
        _build_verdict(
            cand_title_t,
            ex.title_tokens,
            cand_content_t,
            ex.content_tokens,
            cand_combined_ts,
            ex.combined_set,
            cand_combined_list,
            ex.combined_list,
            embedding_similarity=embedding_scores[idx],
            weights=weights,
        )
        for idx, ex in enumerate(precomputed_existing)
    ]


def _normalize_text(text: str) -> str:
    """为比较而规范化文本（小写、去标点、压空白）。"""
    text = text.lower()
    # 仅保留单词字符、空白与中文（\u4e00-\u9fff），标点统一替换为空格
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _char_ngrams(text: str, n: int) -> set[str]:
    """提取字符级 n-gram（适用于中文）。"""
    text = text.replace(" ", "")
    # 不足 n 字时整体作为唯一 token，避免短文本直接得 0 分
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _tokenize(text: str) -> list[str]:
    """分词：英文按空格切分，中文提取 2/3 元组。"""
    tokens: list[str] = []
    parts = text.split()
    for part in parts:
        if re.search(r"[\u4e00-\u9fff]", part):
            tokens.extend(_char_ngrams(part, 2))
            tokens.extend(_char_ngrams(part, 3))
        else:
            tokens.append(part)
    return tokens


async def detect_duplicate_with_embedding(
    candidate: dict[str, Any],
    existing: dict[str, Any],
) -> DuplicateVerdict:
    """结合 embedding 相似度比较候选与已有记忆。

    词面相似度（n-gram、关键词）与语义相似度（embedding）加权融合。
    """
    cand_title_t = _precompute_text_tokens(_normalize_text(candidate.get("title", "")))
    exist_title_t = _precompute_text_tokens(_normalize_text(existing.get("title", "")))
    cand_content_t = _precompute_text_tokens(_normalize_text(candidate.get("content", "")))
    exist_content_t = _precompute_text_tokens(_normalize_text(existing.get("content", "")))

    cand_combined = cand_title_t.token_list + cand_content_t.token_list
    exist_combined = exist_title_t.token_list + exist_content_t.token_list
    cand_combined_ts = cand_title_t.token_set | cand_content_t.token_set
    exist_combined_ts = exist_title_t.token_set | exist_content_t.token_set

    # 计算 embedding 余弦相似度
    embedding_sim = await _compute_embedding_similarity(candidate, existing)

    return _build_verdict(
        cand_title_t,
        exist_title_t,
        cand_content_t,
        exist_content_t,
        cand_combined_ts,
        exist_combined_ts,
        cand_combined,
        exist_combined,
        embedding_similarity=embedding_sim,
    )


async def batch_detect_duplicates_with_embedding(
    candidate: dict[str, Any],
    existing_items: list[dict[str, Any]],
) -> list[DuplicateVerdict]:
    """结合 embedding 相似度，将候选与多条已有项比较。

    候选 embedding 只生成一次；已有项优先复用库中存储的 embedding，
    仅为缺失者现场生成。
    """
    if not existing_items:
        return []

    cand_title_t = _precompute_text_tokens(_normalize_text(candidate.get("title", "")))
    cand_content_t = _precompute_text_tokens(_normalize_text(candidate.get("content", "")))
    cand_combined_ts = cand_title_t.token_set | cand_content_t.token_set
    cand_combined_list = cand_title_t.token_list + cand_content_t.token_list

    # 候选 embedding 只生成一次
    cand_text = format_memory_for_embedding(
        candidate.get("title", ""), candidate.get("content", "")
    )
    embedding_service = get_embedding_service()
    cand_embedding = await embedding_service.generate_embedding(cand_text)

    # 区分已存 embedding 与需现场生成的项
    stored_embeddings: list[tuple[int, list[float]]] = []
    needs_generation: list[tuple[int, str]] = []

    for i, item in enumerate(existing_items):
        stored_emb = item.get("embedding")
        if stored_emb:
            stored_embeddings.append((i, stored_emb))
        else:
            text = format_memory_for_embedding(item.get("title", ""), item.get("content", ""))
            needs_generation.append((i, text))

    # 仅为无存储 embedding 的项批量生成
    generated_embeddings: dict[int, list[float] | None] = {}
    if needs_generation:
        texts = [text for _, text in needs_generation]
        generated = await embedding_service.generate_embeddings_batch(texts)
        for (idx, _), emb in zip(needs_generation, generated):
            generated_embeddings[idx] = emb

    all_embeddings: list[list[float] | None] = [None] * len(existing_items)
    for idx, emb in stored_embeddings:
        all_embeddings[idx] = emb
    for idx, emb in generated_embeddings.items():
        all_embeddings[idx] = emb

    # 计算 embedding 余弦相似度；无 embedding 的项记 0，只按词面通道判定
    embedding_sims: list[float] = []
    if cand_embedding is not None:
        valid_embeddings = [e for e in all_embeddings if e is not None]
        if valid_embeddings:
            similarities = batch_cosine_similarities(cand_embedding, valid_embeddings)
            sim_iter = iter(similarities)
            for e in all_embeddings:
                if e is not None:
                    embedding_sims.append(float(next(sim_iter)))
                else:
                    embedding_sims.append(0.0)
        else:
            embedding_sims = [0.0] * len(existing_items)
    else:
        embedding_sims = [0.0] * len(existing_items)

    # 构建判定结果
    verdicts: list[DuplicateVerdict] = []
    for idx, item in enumerate(existing_items):
        exist_title_t = _precompute_text_tokens(_normalize_text(item.get("title", "")))
        exist_content_t = _precompute_text_tokens(_normalize_text(item.get("content", "")))
        exist_combined_ts = exist_title_t.token_set | exist_content_t.token_set
        exist_combined_list = exist_title_t.token_list + exist_content_t.token_list

        verdict = _build_verdict(
            cand_title_t,
            exist_title_t,
            cand_content_t,
            exist_content_t,
            cand_combined_ts,
            exist_combined_ts,
            cand_combined_list,
            exist_combined_list,
            embedding_similarity=embedding_sims[idx],
        )
        verdicts.append(verdict)

    return verdicts


async def _compute_embedding_similarity(
    text_a: dict[str, Any],
    text_b: dict[str, Any],
) -> float:
    """用 embedding 计算两段文本的余弦相似度。"""
    embedding_service = get_embedding_service()

    text_a_combined = format_memory_for_embedding(
        text_a.get("title", ""), text_a.get("content", "")
    )
    text_b_combined = format_memory_for_embedding(
        text_b.get("title", ""), text_b.get("content", "")
    )

    embeddings = await embedding_service.generate_embeddings_batch(
        [text_a_combined, text_b_combined]
    )

    if len(embeddings) < 2 or embeddings[0] is None or embeddings[1] is None:
        return 0.0

    similarities = batch_cosine_similarities(embeddings[0], [embeddings[1]])
    return float(similarities[0]) if len(similarities) > 0 else 0.0
