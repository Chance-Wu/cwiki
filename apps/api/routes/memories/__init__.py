"""已验证记忆端点。

按职责拆分：
- ``tags``      标签管理（独立 /v1/tags 前缀）
- ``merge``     合并建议 / 整理 / 合并执行
- ``crud``      记忆列表 / 详情 / 更新 / 优化 / 生命周期
- ``relations`` 关系图与关系管理
- ``detail``    版本 / 反馈 / 检索历史

各子模块向 ``_router.router``（单实例）注册端点，下面的导入顺序
即注册顺序——具体路径端点（merge）必须先于 ``/{memory_id}`` 动态
段导入，否则路径参数会吞掉具体路由（isort: off 保持顺序）。
``tags_router`` 保持独立前缀由 main.py 单独挂载。
"""

from __future__ import annotations

from apps.api.routes.memories._router import router
from apps.api.routes.memories.tags import tags_router
from packages.domain.task_queue import queue as task_queue

# isort: off
# 注册顺序敏感：merge（具体路径）→ crud（/{memory_id} 动态段）→ relations → detail
from apps.api.routes.memories import merge as _merge  # noqa: F401  具体路径先注册
from apps.api.routes.memories import merge_history as _merge_history  # noqa: F401
from apps.api.routes.memories import crud as _crud  # noqa: F401
from apps.api.routes.memories import relations as _relations  # noqa: F401
from apps.api.routes.memories import detail as _detail  # noqa: F401
# isort: on

from apps.api.routes.memories._shared import (
    invalidate_merge_suggestions_cache as invalidate_merge_suggestions_cache,
)
from apps.api.routes.memories.crud import (
    get_memory_lifecycle as get_memory_lifecycle,
)
from apps.api.routes.memories.crud import (
    update_memory as update_memory,
)
from apps.api.routes.memories.merge import MergeRequest as MergeRequest
from apps.api.routes.memories.relations import (
    get_memory_relations as get_memory_relations,
)

__all__ = [
    "MergeRequest",
    "get_memory_lifecycle",
    "get_memory_relations",
    "invalidate_merge_suggestions_cache",
    "router",
    "tags_router",
    "task_queue",
    "update_memory",
]
