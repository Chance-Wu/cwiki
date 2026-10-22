"""异步索引器：将 Markdown 文件同步到 SQLite 以加速检索。"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import aiosqlite

from packages.domain.text_utils import format_memory_for_embedding

logger = logging.getLogger(__name__)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

from packages.retrieval.embedding import get_embedding_service
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.vector_index import VectorIndex


def _normalize_path(file_path: str | Path) -> str:
    """以绝对路径 + 平台原生大小写规范作为索引键。"""
    return os.path.normcase(os.path.abspath(file_path))


class MemoryIndexer:
    """将 Markdown 文件索引到 SQLite 以实现快速检索。"""

    def __init__(
        self,
        db_path: str,
        file_store: FileStore,
        vector_index_path: str | None = None,
        embedding_dimensions: int | None = None,
    ) -> None:
        self.db_path = db_path
        self.file_store = file_store
        self._observer: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._embedding_service = get_embedding_service()
        self._db: aiosqlite.Connection | None = None

        # 未显式指定时沿用 embedding 服务的向量维度
        dims = embedding_dimensions or self._embedding_service.dimensions
        self.vector_index = VectorIndex(
            dimensions=dims,
            index_path=vector_index_path or storage_config.vector_index_path,
        )

    async def _get_db(self) -> aiosqlite.Connection:
        """返回持久连接，首次调用时创建（避免重复建连与设置 PRAGMA 的开销）。

        PRAGMA 设置：
        - WAL 日志：支持读写并发，崩溃安全；提交先进 -wal 文件，
          由 cwiki-data/sync.py 在同步前执行 wal_checkpoint(TRUNCATE)
          合入主库，保证随 Git 提交的 .db 完整。
        - synchronous=NORMAL：配合 WAL 安全，远快于 FULL。
        - cache_size=-4000：4 MB 页缓存（负数单位为 KiB）。
        - temp_store=MEMORY：临时表/排序在内存中完成。
        """
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.execute("PRAGMA cache_size=-4000")
            await self._db.execute("PRAGMA temp_store=MEMORY")
        return self._db

    async def close(self) -> None:
        """关闭持久连接（应用关闭时调用）。"""
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def init_db(self) -> None:
        """初始化 SQLite 数据库与记忆索引表。"""
        db = await self._get_db()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS memory_index (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                type TEXT NOT NULL,
                tags TEXT,
                related TEXT,
                version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                source TEXT DEFAULT 'mcp',
                workspace TEXT,
                created TEXT NOT NULL,
                updated TEXT NOT NULL,
                file_path TEXT NOT NULL
            )
        """)
        try:
            await db.execute("ALTER TABLE memory_index ADD COLUMN source TEXT DEFAULT 'mcp'")
        except sqlite3.OperationalError:
            # 重复加列等预期失败；其他异常类型（如磁盘错误）不吞
            logger.debug("Schema migration: ADD COLUMN source skipped (may already exist)")
        try:
            await db.execute("ALTER TABLE memory_index RENAME COLUMN project TO workspace")
        except sqlite3.OperationalError:
            logger.debug("Schema migration: RENAME COLUMN project skipped (may already exist)")
        try:
            await db.execute("ALTER TABLE memory_index ADD COLUMN workspace TEXT")
        except sqlite3.OperationalError:
            logger.debug("Schema migration: ADD COLUMN workspace skipped (may already exist)")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_index(type)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_index(status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_memory_file_path ON memory_index(file_path)
        """)
        await db.commit()

    async def index_memory(
        self,
        memory: MemoryFile,
        embedding: list[float] | None = None,
        update_vector: bool = True,
        file_path: str | Path | None = None,
        commit: bool = True,
    ) -> None:
        """将单条记忆写入 SQLite 索引与向量索引。

        Args:
            memory: 待索引的记忆文件。
            embedding: 可选的预计算 embedding；未提供时会现场生成。
            update_vector: 为 False 时跳过向量索引更新。
            file_path: 实际文件路径；未提供时按 ID 定位。
        """
        if file_path is None:
            file_path = memory.file_path
        if file_path is None:
            file_path = self.file_store._find_file_by_id(
                memory.workspace or "chat", memory.type, memory.id
            )
        if file_path is None:
            file_path = self.file_store._get_file_path(
                memory.workspace or "chat",
                memory.type,
                self.file_store._make_filename(memory.id, memory.title),
            )

        db = await self._get_db()
        await db.execute(
            """
            INSERT OR REPLACE INTO memory_index
            (id, title, content, type, tags, related, version, status, source, workspace, created, updated, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                memory.id,
                memory.title,
                memory.content,
                memory.type,
                str(memory.tags),
                str(memory.related),
                memory.version,
                memory.status,
                memory.source,
                memory.workspace,
                memory.created.isoformat(),
                memory.updated.isoformat(),
                _normalize_path(file_path),
            ),
        )
        if commit:
            await db.commit()

        # 优先使用传入的 embedding，否则现场生成
        if update_vector:
            if embedding is None:
                text = format_memory_for_embedding(memory.title, memory.content)
                embedding = await self._embedding_service.generate_embedding(text)
            if embedding:
                self.vector_index.add(
                    memory.id,
                    embedding,
                    metadata={"type": memory.type, "tags": memory.tags},
                )

    async def remove_from_index(self, memory_id: str) -> None:
        """从 SQLite 与向量索引中同时移除一条记忆。"""
        db = await self._get_db()
        await db.execute("DELETE FROM memory_index WHERE id = ?", (memory_id,))
        await db.commit()
        self.vector_index.remove(memory_id)

    async def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """在 SQLite 索引中搜索记忆。"""
        db = await self._get_db()
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            """
            SELECT * FROM memory_index
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY updated DESC
            LIMIT ?
        """,
            (f"%{query}%", f"%{query}%", limit),
        )

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """按 ID 获取单条记忆。"""
        db = await self._get_db()
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM memory_index WHERE id = ?", (memory_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_memories(
        self,
        status: str | None = None,
        type: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按可选过滤条件与分页列出记忆。"""
        db = await self._get_db()
        db.row_factory = aiosqlite.Row

        query = "SELECT * FROM memory_index WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if type:
            query += " AND type = ?"
            params.append(type)

        query += " ORDER BY updated DESC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        if offset:
            query += " OFFSET ?"
            params.append(offset)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def count_memories(self, status: str | None = None, type: str | None = None) -> int:
        """按可选过滤条件统计记忆数。"""
        db = await self._get_db()
        query = "SELECT COUNT(*) FROM memory_index WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if type:
            query += " AND type = ?"
            params.append(type)

        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def sync_all(self) -> None:
        """将全部 Markdown 文件同步到 SQLite 索引。"""
        memories = await asyncio.to_thread(self.file_store.list)
        valid_ids = {m.id for m in memories}
        # 只有 active 记忆才允许持有向量；archived 记忆不得重新入索引。
        active_ids = {m.id for m in memories if m.status == "active"}

        # 构建已索引记忆的映射，用于 mtime 增量比较
        db = await self._get_db()
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT id, updated, file_path FROM memory_index")
        existing_rows = await cursor.fetchall()
        existing_map = {row["id"]: dict(row) for row in existing_rows}

        indexed_count = 0
        skipped_count = 0
        for memory in memories:
            # 文件自上次索引后未变化则跳过
            if memory.id in existing_map:
                existing = existing_map[memory.id]
                try:
                    if memory.file_path is None:
                        continue
                    file_mtime = os.path.getmtime(memory.file_path)
                    # 路径变化时即使 mtime 未变也要重索引：重命名保留 mtime，
                    # 仅靠时间戳会漏掉 file_path 修复。
                    current_path = os.path.normcase(os.path.abspath(memory.file_path))
                    path_changed = existing["file_path"] != current_path
                    # 解析 ISO 时间戳以与 mtime 比较
                    from datetime import datetime

                    indexed_updated_str = existing["updated"]
                    if indexed_updated_str:
                        indexed_dt = datetime.fromisoformat(indexed_updated_str)
                        indexed_ts = indexed_dt.timestamp()
                        if not path_changed and indexed_ts >= file_mtime:
                            skipped_count += 1
                            continue
                except (ValueError, OSError):
                    pass  # 解析失败则回退为重新索引
            # 批量操作时不立即提交，最后统一提交
            await self.index_memory(memory, update_vector=memory.id in active_ids, commit=False)
            indexed_count += 1

        # 批量索引完成后统一提交
        db = await self._get_db()
        await db.commit()

        # 清理向量索引中的孤儿/过期向量：MD 已删除或已非 active 的
        # 记忆不应再参与语义检索（MD 与 SQLite/索引双轨保持一致）。
        orphan_ids = set(self.vector_index.vectors.keys()) - active_ids
        for oid in orphan_ids:
            self.vector_index.remove(oid)
        if orphan_ids:
            logger.info("Removed %d orphan/stale vectors", len(orphan_ids))

        # 清理 SQLite 中的孤儿行（MD 已删除的记忆），保持双轨一致
        db = await self._get_db()
        cursor = await db.execute("SELECT id FROM memory_index")
        rows = await cursor.fetchall()
        sqlite_ids = {row[0] for row in rows}
        orphan_sqlite_ids = sqlite_ids - valid_ids
        if orphan_sqlite_ids:
            # 批量删除而非逐个删除
            placeholders = ",".join("?" * len(orphan_sqlite_ids))
            await db.execute(
                f"DELETE FROM memory_index WHERE id IN ({placeholders})",
                tuple(orphan_sqlite_ids),
            )
            await db.commit()
            logger.info("Removed %d orphan SQLite index rows", len(orphan_sqlite_ids))

        await asyncio.to_thread(self.vector_index.save)

        logger.info(
            "Synced %d memories (%d indexed, %d skipped unchanged)",
            len(memories),
            indexed_count,
            skipped_count,
        )

    async def save_vector_index(self) -> None:
        """将向量索引写入磁盘（异步封装）。"""
        await asyncio.to_thread(self.vector_index.save)

    async def semantic_search(
        self,
        query_vector: list[float],
        limit: int = 10,
        threshold: float = 0.0,
        *,
        allowed_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """先筛出 active 的已索引行再做排序；元数据单次查询取出。

        提供 allowed_ids 时把过滤条件下推到 SQL，避免整表加载。
        """
        db = await self._get_db()
        db.row_factory = aiosqlite.Row

        if allowed_ids is not None:
            if not allowed_ids:
                return []
            placeholders = ",".join("?" for _ in allowed_ids)
            cursor = await db.execute(
                f"SELECT * FROM memory_index WHERE status = 'active' AND id IN ({placeholders})",
                list(allowed_ids),
            )
        else:
            cursor = await db.execute("SELECT * FROM memory_index WHERE status = 'active'")
        rows = await cursor.fetchall()
        eligible = {row["id"]: dict(row) for row in rows}

        results = await asyncio.to_thread(
            self.vector_index.search,
            query_vector,
            top_k=limit,
            threshold=threshold,
            allowed_ids=set(eligible),
        )
        return [{**eligible[mid], "similarity_score": score} for mid, score in results]

    async def semantic_search_text(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.0,
        *,
        allowed_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """以自然语言文本检索记忆。"""
        if allowed_ids is not None and not allowed_ids:
            return []
        embedding = await self._embedding_service.generate_embedding(query)
        if not embedding:
            return []
        return await self.semantic_search(
            embedding, limit=limit, threshold=threshold, allowed_ids=allowed_ids
        )

    def start_watching(self) -> None:
        """开始监听文件变更。"""
        if not WATCHDOG_AVAILABLE:
            logger.warning("watchdog not installed, file watching disabled")
            return

        if self._observer:
            return

        # 保存事件循环引用：watchdog 回调在独立线程触发，
        # 需通过 run_coroutine_threadsafe 调度回事件循环执行
        self._loop = asyncio.get_event_loop()

        class MemoryFileHandler(FileSystemEventHandler):
            def __init__(self, indexer: MemoryIndexer) -> None:
                self.indexer = indexer
                self._debounce: dict[str, float] = {}
                self._debounce_seconds = 2.0

            def _should_process(self, file_path: str) -> bool:
                """判断文件事件是否需要处理（防抖检查）。"""
                now = time.monotonic()
                last_time = self._debounce.get(file_path, 0)
                if now - last_time < self._debounce_seconds:
                    return False
                self._debounce[file_path] = now
                # 周期性清理旧条目，防止防抖字典无限膨胀
                if len(self._debounce) > 100:
                    cutoff = now - self._debounce_seconds * 2
                    self._debounce = {k: v for k, v in self._debounce.items() if v > cutoff}
                return True

            def on_created(self, event: Any) -> None:
                loop = self.indexer._loop
                assert loop is not None
                if (
                    not event.is_directory
                    and Path(event.src_path).suffix.lower() == ".md"
                    and self._should_process(event.src_path)
                ):
                    asyncio.run_coroutine_threadsafe(self._handle_change(event.src_path), loop)

            def on_modified(self, event: Any) -> None:
                loop = self.indexer._loop
                assert loop is not None
                if (
                    not event.is_directory
                    and Path(event.src_path).suffix.lower() == ".md"
                    and self._should_process(event.src_path)
                ):
                    asyncio.run_coroutine_threadsafe(self._handle_change(event.src_path), loop)

            def on_deleted(self, event: Any) -> None:
                loop = self.indexer._loop
                assert loop is not None
                if not event.is_directory and Path(event.src_path).suffix.lower() == ".md":
                    asyncio.run_coroutine_threadsafe(self._handle_delete(event.src_path), loop)

            def on_moved(self, event: Any) -> None:
                loop = self.indexer._loop
                assert loop is not None
                if not event.is_directory and (
                    Path(event.src_path).suffix.lower() == ".md"
                    or Path(event.dest_path).suffix.lower() == ".md"
                ):
                    asyncio.run_coroutine_threadsafe(
                        self._handle_move(event.src_path, event.dest_path), loop
                    )

            async def _handle_change(self, file_path: str) -> None:
                try:
                    memory = self.indexer.file_store.load_from_path(file_path)
                    if memory:
                        is_active = memory.status == "active"
                        await self.indexer.index_memory(
                            memory, file_path=file_path, update_vector=is_active
                        )
                        if not is_active and memory.id in self.indexer.vector_index.vectors:
                            self.indexer.vector_index.remove(memory.id)
                            await self.indexer.save_vector_index()
                except Exception as e:
                    logger.error("Error indexing %s: %s", file_path, e)

            async def _handle_move(self, src_path: str, dest_path: str) -> None:
                # 保持先删后建的顺序，覆盖仅大小写变化的重命名。
                if Path(src_path).suffix.lower() == ".md":
                    await self._handle_delete(src_path)
                if Path(dest_path).suffix.lower() == ".md":
                    await self._handle_change(dest_path)

            async def _handle_delete(self, file_path: str) -> None:
                try:
                    db = await self.indexer._get_db()
                    db.row_factory = aiosqlite.Row
                    cursor = await db.execute(
                        "SELECT id FROM memory_index WHERE file_path = ?",
                        (_normalize_path(file_path),),
                    )
                    row = await cursor.fetchone()
                    if row:
                        await self.indexer.remove_from_index(row["id"])
                except Exception as e:
                    logger.error("Error removing %s: %s", file_path, e)

        self._observer = Observer()
        handler = MemoryFileHandler(self)
        self._observer.schedule(handler, str(self.file_store.base_path), recursive=True)
        self._observer.start()
        logger.info("Watching for changes in %s", self.file_store.base_path)

    def stop_watching(self) -> None:
        """停止监听文件变更。"""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
