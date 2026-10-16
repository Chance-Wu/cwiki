"""向量相似度公共工具。"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def batch_cosine_similarities(
    query: list[float],
    embeddings: list[list[float]],
) -> np.ndarray:
    """用批量矩阵运算计算查询向量与所有向量的余弦相似度。

    Returns:
        与 embeddings 等长的一维 numpy 相似度数组；
        范数为零的向量对应位置为 0。
    """
    if not embeddings:
        return np.array([], dtype=np.float32)

    q = np.array(query, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return np.zeros(len(embeddings), dtype=np.float32)

    matrix = np.array(embeddings, dtype=np.float32)
    if matrix.ndim == 2 and matrix.shape[1] != len(q):
        raise ValueError(
            f"Embedding dimension mismatch: query has {len(q)} dims, "
            f"embeddings have {matrix.shape[1]} dims"
        )
    e_norms = np.linalg.norm(matrix, axis=1)

    dots = matrix @ q

    valid_mask = e_norms > 0
    similarities = np.zeros(len(embeddings), dtype=np.float32)
    similarities[valid_mask] = dots[valid_mask] / (e_norms[valid_mask] * q_norm)

    return similarities


def top_k_indices(similarities: np.ndarray, k: int) -> list[int]:
    """返回相似度 top-K 的索引（降序）。

    只保留相似度 > 0 的索引。
    用 argpartition 的 O(N) 部分排序替代全量 argsort 的 O(N log N)：
    先以 O(N) 切出前 K 名，再仅对 K 个元素排序。
    """
    if len(similarities) == 0 or k <= 0:
        return []
    k = min(k, len(similarities))
    if k >= len(similarities):
        top = np.argsort(similarities)[::-1]
    else:
        partitioned = np.argpartition(similarities, -k)[-k:]
        top = partitioned[np.argsort(similarities[partitioned])[::-1]]
    return [int(i) for i in top if similarities[i] > 0]
