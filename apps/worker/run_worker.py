"""手动运行的 worker 脚本：把事件加工成 episode。"""

import asyncio
import logging

from sqlalchemy import distinct, select

from apps.worker.tasks import register_tasks, task_finalize_episode
from packages.domain.config import settings
from packages.domain.database import async_session_maker, init_db
from packages.domain.models import Episode, Event
from packages.domain.task_queue import queue
from packages.retrieval.embedding import get_embedding_service

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.WARNING)
logger = logging.getLogger(__name__)


async def get_sessions_with_events() -> list[tuple[str, str]]:
    """从事件中取尚未生成 episode 的 (session_id, workspace_id) 去重对。"""
    async with async_session_maker() as db:
        processed_sessions = select(Episode.session_id)
        result = await db.execute(
            select(distinct(Event.session_id), Event.workspace_id).where(
                Event.session_id.not_in(processed_sessions)
            )
        )
        return [(str(session_id), str(workspace_id)) for session_id, workspace_id in result.all()]


async def main() -> None:
    """处理所有未加工的会话。"""
    logger.info("Initializing database...")
    await init_db()

    logger.info("Registering tasks and setting up embedding service...")
    register_tasks(queue)
    queue.set_context("embedding_service", get_embedding_service())

    sessions = await get_sessions_with_events()
    logger.info(f"Found {len(sessions)} sessions to process")

    # 并发上限 4，避免 episode 构建的 LLM/embedding 调用挤爆资源
    sem = asyncio.Semaphore(4)

    async def _process(sid: str, wid: str) -> None:
        async with sem:
            logger.info(f"Processing session {sid}")
            try:
                result = await task_finalize_episode(queue._context, sid, wid)
                logger.info(f"Episode result: {result}")
            except Exception:
                logger.exception(f"Failed to process session {sid}")

    await asyncio.gather(*[_process(sid, wid) for sid, wid in sessions])
    logger.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())
