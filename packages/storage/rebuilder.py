"""DatabaseRebuilder：从 Markdown + _meta 文件重建 cwiki.db。

SQLite → Markdown 迁移的第 1.3 阶段。读取 ``cwiki-data/`` 下的全部
``.md`` 文件（经 FileStore）与 ``_meta/*.json`` 伴随文件
（经 MetaStore），在单个事务内重建 ``cwiki.db`` 中的记忆相关表。

除记忆本体与七类关系数据外，还恢复三类易丢数据：每记忆 _meta 中的
``versions``（版本快照，导出侧按 meta_version_limit 截断保留最新）与
``review_history``（复习事件史），以及 store 级
``_meta/_review_queue.json`` 中的候选审核队列（candidate_memory 全部
状态 + review 评审留痕）。

非记忆表（workspace、project、agent、session、event、episode、
agent_session、session_note）保持不动 —— 它们不体现在 Markdown 存储
中，重建后必须原样保留。``workspace`` 表额外从
``_meta/_workspaces.json``（旧版导出无此文件时退回 MD frontmatter）
恢复，使空库上的完整重建也能保住每条记忆的 workspace 归属。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.domain.models import (
    AgentSession,
    CandidateMemory,
    Evidence,
    Memory,
    MemoryConflict,
    MemoryFeedback,
    MemoryLifecycleEvent,
    MemoryRelation,
    MemoryUsage,
    MemoryVersion,
    Review,
    ReviewHistory,
    ReviewSchedule,
    SessionNote,
    Workspace,
)
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.meta_store import MetaStore

logger = logging.getLogger(__name__)

# 项目根 —— Alembic 必须从这里运行：alembic.ini / migrations/ 按 CWD
# 定位，且 config.yaml 中的数据库 URL 是相对项目根的路径
# （"./cwiki-data/cwiki.db"）。
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 结果数据类
# ---------------------------------------------------------------------------


@dataclass
class RebuildResult:
    """一次成功重建产出的统计信息。"""

    memory_count: int = 0
    relation_counts: dict[str, int] = field(default_factory=dict)
    workspace_map: dict[str, str] = field(default_factory=dict)
    skipped_files: list[str] = field(default_factory=list)
    candidate_count: int = 0
    review_count: int = 0
    capture_session_count: int = 0
    capture_note_count: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# 待清空表（按依赖顺序 —— 子表在前）
# ---------------------------------------------------------------------------

# 需要清空并从 MD/_meta 重新填充的记忆相关表。
# 顺序很重要：持有外键引用其他记忆表的表排在前（先删引用方）。
#
# 注意：retrieval_trace / retrieval_trace_item / proactive_push_record 为
# 运行时遥测（检索留痕与主动推送去重），依附会话生命周期而非知识本身，
# 有意不随重建保留 —— 清空后不再重灌，重建后为空是预期行为。
_MEMORY_TABLES_TO_CLEAR: list[str] = [
    "session_note",
    "agent_session",
    "retrieval_trace_item",
    "retrieval_trace",
    "proactive_push_record",
    "review_history",
    "review_schedule",
    "memory_relation",
    "memory_lifecycle_event",
    "memory_conflict",
    "memory_feedback",
    "memory_usage",
    "evidence",
    "review",
    "memory_version",
    "candidate_memory",
    "memory",
]


# ---------------------------------------------------------------------------
# 辅助函数：安全解析 datetime
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    """解析 ISO datetime 字符串，失败时返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 派生索引辅助（index.db + vectors.npz + vectors.json）
# ---------------------------------------------------------------------------


def index_files_present() -> tuple[bool, list[str]]:
    """检查派生索引文件是否齐备且非空。

    三个文件全部存在时向量索引才可加载：``index.db``（SQLite 索引）、
    ``vectors.npz``（embedding 矩阵）和 ``vectors.json``（向量 id/元数据
    伴随文件 —— ``VectorIndex.save()`` 写 npz 时一并写出；缺少它 npz
    无法加载）。任一文件缺失或为 0 字节即视为索引需要重建。

    返回 ``(all_present, missing_names)``。
    """
    from packages.storage import config as storage_config

    missing: list[str] = []
    for name, raw_path in (
        ("index.db", storage_config.index_db_path),
        ("vectors.npz", storage_config.vector_index_path),
        ("vectors.json", storage_config.vector_meta_path),
    ):
        path = Path(raw_path)
        if not path.exists() or path.stat().st_size == 0:
            missing.append(name)
    return not missing, missing


def indexed_active_count() -> int | None:
    """统计 ``memory_index``（index.db）中的 active 行数；不可读时返回 None。

    ``rebuild_vector_index()`` 只索引 ``status == "active"`` 的记忆，
    因此该计数即一次全新索引重建的产出规模。与 index_files_present()
    配合支撑"轻量重建"策略：存留索引仍覆盖重建后的记忆集合时，
    重建 DB 无需重新生成 embedding（省去最慢的向量化步骤）。
    """
    from packages.storage import config as storage_config

    path = Path(storage_config.index_db_path)
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_index WHERE status = 'active'"
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None


def vector_meta_count() -> int | None:
    """统计 vectors.json 中的向量条数；不可读时返回 None。

    ``indexed_active_count()`` 只校验 index.db 一侧；vectors.npz/json
    可能因旧版中断偏少（索引行在、向量缺失）。ids 数与 npz 向量数
    不一致时 VectorIndex 会整体丢弃内容，因此 ids 长度即有效向量数。
    """
    from packages.storage import config as storage_config

    path = Path(storage_config.vector_meta_path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
        ids = meta.get("ids")
        return len(ids) if isinstance(ids, list) else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# DatabaseRebuilder
# ---------------------------------------------------------------------------


class DatabaseRebuilder:
    """从 Markdown + _meta 文件重建 cwiki.db 的记忆表。

    若数据库文件还没有 schema（全新克隆、``cwiki.db`` 丢失或损坏），
    重建开始前会先通过 Alembic 建出完整 schema —— 包括需保留的非记忆表
    —— 使"DB 丢失 → 从 MD + _meta 重建"的兜底路径始终可用。

    Parameters
    ----------
    db_url:
        异步 SQLAlchemy 连接串，例如
        ``sqlite+aiosqlite:///./cwiki-data/cwiki.db``。
    data_dir:
        ``cwiki-data/`` 目录路径，需同时包含 Markdown 记忆文件
        与 ``_meta/`` 伴随目录。
    """

    def __init__(self, db_url: str, data_dir: str) -> None:
        self.db_url = db_url
        self.data_dir = data_dir
        self.file_store = FileStore(data_dir)
        self.meta_store = MetaStore(f"{data_dir}/_meta")

        # 创建独立的 engine 与 session 工厂，避免干扰应用的全局 engine。
        connect_args: dict[str, Any] = {}
        if "sqlite" in db_url:
            connect_args["check_same_thread"] = False

        self._engine = create_async_engine(
            db_url,
            echo=False,
            connect_args=connect_args,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def rebuild(self) -> RebuildResult:
        """执行一次完整重建，返回 :class:`RebuildResult`。

        事务边界：整个操作在单个事务内运行，要么全部落库要么全部回滚。
        失败时回滚事务并重新抛出异常，数据库保持重建前的完整状态。
        """
        t0 = time.monotonic()
        result = RebuildResult()

        # 0. 确保 schema 存在（全新 DB → 经 Alembic 创建）。
        await self._ensure_schema()

        async with self._session_factory() as session:
            try:
                # 1. 构建 workspace 名称 → UUID 映射（行缺失时从
                #    _meta/_workspaces.json 恢复）。
                ws_map = await self._build_workspace_map(session)
                result.workspace_map = ws_map
                logger.info("Found %d workspaces: %s", len(ws_map), list(ws_map.keys()))

                # 2. 清空记忆相关表。
                await self._clear_tables(session)
                logger.info("Cleared memory-related tables")

                # 3. 从 Markdown 文件导入记忆。
                memories = await self._import_memories(session, ws_map, result)
                logger.info("Imported %d memories from Markdown files", len(memories))

                # 3.5 从 _meta/_review_queue.json 恢复候选审核队列
                #     （候选 + 评审留痕）。必须先于 _import_relations：
                #     conflict / evidence 的 candidate_id 引用这些候选行。
                await self._import_candidates(session, result)
                logger.info(
                    "Imported review queue: %d candidates, %d reviews",
                    result.candidate_count,
                    result.review_count,
                )

                # 3.6 从 _meta/_capture_notes.json 恢复捕获会话与待整理笔记
                await self._import_capture(session, result)
                logger.info(
                    "Imported capture: %d sessions, %d notes",
                    result.capture_session_count,
                    result.capture_note_count,
                )

                # 4. 从 _meta JSON 文件导入关系数据。
                await self._import_relations(session, result)
                logger.info(
                    "Imported relations: %s",
                    {k: v for k, v in result.relation_counts.items() if v > 0},
                )

                # 5. 提交事务。
                await session.commit()
                logger.info("Rebuild committed successfully")

            except Exception:
                await session.rollback()
                logger.exception("Rebuild failed, transaction rolled back")
                raise

        result.elapsed_seconds = time.monotonic() - t0
        return result

    async def rebuild_vector_index(self) -> int:
        """从 Markdown 文件重建向量索引（index.db + vectors.npz）。

        embedding 生成较慢，因此作为独立步骤执行；索引文件齐备时
        上层流程可整体跳过本步骤（轻量重建）。
        返回索引的记忆条数。
        """
        from packages.domain.text_utils import format_memory_for_embedding
        from packages.retrieval.embedding import get_embedding_service
        from packages.storage import config as storage_config
        from packages.storage.indexer import MemoryIndexer

        indexer = MemoryIndexer(
            db_path=storage_config.index_db_path,
            file_store=self.file_store,
            vector_index_path=storage_config.vector_index_path,
        )
        await indexer.init_db()

        memories = await asyncio.to_thread(self.file_store.list)
        embedding_service = get_embedding_service()
        indexed = 0
        embedding_updates: list[tuple[str, list[float]]] = []

        logger.info("Rebuilding vector index for %d memories...", len(memories))
        for i, memory in enumerate(memories):
            if memory.status != "active":
                continue
            emb_text = format_memory_for_embedding(memory.title, memory.content)
            embedding = await embedding_service.generate_embedding(emb_text)
            await indexer.index_memory(memory, embedding=embedding, update_vector=True)
            if embedding is not None:
                embedding_updates.append((memory.id, embedding))
            indexed += 1
            if (indexed + 1) % 100 == 0:
                logger.info("Vector index progress: %d / %d", indexed, len(memories))

        await indexer.save_vector_index()
        await indexer.close()
        backfilled = await self._backfill_memory_embeddings(embedding_updates)
        logger.info(
            "Vector index rebuild complete: %d memories indexed, %d embedding columns backfilled",
            indexed,
            backfilled,
        )
        return indexed

    async def _backfill_memory_embeddings(self, updates: list[tuple[str, list[float]]]) -> int:
        """把重建生成的向量回填 DB ``memory.embedding`` 列。

        score_candidate 的向量新颖度与重复概率都依赖该列；重建后若全
        NULL，auto-approve 会因重复概率未知而全部跳过。DB 中不存在的
        id（孤儿 MD）影响 0 行，无害。
        """
        if not updates:
            return 0
        async with self._session_factory() as session:
            for mid, vec in updates:
                await session.execute(
                    update(Memory).where(Memory.id == uuid.UUID(mid)).values(embedding=vec)
                )
            await session.commit()
        return len(updates)

    async def table_counts(self) -> tuple[int, int, int]:
        """重建后数据库的行数统计。

        返回 ``(memory_total, memory_active, review_schedule)``。
        ``rebuild_vector_index()`` 只索引 active 记忆；而只有当 ``_meta``
        未能恢复任何复习计划时才需要执行 ``recompute``。
        """
        async with self._session_factory() as session:
            total = (await session.execute(select(func.count()).select_from(Memory))).scalar_one()
            active = (
                await session.execute(
                    select(func.count()).select_from(Memory).where(Memory.status == "active")
                )
            ).scalar_one()
            schedules = (
                await session.execute(select(func.count()).select_from(ReviewSchedule))
            ).scalar_one()
        return int(total), int(active), int(schedules)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    async def _ensure_schema(self) -> None:
        """确保数据库 schema 存在，缺失时通过 Alembic 创建。

        ``rebuild()`` 本身只清空并重填记忆相关表，默认 schema 已存在。
        对全新数据库文件（DB 丢失/损坏、全新克隆）而言没有任何表 ——
        连 ``workspace`` 都没有，首个查询就会报 ``no such table``。

        先探测 ``sqlite_master``（绝不查询可能不存在的表）。当
        ``workspace`` 表缺失时，在子进程中运行完整 Alembic 迁移链
        （``upgrade head``）建出所有表，包括需保留的非记忆表
        （workspace、agent、session 等）。幂等：schema 已存在时直接跳过。
        """
        async with self._session_factory() as session:
            try:
                probe = await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name='workspace'")
                )
                schema_exists = probe.scalar_one_or_none() is not None
            except DatabaseError as exc:
                raise RuntimeError(
                    f"Database at {self.db_url!r} exists but is not a readable "
                    "SQLite database (possibly corrupted). Delete the database "
                    "file and re-run the rebuild to recreate it from MD + _meta. "
                    f"Original error: {exc}"
                ) from exc

        if schema_exists:
            return

        cmd = [
            sys.executable,
            str(_PROJECT_ROOT / "scripts" / "run_alembic.py"),
            "upgrade",
            "head",
        ]
        logger.info("No schema found — creating tables via Alembic: %s", " ".join(cmd))
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "Failed to create schema via Alembic "
                f"(exit code {proc.returncode}).\n"
                f"Command: {' '.join(cmd)} (cwd: {_PROJECT_ROOT})\n"
                f"stdout:\n{proc.stdout}\n"
                f"stderr:\n{proc.stderr}"
            )
        logger.info("Schema created via Alembic (upgrade head)")

    async def _build_workspace_map(self, session: AsyncSession) -> dict[str, str]:
        """构建 ``{名称: uuid字符串}`` 的 workspace 映射，并补齐缺失行。

        恢复顺序：

        1. ``workspace`` 表中已存在的行（被保留的数据）。
        2. ``_meta/_workspaces.json`` —— 由 ``scripts/migrate_to_git.py``
           写出。每个导出的 workspace 都以原始 id 与时间戳重建，
           包括没有 MD 文件的空 workspace。名称或 id 已存在的条目
           跳过（幂等合并 —— 以数据库现有行为准）。
        3. MD frontmatter（workspace 目录名）—— 兜底用于没有
           ``_workspaces.json`` 的旧版导出，也为 MD 引用但文件中缺失的
           名称兜底。缺失的名称用全新 UUID 创建。
        """
        ws_rows = (await session.execute(select(Workspace))).scalars().all()
        by_name: dict[str, Workspace] = {ws.name: ws for ws in ws_rows}
        by_id: set[str] = {str(ws.id) for ws in ws_rows}

        # 2. 从导出的 workspace 元数据恢复（id 精确保留）。
        restored = 0
        payload = await asyncio.to_thread(self.meta_store.import_workspaces)
        if payload is None:
            logger.info(
                "_meta/_workspaces.json not found — falling back to MD "
                "frontmatter for workspace restoration"
            )
        else:
            for entry in payload:
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    logger.warning("Skipping workspace entry with no name: %r", entry)
                    continue
                if name in by_name:
                    continue  # 幂等合并：以数据库现有行为准

                raw_id = entry.get("id")
                ws_id: uuid.UUID | None = None
                if isinstance(raw_id, str) and raw_id:
                    try:
                        ws_id = uuid.UUID(raw_id)
                    except ValueError:
                        logger.warning(
                            "Workspace %r has invalid id %r — using a new UUID",
                            name,
                            raw_id,
                        )
                if ws_id is not None and str(ws_id) in by_id:
                    continue  # 同一 id 已被其他名称占用

                kwargs: dict[str, Any] = {"id": ws_id or uuid.uuid4(), "name": name}
                created_at = _parse_dt(entry.get("created_at"))
                if created_at is not None:
                    kwargs["created_at"] = created_at
                updated_at = _parse_dt(entry.get("updated_at"))
                if updated_at is not None:
                    kwargs["updated_at"] = updated_at

                ws = Workspace(**kwargs)
                session.add(ws)
                by_name[ws.name] = ws
                by_id.add(str(ws.id))
                restored += 1

        # 3. 兜底：确保 MD 引用的每个 workspace 都存在。
        memories = await asyncio.to_thread(self.file_store.list)
        md_names = sorted({mf.workspace for mf in memories if mf.workspace})
        created = 0
        for name in md_names:
            if name in by_name:
                continue
            ws = Workspace(id=uuid.uuid4(), name=name)
            session.add(ws)
            by_name[name] = ws
            by_id.add(str(ws.id))
            created += 1

        if restored or created:
            await session.flush()

        logger.info(
            "Workspace map: %d total (%d restored from _workspaces.json, "
            "%d created from MD frontmatter)",
            len(by_name),
            restored,
            created,
        )
        return {name: str(ws.id) for name, ws in by_name.items()}

    async def _clear_tables(self, session: AsyncSession) -> None:
        """按依赖顺序删除记忆相关表中的全部行。"""
        # SQLite 临时关闭外键检查，避免删除顺序引发约束问题。
        if "sqlite" in self.db_url:
            await session.execute(text("PRAGMA foreign_keys = OFF"))

        for table_name in _MEMORY_TABLES_TO_CLEAR:
            await session.execute(text(f'DELETE FROM "{table_name}"'))

        if "sqlite" in self.db_url:
            await session.execute(text("PRAGMA foreign_keys = ON"))

    async def _import_memories(
        self,
        session: AsyncSession,
        ws_map: dict[str, str],
        result: RebuildResult,
    ) -> list[MemoryFile]:
        """扫描 Markdown 文件并插入 Memory 行。"""
        memories, parse_skipped = await asyncio.to_thread(self.file_store.list_with_skipped)
        for path, reason in parse_skipped:
            logger.warning("Rebuild skips unparsable memory file: %s (%s)", path, reason)
            result.skipped_files.append(f"{path} ({reason})")
        batch: list[Memory] = []
        # 构造阶段跳过数与 parse_skipped 分开计数：后者不在 memories 里，
        # 混入同一算式会重复扣减 memory_count。
        construction_skipped = 0

        # 为 workspace 未知的记忆寻找或创建兜底 workspace。
        fallback_ws_id: str | None = None
        if "chat" not in ws_map:
            # 检查是否有现成 workspace 可作兜底。
            if ws_map:
                fallback_ws_id = next(iter(ws_map.values()))
            else:
                # 创建默认 workspace。
                default_ws = Workspace(id=uuid.uuid4(), name="chat")
                session.add(default_ws)
                await session.flush()
                ws_map["chat"] = str(default_ws.id)
                fallback_ws_id = ws_map["chat"]
        else:
            fallback_ws_id = ws_map["chat"]

        for mf in memories:
            ws_name = mf.workspace or "chat"
            ws_id_str = ws_map.get(ws_name)
            if ws_id_str is None:
                # 未知 workspace —— 使用兜底。
                logger.warning(
                    "Memory %s references unknown workspace '%s', using fallback",
                    mf.id,
                    ws_name,
                )
                ws_id_str = fallback_ws_id

            try:
                memory = Memory(
                    id=uuid.UUID(mf.id),
                    workspace_id=uuid.UUID(ws_id_str),
                    title=mf.title,
                    content=mf.content,
                    type=mf.type,
                    tags=list(mf.tags or []),
                    source=mf.source,
                    status=mf.status,
                    confidence=mf.confidence if mf.confidence is not None else 0.5,
                    importance=mf.importance if mf.importance is not None else 0.5,
                    version=mf.version,
                    usage_count=mf.usage_count,
                    last_used_at=mf.last_used_at,
                    is_permanent=mf.is_permanent,
                    metadata_=mf.metadata,
                    created_at=_parse_dt(mf.created),
                    updated_at=_parse_dt(mf.updated),
                    # embedding 不存于 MD —— 将单独重建
                )
                batch.append(memory)
            except (ValueError, KeyError) as exc:
                logger.warning("Skipping memory file %s: %s", mf.id, exc)
                result.skipped_files.append(mf.id)
                construction_skipped += 1
                continue

            # 分批写入，控制单次 flush 的内存占用
            if len(batch) >= 200:
                session.add_all(batch)
                await session.flush()
                batch.clear()

        if batch:
            session.add_all(batch)
            await session.flush()

        result.memory_count = len(memories) - construction_skipped
        return memories

    async def _import_capture(self, session: AsyncSession, result: RebuildResult) -> None:
        """从 ``_meta/_capture_notes.json`` 恢复 Agent 会话与待整理笔记。

        笔记是“未整理内容”的唯一副本；旧版导出没有该文件时只告警，
        重建照常完成。逐行容错：坏行跳过，不让一条脏数据阻断整次重建。
        """
        payload = await asyncio.to_thread(self.meta_store.import_capture)
        if payload is None:
            logger.warning(
                "_meta/_capture_notes.json not found — capture notes "
                "will be empty after rebuild (old export?)"
            )
            return

        sessions: list[AgentSession] = []
        seen_sessions: set[str] = set()
        for entry in payload.get("sessions") or []:
            if not isinstance(entry, dict):
                continue
            try:
                session_id = str(entry["id"])
                if session_id in seen_sessions:
                    continue
                seen_sessions.add(session_id)
                sessions.append(
                    AgentSession(
                        id=uuid.UUID(session_id),
                        workspace_id=uuid.UUID(str(entry["workspace_id"])),
                        agent=str(entry.get("agent") or "unknown"),
                        agent_version=entry.get("agent_version"),
                        repository=entry.get("repository"),
                        branch=entry.get("branch"),
                        task=entry.get("task"),
                        event_session_id=(
                            uuid.UUID(str(entry["event_session_id"]))
                            if entry.get("event_session_id")
                            else None
                        ),
                        started_at=_parse_dt(entry.get("started_at")) or datetime.now(UTC),
                        ended_at=_parse_dt(entry.get("ended_at")),
                        outcome=entry.get("outcome"),
                        metadata_=entry.get("metadata_"),
                        created_at=_parse_dt(entry.get("created_at")) or datetime.now(UTC),
                    )
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("Skipping invalid capture session: %s", entry, exc_info=True)

        if sessions:
            session.add_all(sessions)
            await session.flush()
            result.capture_session_count = len(sessions)

        notes: list[SessionNote] = []
        seen_notes: set[str] = set()
        for entry in payload.get("notes") or []:
            if not isinstance(entry, dict):
                continue
            try:
                note_id = str(entry["id"])
                if note_id in seen_notes:
                    continue
                if str(entry.get("session_id")) not in seen_sessions:
                    logger.warning("Skipping capture note with missing session: %s", note_id)
                    continue
                seen_notes.add(note_id)
                notes.append(
                    SessionNote(
                        id=uuid.UUID(note_id),
                        session_id=uuid.UUID(str(entry["session_id"])),
                        workspace_id=uuid.UUID(str(entry["workspace_id"])),
                        content=str(entry["content"]),
                        signal_type=str(entry.get("signal_type") or "other"),
                        formalized=bool(entry.get("formalized", False)),
                        formalized_memory_id=(
                            uuid.UUID(str(entry["formalized_memory_id"]))
                            if entry.get("formalized_memory_id")
                            else None
                        ),
                        candidate_id=(
                            uuid.UUID(str(entry["candidate_id"]))
                            if entry.get("candidate_id")
                            else None
                        ),
                        created_at=_parse_dt(entry.get("created_at")) or datetime.now(UTC),
                    )
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("Skipping invalid capture note: %s", entry, exc_info=True)

        if notes:
            session.add_all(notes)
            await session.flush()
            result.capture_note_count = len(notes)

    async def _import_candidates(self, session: AsyncSession, result: RebuildResult) -> None:
        """从 ``_meta/_review_queue.json`` 恢复候选记忆与评审留痕。

        候选不经 Markdown 承载，唯一来源是 migrate_to_git 写出的这份
        store 级伴随文件。旧版导出没有该文件时（向前兼容）记 warning
        并跳过，重建照常完成 —— 队列为空与旧行为一致。
        """
        payload = await asyncio.to_thread(self.meta_store.import_review_queue)
        if payload is None:
            logger.warning(
                "_meta/_review_queue.json not found — candidate review queue "
                "will be empty after rebuild (old export?)"
            )
            return

        # 候选的 project_id / episode_id 指向不随重建重灌的非记忆表
        # （project / episode），多设备同步后可能悬空（例如对端清理过
        # episode 行）。SQLite FK 检查会拒绝整批导入 —— 悬空引用保留
        # 原值远比丢掉候选更符合"重建兜底"的目的，故导入期间临时关闭
        # FK 检查，结束后恢复（与 _clear_tables 的做法对称）。
        if "sqlite" in self.db_url:
            await session.execute(text("PRAGMA foreign_keys = OFF"))
        try:
            candidate_batch: list[CandidateMemory] = []
            review_batch: list[Review] = []
            seen_ids: set[str] = set()

            raw_candidates = payload.get("candidates")
            for entry in raw_candidates if isinstance(raw_candidates, list) else []:
                if not isinstance(entry, dict):
                    continue

                try:
                    cand_id = entry["id"]
                    if cand_id in seen_ids:
                        continue  # 坏导出的重复候选：跳过防主键冲突
                    kwargs: dict[str, Any] = {
                        "id": uuid.UUID(cand_id),
                        "workspace_id": uuid.UUID(entry["workspace_id"]),
                        "project_id": (
                            uuid.UUID(entry["project_id"]) if entry.get("project_id") else None
                        ),
                        "episode_id": (
                            uuid.UUID(entry["episode_id"]) if entry.get("episode_id") else None
                        ),
                        "title": entry["title"],
                        "content": entry["content"],
                        "type": entry.get("type", "fact"),
                        "client_write_id": entry.get("client_write_id"),
                        "confidence": entry.get("confidence"),
                        "importance": entry.get("importance"),
                        "novelty": entry.get("novelty"),
                        "reusability": entry.get("reusability"),
                        "stability": entry.get("stability"),
                        "future_utility": entry.get("future_utility"),
                        "actionability": entry.get("actionability"),
                        "evidence_strength": entry.get("evidence_strength"),
                        "scope_confidence": entry.get("scope_confidence"),
                        "quality_score": entry.get("quality_score"),
                        "value_score": entry.get("value_score"),
                        "quality_gate_score": entry.get("quality_gate_score"),
                        "quality_gate_reason": entry.get("quality_gate_reason"),
                        "review_priority": entry.get("review_priority"),
                        "duplicate_probability": entry.get("duplicate_probability"),
                        "similar_memory_id": (
                            uuid.UUID(entry["similar_memory_id"])
                            if entry.get("similar_memory_id")
                            else None
                        ),
                        "similar_memory_source": entry.get("similar_memory_source"),
                        "dedup_relation_type": entry.get("dedup_relation_type"),
                        # embedding 不导出 —— 重建后由启动时批量重算
                        "status": entry.get("status", "pending_review"),
                        "source": entry.get("source", "mcp"),
                    }
                    # 时间戳解析失败时不传 —— 让列默认值兜底，
                    # 避免 NOT NULL 列拿到 None 导致整个重建回滚。
                    created_at = _parse_dt(entry.get("created_at"))
                    if created_at is not None:
                        kwargs["created_at"] = created_at
                    updated_at = _parse_dt(entry.get("updated_at"))
                    if updated_at is not None:
                        kwargs["updated_at"] = updated_at

                    candidate_batch.append(CandidateMemory(**kwargs))
                    seen_ids.add(cand_id)
                    result.candidate_count += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping candidate in _review_queue.json: %s", exc)

                raw_reviews = entry.get("reviews")
                for item in raw_reviews if isinstance(raw_reviews, list) else []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        review_kwargs: dict[str, Any] = {
                            "id": uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            "candidate_id": uuid.UUID(item["candidate_id"]),
                            "reviewer_type": item.get("reviewer_type", "agent"),
                            "reviewer_id": item.get("reviewer_id"),
                            "action": item.get("action", "unknown"),
                            "before_content": item.get("before_content"),
                            "after_content": item.get("after_content"),
                            "reason": item.get("reason"),
                        }
                        review_created = _parse_dt(item.get("created_at"))
                        if review_created is not None:
                            review_kwargs["created_at"] = review_created
                        review_batch.append(Review(**review_kwargs))
                        result.review_count += 1
                    except (ValueError, KeyError) as exc:
                        logger.debug("Skipping review in _review_queue.json: %s", exc)

            if candidate_batch:
                session.add_all(candidate_batch)
            if review_batch:
                session.add_all(review_batch)
            await session.flush()
        finally:
            if "sqlite" in self.db_url:
                await session.execute(text("PRAGMA foreign_keys = ON"))

    async def _import_relations(
        self,
        session: AsyncSession,
        result: RebuildResult,
    ) -> None:
        """扫描 _meta JSON 文件并插入关系数据行。"""
        memory_ids = await asyncio.to_thread(self.meta_store.list_memories)
        counts: dict[str, int] = {
            "feedback": 0,
            "usage": 0,
            "conflict": 0,
            "review_schedule": 0,
            "relation": 0,
            "lifecycle_event": 0,
            "evidence": 0,
            "versions": 0,
            "review_history": 0,
        }

        # 按批次收集待插入的关系数据行。
        feedback_batch: list[MemoryFeedback] = []
        usage_batch: list[MemoryUsage] = []
        conflict_batch: list[MemoryConflict] = []
        lifecycle_batch: list[MemoryLifecycleEvent] = []
        relation_batch: list[MemoryRelation] = []
        schedule_batch: list[ReviewSchedule] = []
        evidence_batch: list[Evidence] = []
        version_batch: list[MemoryVersion] = []
        history_batch: list[ReviewHistory] = []

        # (memory_id, version) 唯一约束兜底：memory_version 表带
        # uq_memory_version，重复行若直接插入会让 flush 抛
        # IntegrityError 回滚整个重建，故先去重再入批。
        seen_versions: set[tuple[str, int]] = set()

        for memory_id_str in memory_ids:
            meta = await asyncio.to_thread(self.meta_store.import_memory, memory_id_str)
            if meta is None:
                continue

            # --- feedback ---
            for item in meta.get("feedback", []):
                try:
                    feedback_batch.append(
                        MemoryFeedback(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            workspace_id=uuid.UUID(item["workspace_id"]),
                            memory_id=uuid.UUID(memory_id_str),
                            feedback_type=item.get("feedback_type", "unknown"),
                            source_type=item.get("source_type", "agent"),
                            source_id=item.get("source_id"),
                            reason=item.get("reason"),
                            created_at=_parse_dt(item.get("created_at")),
                        )
                    )
                    counts["feedback"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping feedback for %s: %s", memory_id_str, exc)

            # --- usage ---
            for item in meta.get("usage", []):
                try:
                    usage_batch.append(
                        MemoryUsage(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            workspace_id=uuid.UUID(item["workspace_id"]),
                            memory_id=uuid.UUID(memory_id_str),
                            trace_id=uuid.UUID(item["trace_id"]) if item.get("trace_id") else None,
                            session_id=(
                                uuid.UUID(item["session_id"]) if item.get("session_id") else None
                            ),
                            position=item.get("position"),
                            stage=item.get("stage", "retrieved"),
                            created_at=_parse_dt(item.get("created_at")),
                        )
                    )
                    counts["usage"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping usage for %s: %s", memory_id_str, exc)

            # --- conflict ---
            for item in meta.get("conflict", []):
                try:
                    conflict_batch.append(
                        MemoryConflict(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            workspace_id=uuid.UUID(item["workspace_id"]),
                            memory_id=uuid.UUID(memory_id_str),
                            candidate_id=(
                                uuid.UUID(item["candidate_id"])
                                if item.get("candidate_id")
                                else None
                            ),
                            conflict_type=item.get("conflict_type", "contradiction"),
                            description=item.get("description"),
                            evidence=item.get("evidence"),
                            status=item.get("status", "open"),
                            resolution=item.get("resolution"),
                            created_at=_parse_dt(item.get("created_at")),
                            resolved_at=_parse_dt(item.get("resolved_at")),
                        )
                    )
                    counts["conflict"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping conflict for %s: %s", memory_id_str, exc)

            # --- review_schedule (1:1) ---
            rs = meta.get("review_schedule")
            if rs and isinstance(rs, dict) and rs.get("id"):
                try:
                    # 此处需要该记忆的 workspace_id，
                    # 从刚导入的记忆行中查得。
                    mem_row = (
                        await session.execute(
                            select(Memory.workspace_id).where(Memory.id == uuid.UUID(memory_id_str))
                        )
                    ).scalar_one_or_none()
                    if mem_row:
                        schedule_batch.append(
                            ReviewSchedule(
                                id=uuid.UUID(rs["id"]),
                                workspace_id=uuid.UUID(str(mem_row)),
                                memory_id=uuid.UUID(memory_id_str),
                                ease_factor=rs.get("ease_factor", 2.5),
                                interval_days=rs.get("interval_days", 1),
                                repetitions=rs.get("repetitions", 0),
                                next_review=_parse_dt(rs.get("next_review"))
                                or datetime.now(UTC).replace(tzinfo=None),
                                last_review=_parse_dt(rs.get("last_review")),
                                total_reviews=rs.get("total_reviews", 0),
                                created_at=_parse_dt(rs.get("created_at")),
                                updated_at=_parse_dt(rs.get("updated_at")),
                            )
                        )
                        counts["review_schedule"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping review_schedule for %s: %s", memory_id_str, exc)

            # --- relation ---
            for item in meta.get("relation", []):
                try:
                    relation_batch.append(
                        MemoryRelation(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            source_memory_id=uuid.UUID(item.get("source_memory_id", memory_id_str)),
                            target_memory_id=uuid.UUID(item["target_memory_id"]),
                            relation_type=item.get("relation_type", "related"),
                            confidence=item.get("confidence", 1.0),
                            created_at=_parse_dt(item.get("created_at")),
                        )
                    )
                    counts["relation"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping relation for %s: %s", memory_id_str, exc)

            # --- lifecycle_event ---
            for item in meta.get("lifecycle_event", []):
                try:
                    lifecycle_batch.append(
                        MemoryLifecycleEvent(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            memory_id=uuid.UUID(memory_id_str),
                            event_type=item.get("event_type", "unknown"),
                            metadata_json=(
                                json.dumps(item["metadata_json"])
                                if item.get("metadata_json")
                                and isinstance(item["metadata_json"], dict)
                                else item.get("metadata_json")
                            ),
                            created_at=_parse_dt(item.get("created_at")),
                        )
                    )
                    counts["lifecycle_event"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping lifecycle_event for %s: %s", memory_id_str, exc)

            # --- evidence ---
            for item in meta.get("evidence", []):
                try:
                    evidence_batch.append(
                        Evidence(
                            id=uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                            memory_id=uuid.UUID(memory_id_str),
                            candidate_id=(
                                uuid.UUID(item["candidate_id"])
                                if item.get("candidate_id")
                                else None
                            ),
                            episode_id=(
                                uuid.UUID(item["episode_id"]) if item.get("episode_id") else None
                            ),
                            event_id=(
                                uuid.UUID(item["event_id"]) if item.get("event_id") else None
                            ),
                            source_type=item.get("source_type", "unknown"),
                            source_ref=item.get("source_ref"),
                            content=item.get("content"),
                            metadata_=item.get("metadata"),
                            created_at=_parse_dt(item.get("created_at")),
                        )
                    )
                    counts["evidence"] += 1
                except (ValueError, KeyError) as exc:
                    logger.debug("Skipping evidence for %s: %s", memory_id_str, exc)

            # --- versions（版本快照）---
            for item in meta.get("versions", []):
                try:
                    ver = int(item["version"])  # 缺失/非法 → 坏行跳过
                    key = (memory_id_str, ver)
                    if key in seen_versions:
                        logger.debug("Skipping duplicate version %d for %s", ver, memory_id_str)
                        continue
                    version_kwargs: dict[str, Any] = {
                        "id": uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                        "memory_id": uuid.UUID(memory_id_str),
                        "version": ver,
                        "title": item["title"],
                        "content": item["content"],
                        "change_type": item.get("change_type", "unknown"),
                        "changed_by_type": item.get("changed_by_type", "agent"),
                        "changed_by_id": item.get("changed_by_id"),
                        "reason": item.get("reason"),
                    }
                    version_created = _parse_dt(item.get("created_at"))
                    if version_created is not None:
                        version_kwargs["created_at"] = version_created
                    version_batch.append(MemoryVersion(**version_kwargs))
                    seen_versions.add(key)
                    counts["versions"] += 1
                except (ValueError, KeyError, TypeError) as exc:
                    logger.debug("Skipping version for %s: %s", memory_id_str, exc)

            # --- review_history（复习事件史）---
            for item in meta.get("review_history", []):
                try:
                    # NOT NULL 的调度时间字段解析失败视为坏行跳过，
                    # 避免 flush 时 IntegrityError 回滚整个重建。
                    reviewed_at = _parse_dt(item["reviewed_at"])
                    next_before = _parse_dt(item["next_review_before"])
                    next_after = _parse_dt(item["next_review_after"])
                    if reviewed_at is None or next_before is None or next_after is None:
                        raise ValueError("invalid required datetime field")
                    history_kwargs: dict[str, Any] = {
                        "id": uuid.UUID(item["id"]) if item.get("id") else uuid.uuid4(),
                        "workspace_id": uuid.UUID(item["workspace_id"]),
                        "memory_id": uuid.UUID(memory_id_str),
                        "quality": int(item["quality"]),
                        "ease_factor_before": float(item["ease_factor_before"]),
                        "interval_before": int(item["interval_before"]),
                        "repetitions_before": int(item["repetitions_before"]),
                        "next_review_before": next_before,
                        "mastery_level_before": item.get("mastery_level_before", "new"),
                        "ease_factor_after": float(item["ease_factor_after"]),
                        "interval_after": int(item["interval_after"]),
                        "repetitions_after": int(item["repetitions_after"]),
                        "next_review_after": next_after,
                        "mastery_level_after": item.get("mastery_level_after", "new"),
                        "reviewed_at": reviewed_at,
                    }
                    history_created = _parse_dt(item.get("created_at"))
                    if history_created is not None:
                        history_kwargs["created_at"] = history_created
                    history_batch.append(ReviewHistory(**history_kwargs))
                    counts["review_history"] += 1
                except (ValueError, KeyError, TypeError) as exc:
                    logger.debug("Skipping review_history for %s: %s", memory_id_str, exc)

        # 统一 flush 全部批次。
        batches: list[list[Any]] = [
            feedback_batch,
            usage_batch,
            conflict_batch,
            lifecycle_batch,
            relation_batch,
            schedule_batch,
            evidence_batch,
            version_batch,
            history_batch,
        ]
        for batch_list in batches:
            if batch_list:
                session.add_all(batch_list)
        await session.flush()

        result.relation_counts = counts

    async def close(self) -> None:
        """释放内部 engine。"""
        await self._engine.dispose()
