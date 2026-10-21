"""将 SQLite 中的记忆迁移为 Markdown + _meta 文件（Phase 1.4）。

通过 :class:`FileStore` 把 ``memory`` 表的每一行导出为 Markdown 文件，
通过 :class:`MetaStore` 把各关联表行导出为 ``_meta/{id}.json`` 侧车文件。

用法::

    python scripts/migrate_to_git.py
    # 或经由 tasks.py：
    python tasks.py migrate-to-git
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 上。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import patch_metadata, print_message

patch_metadata()

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from packages.domain.config import settings
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
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.meta_store import MetaStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


# CandidateMemory 导出字段（除 embedding —— 不进 Git 同步文件，
# 重建后由启动时批量重算）。
_CANDIDATE_FIELDS = [
    "id",
    "workspace_id",
    "project_id",
    "episode_id",
    "title",
    "content",
    "type",
    "tags",
    "client_write_id",
    "confidence",
    "importance",
    "novelty",
    "reusability",
    "stability",
    "future_utility",
    "actionability",
    "evidence_strength",
    "scope_confidence",
    "quality_score",
    "value_score",
    "quality_gate_score",
    "quality_gate_reason",
    "review_priority",
    "duplicate_probability",
    "similar_memory_id",
    "similar_memory_source",
    "dedup_relation_type",
    "status",
    "source",
    "created_at",
    "updated_at",
]

# Review（评审留痕）导出字段。
_REVIEW_FIELDS = [
    "id",
    "candidate_id",
    "reviewer_type",
    "reviewer_id",
    "action",
    "before_content",
    "after_content",
    "reason",
    "created_at",
]


def _memory_to_file(mem: Memory, workspace_name: str) -> MemoryFile:
    """把 SQLAlchemy Memory 行转换为用于 MD 导出的 MemoryFile。"""
    return MemoryFile(
        id=str(mem.id),
        title=mem.title,
        content=mem.content,
        type=mem.type,
        tags=list(mem.tags or []),
        related=[],  # DB 不直接存 related
        version=mem.version,
        status=mem.status,
        source=mem.source,
        workspace=workspace_name,
        created=mem.created_at,
        updated=mem.updated_at,
        confidence=mem.confidence,
        importance=mem.importance,
        usage_count=mem.usage_count,
        last_used_at=mem.last_used_at,
        is_permanent=mem.is_permanent,
        metadata=mem.metadata_,
    )


def _serialize_row(row: Any, fields: list[str]) -> dict[str, Any]:
    """把 SQLAlchemy 行序列化为普通 dict，UUID/日期转为字符串。"""
    result: dict[str, Any] = {}
    for f in fields:
        val = getattr(row, f, None)
        if isinstance(val, uuid.UUID):
            result[f] = str(val)
        elif isinstance(val, datetime):
            result[f] = val.isoformat()
        else:
            result[f] = val
    return result


# ---------------------------------------------------------------------------
# 主迁移流程
# ---------------------------------------------------------------------------


async def migrate_to_git() -> dict[str, int]:
    """把全部记忆从 SQLite 导出为 Markdown + _meta 文件（全局配置入口）。"""
    return await export_all(settings.database_url, storage_config.memory_dir)


async def export_all(db_url: str, data_dir: str) -> dict[str, int]:
    """把全部记忆从 SQLite 导出为 Markdown + _meta 文件。

    参数化入口：CLI 走 :func:`migrate_to_git`（读全局配置），测试与
    其他调用方可直接传入临时 db_url / data_dir 复用同一导出逻辑。

    返回含 memory_count、file_count、meta_count 等的统计 dict。
    """
    print_message(f"DB URL:   {db_url}")
    print_message(f"Data dir: {data_dir}")
    print_message()

    file_store = FileStore(data_dir)
    meta_store = MetaStore(f"{data_dir}/_meta")

    connect_args: dict[str, Any] = {}
    if "sqlite" in db_url:
        # SQLite 需关闭同线程检查，异步驱动会跨线程使用连接
        connect_args["check_same_thread"] = False

    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats: dict[str, int] = {
        "memory_count": 0,
        "file_count": 0,
        "meta_count": 0,
        "workspace_count": 0,
        "candidate_count": 0,
        "review_count": 0,
        "capture_session_count": 0,
        "capture_note_count": 0,
        "orphan_meta_deleted": 0,
        "errors": 0,
    }

    async with session_factory() as session:
        # 1. 构建 workspace UUID → 名称映射。
        ws_rows = (await session.execute(select(Workspace))).scalars().all()
        ws_name_map: dict[str, str] = {str(ws.id): ws.name for ws in ws_rows}
        print_message(f"Found {len(ws_name_map)} workspaces: {list(ws_name_map.values())}")

        # 1a. 导出 workspace 元数据，使空库重建时能精确恢复 workspace 表
        #     （保留原始 id 与时间戳，包括没有 MD 文件的空 workspace）。
        try:
            payload = [
                _serialize_row(ws, ["name", "id", "created_at", "updated_at"])
                for ws in sorted(ws_rows, key=lambda w: w.name)
            ]
            meta_store.export_workspaces(payload)
            stats["workspace_count"] = len(payload)
        except Exception:
            logger.exception("Failed to write _meta/_workspaces.json")
            stats["errors"] += 1

        # 1b. 导出候选审核队列（全部状态的候选 + 评审留痕）。候选不经
        #     Markdown 承载，重建后能否找回待审/隔离/已审候选与评审
        #     历史，全靠这份 store 级伴随文件。
        try:
            await _export_review_queue(session, meta_store, stats)
        except Exception:
            logger.exception("Failed to write _meta/_review_queue.json")
            stats["errors"] += 1

        # 1c. 导出 Agent 捕获会话与待整理笔记。笔记同样不经 Markdown
        #     承载；不导出会导致重建/换设备后“待整理内容”丢失。
        try:
            await _export_capture(session, meta_store, stats)
        except Exception:
            logger.exception("Failed to write _meta/_capture_notes.json")
            stats["errors"] += 1

        # 2. 拉取全部记忆。
        memories = (await session.execute(select(Memory))).scalars().all()
        total = len(memories)
        print_message(f"Found {total} memories to export")
        print_message()

        for i, mem in enumerate(memories):
            # workspace 已被删除时回退默认名，避免导出中断
            ws_name = ws_name_map.get(str(mem.workspace_id), "chat")

            # 2a. 写 Markdown 文件。
            try:
                mf = _memory_to_file(mem, ws_name)
                file_store.save(mf, workspace_name=ws_name)
                stats["file_count"] += 1
            except Exception:
                logger.exception("Failed to write MD for memory %s", mem.id)
                stats["errors"] += 1

            # 2b. 查询关联表并写 _meta JSON。
            try:
                relations = await _collect_relations(session, mem.id)
                meta_store.export_memory(str(mem.id), relations)
                stats["meta_count"] += 1
            except Exception:
                logger.exception("Failed to write _meta for memory %s", mem.id)
                stats["errors"] += 1

            stats["memory_count"] += 1
            if (i + 1) % 100 == 0:
                print_message(f"  Progress: {i + 1} / {total}")

        # 3. 对账 _meta/：删除 SQLite 中已不存在的记忆的侧车文件。
        #    删除流程会清掉 DB 行和 MD 文件，但没有运行时路径会重写
        #    _meta，孤儿侧车会持续累积，直到此处导出时统一清理。
        try:
            db_ids = {str(mem.id) for mem in memories}
            for orphan_id in meta_store.list_memories():
                if orphan_id not in db_ids and meta_store.delete_memory(orphan_id):
                    stats["orphan_meta_deleted"] += 1
            if stats["orphan_meta_deleted"]:
                print_message(f"Removed {stats['orphan_meta_deleted']} orphan _meta sidecar(s)")
        except Exception:
            logger.exception("Failed to reconcile _meta directory")
            stats["errors"] += 1

    await engine.dispose()

    print_message()
    print_message("Migration complete:")
    print_message(f"  Memories processed:  {stats['memory_count']}")
    print_message(f"  MD files written:    {stats['file_count']}")
    print_message(f"  Meta files written:  {stats['meta_count']}")
    print_message(f"  Workspaces exported: {stats['workspace_count']}")
    print_message(f"  Candidates exported: {stats['candidate_count']}")
    print_message(f"  Reviews exported:    {stats['review_count']}")
    print_message(f"  Capture sessions:    {stats['capture_session_count']}")
    print_message(f"  Capture notes:       {stats['capture_note_count']}")
    print_message(f"  Orphan _meta removed: {stats['orphan_meta_deleted']}")
    print_message(f"  Errors:              {stats['errors']}")

    return stats


async def _export_review_queue(
    session: AsyncSession,
    meta_store: MetaStore,
    stats: dict[str, int],
) -> None:
    """导出全部候选（所有状态）及各自评审留痕到 ``_review_queue.json``。

    候选审批后行保留（status=approved 等），因此历史候选与其 review
    留痕一并导出 —— 重建后审核历史不丢。
    """
    candidates = (await session.execute(select(CandidateMemory))).scalars().all()
    reviews = (await session.execute(select(Review))).scalars().all()

    # 按 candidate_id 分组，一次全量查询避免逐候选 N+1。
    reviews_by_candidate: dict[uuid.UUID, list[Review]] = {}
    for r in reviews:
        reviews_by_candidate.setdefault(r.candidate_id, []).append(r)

    # 排序保证输出确定（git diff 稳定）：候选按创建时间，留痕按创建时间。
    candidates_sorted = sorted(candidates, key=lambda c: (c.created_at, str(c.id)))
    entries: list[dict[str, Any]] = []
    for c in candidates_sorted:
        cand_reviews = sorted(
            reviews_by_candidate.get(c.id, []),
            key=lambda r: (r.created_at, str(r.id)),
        )
        entries.append(
            {
                **_serialize_row(c, _CANDIDATE_FIELDS),
                "reviews": [_serialize_row(r, _REVIEW_FIELDS) for r in cand_reviews],
            }
        )

    payload = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "candidates": entries,
    }
    meta_store.export_review_queue(payload)
    stats["candidate_count"] = len(entries)
    stats["review_count"] = sum(len(e["reviews"]) for e in entries)


async def _export_capture(
    session: AsyncSession,
    meta_store: MetaStore,
    stats: dict[str, int],
) -> None:
    """导出 Agent 会话与待整理笔记全文到 ``_capture_notes.json``。"""
    sessions = (await session.execute(select(AgentSession))).scalars().all()
    notes = (await session.execute(select(SessionNote))).scalars().all()

    session_fields = [
        "id",
        "workspace_id",
        "agent",
        "agent_version",
        "repository",
        "branch",
        "task",
        "event_session_id",
        "started_at",
        "ended_at",
        "outcome",
        "metadata_",
        "created_at",
    ]
    note_fields = [
        "id",
        "session_id",
        "workspace_id",
        "content",
        "signal_type",
        "formalized",
        "formalized_memory_id",
        "candidate_id",
        "created_at",
    ]
    payload = {
        "schema_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "sessions": [
            _serialize_row(row, session_fields)
            for row in sorted(sessions, key=lambda r: (r.started_at, str(r.id)))
        ],
        "notes": [
            _serialize_row(row, note_fields)
            for row in sorted(notes, key=lambda r: (r.created_at, str(r.id)))
        ],
    }
    meta_store.export_capture(payload)
    stats["capture_session_count"] = len(payload["sessions"])
    stats["capture_note_count"] = len(payload["notes"])


async def _collect_relations(session: AsyncSession, memory_id: uuid.UUID) -> dict[str, Any]:
    """查询单条记忆在全部关联表中的行，返回 dict。"""
    relations: dict[str, Any] = {}

    # feedback（反馈）
    rows = (
        (await session.execute(select(MemoryFeedback).where(MemoryFeedback.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["feedback"] = [
        _serialize_row(
            r,
            [
                "id",
                "workspace_id",
                "memory_id",
                "feedback_type",
                "source_type",
                "source_id",
                "reason",
                "created_at",
            ],
        )
        for r in rows
    ]

    # usage（使用记录）
    rows = (
        (await session.execute(select(MemoryUsage).where(MemoryUsage.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["usage"] = [
        _serialize_row(
            r,
            [
                "id",
                "workspace_id",
                "memory_id",
                "trace_id",
                "session_id",
                "position",
                "stage",
                "created_at",
            ],
        )
        for r in rows
    ]

    # conflict（冲突）
    rows = (
        (await session.execute(select(MemoryConflict).where(MemoryConflict.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["conflict"] = [
        _serialize_row(
            r,
            [
                "id",
                "workspace_id",
                "memory_id",
                "candidate_id",
                "conflict_type",
                "description",
                "evidence",
                "status",
                "resolution",
                "created_at",
                "resolved_at",
            ],
        )
        for r in rows
    ]

    # review_schedule（复习计划，1:1）
    row = (
        await session.execute(select(ReviewSchedule).where(ReviewSchedule.memory_id == memory_id))
    ).scalar_one_or_none()
    if row:
        relations["review_schedule"] = _serialize_row(
            row,
            [
                "id",
                "workspace_id",
                "memory_id",
                "ease_factor",
                "interval_days",
                "repetitions",
                "next_review",
                "last_review",
                "total_reviews",
                "created_at",
                "updated_at",
            ],
        )
    else:
        relations["review_schedule"] = {}

    # relation（作为 source 或 target 的关联）
    rows = (
        (
            await session.execute(
                select(MemoryRelation).where(
                    (MemoryRelation.source_memory_id == memory_id)
                    | (MemoryRelation.target_memory_id == memory_id)
                )
            )
        )
        .scalars()
        .all()
    )
    relations["relation"] = [
        _serialize_row(
            r,
            [
                "id",
                "source_memory_id",
                "target_memory_id",
                "relation_type",
                "confidence",
                "created_at",
            ],
        )
        for r in rows
    ]

    # lifecycle_event（生命周期事件）
    rows = (
        (
            await session.execute(
                select(MemoryLifecycleEvent).where(MemoryLifecycleEvent.memory_id == memory_id)
            )
        )
        .scalars()
        .all()
    )
    relations["lifecycle_event"] = [
        _serialize_row(
            r,
            ["id", "memory_id", "event_type", "metadata_json", "created_at"],
        )
        for r in rows
    ]

    # evidence（证据）
    rows = (
        (await session.execute(select(Evidence).where(Evidence.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["evidence"] = [
        _serialize_row(
            r,
            [
                "id",
                "memory_id",
                "candidate_id",
                "episode_id",
                "event_id",
                "source_type",
                "source_ref",
                "content",
                "metadata",
                "created_at",
            ],
        )
        for r in rows
    ]

    # versions（版本快照）—— 按 version 降序截断到 meta_version_limit 条：
    # 保留最新、丢弃最旧，既控制 _meta JSON 体积，也保住最常被回溯的
    # 近期版本链。序列化时恢复升序，文件内版本链由旧到新便于阅读。
    limit = storage_config.meta_version_limit
    rows = (
        (
            await session.execute(
                select(MemoryVersion)
                .where(MemoryVersion.memory_id == memory_id)
                .order_by(MemoryVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    relations["versions"] = [
        _serialize_row(
            r,
            [
                "id",
                "memory_id",
                "version",
                "title",
                "content",
                "change_type",
                "changed_by_type",
                "changed_by_id",
                "reason",
                "created_at",
            ],
        )
        for r in reversed(rows[:limit])
    ]

    # review_history（复习事件史）—— 全量导出，行数通常很小。
    rows = (
        (await session.execute(select(ReviewHistory).where(ReviewHistory.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["review_history"] = [
        _serialize_row(
            r,
            [
                "id",
                "workspace_id",
                "memory_id",
                "quality",
                "ease_factor_before",
                "interval_before",
                "repetitions_before",
                "next_review_before",
                "mastery_level_before",
                "ease_factor_after",
                "interval_after",
                "repetitions_after",
                "next_review_after",
                "mastery_level_after",
                "reviewed_at",
                "created_at",
            ],
        )
        for r in rows
    ]

    return relations


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main() -> int:
    result = asyncio.run(migrate_to_git())
    return 1 if result.get("errors", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
