"""从源数据重算全部派生字段。

把 review_history 通过 SM-2 重放以重建 review_schedule，并确保每条
活跃记忆都有计划行。

用法::

    python scripts/recompute.py
    # 或经由 tasks.py：
    python tasks.py recompute
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
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
from packages.domain.models import Memory, ReviewHistory, ReviewSchedule
from packages.memory.spaced_repetition import (
    get_initial_schedule,
    sm2_algorithm,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def recompute() -> dict[str, int]:
    """重算全部派生字段。

    返回新建 / 重算 / 保持不变的复习计划数量的统计 dict。
    """
    db_url = settings.database_url
    t0 = time.monotonic()

    connect_args: dict[str, Any] = {}
    if "sqlite" in db_url:
        # SQLite 需关闭同线程检查，异步驱动会跨线程使用连接
        connect_args["check_same_thread"] = False

    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    stats: dict[str, int] = {
        "total_memories": 0,
        "schedules_created": 0,
        "schedules_recomputed": 0,
        "schedules_unchanged": 0,
        "errors": 0,
    }

    async with session_factory() as session:
        try:
            # 1. 拉取全部活跃记忆。
            mem_rows = (
                (await session.execute(select(Memory).where(Memory.status == "active")))
                .scalars()
                .all()
            )
            stats["total_memories"] = len(mem_rows)
            print_message(f"Found {len(mem_rows)} active memories")

            # 2. 拉取现有复习计划，按 memory_id 建索引。
            schedule_rows = (await session.execute(select(ReviewSchedule))).scalars().all()
            existing_schedules: dict[uuid.UUID, ReviewSchedule] = {
                s.memory_id: s for s in schedule_rows
            }
            print_message(f"Found {len(existing_schedules)} existing review schedules")

            # 3. 拉取全部复习历史，按 memory_id 分组。
            history_rows = (
                (
                    await session.execute(
                        select(ReviewHistory).order_by(
                            ReviewHistory.memory_id, ReviewHistory.reviewed_at
                        )
                    )
                )
                .scalars()
                .all()
            )

            history_by_memory: dict[uuid.UUID, list[ReviewHistory]] = {}
            for h in history_rows:
                history_by_memory.setdefault(h.memory_id, []).append(h)

            print_message(
                f"Found {len(history_rows)} review history entries "
                f"for {len(history_by_memory)} memories"
            )
            print_message()

            # 4. 逐条重算每条记忆的复习计划。
            for mem in mem_rows:
                try:
                    history = history_by_memory.get(mem.id, [])
                    existing = existing_schedules.get(mem.id)

                    if history:
                        # 通过 SM-2 重放复习历史。
                        new_schedule = _replay_history(mem.id, mem.workspace_id, history)
                        if existing is None:
                            session.add(new_schedule)
                            stats["schedules_created"] += 1
                        else:
                            # 用重放得到的值更新现有计划。
                            existing.ease_factor = new_schedule.ease_factor
                            existing.interval_days = new_schedule.interval_days
                            existing.repetitions = new_schedule.repetitions
                            existing.next_review = new_schedule.next_review
                            existing.last_review = new_schedule.last_review
                            existing.total_reviews = new_schedule.total_reviews
                            stats["schedules_recomputed"] += 1
                    elif existing is None:
                        # 无历史也无计划——创建初始计划。
                        initial = get_initial_schedule(mem.created_at)
                        schedule = ReviewSchedule(
                            id=uuid.uuid4(),
                            workspace_id=mem.workspace_id,
                            memory_id=mem.id,
                            ease_factor=initial.ease_factor,
                            interval_days=initial.interval_days,
                            repetitions=initial.repetitions,
                            next_review=initial.next_review,
                            total_reviews=0,
                        )
                        session.add(schedule)
                        stats["schedules_created"] += 1
                    else:
                        # 有计划但无历史——保持不变。
                        stats["schedules_unchanged"] += 1

                except Exception:
                    logger.exception("Failed to recompute schedule for memory %s", mem.id)
                    stats["errors"] += 1

            await session.commit()
            elapsed = time.monotonic() - t0
            print_message(f"Recompute complete in {elapsed:.1f}s:")
            print_message(f"  Total memories:    {stats['total_memories']}")
            print_message(f"  Schedules created: {stats['schedules_created']}")
            print_message(f"  Schedules updated: {stats['schedules_recomputed']}")
            print_message(f"  Schedules unchanged: {stats['schedules_unchanged']}")
            print_message(f"  Errors:            {stats['errors']}")

        except Exception:
            await session.rollback()
            logger.exception("Recompute failed, transaction rolled back")
            stats["errors"] += 1
            raise
        finally:
            await engine.dispose()

    return stats


def _replay_history(
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID,
    history: list[ReviewHistory],
) -> ReviewSchedule:
    """通过 SM-2 重放复习历史，生成 ReviewSchedule。

    history 列表必须按 reviewed_at 升序排列。
    """
    # 查询虽已按时间排序，这里再排一次，保证任意调用顺序下结果一致。
    history = sorted(history, key=lambda h: h.reviewed_at)

    # 从初始计划出发。
    schedule = get_initial_schedule(history[0].reviewed_at)
    total_reviews = 0

    for h in history:
        result = sm2_algorithm(
            ease_factor=schedule.ease_factor,
            interval_days=schedule.interval_days,
            repetitions=schedule.repetitions,
            quality=h.quality,
            review_time=h.reviewed_at,
        )
        schedule.ease_factor = result.ease_factor
        schedule.interval_days = result.interval_days
        schedule.repetitions = result.repetitions
        schedule.next_review = result.next_review
        total_reviews += 1

    return ReviewSchedule(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        memory_id=memory_id,
        ease_factor=schedule.ease_factor,
        interval_days=schedule.interval_days,
        repetitions=schedule.repetitions,
        next_review=schedule.next_review,
        last_review=history[-1].reviewed_at,
        total_reviews=total_reviews,
    )


def main() -> int:
    try:
        result = asyncio.run(recompute())
        return 1 if result.get("errors", 0) > 0 else 0
    except Exception:
        logger.exception("Recompute script failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
