"""共享的文本相似度计算。

为中英文文本提供统一的分词与 Jaccard 相似度，供去重检测、笔记去重、
检索去重、跨会话模式识别、记忆合并与冲突检测等模块复用。
"""

from __future__ import annotations

import re


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
