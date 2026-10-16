"""MCP 服务端内容工具：自动标题、关键词提取与响应格式化。"""

from __future__ import annotations

import re
from typing import Any

_SENTENCE_ENDS = frozenset("。！？")
_CLAUSE_ENDS = frozenset("，；,")

_TEST_KEYWORDS = ["测试", "验证", "临时", "test", "tmp", "temp", "试用", "demo", "poc"]

_STOP_WORDS = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
        "他",
        "她",
        "它",
        "们",
        "那",
        "些",
        "什么",
        "怎么",
        "如何",
        "为什么",
        "可以",
        "已经",
        "还是",
        "或者",
        "但是",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "about",
        "it",
        "its",
        "this",
        "that",
        "and",
        "or",
        "but",
        "not",
        "no",
        "if",
        "then",
        "than",
        "so",
        "such",
        "too",
        "very",
        "just",
        "also",
        "more",
        "most",
        "some",
        "any",
        "all",
        "each",
        "every",
        "both",
        "few",
        "many",
        "much",
        "own",
        "other",
        "another",
        "here",
        "there",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "what",
        "why",
        "how",
        "up",
        "out",
        "off",
        "over",
        "under",
    }
)

_WORD_RE = re.compile(r"[A-Za-z_]\w{2,}|[\u4e00-\u9fff]{2,}")


def smart_truncate(text: str, max_len: int) -> str:
    """在自然标点边界处截断，避免产生悬尾标题。"""
    if len(text) <= max_len:
        result = text
    else:
        result = text
        for chars in (_SENTENCE_ENDS, _CLAUSE_ENDS):
            for i in range(max_len - 1, max_len // 3, -1):
                if text[i] in chars:
                    result = text[: i + 1]
                    break
                if result != text:
                    break
            if result != text:
                break
        else:
            for sep in ["、", " "]:
                idx = text.rfind(sep, max_len // 3, max_len)
                if idx > 0:
                    result = text[:idx]
                    break
            else:
                result = text[:max_len]
    return re.sub(r"[。！？，；：、" "''【】（）《》…—～.!?,:;'\"\\[\\](){}-]+$", "", result)


_SENTENCE_PREFIX_PATTERNS = [
    re.compile(r"^(当[^，,。！？]{2,20}(?:时|的时候))[,，]?\s*"),
    re.compile(r"^(在[^，,。！？]{2,20}(?:中|时|的时候))[,，]?\s*"),
    re.compile(
        r"^(发现了?|遇到了?|碰到了?|解决了?|修复了?|实现了?|完成了?)[\u4e00-\u9fff]{0,5}?[,，]?\s*"
    ),
    re.compile(r"^(因为|由于|所以|因此)[^，,。！？]{0,10}[,，]?\s*"),
]

_TITLE_STOP_CHARS = frozenset("。！？；\n")


def _extract_core_phrase(text: str) -> str:
    """剥掉句式前缀（"当…时"、"在…中"、"发现了…"等），提取核心描述短语。"""
    for pat in _SENTENCE_PREFIX_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


_SECTION_HEADERS = frozenset(
    {
        "场景",
        "知识",
        "原因",
        "问题",
        "解决方案",
        "步骤",
        "资源",
        "用途",
        "访问方式",
        "背景",
        "决策",
        "约定",
        "模式",
        "规则",
        "强制",
        "约束",
        "限制",
        "教训",
        "经验",
    }
)
_COLON_SPLIT = re.compile(r"[：:]+|——|—")
_FIRST_SENTENCE = re.compile(r"^(.+?)[。！？\n]")


_CLAUSE_SPLIT = re.compile(r"[，,、]")


def auto_title(content: str, max_len: int = 60) -> str:
    """从内容中提取简洁的描述性标题。

    策略：
    1. 跳过固定段落标题（场景/知识/原因等）
    2. 去掉句式前缀（"当…时"、"在…中"等）
    3. 在冒号/破折号处取前半段（标题应是主题，不是展开说明）
    4. 在第一句边界截断；若仍超长则在逗号处断开
    """
    for line in content.split("\n"):
        stripped = line.strip().lstrip("#-•* ")
        if not stripped or len(stripped) < 3:
            continue
        first_word = re.split(r"[：:，,（]", stripped, maxsplit=1)[0].strip()
        if first_word in _SECTION_HEADERS:
            continue
        core = _extract_core_phrase(stripped)
        if len(core) < 3:
            continue
        core = _COLON_SPLIT.split(core, maxsplit=1)[0].strip()
        m = _FIRST_SENTENCE.match(core)
        if m:
            core = m.group(1)
        if len(core) > max_len:
            core = _CLAUSE_SPLIT.split(core, maxsplit=1)[0].strip()
        if len(core) > max_len:
            idx = core.rfind(" ", 0, max_len)
            if idx > max_len // 3:
                core = core[:idx]
        return smart_truncate(core, max_len)
    return smart_truncate(content[:max_len], max_len)


def is_test_content(content: str) -> bool:
    """检测内容是否为测试/验证性质的临时记忆。"""
    content_lower = content.lower()
    matches = sum(1 for kw in _TEST_KEYWORDS if kw in content_lower)
    return matches >= 2


def extract_keywords(texts: list[str], top_n: int = 5) -> list[str]:
    """从文本列表中提取高频关键词。"""
    freq: dict[str, int] = {}
    for text in texts:
        for m in _WORD_RE.finditer(text):
            w = m.group().lower()
            if w not in _STOP_WORDS:
                freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:top_n]]


def format_remember_response(response: dict[str, Any]) -> dict[str, Any]:
    """把候选创建响应格式化为面向 Agent 的精简结果。"""
    candidate = response.get("candidate", response)
    similar_items = response.get("similar_items", [])
    hint = response.get("hint")

    result: dict[str, Any] = {
        "status": "submitted",
        "candidate_id": candidate.get("id"),
        "title": candidate.get("title"),
        "type": candidate.get("type"),
    }

    if similar_items:
        result["similar_memories"] = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "similarity": round(item.get("similarity", 0), 2),
                "source": item.get("source"),
                "content_preview": item.get("content_preview", "")[:100],
            }
            for item in similar_items
        ]
        result["hint"] = hint or "发现相似记忆。如果是纠正错误，请保留原提交；如果是重复，可忽略。"

    return result
