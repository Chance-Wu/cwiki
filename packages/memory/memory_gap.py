"""智能记忆缺口检测。"""

from __future__ import annotations

import re
from typing import Any


def extract_technical_terms(text: str) -> list[str]:
    """用模式匹配从文本中提取技术术语。

    匹配 camelCase、snake_case、CONSTANT_CASE 及其他技术命名模式。
    """
    patterns = [
        r"[a-z]+[A-Z][a-zA-Z]*",  # 驼峰命名（camelCase）
        r"[a-z]+_[a-z_]+",  # 下划线命名（snake_case）
        r"[A-Z][A-Z0-9_]+",  # 常量大写命名（CONSTANT_CASE）
        r"[a-zA-Z]+(?:Service|Manager|Handler|Factory|Builder|Config|Util|Helper)",  # 常见技术后缀
    ]

    terms = []
    for pattern in patterns:
        matches = re.findall(pattern, text)
        terms.extend(matches)

    # 去重并过滤常见停用词
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being"}
    terms = [t for t in set(terms) if t.lower() not in stop_words and len(t) > 2]

    return terms


def is_question(text: str) -> bool:
    """判断文本是否为疑问句。"""
    text = text.strip()
    question_patterns = [
        r"^\s*(what|how|why|when|where|who|which|is|are|can|could|should|would|do|does|did)\b",
        r"\?\s*$",
        r"怎么|如何|为什么|什么|哪|谁|多少|能否|可以|应该",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in question_patterns)


def detect_memory_gap(query: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """智能记忆缺口检测。

    分析检索结果以判定缺口类型：
    - low_confidence_retrieval：有结果但得分都很低
    - memory_gap：无结果且查询含技术术语
    - question_gap：无结果且查询是疑问句

    Args:
        query: 检索查询文本
        items: 检索结果列表，每项含 'score' 字段

    Returns:
        含缺口类型、消息与建议的字典；未检测到缺口时返回 None
    """
    # 情况 1：有结果但置信度都很低。阈值 0.3 之下宁可提示缺口，也不拿弱命中误导
    if items and all(item.get("score", 0) < 0.3 for item in items):
        max_score = max(item.get("score", 0) for item in items)
        return {
            "type": "low_confidence_retrieval",
            "message": f"检索到 {len(items)} 条结果，但置信度较低（最高 {max_score:.2f}）",
            "suggestion": "可能是查询方式不匹配，尝试调整关键词或使用 memory_search 精确搜索",
        }

    # 情况 2：无结果且查询含技术术语。至少 2 个术语才视为技术性查询，避免误报
    if not items:
        technical_terms = extract_technical_terms(query)
        if len(technical_terms) >= 2:
            return {
                "type": "memory_gap",
                "message": f"检测到记忆缺口：'{query}' 无匹配记忆",
                "technical_terms": technical_terms,
                "suggestion": "如掌握相关知识，请调用 memory_remember 补充",
            }

    # 情况 3：无结果且查询是疑问句
    if not items and is_question(query):
        return {
            "type": "question_gap",
            "message": f"问题 '{query}' 无匹配记忆",
            "suggestion": "解答后可调用 memory_remember 记录答案",
        }

    return None
