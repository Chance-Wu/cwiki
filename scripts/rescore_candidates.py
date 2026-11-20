"""为存量 pending 候选回填评分与质量门五维明细。

五维明细（quality_report.quality_gate.criteria）从 2026-11 评分任务改造后
才开始写入；此前的 pending 候选只有均分（或 value_score 为空）。本脚本
对缺明细或缺 value_score 的候选逐条重跑评分任务——与队列任务同一实现
（task_score_candidate 会重算 value/gate 并写 quality_report）。

用法：python scripts/rescore_candidates.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def rescore(dry_run: bool) -> None:
    from sqlalchemy import or_, select

    from apps.worker.tasks import task_score_candidate
    from packages.domain.database import async_session_maker, init_db
    from packages.domain.models import CandidateMemory
    from packages.retrieval.embedding import get_embedding_service

    await init_db()

    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(CandidateMemory.id, CandidateMemory.workspace_id)
                .where(
                    CandidateMemory.status == "pending_review",
                    or_(
                        CandidateMemory.value_score.is_(None),
                        CandidateMemory.quality_report.is_(None),
                    ),
                )
                .order_by(CandidateMemory.created_at)
            )
        ).all()
    targets = [(str(r[0]), str(r[1])) for r in rows]
    logger.info("待回填候选：%d 条（dry_run=%s）", len(targets), dry_run)
    if dry_run or not targets:
        return

    embedding_service = get_embedding_service()
    ctx = {"embedding_service": embedding_service}
    ok = failed = 0
    for candidate_id, workspace_id in targets:
        try:
            result = await task_score_candidate(ctx, candidate_id, workspace_id)
            ok += 1
            logger.info("  %s -> %s", candidate_id[:8], result.get("status"))
        except Exception:
            failed += 1
            logger.exception("评分失败：%s", candidate_id)

    logger.info("回填完成：%d 成功，%d 失败", ok, failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填存量候选的评分与质量门五维明细")
    parser.add_argument("--dry-run", action="store_true", help="只列出目标，不执行")
    args = parser.parse_args()
    asyncio.run(rescore(args.dry_run))
