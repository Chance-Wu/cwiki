"""从 Markdown + _meta 文件重建 cwiki.db（Phase 1.3）。

用法::

    python scripts/rebuild_db.py                  # 全量重建（索引仍新时跳过向量索引）
    python scripts/rebuild_db.py --force-index    # 即使索引存在也重新生成 embedding
    python scripts/rebuild_db.py --index-only     # 只重建 index.db + vectors.npz（+ vectors.json）
    # 或经由 tasks.py：
    python tasks.py rebuild-db [--force-index | --index-only]

派生索引文件随 git 同步、仍然有效时，重建是轻量的：仅当索引行数与
重建后的记忆数不一致、或显式传入 ``--force-index`` 时才重建向量索引。
仅当 ``_meta`` 未恢复任何复习计划（重建后无 ``review_schedule`` 行）
时才执行 ``recompute``。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 上。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import patch_metadata, print_message

patch_metadata()

from packages.domain.config import settings
from packages.storage import config as storage_config
from packages.storage.rebuilder import (
    DatabaseRebuilder,
    index_files_present,
    indexed_active_count,
    vector_meta_count,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild cwiki.db from Markdown + _meta files.")
    parser.add_argument(
        "--force-index",
        action="store_true",
        help="Rebuild the vector index even when index files are present and current",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Rebuild only the vector index (skip database rebuild and recompute)",
    )
    return parser.parse_args(argv)


async def _rebuild_vector_index_step(rebuilder: DatabaseRebuilder, *, force: bool) -> None:
    """第 2 步：除非现有索引仍然有效，否则重新生成向量索引。

    仅当索引文件齐全、index.db 活跃行数与 vectors.json 向量数均覆盖
    全量重建会产生的活跃记忆集时，跳过才是安全的 —— 两套文件任一
    偏少（如旧版中断残留）都可能导致检索静默缺向量。
    """
    print_message("=== Step 2: Vector index ===")

    if not force:
        present, missing = index_files_present()
        if not present:
            reason = f"index files missing or incomplete: {', '.join(missing)}"
        else:
            indexed_count = indexed_active_count()
            vector_count = vector_meta_count()
            _, active_memories, _ = await rebuilder.table_counts()
            if indexed_count == active_memories and vector_count == active_memories:
                print_message(
                    "  Skipped: index files present "
                    f"(use --force-index to rebuild) [{active_memories} active memories]"
                )
                return
            reason = (
                "index out of sync with memories "
                f"(indexed active: {indexed_count}, vectors: {vector_count}, "
                f"memories active: {active_memories})"
            )
    else:
        reason = "--force-index requested"

    print_message(
        f"  Rebuilding vector index ({reason}) — embedding generation may take a while..."
    )
    indexed = await rebuilder.rebuild_vector_index()
    print_message(f"  Indexed: {indexed} memories")


async def _recompute_step(rebuilder: DatabaseRebuilder) -> None:
    """第 3 步：仅当 _meta 未恢复复习计划时才运行 recompute。"""
    print_message("=== Step 3: Derived fields (review schedules) ===")
    memory_total, _, schedule_count = await rebuilder.table_counts()

    if schedule_count > 0:
        print_message(f"  Skipped: review schedules restored from _meta ({schedule_count} rows)")
        return
    if memory_total == 0:
        print_message("  Skipped: no memories to recompute")
        return

    print_message("  No review schedules found — recomputing derived fields ...")
    # 以独立子进程运行 recompute.py，隔离其引擎初始化与日志输出
    proc = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(ROOT / "scripts" / "recompute.py")],
        cwd=str(ROOT),
        check=False,
    )
    if proc.returncode != 0:
        print_message("  recompute failed (non-blocking, derived fields may be incomplete)")


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    db_url = settings.database_url
    data_dir = storage_config.memory_dir

    print_message(f"DB URL:   {db_url}")
    print_message(f"Data dir: {data_dir}")
    print_message()

    rebuilder = DatabaseRebuilder(db_url=db_url, data_dir=data_dir)

    try:
        if args.index_only:
            # 仅修复索引：不重建数据库，不重算派生字段。
            print_message("=== Rebuilding vector index only ===")
            print_message("  This may take a while (embedding generation)...")
            indexed = await rebuilder.rebuild_vector_index()
            print_message(f"  Indexed: {indexed} memories")
            print_message()
            print_message("Index rebuild complete!")
            return 0

        # 第 1 步：重建数据库表。
        print_message("=== Step 1: Rebuilding database tables ===")
        result = await rebuilder.rebuild()
        print_message(f"  Memories imported: {result.memory_count}")
        print_message(f"  Skipped files:     {len(result.skipped_files)}")
        print_message("  Relation counts:")
        for k, v in result.relation_counts.items():
            print_message(f"    {k}: {v}")
        print_message(f"  Elapsed:           {result.elapsed_seconds:.1f}s")
        print_message()

        # 第 2 步：向量索引——现有索引仍有效时跳过。
        await _rebuild_vector_index_step(rebuilder, force=args.force_index)
        print_message()

        # 第 3 步：派生字段——_meta 已恢复复习计划时跳过。
        await _recompute_step(rebuilder)
        print_message()

        print_message("Rebuild complete!")
        return 0

    except Exception:
        logger.exception("Rebuild failed")
        return 1
    finally:
        await rebuilder.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
