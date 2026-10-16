"""校验重建一致性：对比 MD/_meta 数据与重建后的 SQLite。

用法:
    python scripts/verify_rebuild.py

本脚本检查：
1. MD 文件中的记忆数 vs memory 表行数。
2. 抽样对比关键字段（title、content、confidence、importance）。
3. 各关联表行数 vs _meta JSON 数据（含版本快照与复习事件史）。
4. 候选审核队列行数（candidate_memory / review）vs _review_queue.json。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
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
)
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore
from packages.storage.meta_store import MetaStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> int:
    data_dir = storage_config.memory_dir
    db_url = settings.database_url

    print_message(f"Data dir: {data_dir}")
    print_message(f"DB URL:   {db_url}")
    print_message()

    file_store = FileStore(data_dir)
    meta_store = MetaStore(f"{data_dir}/_meta")

    # --- 统计 MD 文件数 ---
    md_memories = file_store.list()
    md_count = len(md_memories)
    print_message(f"[MD]   Memory files: {md_count}")

    # --- 统计 _meta 文件数 ---
    meta_ids = meta_store.list_memories()
    meta_count = len(meta_ids)
    print_message(f"[META] Meta files:   {meta_count}")

    # --- 统计 DB 行数 ---
    connect_args: dict[str, Any] = {}
    if "sqlite" in db_url:
        # SQLite 需关闭同线程检查，异步驱动会跨线程使用连接
        connect_args["check_same_thread"] = False

    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        db_memory_count = (await session.execute(select(Memory))).scalars().all()
        db_count = len(db_memory_count)
        print_message(f"[DB]   Memory rows: {db_count}")
        print_message()

        # --- 数量对比 ---
        ok = True
        if md_count != db_count:
            print_message(f"[WARN] MD count ({md_count}) != DB count ({db_count})")
            ok = False
        else:
            print_message(f"[OK]   Memory counts match: {md_count}")

        if meta_count != db_count:
            print_message(f"[WARN] Meta count ({meta_count}) != DB memory count ({db_count})")
            # 未必是错误——部分记忆可能没有任何关联数据。
        else:
            print_message(f"[OK]   Meta counts match: {meta_count}")

        # --- 抽样对比关键字段 ---
        print_message()
        print_message("=== Sample field comparison (up to 5 memories) ===")
        sample_size = min(5, md_count)
        sample_ok = 0
        for mf in md_memories[:sample_size]:
            db_mem = (
                await session.execute(select(Memory).where(Memory.id == uuid.UUID(mf.id)))
            ).scalar_one_or_none()
            if db_mem is None:
                print_message(f"  [MISS] {mf.id} not found in DB")
                continue

            issues: list[str] = []
            if db_mem.title != mf.title:
                issues.append(f"title: DB={db_mem.title!r} vs MD={mf.title!r}")
            if db_mem.content.strip() != mf.content.strip():
                issues.append("content differs")
            if mf.confidence is not None and abs(db_mem.confidence - mf.confidence) > 0.001:
                issues.append(f"confidence: DB={db_mem.confidence} vs MD={mf.confidence}")
            if mf.importance is not None and abs(db_mem.importance - mf.importance) > 0.001:
                issues.append(f"importance: DB={db_mem.importance} vs MD={mf.importance}")
            if db_mem.is_permanent != mf.is_permanent:
                issues.append(f"is_permanent: DB={db_mem.is_permanent} vs MD={mf.is_permanent}")
            if db_mem.usage_count != mf.usage_count:
                issues.append(f"usage_count: DB={db_mem.usage_count} vs MD={mf.usage_count}")

            if issues:
                print_message(f"  [DIFF] {mf.id}: {'; '.join(issues)}")
            else:
                sample_ok += 1
                print_message(f"  [OK]   {mf.id}: {mf.title[:50]}")

        print_message(f"  Sample result: {sample_ok}/{sample_size} match")

        # --- 关联表行数对比 ---
        print_message()
        print_message("=== Relation table counts ===")
        relation_tables = {
            "memory_feedback": MemoryFeedback,
            "memory_usage": MemoryUsage,
            "memory_conflict": MemoryConflict,
            "review_schedule": ReviewSchedule,
            "memory_relation": MemoryRelation,
            "memory_lifecycle_event": MemoryLifecycleEvent,
            "evidence": Evidence,
            "memory_version": MemoryVersion,
            "review_history": ReviewHistory,
        }

        db_relation_counts: dict[str, int] = {}
        for name, model in relation_tables.items():
            count = len((await session.execute(select(model))).scalars().all())
            db_relation_counts[name] = count

        # 从 _meta 侧统计
        meta_relation_counts: dict[str, int] = {
            "memory_feedback": 0,
            "memory_usage": 0,
            "memory_conflict": 0,
            "review_schedule": 0,
            "memory_relation": 0,
            "memory_lifecycle_event": 0,
            "evidence": 0,
            "memory_version": 0,
            "review_history": 0,
        }
        for mid in meta_ids:
            meta = meta_store.import_memory(mid)
            if meta is None:
                continue
            meta_relation_counts["memory_feedback"] += len(meta.get("feedback", []))
            meta_relation_counts["memory_usage"] += len(meta.get("usage", []))
            meta_relation_counts["memory_conflict"] += len(meta.get("conflict", []))
            rs = meta.get("review_schedule")
            # review_schedule 是 1:1 对象而非列表，仅含有效 id 时才计数
            if rs and isinstance(rs, dict) and rs.get("id"):
                meta_relation_counts["review_schedule"] += 1
            meta_relation_counts["memory_relation"] += len(meta.get("relation", []))
            meta_relation_counts["memory_lifecycle_event"] += len(meta.get("lifecycle_event", []))
            meta_relation_counts["evidence"] += len(meta.get("evidence", []))
            meta_relation_counts["memory_version"] += len(meta.get("versions", []))
            meta_relation_counts["review_history"] += len(meta.get("review_history", []))

        for name in relation_tables:
            db_c = db_relation_counts[name]
            meta_c = meta_relation_counts[name]
            status = "OK" if db_c == meta_c else "DIFF"
            note = ""
            if name == "memory_version" and db_c > meta_c:
                # 导出侧按 meta_version_limit 截断：重建后 DB 只含最新
                # N 个版本，DB 多于 _meta 属预期（截断丢最旧）。
                note = " (expected: export truncates to meta_version_limit)"
            print_message(f"  [{status}] {name}: DB={db_c}, META={meta_c}{note}")

        # --- 候选审核队列对比（DB vs _meta/_review_queue.json）---
        print_message()
        print_message("=== Review queue counts ===")
        queue = meta_store.import_review_queue()
        queue_entries = []
        if queue is not None and isinstance(queue.get("candidates"), list):
            queue_entries = [c for c in queue["candidates"] if isinstance(c, dict)]
        queue_candidates = len(queue_entries)
        queue_reviews = sum(
            len(c.get("reviews") or []) if isinstance(c.get("reviews"), list) else 0
            for c in queue_entries
        )
        db_candidates = len((await session.execute(select(CandidateMemory))).scalars().all())
        db_reviews = len((await session.execute(select(Review))).scalars().all())
        for name, db_c, export_c in (
            ("candidate_memory", db_candidates, queue_candidates),
            ("review", db_reviews, queue_reviews),
        ):
            status = "OK" if db_c == export_c else "DIFF"
            print_message(f"  [{status}] {name}: DB={db_c}, EXPORT={export_c}")

    await engine.dispose()
    print_message()
    print_message("Verification complete.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
