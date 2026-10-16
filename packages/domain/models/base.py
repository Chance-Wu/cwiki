"""全部 ORM 模型的公共自定义类型与声明基类。"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import String, Text, TypeDecorator
from sqlalchemy.types import JSON

from packages.domain.database import Base

__all__ = ["Base", "JSONBType", "UUIDType", "VectorType"]


class UUIDType(TypeDecorator[str]):
    """跨数据库 UUID 类型 —— 以 String(36) 存储以保证可移植性。"""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        # 统一规范化为标准 UUID 字符串形式，避免不同输入格式落库不一致
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:  # type: ignore[override]
        if value is None:
            return None
        return uuid.UUID(value)


class JSONBType(TypeDecorator[Any]):
    """跨数据库 JSON 类型。"""

    impl = JSON
    cache_ok = True


class VectorType(TypeDecorator[str]):
    """跨数据库向量类型 —— 以 JSON 文本形式存储（SQLite 无原生向量列）。"""

    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        # 向量以 JSON 数组文本落库，读取时再反序列化回 float 列表
        if isinstance(value, (list, tuple)):
            return json.dumps(list(value))
        return str(value) if value is not None else None

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, str):
            result: list[float] = json.loads(value)
            return result
        return None
