"""标签的 SQL 查询条件。

标签以 JSON 数组存在 SQLite 文本列中，序列化会把中文转义为 ``\\uXXXX``，
直接对列文本 LIKE 匹配中文会静默失效（含 ``"`` / ``%`` / ``_`` 时也会误判）。
统一用 JSON1 的 ``json_each`` 按数组元素精确比较。
"""

from __future__ import annotations

from sqlalchemy import exists, func, select
from sqlalchemy.sql.elements import ColumnElement

from packages.domain.models import Memory


def memory_has_tag(tag: str) -> ColumnElement[bool]:
    """返回「tags 数组包含指定标签」的 SQL 条件。"""
    tag_values = func.json_each(Memory.tags).table_valued("value").alias("tag_values")
    return exists(select(1).select_from(tag_values).where(tag_values.c.value == tag))
