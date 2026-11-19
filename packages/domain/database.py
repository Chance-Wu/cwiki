"""异步 SQLAlchemy 引擎、会话工厂与 Base 声明基类。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from packages.domain.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 SQLAlchemy 模型的声明基类。"""


def _create_engine() -> AsyncEngine:
    """按数据库类型创建异步引擎。

    SQLite 使用 QueuePool（连接按会话独立）：WAL 模式下并发读互不阻塞，
    并发写靠 busy_timeout 忙等；每个会话独立事务，请求 A 的 commit 不再
    连带请求 B 已 flush 的语句（旧 StaticPool 单连接的交叉提交隐患）。
    """
    if settings.is_sqlite:
        engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            connect_args={"check_same_thread": False},
            pool_size=10,
            max_overflow=20,
            pool_timeout=30,
            pool_pre_ping=True,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-4000")  # 优化：从 8MB 缩减到 4MB
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute(
                "PRAGMA wal_autocheckpoint=100"
            )  # 优化：自动 checkpoint，减少 WAL 文件堆积
            # 多连接后并发写靠 SQLite 锁串行化；5s 忙等吸收毫秒级写事务竞争
            cursor.execute("PRAGMA busy_timeout=5000")
            # SQLite 默认关闭外键约束；开启后 DDL 里的 ON DELETE CASCADE
            # 才会在删除 memory/workspace 时自动清理关系行。
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    else:
        return create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_timeout=30,
        )


engine = _create_engine()

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：产出一个异步数据库会话。

    请求结束时统一提交、异常时回滚，保证每个请求一个事务。
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """初始化数据库引擎并创建缺失的表。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """释放数据库引擎资源。"""
    await engine.dispose()
