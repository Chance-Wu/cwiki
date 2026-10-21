"""后台任务共享辅助。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_embedding_service(ctx: dict[str, Any]) -> Any:
    """从上下文取 embedding 服务，缺失时回退创建单例。"""
    svc = ctx.get("embedding_service")
    if not svc:
        from packages.retrieval.embedding import get_embedding_service

        logger.warning("embedding_service not in context, using fallback singleton")
        svc = get_embedding_service()
    return svc
