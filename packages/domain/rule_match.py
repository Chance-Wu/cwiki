"""写入规则共用的匹配语义。

write_policy（写入后审核方式）与 write_decisions（是否准入）使用同一套
workspace/type/tags/keyword 匹配规则，避免两套配置行为漂移。
"""

from __future__ import annotations

from collections.abc import Sequence


def matches_fields(
    *,
    workspaces: Sequence[str],
    types: Sequence[str],
    tags: Sequence[str],
    keywords: Sequence[str],
    workspace_name: str,
    workspace_id: str,
    memory_type: str,
    memory_tags: Sequence[str],
    title: str,
    content: str,
) -> bool:
    """所有非空字段之间是 AND；type/workspace/keyword 多值任一命中，tags 需全部存在。"""
    if workspaces:
        candidates = {
            workspace_name.strip().casefold(),
            workspace_id.strip().casefold(),
        }
        if not candidates.intersection(item.casefold() for item in workspaces):
            return False

    if types and memory_type.strip().casefold() not in {item.casefold() for item in types}:
        return False

    if tags:
        available = {tag.strip().casefold() for tag in memory_tags}
        if not all(tag.casefold() in available for tag in tags):
            return False

    if keywords:
        haystack = f"{title}\n{content}".casefold()
        if not any(keyword.casefold() in haystack for keyword in keywords):
            return False

    return True
