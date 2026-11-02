"""复习填空题：确定性出题与判分。

与前端 `apps/web/src/lib/cloze.ts` 保持同一套选词/挖空规则：
标签、标题中的反引号、英文标识符、标题按标点切出的中文短语；
最多挖 3 个术语，跳过代码块，避免生成歧义题。

判分只依赖记忆内容，不信任客户端提交的答案；答案按大小写/空白/
标点归一后做多重集匹配，再映射为 SM-2 quality。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

MAX_TERMS = 3
MIN_CJK_LENGTH = 2
MAX_CJK_LENGTH = 16
MIN_LATIN_LENGTH = 4
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")
_TITLE_SPLIT_PATTERN = re.compile(r"[，。、；：,.;:！？!?\s·\-/|（）()【】\[\]]+")
# split 带捕获组：奇数下标是代码块/行内代码，挖空时必须原样保留
_PROTECTED_PATTERN = re.compile(r"(```[\s\S]*?```|`[^`\n]*`)")
_LATIN_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
_ANSWER_NOISE_PATTERN = re.compile(r"[\s\W_]+", re.UNICODE)

_STOP_WORDS = {
    "如何",
    "什么",
    "为什么",
    "怎么",
    "以及",
    "一个",
    "我们",
    "可以",
    "需要",
    "使用",
    "通过",
    "进行",
    "相关",
    "主要",
    "常见",
    "实现",
}


@dataclass
class ClozeQuiz:
    prompt: str
    terms: list[str]


@dataclass
class ClozeScore:
    correct: bool
    matched: int
    total: int
    quality: int


def _is_usable_term(term: str) -> bool:
    if term in _STOP_WORDS:
        return False
    if _CJK_PATTERN.search(term):
        return MIN_CJK_LENGTH <= len(term) <= MAX_CJK_LENGTH
    return len(term) >= MIN_LATIN_LENGTH


def _collect_candidates(title: str, tags: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        term = raw.strip()
        if not term or not _is_usable_term(term):
            return
        key = term.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(term)

    for tag in tags:
        push(tag)
    for match in _BACKTICK_PATTERN.findall(title):
        push(match)
    for match in _LATIN_TOKEN_PATTERN.findall(title):
        push(match)
    for part in _TITLE_SPLIT_PATTERN.split(title):
        push(part)
    return candidates


def _mask_terms(content: str, terms: list[str]) -> tuple[str, list[str]]:
    used: list[str] = []
    parts = _PROTECTED_PATTERN.split(content)
    masked_parts: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:  # 代码片段原样保留
            masked_parts.append(part)
            continue
        text = part
        for term in terms:
            if term in used or term not in text:
                continue
            if _LATIN_WORD_PATTERN.match(term):
                pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])")
                if not pattern.search(text):
                    continue
                text = pattern.sub("____", text, count=1)
            else:
                text = text.replace(term, "____", 1)
            used.append(term)
        masked_parts.append(text)
    return "".join(masked_parts), used


def build_cloze_quiz(title: str, content: str, tags: list[str] | None = None) -> ClozeQuiz | None:
    """从标题/标签选词，在正文中挖空；无可用术语时返回 None。"""
    candidates = _collect_candidates(title, tags or [])
    if not candidates:
        return None
    present = [term for term in candidates if term in content][:MAX_TERMS]
    if not present:
        return None
    prompt, used = _mask_terms(content, present)
    if not used:
        return None
    return ClozeQuiz(prompt=prompt, terms=used)


def normalize_answer(value: str) -> str:
    """答案归一：忽略大小写、空白、标点与下划线。"""
    return _ANSWER_NOISE_PATTERN.sub("", value.casefold())


def score_cloze_quiz(quiz: ClozeQuiz, answers: list[str]) -> ClozeScore:
    """按多重集匹配答案，并映射到 SM-2 quality。

    - 全对：5
    - 超过一半：4
    - 部分命中：3
    - 全错：1
    """
    expected = Counter(normalize_answer(term) for term in quiz.terms)
    actual = Counter(normalized for answer in answers if (normalized := normalize_answer(answer)))
    matched = sum(min(count, expected.get(key, 0)) for key, count in actual.items())
    total = len(quiz.terms)
    if total and matched == total:
        quality = 5
    elif matched * 2 > total:
        quality = 4
    elif matched > 0:
        quality = 3
    else:
        quality = 1
    return ClozeScore(
        correct=bool(total) and matched == total,
        matched=matched,
        total=total,
        quality=quality,
    )
