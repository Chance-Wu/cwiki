"""memories 路由的共享 router 实例。

各子模块（merge/crud/relations/detail）从此处导入同一 router 并
注册端点，避免二阶嵌套 include_router（FastAPI 0.150 的
_IncludedRouter 懒匹配对嵌套 include 返回 404）。

注册顺序由 ``__init__.py`` 的子模块导入顺序决定：
具体路径端点（merge）必须先于 ``/{memory_id}`` 动态段导入。
"""

from __future__ import annotations

from fastapi import APIRouter

from packages.domain.config import API_V1_PREFIX

router = APIRouter(prefix=f"{API_V1_PREFIX}/memories", tags=["memories"])
