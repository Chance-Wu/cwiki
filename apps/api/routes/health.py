"""健康检查端点，用于监控服务可用性和数据库连通性。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps import get_db
from packages.domain.config import API_V1_PREFIX
from packages.domain.schemas import ConsistencyReport, HealthResponse
from packages.storage.consistency import run_consistency_check

logger = logging.getLogger(__name__)

# 创建健康检查路由组，tags 用于 OpenAPI 文档分组
router = APIRouter(tags=["health"])


@router.get(f"{API_V1_PREFIX}/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """基础健康检查：验证数据库连通性并返回服务状态。

    通过执行 SELECT 1 探测数据库连接，根据结果返回整体健康状态。
    """
    db_status = "ok"
    try:
        # 轻量级查询探测数据库连接是否可用
        await db.execute(text("SELECT 1"))
    except SQLAlchemyError as e:
        # 仅捕获数据库相关异常，避免吞掉其他程序错误
        logger.warning("健康检查：数据库连接异常 - %s", e)
        db_status = f"error: {e}"

    # 数据库正常则整体健康，否则标记为降级状态
    overall_status = "healthy" if db_status == "ok" else "degraded"

    return HealthResponse(
        status=overall_status,
        database=db_status,
    )


@router.get(f"{API_V1_PREFIX}/consistency", response_model=ConsistencyReport)
async def consistency_check(db: AsyncSession = Depends(get_db)) -> ConsistencyReport:
    """三方数据一致性对账：DB / Markdown / 检索索引（只读报告，不做修复）。

    载体读取失败不抛异常，差异与错误原因在报告体中呈现，供运维排查漂移。
    """
    return await run_consistency_check(db)
