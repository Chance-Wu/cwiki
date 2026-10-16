"""基于 numpy 的语义检索向量索引。"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from packages.storage import config as storage_config

logger = logging.getLogger(__name__)


def _atomic_replace(src: str, dst: Path) -> None:
    """使用 os.replace 将 dst 原子替换为 src。"""
    os.replace(src, dst)


class VectorIndex:
    """基于 numpy 余弦相似度检索的简易向量索引。"""

    def __init__(self, dimensions: int = 1536, index_path: str | None = None):
        self.dimensions = dimensions
        self.index_path = Path(index_path) if index_path else Path(storage_config.vector_index_path)
        self._meta_path = self.index_path.with_suffix(".json")

        self.vectors: dict[str, np.ndarray] = {}
        self.metadata: dict[str, dict[str, Any]] = {}

        # 检索用的缓存矩阵 —— 增删向量时置为脏，下次检索重建
        self._matrix_cache: np.ndarray | None = None
        self._matrix_ids_cache: list[str] | None = None
        self._norms_cache: np.ndarray | None = None
        self._dirty = False

        self._dirty = True  # 缓存延迟到首次检索时构建
        self._load()

    def _load(self) -> None:
        """从磁盘加载索引，并检测文件损坏。"""
        if self._meta_path.exists() and self.index_path.exists():
            try:
                with open(self._meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                ids = meta["ids"]
                data = np.load(self.index_path)
                vecs = data["vectors"]
                # id 数与向量数不一致视为索引损坏，丢弃全部内容
                if len(ids) != len(vecs):
                    logger.warning(
                        "Vector index corruption: %d ids but %d vectors, rebuilding",
                        len(ids),
                        len(vecs),
                    )
                    self.vectors.clear()
                    self.metadata.clear()
                    return
                for i, id_str in enumerate(ids):
                    self.vectors[id_str] = vecs[i]
                self.metadata = meta.get("metadata", {})
                logger.info("Loaded %d vectors from index", len(self.vectors))
            except Exception as e:
                logger.warning("Failed to load vector index: %s, trying legacy", e)
                self._load_legacy()
        elif self.index_path.exists():
            self._load_legacy()

    def _load_legacy(self) -> None:
        """从旧版基于 pickle 的 npz 格式加载。"""
        try:
            data = np.load(self.index_path, allow_pickle=True)
            vectors_data = data["vectors"].item()
            metadata_data = data["metadata"].item()
            for id_str, vec in vectors_data.items():
                self.vectors[id_str] = np.array(vec)
            self.metadata = metadata_data
            logger.info("Loaded %d vectors from legacy index", len(self.vectors))
            # 旧格式加载成功后立即按新格式落盘，完成格式升级
            self.save()
        except Exception as e:
            logger.error("Error loading vector index: %s", e)

    def save(self) -> None:
        """将索引原子写入磁盘。

        采用先写临时文件再重命名的模式，防止写入中途崩溃导致索引损坏。
        """
        try:
            if not self.vectors:
                self.index_path.unlink(missing_ok=True)
                self._meta_path.unlink(missing_ok=True)
                return

            self.index_path.parent.mkdir(parents=True, exist_ok=True)

            ids = list(self.vectors.keys())
            vecs = np.stack([self.vectors[i] for i in ids])
            meta_data = {"ids": ids, "metadata": self.metadata, "version": 1}

            # 先写临时 npz 再原子重命名。
            # 名字缺后缀时 np.savez 会自动补 ".npz"，因此临时名用 ".tmp"
            # 后缀，实际文件为 "<tmp>.npz"。删掉 mkstemp 产生的 0 字节空壳，
            # 只保留 "<tmp>.npz"。
            fd, tmp_base = tempfile.mkstemp(suffix=".tmp", dir=self.index_path.parent)
            os.close(fd)
            os.unlink(tmp_base)
            tmp_data = tmp_base + ".npz"
            try:
                np.savez(tmp_base, vectors=vecs)
                _atomic_replace(tmp_data, self.index_path)
            except Exception:
                Path(tmp_data).unlink(missing_ok=True)
                raise

            # 元数据同样先写临时文件再原子重命名
            fd, tmp_meta = tempfile.mkstemp(suffix=".json.tmp", dir=self.index_path.parent)
            try:
                os.close(fd)
                with open(tmp_meta, "w", encoding="utf-8") as f:
                    json.dump(meta_data, f)
                _atomic_replace(tmp_meta, self._meta_path)
            except Exception:
                Path(tmp_meta).unlink(missing_ok=True)
                raise

            logger.info("Saved %d vectors to index", len(self.vectors))
        except Exception as e:
            logger.error("Error saving vector index: %s", e)

    def add(
        self, memory_id: str, vector: list[float], metadata: dict[str, Any] | None = None
    ) -> None:
        """向索引添加一个向量。"""
        self.vectors[memory_id] = np.array(vector, dtype=np.float32)
        if metadata:
            self.metadata[memory_id] = metadata
        self._dirty = True

    def remove(self, memory_id: str) -> None:
        """从索引移除一个向量。"""
        if memory_id in self.vectors:
            del self.vectors[memory_id]
        if memory_id in self.metadata:
            del self.metadata[memory_id]
        self._dirty = True

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        threshold: float = 0.0,
        *,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """仅对符合条件的向量执行批量 numpy 运算排序。

        用单次矩阵 @ 向量乘法取代逐向量的 Python 循环，
        再用 argpartition 做 O(n) 的 top-k 选取。
        """
        if not self.vectors:
            return []

        query_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return []

        # 仅为符合条件的向量构建有序 id 列表与堆叠矩阵
        if allowed_ids is not None:
            ids = [mid for mid in self.vectors if mid in allowed_ids]
            if not ids:
                return []
            matrix = np.stack([self.vectors[mid] for mid in ids])  # (n, d)
            e_norms = np.linalg.norm(matrix, axis=1)
        else:
            # 检索全部向量时使用缓存矩阵
            if self._dirty or self._matrix_cache is None:
                ids = list(self.vectors.keys())
                if not ids:
                    return []
                self._matrix_cache = np.stack([self.vectors[mid] for mid in ids])
                self._norms_cache = np.linalg.norm(self._matrix_cache, axis=1)
                self._matrix_ids_cache = ids
                self._dirty = False
            ids = self._matrix_ids_cache  # type: ignore[assignment]
            matrix = self._matrix_cache
            e_norms = self._norms_cache

        # 批量点积
        dots = matrix @ query_vec  # (n,)

        # 余弦相似度，零范数向量的相似度置 0
        valid_mask = e_norms > 0
        similarities = np.zeros(len(ids), dtype=np.float32)
        similarities[valid_mask] = dots[valid_mask] / (e_norms[valid_mask] * q_norm)

        above_threshold = similarities >= threshold
        if not np.any(above_threshold):
            return []

        eligible_indices = np.where(above_threshold)[0]
        eligible_sims = similarities[eligible_indices]

        # 用 argpartition（O(n)）取 top-k，再只对选出的 k 个排序
        k = min(top_k, len(eligible_sims))
        if k == 0:
            return []

        if k < len(eligible_sims):
            partitioned = np.argpartition(eligible_sims, -k)[-k:]
            order = np.argsort(eligible_sims[partitioned])[::-1]
            selected = partitioned[order]
        else:
            order = np.argsort(eligible_sims)[::-1]
            selected = order

        return [(ids[int(eligible_indices[i])], float(eligible_sims[i])) for i in selected]

    def get_vector(self, memory_id: str) -> np.ndarray | None:
        """按 ID 获取向量。"""
        return self.vectors.get(memory_id)

    def get_metadata(
        self, memory_id: str, default: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """按 ID 获取元数据。"""
        return self.metadata.get(memory_id, default)

    def size(self) -> int:
        """返回索引中的向量数量。"""
        return len(self.vectors)
