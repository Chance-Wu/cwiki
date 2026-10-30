"""写入规则共用的匹配语义。

write_policy（写入后审核方式）与 write_decisions（是否准入）使用同一套
workspace/type/tags/keyword/regex 匹配规则，避免两套配置行为漂移。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# 匹配维度的硬限制；解析、API 模型与前端计数器共用同一组数值
MAX_MATCH_VALUES = 20
MAX_KEYWORD_VALUES = 40
MAX_REGEX_VALUES = 20
MAX_MATCH_VALUE_CHARS = 100


def matches_fields(
    *,
    workspaces: Sequence[str],
    types: Sequence[str],
    tags: Sequence[str],
    keywords: Sequence[str],
    regexes: Sequence[str] = (),
    workspace_name: str,
    workspace_id: str,
    memory_type: str,
    memory_tags: Sequence[str],
    title: str,
    content: str,
) -> bool:
    """所有非空字段之间是 AND；type/workspace 多值任一命中，tags 需全部存在。

    keyword 与 regex 同属文本维度：两者都配置时任一命中即可，二者都不命中才失败。
    """
    if workspaces:
        candidates = {ws.strip().casefold() for ws in (workspace_name, workspace_id) if ws.strip()}
        if not candidates or not candidates.intersection(
            item.casefold() for item in workspaces if item.strip()
        ):
            return False

    if types and memory_type.strip().casefold() not in {
        item.casefold() for item in types if item.strip()
    }:
        return False

    if tags:
        available = {tag.strip().casefold() for tag in memory_tags}
        required = [tag.casefold() for tag in tags if tag.strip()]
        if required and not all(tag in available for tag in required):
            return False

    if keywords or regexes:
        keyword_values = [kw.casefold() for kw in keywords if kw.strip()]
        regex_values = [pattern for pattern in regexes if pattern.strip()]
        # 空白值不算约束，全部为空时该维度不限制（与历史行为一致）
        if keyword_values or regex_values:
            haystack = f"{title}\n{content}"
            keyword_hit = any(kw in haystack.casefold() for kw in keyword_values)
            # 正则按原文匹配，保留大小写语义；需要忽略大小写时由正则自身写 (?i)
            regex_hit = any(re.search(pattern, haystack) for pattern in regex_values)
            if not (keyword_hit or regex_hit):
                return False

    return True
