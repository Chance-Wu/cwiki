"""校验重建一致性：对比 MD/_meta 数据与重建后的 SQLite。

用法:
    python scripts/verify_rebuild.py
        MD/_meta 与当前 DB 核对（数量 + 抽样字段 + 关联表行数）。

    python scripts/verify_rebuild.py --against-db BASELINE.db
        列级对账模式：重建后的 DB 与恢复演练前的基线 DB 快照逐表逐列
        对比（W7 恢复演练验收"恢复结果经自动化对账"的配套工具）。
        归一化规则（W7-03 演练实测的三类格式噪音）：
        1. 行尾换行——MD 往返中正文尾部 \\n 不保真；
        2. datetime 零微秒——`.000000` 与无微秒形式等效；
        3. 字符串 'null' 与 SQL NULL 等效（历史 JSON 列 None 落库格式，
           JSONBType none_as_null 修复后新数据不再产生）。
        embedding 列跳过（重建后重新生成，模型/内容任一变化即不同）；
        运行期表（session/agent/retrieval_trace 等）不在重建范围，只报
        行数不参与对账（是否纳入导出范围待决策，见审计 3.5）。

本脚本默认模式检查：
1. MD 文件中的记忆数 vs memory 表行数。
2. 抽样对比关键字段（title、content、confidence、importance）。
3. 各关联表行数 vs _meta JSON 数据（含版本快照与复习事件史）。
4. 候选审核队列行数（candidate_memory / review）vs _review_queue.json。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sqlite3
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
)
from packages.storage import config as storage_config
from packages.storage.file_store import FileStore
from packages.storage.meta_store import MetaStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 重建范围表：由 MD + _meta 完整重建的表，参与列级对账。
REBUILD_TABLES: tuple[str, ...] = (
    "memory",
    "workspace",
    "candidate_memory",
    "agent_session",
    "session_note",
    "review",
    "review_schedule",
    "review_history",
    "memory_relation",
    "memory_feedback",
    "memory_usage",
    "memory_conflict",
    "memory_version",
    "memory_lifecycle_event",
    "evidence",
)

# 重建后重新生成的列：对账无意义（值随 embedding 模型/内容重算而变）。
SKIP_COLUMNS: dict[str, set[str]] = {
    "memory": {"embedding"},
    "candidate_memory": {"embedding"},
}

_DATETIME_ZERO_FRAC = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\.0{1,6}$")

_norm_stats = {"null_text": 0, "datetime_frac": 0, "trailing_newline": 0}


def _normalize(value: Any) -> Any:
    """对账归一化：把已知格式噪音折算成等效形式（规则见模块 docstring）。"""
    if not isinstance(value, str):
        return value
    if value == "null":
        _norm_stats["null_text"] += 1
        return None
    match = _DATETIME_ZERO_FRAC.match(value)
    if match:
        _norm_stats["datetime_frac"] += 1
        return match.group(1)
    if value.endswith("\n"):
        _norm_stats["trailing_newline"] += 1
        return value.rstrip("\n")
    return value


def _short(value: Any) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= 60 else f"{text[:57]}..."


def _sqlite_path(db_url: str) -> Path | None:
    if not db_url.startswith("sqlite"):
        return None
    raw = db_url.split("///", 1)[-1]
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _user_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _load_rows(conn: sqlite3.Connection, table: str, columns: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in conn.execute(f'SELECT * FROM "{table}"'):
        record = {k: _normalize(v) for k, v in dict(row).items() if k in columns}
        rows[str(record.get("id"))] = record
    return rows


def _compare_table(
    base_conn: sqlite3.Connection, rebuilt_conn: sqlite3.Connection, table: str
) -> bool:
    """逐行逐列对比一张重建范围表，返回该表是否一致。"""
    base_cols = _table_columns(base_conn, table)
    rebuilt_cols = _table_columns(rebuilt_conn, table)
    common = [c for c in base_cols if c in rebuilt_cols and c not in SKIP_COLUMNS.get(table, set())]
    skipped = (set(base_cols) | set(rebuilt_cols)) - set(common)
    note = f"（跳过列: {', '.join(sorted(skipped))}）" if skipped else ""
    print_message(f"  {table}{note}")

    if "id" not in common:
        # 无主键则退化为行数对比，不做列级断言。
        b, r = _row_count(base_conn, table), _row_count(rebuilt_conn, table)
        status = "OK" if b == r else "DIFF"
        print_message(f"    [{status}] 无 id 列，仅对比行数: baseline={b}, rebuilt={r}")
        return b == r

    base_rows = _load_rows(base_conn, table, common)
    rebuilt_rows = _load_rows(rebuilt_conn, table, common)
    ok = True

    missing_in_rebuilt = sorted(set(base_rows) - set(rebuilt_rows))
    missing_in_base = sorted(set(rebuilt_rows) - set(base_rows))
    if missing_in_rebuilt:
        ok = False
        preview = ", ".join(missing_in_rebuilt[:5])
        more = " ..." if len(missing_in_rebuilt) > 5 else ""
        print_message(f"    [DIFF] 基线有、重建后缺 {len(missing_in_rebuilt)} 行: {preview}{more}")
    if missing_in_base:
        ok = False
        preview = ", ".join(missing_in_base[:5])
        more = " ..." if len(missing_in_base) > 5 else ""
        print_message(f"    [DIFF] 重建后多出 {len(missing_in_base)} 行: {preview}{more}")

    diff_rows = 0
    shown = 0
    for mid in sorted(set(base_rows) & set(rebuilt_rows)):
        b_row, r_row = base_rows[mid], rebuilt_rows[mid]
        cols_diff = [c for c in common if b_row[c] != r_row[c]]
        if not cols_diff:
            continue
        diff_rows += 1
        if shown < 5:
            shown += 1
            detail = "; ".join(
                f"{c}: {_short(b_row[c])} -> {_short(r_row[c])}" for c in cols_diff[:3]
            )
            extra = f" (+{len(cols_diff) - 3} cols)" if len(cols_diff) > 3 else ""
            print_message(f"    [DIFF] {mid}: {detail}{extra}")
    if diff_rows:
        ok = False
        print_message(f"    [DIFF] 内容不一致 {diff_rows} 行")
    else:
        print_message(f"    [OK] {len(base_rows)} 行逐列一致")
    return ok


def verify_against_db(baseline_path: Path, rebuilt_path: Path | None = None) -> int:
    """列级对账：重建后 DB vs 基线快照（W7 恢复演练配套验收工具）。"""
    if rebuilt_path is None:
        rebuilt_path = _sqlite_path(settings.database_url)
        if rebuilt_path is None:
            print_message(f"[ERROR] 仅支持 SQLite 对账，当前 database_url: {settings.database_url}")
            return 1
    for label, path in (("基线", baseline_path), ("重建后", rebuilt_path)):
        if not path.exists():
            print_message(f"[ERROR] {label}数据库不存在: {path}")
            return 1

    print_message("=== DB 列级对账（重建后 vs 基线） ===")
    print_message(f"  基线:   {baseline_path}")
    print_message(f"  重建后: {rebuilt_path}")
    print_message()

    base_conn = sqlite3.connect(str(baseline_path))
    rebuilt_conn = sqlite3.connect(str(rebuilt_path))
    base_conn.row_factory = sqlite3.Row
    rebuilt_conn.row_factory = sqlite3.Row
    ok = True
    try:
        print_message("--- 重建范围表 ---")
        base_tables = _user_tables(base_conn)
        rebuilt_tables = _user_tables(rebuilt_conn)
        for table in REBUILD_TABLES:
            if table not in base_tables:
                print_message(f"  [SKIP] {table}: 基线库中不存在")
                continue
            if table not in rebuilt_tables:
                ok = False
                print_message(f"  [DIFF] {table}: 重建后库中缺失")
                continue
            if not _compare_table(base_conn, rebuilt_conn, table):
                ok = False

        runtime = sorted((base_tables | rebuilt_tables) - set(REBUILD_TABLES))
        print_message()
        print_message("--- 运行期表（不在重建范围，仅报行数，见审计 3.5 决策点） ---")
        for table in runtime:
            b = _row_count(base_conn, table) if table in base_tables else None
            r = _row_count(rebuilt_conn, table) if table in rebuilt_tables else None
            print_message(f"  [INFO] {table}: baseline={b}, rebuilt={r}")
    finally:
        base_conn.close()
        rebuilt_conn.close()

    print_message()
    stats = ", ".join(f"{k}={v}" for k, v in _norm_stats.items())
    print_message(f"归一化规则命中（两侧合计，均为等效折算非真实差异）: {stats}")
    print_message()
    print_message("对账结果: " + ("PASS —— 重建范围表全部一致" if ok else "FAIL —— 存在真实差异"))
    return 0 if ok else 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify rebuild consistency.")
    parser.add_argument(
        "--against-db",
        type=Path,
        metavar="BASELINE_DB",
        help="列级对账模式：重建后 DB 与基线 DB 快照逐表逐列对比",
    )
    parser.add_argument(
        "--rebuilt-db",
        type=Path,
        metavar="REBUILT_DB",
        help="覆盖对账的重建侧 DB（默认取 config 的 database_url；沙箱演练用）",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.against_db:
        return verify_against_db(args.against_db, args.rebuilt_db)

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

        # --- 捕获会话 / 待整理笔记对比（DB vs _meta/_capture_notes.json）---
        print_message()
        print_message("=== Capture notes counts ===")
        capture = meta_store.import_capture() or {}
        export_sessions = (
            capture.get("sessions") if isinstance(capture.get("sessions"), list) else []
        )
        export_notes = capture.get("notes") if isinstance(capture.get("notes"), list) else []
        db_sessions = len((await session.execute(select(AgentSession))).scalars().all())
        db_notes = len((await session.execute(select(SessionNote))).scalars().all())
        for name, db_c, export_c in (
            ("agent_session", db_sessions, len(export_sessions)),
            ("session_note", db_notes, len(export_notes)),
        ):
            status = "OK" if db_c == export_c else "DIFF"
            print_message(f"  [{status}] {name}: DB={db_c}, EXPORT={export_c}")

    await engine.dispose()
    print_message()
    print_message("Verification complete.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
