"""BM25 索引，用于基于关键词的记忆检索。"""

from __future__ import annotations

import math
import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
_ASCII_RE = re.compile(r"[a-z0-9_]+")

# BM25 经典参数：k1 控制词频饱和增益，b 控制文档长度归一强度（0=不归一，1=全归一）；
# 1.5 / 0.75 为原论文推荐的经验值，是通用场景下召回与精度的平衡点。
_BM25_K1 = 1.5
_BM25_B = 0.75
# 标题词重复份数：标题 token 重复两份混入正文，等效放大标题词的 TF 权重
_TITLE_BOOST_REPS = 2


class BM25Index:
    """内存中的 BM25 索引，用于记忆搜索。

    IDF 采用 log(1 + N/n)（而非 rank_bm25 BM25Okapi 的 log((N-n+0.5)/(n+0.5))），
    保证小语料下得分为正——后者的公式在词出现于 ≤50% 文档时得分为 0，
    会让小语料的检索结果失去区分度。

    支持增量更新：``add()`` 与 ``remove()`` 直接维护索引有效性，
    无需再调用完整的 ``build()``。
    """

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._id_to_idx: dict[str, int] = {}
        self._documents: list[list[str]] = []
        self._tf_maps: list[dict[str, int]] = []  # 预计算的词频表
        self._df: dict[str, int] = {}
        self._dl: list[int] = []
        self._avgdl: float = 0.0
        self._total_dl: int = 0
        self._built: bool = False
        self._postings: dict[str, list[int]] = {}
        self._tombstones: set[str] = set()

    def add(self, doc_id: str, text: str, title: str | None = None) -> None:
        """添加文档并增量更新索引统计。"""
        tokens = self._tokenize(text)
        if title:
            title_tokens = self._tokenize(title)
            tokens = title_tokens * _TITLE_BOOST_REPS + tokens
        if not tokens:
            return

        # 若 doc_id 已存在，先移除旧版本及其统计量，避免重复计数
        if doc_id in self._id_to_idx:
            self._remove_by_index(self._id_to_idx[doc_id])

        self._tombstones.discard(doc_id)

        idx = len(self._documents)
        self._ids.append(doc_id)
        self._id_to_idx[doc_id] = idx
        self._documents.append(tokens)

        # 预计算该文档的词频表，检索时无需逐 token 重复统计
        tf_map: dict[str, int] = {}
        for t in tokens:
            tf_map[t] = tf_map.get(t, 0) + 1
        self._tf_maps.append(tf_map)

        dl = len(tokens)
        self._dl.append(dl)
        self._total_dl += dl
        n = len(self._documents)
        self._avgdl = self._total_dl / n

        # 仅对文档内去重后的 token 更新文档频率与倒排表（每文档每词只加 1）
        for token in set(tokens):
            self._df[token] = self._df.get(token, 0) + 1
            self._postings.setdefault(token, []).append(idx)

        self._built = True  # 增量添加后索引保持可检索

    def build(self) -> None:
        """完整重建全部统计量（批量操作后使用）。"""
        if not self._documents:
            self._df.clear()
            self._dl.clear()
            self._avgdl = 0.0
            self._total_dl = 0
            self._id_to_idx.clear()
            self._postings.clear()
            self._tf_maps.clear()
            self._built = True
            return

        self._id_to_idx = {doc_id: idx for idx, doc_id in enumerate(self._ids)}

        self._df.clear()
        self._postings.clear()
        self._dl = [len(doc) for doc in self._documents]
        self._total_dl = sum(self._dl)
        self._avgdl = self._total_dl / len(self._dl) if self._dl else 0.0

        self._tf_maps = []
        for doc_idx, doc in enumerate(self._documents):
            tf_map: dict[str, int] = {}
            for token in doc:
                tf_map[token] = tf_map.get(token, 0) + 1
            self._tf_maps.append(tf_map)
            for token in set(doc):
                self._df[token] = self._df.get(token, 0) + 1
                self._postings.setdefault(token, []).append(doc_idx)
        self._built = True

    def search(self, query: str, top_k: int = 50) -> list[tuple[str, float]]:
        if not self._built:
            self.build()
        if not self._documents:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        n = len(self._documents)

        # 先用倒排表取候选集（出现任一查询词的文档），只对候选打分，避免全库扫描
        candidate_doc_ids: set[int] = set()
        for token in tokens:
            postings = self._postings.get(token)
            if postings:
                candidate_doc_ids.update(postings)
        if not candidate_doc_ids:
            return []

        scores: dict[int, float] = {}
        for doc_idx in candidate_doc_ids:
            if self._ids[doc_idx] in self._tombstones:
                continue
            tf_map = self._tf_maps[doc_idx]
            dl = self._dl[doc_idx]
            score = 0.0
            for token in tokens:
                df = self._df.get(token, 0)
                if df == 0:
                    continue
                # IDF = log(1 + N/n)：加 1 平滑保证任何 df 下都为正值（见类 docstring）
                idf = math.log(1.0 + n / df)
                tf = tf_map.get(token, 0)
                numerator = tf * (_BM25_K1 + 1)
                denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / self._avgdl)
                score += idf * numerator / denominator
            if score > 0:
                scores[doc_idx] = score

        # 按得分降序截断 top_k
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self._ids[idx], round(score, 6)) for idx, score in ranked]

    def remove(self, doc_id: str) -> None:
        """移除文档并增量更新索引统计。"""
        if doc_id not in self._id_to_idx:
            return
        self._remove_by_index(self._id_to_idx[doc_id])

    def _remove_by_index(self, idx: int) -> None:
        """内部方法：将位置 *idx* 的文档标记为墓碑并增量更新统计量。"""
        doc_id = self._ids[idx]
        old_tokens = self._documents[idx]
        old_dl = self._dl[idx]

        for token in set(old_tokens):
            count = self._df.get(token, 0)
            if count <= 1:
                del self._df[token]
            else:
                self._df[token] = count - 1

        self._dl[idx] = 0
        self._documents[idx] = []
        self._tf_maps[idx] = {}
        self._total_dl -= old_dl
        n = len(self._documents)
        self._avgdl = self._total_dl / n if n > 0 else 0.0

        self._tombstones.add(doc_id)
        self._maybe_compact()

    def _maybe_compact(self) -> None:
        """墓碑数超过文档数一半时自动压缩，回收空洞、控制索引膨胀。"""
        if len(self._tombstones) > max(len(self._documents) // 2, 10):
            self.compact()

    def compact(self) -> None:
        """清除墓碑文档并重建倒排表。"""
        if not self._tombstones:
            return
        keep = [i for i, doc_id in enumerate(self._ids) if doc_id not in self._tombstones]
        self._ids = [self._ids[i] for i in keep]
        self._documents = [self._documents[i] for i in keep]
        self._tf_maps = [self._tf_maps[i] for i in keep]
        self._dl = [len(doc) for doc in self._documents]
        self._id_to_idx = {doc_id: idx for idx, doc_id in enumerate(self._ids)}
        self._total_dl = sum(self._dl)
        self._avgdl = self._total_dl / len(self._documents) if self._documents else 0.0
        self._postings.clear()
        for doc_idx, doc in enumerate(self._documents):
            for token in set(doc):
                self._postings.setdefault(token, []).append(doc_idx)
        self._tombstones.clear()

    def update(self, doc_id: str, text: str, title: str | None = None) -> None:
        """更新已有文档（不存在时等价于新增）。"""
        self.add(doc_id, text, title)

    def clear(self) -> None:
        self._ids.clear()
        self._id_to_idx.clear()
        self._documents.clear()
        self._tf_maps.clear()
        self._df.clear()
        self._dl.clear()
        self._postings.clear()
        self._tombstones.clear()
        self._avgdl = 0.0
        self._total_dl = 0
        self._built = False

    @property
    def size(self) -> int:
        return len(self._documents)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """分词：ASCII 词整段提取，中文连续片段交给 jieba 切分。

        英文经小写化后按 ``[a-z0-9_]+`` 整词提取；中文没有空格分隔，
        无法用字符类切词，故用 jieba 切出语义单元。两种 token 顺序拼接。
        """
        text = text.lower()
        tokens: list[str] = _ASCII_RE.findall(text)

        cjk_spans = _CJK_RE.findall(text)
        if cjk_spans:
            import jieba  # type: ignore[import-untyped]

            for span in cjk_spans:
                tokens.extend(t for t in jieba.cut(span) if t.strip())

        return tokens
