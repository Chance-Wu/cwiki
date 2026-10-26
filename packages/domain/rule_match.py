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
            ws.strip().casefold()
            for ws in (workspace_name, workspace_id)
            if ws.strip()
        }
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

    if keywords:
        haystack = f"{title}\n{content}".casefold()
        non_empty = [kw.casefold() for kw in keywords if kw.strip()]
        if non_empty and not any(kw in haystack for kw in non_empty):
            return False

    return True
