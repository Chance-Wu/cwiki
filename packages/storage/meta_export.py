"""记忆侧车（``_meta``）导出的共享实现。

两条路径共用同一套字段定义：

- 写入路径（``apps/api/file_sync.py``）在 MD 镜像落盘后按条增量导出，
  消除“保存后要等周期全量导出才有 _meta”的窗口期；
- 全量导出（``scripts/migrate_to_git.py``）供 Git 同步与数据重建。

关系表字段在此集中维护，避免增量导出与全量导出出现 schema 漂移。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import (
    Evidence,
    MemoryConflict,
    MemoryFeedback,
    MemoryLifecycleEvent,
    MemoryRelation,
    MemoryUsage,
    MemoryVersion,
    ReviewHistory,
    ReviewSchedule,
    Workspace,
)
from packages.storage import config as storage_config
from packages.storage.meta_store import MetaStore


def serialize_row(row: Any, fields: list[str]) -> dict[str, Any]:
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


def default_meta_dir() -> Path:
    """配置里的 memory_dir 下的 ``_meta`` 目录。"""
    return Path(storage_config.memory_dir) / "_meta"


async def collect_memory_relations(session: AsyncSession, memory_id: uuid.UUID) -> dict[str, Any]:
    """查询单条记忆在全部关联表中的行，返回 _meta 字典。"""
    relations: dict[str, Any] = {}

    # feedback（反馈）
    rows: Any = (
        (await session.execute(select(MemoryFeedback).where(MemoryFeedback.memory_id == memory_id)))
        .scalars()
        .all()
    )
    relations["feedback"] = [
        serialize_row(
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
        serialize_row(
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
        serialize_row(
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
        relations["review_schedule"] = serialize_row(
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
                "lapse_streak",
                "suspended_at",
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
        serialize_row(
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
        serialize_row(
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
        serialize_row(
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
        serialize_row(
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
        serialize_row(
            r,
            [
                "id",
                "workspace_id",
                "memory_id",
                "quality",
                "quiz_type",
                "quiz_correct",
                "quiz_prompt",
                "quiz_expected",
                "quiz_response",
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


async def export_memory_meta(
    session: AsyncSession,
    memory_id: uuid.UUID,
    meta_dir: Path | None = None,
) -> Path:
    """导出单条记忆的 ``_meta/{id}.json``（覆盖写）。

    必须整份重写而不是补空字段：_meta 是重建 DB 的源，写空对象会把
    已有关联数据（关系/复习计划/反馈）抹掉。
    """
    store = MetaStore(meta_dir or default_meta_dir())
    relations = await collect_memory_relations(session, memory_id)
    return await asyncio.to_thread(store.export_memory, str(memory_id), relations)


async def export_workspaces_meta(
    session: AsyncSession,
    meta_dir: Path | None = None,
) -> int:
    """导出 ``_meta/_workspaces.json``，返回工作区数量。

    包含没有记忆的空工作区；重建器依赖它精确恢复 workspace 表。
    """
    rows = (await session.execute(select(Workspace))).scalars().all()
    payload = [
        serialize_row(ws, ["name", "id", "created_at", "updated_at"])
        for ws in sorted(rows, key=lambda w: w.name)
    ]
    store = MetaStore(meta_dir or default_meta_dir())
    await asyncio.to_thread(store.export_workspaces, payload)
    return len(payload)
