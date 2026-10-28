"""共享的文本相似度计算。

为中英文文本提供统一的分词与 Jaccard 相似度，供去重检测、笔记去重、
检索去重、跨会话模式识别、记忆合并与冲突检测等模块复用。

统一相似度计算策略：
- jaccard: 基于 token 的 Jaccard 相似度（词面匹配）
- embedding: 基于向量余弦相似度（语义匹配）
- hybrid: 加权融合多信号（标题、正文、关键词、embedding）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# 混合相似度权重配置（可在 config.yaml 覆盖）
@dataclass
class HybridWeights:
    """混合相似度各通道权重，归一化为 1.0。"""

    title: float = 0.20
    content: float = 0.35
    keyword: float = 0.15
    embedding: float = 0.30

    def normalize(self) -> None:
        """归一化权重，确保总和为 1.0。"""
        total = self.title + self.content + self.keyword + self.embedding
        if total > 0:
            self.title /= total
            self.content /= total
            self.keyword /= total
            self.embedding /= total


# 默认权重（与 duplicate_detection.py 保持一致）
DEFAULT_HYBRID_WEIGHTS = HybridWeights()


def tokenize(text: str) -> set[str]:
    """分词：英文按单词，中文取字符二元组（bigram），孤立单字退化为单字。"""
    text = text.lower().strip()

    english_words = set(re.findall(r"[a-z0-9_]+", text))

    # 中文没有空格分词边界，用相邻字符二元组近似词粒度，实现简单且足够判重
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    chinese_bigrams = {"".join(chinese_chars[i : i + 2]) for i in range(len(chinese_chars) - 1)}
    if len(chinese_chars) == 1:
        chinese_bigrams.add(chinese_chars[0])

    return english_words | chinese_bigrams


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的 Jaccard 相似度。"""
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    return jaccard_from_sets(tokens_a, tokens_b)


def jaccard_from_sets(tokens_a: set[str], tokens_b: set[str]) -> float:
    """基于已分词的集合计算 Jaccard 相似度。"""
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


async def compute_similarity(
    text_a: dict[str, Any],
    text_b: dict[str, Any],
    strategy: str = "hybrid",
    weights: HybridWeights | None = None,
) -> float:
    """统一相似度计算入口。

    Args:
        text_a: {"title": str, "content": str, "embedding": list[float] | None}
        text_b: 同 text_a
        strategy: "jaccard" | "embedding" | "hybrid"
        weights: 混合策略权重，None 时使用默认值

    Returns:
        0.0-1.0 的相似度分数
    """
    if strategy == "jaccard":
        combined_a = f"{text_a.get('title', '')} {text_a.get('content', '')}"
        combined_b = f"{text_b.get('title', '')} {text_b.get('content', '')}"
        return jaccard_similarity(combined_a, combined_b)

    elif strategy == "embedding":
        return await _embedding_similarity(text_a, text_b)

    elif strategy == "hybrid":
        return await _hybrid_similarity(text_a, text_b, weights or DEFAULT_HYBRID_WEIGHTS)

    else:
        raise ValueError(f"Unknown similarity strategy: {strategy}")


async def _embedding_similarity(text_a: dict[str, Any], text_b: dict[str, Any]) -> float:
    """基于 embedding 余弦相似度。"""
    from packages.domain.text_utils import format_memory_for_embedding
    from packages.retrieval.embedding import get_embedding_service
    from packages.retrieval.vector_utils import batch_cosine_similarities

    emb_a = text_a.get("embedding")
    emb_b = text_b.get("embedding")

    # 优先复用已存储的 embedding
    if emb_a and emb_b:
        return float(batch_cosine_similarities(emb_a, [emb_b])[0])

    # 否则现场生成
    embedding_service = get_embedding_service()
    texts_to_embed = []
    if not emb_a:
        texts_to_embed.append(
            format_memory_for_embedding(text_a.get("title", ""), text_a.get("content", ""))
        )
    if not emb_b:
        texts_to_embed.append(
            format_memory_for_embedding(text_b.get("title", ""), text_b.get("content", ""))
        )

    generated = (
        await embedding_service.generate_embeddings_batch(texts_to_embed) if texts_to_embed else []
    )
    gen_iter = iter(generated)

    final_emb_a = emb_a or next(gen_iter, None)
    final_emb_b = emb_b or next(gen_iter, None)

    if not final_emb_a or not final_emb_b:
        return 0.0

    return float(batch_cosine_similarities(final_emb_a, [final_emb_b])[0])


async def _hybrid_similarity(
    text_a: dict[str, Any],
    text_b: dict[str, Any],
    weights: HybridWeights,
) -> float:
    """多信号加权融合相似度。

    融合标题、正文、关键词、embedding 四路信号。
    """
    from packages.memory.duplicate_detection import (
        _build_verdict,
        _normalize_text,
        _precompute_text_tokens,
    )

    # 预计算 token
    cand_title_t = _precompute_text_tokens(_normalize_text(text_a.get("title", "")))
    exist_title_t = _precompute_text_tokens(_normalize_text(text_b.get("title", "")))
    cand_content_t = _precompute_text_tokens(_normalize_text(text_a.get("content", "")))
    exist_content_t = _precompute_text_tokens(_normalize_text(text_b.get("content", "")))

    cand_combined = cand_title_t.token_list + cand_content_t.token_list
    exist_combined = exist_title_t.token_list + exist_content_t.token_list
    cand_combined_ts = cand_title_t.token_set | cand_content_t.token_set
    exist_combined_ts = exist_title_t.token_set | exist_content_t.token_set

    # 计算 embedding 相似度
    embedding_sim = await _embedding_similarity(text_a, text_b)

    # 复用 duplicate_detection 的 verdict 构建逻辑（权重按总和归一化）
    verdict = _build_verdict(
        cand_title_t,
        exist_title_t,
        cand_content_t,
        exist_content_t,
        cand_combined_ts,
        exist_combined_ts,
        cand_combined,
        exist_combined,
        embedding_similarity=embedding_sim,
        weights=weights,
    )

    return verdict.combined_score
