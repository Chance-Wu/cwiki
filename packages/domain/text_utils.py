"""记忆处理的共享文本工具。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.retrieval.query.analyzer import AnalyzedQuery


def format_memory_for_embedding(title: str, content: str) -> str:
    """将标题与正文拼接为生成 embedding 的规范文本。

    所有 embedding 调用点必须使用此格式，以保证入库向量与
    查询向量的文本构成一致，否则相似度计算失真。
    """
    if not content:
        return title
    if not title:
        return content
    return f"{title}\n{content}"


def preprocess_query_for_embedding(query: str, analyzed: AnalyzedQuery | None = None) -> str:
    """在生成查询 embedding 前预处理查询。

    应用与检索引擎相同的变换，保证所有向量检索路径
    产生一致的查询向量。
    """
    if analyzed is None:
        return query
    if analyzed.is_short and analyzed.key_terms:
        return " ".join(analyzed.key_terms[:5])
    if analyzed.expanded_terms:
        return query + " " + " ".join(analyzed.expanded_terms[:3])
    return query


_BLANK_LINE_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_HEADING_SURROUND_RE = re.compile(r"\n{3,}(?=#+\s)")

_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def signal_tokens(text: str) -> set[str]:
    """提取实体信号 token：ASCII 词 + CJK 二元组（孤立单字保留原样）。

    CJK 按连续汉字 run 切分后在 run 内取相邻二元组——整段 run 作 token
    时换个措辞就完全无法对齐，二元组能保留实体字面的重叠信号；run 之间
    不跨边界连字（跨标点/英文产生的"好世"类组合是噪音）。供去重、
    冲突粗筛等需要中英文统一词面信号的模块复用。
    """
    tokens: set[str] = set(_ASCII_TOKEN_RE.findall(text.lower()))
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def normalize_memory_content(content: str) -> str:
    """规范化 Markdown 排版，不改变语义。

    写入时调用，使记忆格式统一：
    - 去除每行行尾空白
    - 3 个及以上连续空行压缩为一个
    - 标题前确保恰好一个空行
    - 确保内容以单个换行结尾
    """
    if not content:
        return content

    result = _TRAILING_WS_RE.sub("", content)
    result = _HEADING_SURROUND_RE.sub("\n\n", result)
    result = _BLANK_LINE_RE.sub("\n\n", result)
    result = result.strip("\n")
    if result:
        result += "\n"
    return result
