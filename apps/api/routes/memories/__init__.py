"""已验证记忆端点。

按职责拆分：
- ``tags``      标签管理（独立 /v1/tags 前缀）
- ``crud``      记忆列表 / 详情 / 更新 / 删除 / 优化 / 生命周期
- ``relations`` 关系图与关系管理
- ``detail``    版本 / 反馈 / 检索历史

各子模块向 ``_router.router``（单实例）注册端点。
``tags_router`` 保持独立前缀由 main.py 单独挂载。
"""

from __future__ import annotations

from apps.api.routes.memories import crud as _crud  # noqa: F401
from apps.api.routes.memories import detail as _detail  # noqa: F401
from apps.api.routes.memories import relations as _relations  # noqa: F401
from apps.api.routes.memories._router import router
from apps.api.routes.memories.crud import (
    delete_memory as delete_memory,
)
from apps.api.routes.memories.crud import (
    get_memory_lifecycle as get_memory_lifecycle,
)
from apps.api.routes.memories.crud import (
    update_memory as update_memory,
)
from apps.api.routes.memories.relations import (
    get_memory_relations as get_memory_relations,
)
from apps.api.routes.memories.tags import tags_router
from packages.domain.task_queue import queue as task_queue

__all__ = [
    "delete_memory",
    "get_memory_lifecycle",
    "get_memory_relations",
    "router",
    "tags_router",
    "task_queue",
    "update_memory",
]
