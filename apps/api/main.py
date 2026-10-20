"""cwiki FastAPI 应用工厂与 CLI 入口。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import typer
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.deps import get_memory_indexer, init_storage_components
from packages.domain.config import parasitic_evolution_config, scheduler_config
from packages.domain.database import async_session_maker, close_db, init_db
from packages.domain.scheduler import PeriodicScheduler
from packages.domain.settings import get_settings
from packages.domain.task_queue import shutdown as task_queue_shutdown
from packages.domain.task_queue import startup as task_queue_startup
from packages.domain.version import app_version
from packages.retrieval.engine import get_retrieval_engine
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore
from packages.storage.indexer import MemoryIndexer

logger = logging.getLogger(__name__)

_indexer: MemoryIndexer | None = None
_scheduler: PeriodicScheduler | None = None


async def _sync_index_background(indexer: MemoryIndexer) -> None:
    """同步索引后预热缓存，串行执行避免资源峰值"""
    try:
        await indexer.sync_all()
        logger.info("Background index sync completed")
        # 索引同步完成后立即预热缓存（串行，避免同时执行）
        await _warm_up_retrieval_caches()
    except Exception:
        logger.exception("Background index sync failed")


async def _warm_up_retrieval_caches() -> None:
    """预热 BM25 + embedding 缓存，让首批查询无需现场构建。"""
    try:
        engine = get_retrieval_engine()
        async with async_session_maker() as db:
            summary = await engine.warm_up(db)
            logger.info(
                "Retrieval cache warm-up completed: %d workspaces, %d caches built",
                summary["workspaces_found"],
                summary["caches_built"],
            )
    except Exception:
        logger.exception("Retrieval cache warm-up failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用 lifespan 处理器：负责启动/关闭流程。"""
    global _indexer

    logger.info("cwiki API starting up")
    # 安全告警（W7-05 审计）：监听非回环地址且未配置 token 时，
    # 局域网内任何设备都能调用全部端点（含 data/import 与死信重试）
    cfg = get_settings()
    if cfg.api_host not in ("127.0.0.1", "localhost") and not cfg.api_auth_token:
        logger.warning(
            "API is listening on %s without an auth token — set app.auth_token "
            "(config.local.yaml) to require Bearer auth on LAN-exposed endpoints",
            cfg.api_host,
        )
    await init_db()
    await task_queue_startup()

    # 周期调度器：按固定间隔触发后台任务（自动整合/复习提醒/_meta 导出）
    global _scheduler
    from packages.domain.task_queue import queue as task_queue

    _scheduler = PeriodicScheduler(queue=task_queue)
    if parasitic_evolution_config.auto_consolidate_enabled:
        _scheduler.add(
            "auto_consolidate_similar",
            scheduler_config.auto_consolidate_interval_hours * 3600,
        )
    if parasitic_evolution_config.review_reminders_enabled:
        _scheduler.add(
            "check_review_reminders",
            scheduler_config.review_reminders_interval_hours * 3600,
        )
    _scheduler.add(
        "periodic_meta_export",
        scheduler_config.meta_export_interval_hours * 3600,
    )
    await _scheduler.start()

    # 一次性清理：拒绝即删除语义，移除历史遗留的 rejected 候选
    try:
        from sqlalchemy import CursorResult
        from sqlalchemy import delete as sa_delete

        from packages.domain.models import CandidateMemory

        async with async_session_maker() as cleanup_db:
            result = await cleanup_db.execute(
                sa_delete(CandidateMemory).where(CandidateMemory.status == "rejected")
            )
            # DELETE 语句返回 CursorResult，rowcount 仅在其上可用
            rowcount = cast(CursorResult[Any], result).rowcount
            if rowcount > 0:
                await cleanup_db.commit()
                logger.info("Cleaned up %d historical rejected candidates", rowcount)
    except Exception:
        logger.warning("Failed to clean up rejected candidates", exc_info=True)

    file_store = FileStore(storage_config.memory_dir)
    _indexer = MemoryIndexer(storage_config.index_db_path, file_store)
    await _indexer.init_db()
    init_storage_components(file_store, _indexer)
    # 向量检索以 vectors.npz 为权威源：DB embedding 列由单一任务双写维护，
    # 但历史/导入数据可能为空，检索不再依赖它
    get_retrieval_engine().set_vector_source(lambda: get_memory_indexer().vector_index)
    # 优化：串行执行，sync 完成后自动 warm_up，避免资源峰值
    asyncio.create_task(_sync_index_background(_indexer))
    _indexer.start_watching()

    yield

    if _indexer:
        _indexer.stop_watching()
        await _indexer.save_vector_index()
        await _indexer.close()
    if _scheduler:
        await _scheduler.stop()
    await task_queue_shutdown()
    await close_db()
    logger.info("cwiki API shut down")


def create_app() -> FastAPI:
    """FastAPI 应用工厂。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        # 版本号权威源是 pyproject.toml，勿在此处硬编码（见 packages/domain/version.py）
        version=app_version(),
        description="Agent Persistent Memory Infrastructure",
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 领域错误全局异常处理器
    from packages.domain.errors import AppError

    @app.exception_handler(AppError)
    async def app_error_handler(request: Any, exc: AppError) -> Any:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "code": exc.code},
        )

    # 挂载全部路由（每个路由自带 /v1 前缀）
    from apps.api.routes.agent_capture import router as agent_capture_router
    from apps.api.routes.agent_sessions import router as agent_sessions_router
    from apps.api.routes.agents import router as agents_router
    from apps.api.routes.candidates import router as candidates_router
    from apps.api.routes.config import router as config_router
    from apps.api.routes.context import router as context_router
    from apps.api.routes.data_io import router as data_io_router
    from apps.api.routes.events import router as events_router
    from apps.api.routes.file_memories import router as file_memories_router
    from apps.api.routes.health import router as health_router
    from apps.api.routes.markdown_export import router as markdown_export_router
    from apps.api.routes.memories import router as memories_router
    from apps.api.routes.memories import tags_router
    from apps.api.routes.memory_quality import router as memory_quality_router
    from apps.api.routes.memory_status import router as memory_status_router
    from apps.api.routes.notes import router as notes_router
    from apps.api.routes.reviews import router as reviews_router
    from apps.api.routes.search import router as search_router
    from apps.api.routes.skills import router as skills_router
    from apps.api.routes.spaced_review import router as spaced_review_router
    from apps.api.routes.system import router as system_router
    from apps.api.routes.task_queue import router as task_queue_router
    from apps.api.routes.weekly_review import router as weekly_review_router
    from apps.api.routes.workspaces import router as workspaces_router

    app.include_router(health_router)
    app.include_router(markdown_export_router)
    app.include_router(workspaces_router)
    app.include_router(agents_router)
    app.include_router(events_router)
    app.include_router(candidates_router)
    app.include_router(memories_router)
    app.include_router(tags_router)
    app.include_router(reviews_router)
    app.include_router(context_router)
    app.include_router(search_router)
    app.include_router(memory_quality_router)
    app.include_router(memory_status_router)
    app.include_router(agent_sessions_router)
    app.include_router(agent_capture_router)
    app.include_router(file_memories_router)
    app.include_router(notes_router)
    app.include_router(data_io_router)
    app.include_router(skills_router)
    app.include_router(spaced_review_router)
    app.include_router(config_router)
    app.include_router(system_router)
    app.include_router(task_queue_router)
    app.include_router(weekly_review_router)

    return app


app = create_app()


# CLI 入口
cli_app = typer.Typer(name="cwiki", help="cwiki API server")


@cli_app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    port: int = typer.Option(5172, help="Port to listen on"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
    log_level: str = typer.Option("info", help="Log level"),
) -> None:
    """启动 cwiki API 服务。"""
    uvicorn.run(
        "apps.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@cli_app.command()
def rebuild_index() -> None:
    """从 Markdown 文件重建 SQLite 索引与向量索引。"""
    import asyncio

    from packages.storage import config as storage_config
    from packages.storage.file_store import FileStore
    from packages.storage.indexer import MemoryIndexer

    async def _rebuild() -> None:
        file_store = FileStore(storage_config.memory_dir)
        idx = MemoryIndexer(storage_config.index_db_path, file_store)
        await idx.init_db()
        memories = file_store.list()
        valid_ids = {m.id for m in memories}
        for m in memories:
            await idx.index_memory(m)
        orphan_ids = set(idx.vector_index.vectors.keys()) - valid_ids
        for oid in orphan_ids:
            idx.vector_index.remove(oid)
        await asyncio.to_thread(idx.vector_index.save)
        logger.info(
            "Rebuilt index: %d memories indexed, %d vectors", len(memories), idx.vector_index.size()
        )

    asyncio.run(_rebuild())


def cli() -> None:
    """CLI 入口（由 pyproject.toml scripts 引用）。"""
    cli_app()


if __name__ == "__main__":
    cli()
