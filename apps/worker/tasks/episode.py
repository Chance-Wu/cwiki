"""Episode 任务：会话结束构建 episode 并提取记忆候选。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.worker.episode_builder import EpisodeData, build_episode
from packages.domain.config import parasitic_evolution_config, settings
from packages.domain.database import async_session_maker
from packages.domain.models import CandidateMemory, Episode, Event
from packages.domain.task_queue import TaskQueue
from packages.memory.service import ContentFormatError, create_candidate

logger = logging.getLogger(__name__)


async def task_finalize_episode(
    ctx: dict[str, Any], session_id: str, workspace_id: str
) -> dict[str, Any]:
    """从事件构建 episode 并提取记忆。"""
    logger.info("Finalizing episode for session %s", session_id)

    async with async_session_maker() as db_session:
        sid = uuid.UUID(session_id)
        wid = uuid.UUID(workspace_id)

        # 幂等守卫：队列是 at-least-once，finalize 重放/重复入队不得重建
        # episode（否则时间窗回填与规则候选生成会重复执行）
        existing_episode = (
            await db_session.execute(
                select(Episode.id).where(
                    Episode.session_id == sid,
                    Episode.workspace_id == wid,
                )
            )
        ).scalar_one_or_none()
        if existing_episode is not None:
            logger.info(
                "Episode %s already exists for session %s, skipping finalize",
                existing_episode,
                session_id,
            )
            return {"episode_id": str(existing_episode), "status": "already_finalized"}

        events_query = select(Event).where(Event.session_id == sid).order_by(Event.sequence)
        events_result = await db_session.execute(events_query)
        events = []
        for event in events_result.scalars().all():
            events.append(
                {
                    "id": str(event.id),
                    "event_type": event.event_type,
                    "sequence": event.sequence,
                    "payload": event.payload,
                    "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                }
            )

        if not events:
            logger.warning("No events found for session %s", session_id)
            return {"episode_id": None, "status": "no_events"}

        episode_data = build_episode(session_id, events)

        episode = Episode(
            workspace_id=wid,
            session_id=sid,
            goal=episode_data.goal,
            summary=episode_data.summary,
            status="completed",
            importance=sum(1 for _ in episode_data.actions) * 0.05,
            started_at=(
                datetime.fromisoformat(str(events[0]["occurred_at"]))
                if events[0].get("occurred_at")
                else datetime.now(UTC)
            ),
            ended_at=(
                datetime.fromisoformat(str(events[-1]["occurred_at"]))
                if events[-1].get("occurred_at")
                else datetime.now(UTC)
            ),
            event_count=len(events),
            metadata_={"lessons": episode_data.lessons},
        )

        db_session.add(episode)
        await db_session.commit()
        await db_session.refresh(episode)

        # 为 episode 生成向量以支持情节化检索
        try:
            from packages.domain.config import parasitic_evolution_config as _pec

            if _pec.episodic_retrieval_enabled:
                from packages.retrieval.embedding import get_embedding_service

                emb_text = f"{episode_data.goal or ''} {episode_data.summary or ''}".strip()
                if emb_text:
                    emb_svc = get_embedding_service()
                    vec = await emb_svc.generate_embedding(emb_text)
                    if vec is not None:
                        episode.embedding = vec
                        await db_session.flush()
        except Exception:
            logger.debug("Episode embedding generation failed", exc_info=True)

        # 回填：把 episode 时间窗内尚未关联的 pending 候选挂到该 episode 上
        # （候选表无 session 外键，这是候选与 episode 建立关联的唯一途径）
        candidates_linked = 0
        try:
            # 独立 commit：同时把上方 flush 的 episode 向量一并落库；
            # 回填失败不应让整个任务失败（episode 本身已落库成功）
            candidates_linked = await _backfill_episode_candidates(db_session, episode)
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            logger.warning(
                "Backfilling episode_id for episode %s failed", episode.id, exc_info=True
            )

        # 规则候选生成：仅当「失败→修复」信号齐备（保守触发，默认关）
        candidate_generated = False
        if (
            parasitic_evolution_config.episode_candidate_extraction_enabled
            and episode_data.problems
            and episode_data.solutions
        ):
            candidate_generated = await _generate_episode_candidate(
                db_session, ctx, episode, episode_data
            )

        logger.info("Episode %s created for session %s", episode.id, session_id)

        return {
            "episode_id": str(episode.id),
            "status": "completed",
            "event_count": len(events),
            "goal": episode_data.goal,
            "candidates_linked": candidates_linked,
            "candidate_generated": candidate_generated,
        }


# 回填时间窗的余量：单事件 episode 的 started_at == ended_at，
# 过窄的窗口会漏掉几乎同时产生的候选，前后各放宽数秒兜底
_EPISODE_BACKFILL_MARGIN = timedelta(seconds=5)


async def _backfill_episode_candidates(db_session: AsyncSession, episode: Episode) -> int:
    """把 episode 时间窗内符合条件的 pending 候选批量回填 episode_id。

    候选表没有 session 外键，只能按 workspace + 创建时间窗近似关联；
    episode_id IS NULL 条件保证重复 finalize 不会改写既有关联。
    返回回填行数。
    """
    if episode.started_at is None or episode.ended_at is None:
        return 0
    result = await db_session.execute(
        update(CandidateMemory)
        .where(
            CandidateMemory.workspace_id == episode.workspace_id,
            CandidateMemory.status == "pending_review",
            CandidateMemory.episode_id.is_(None),
            CandidateMemory.created_at >= episode.started_at - _EPISODE_BACKFILL_MARGIN,
            CandidateMemory.created_at <= episode.ended_at + _EPISODE_BACKFILL_MARGIN,
        )
        .values(episode_id=episode.id)
        .execution_options(synchronize_session=False)
    )
    # UPDATE 返回 CursorResult，rowcount 仅在其上可用
    linked = cast("CursorResult[Any]", result).rowcount
    if linked > 0:
        logger.info("Backfilled %d candidate(s) to episode %s", linked, episode.id)
    return linked


def _describe_problem(problem: dict[str, Any]) -> str | None:
    """把单条 problem 信号转成一行描述；关键字段缺失时返回 None（不编造内容）。"""
    if problem.get("type") == "tool_failure":
        tool_name = problem.get("tool_name")
        if not tool_name:
            return None
        line = f"工具 {tool_name} 调用失败"
        error = problem.get("error")
        if error:
            line += f"：{error}"
        return line
    if problem.get("type") == "test_failure":
        test_name = problem.get("test_name")
        if not test_name:
            return None
        line = f"测试 {test_name} 失败"
        error = problem.get("error")
        if error:
            line += f"：{error}"
        return line
    return None


def _describe_solution(solution: dict[str, Any]) -> str | None:
    """把单条 solution 信号转成一行描述；关键字段缺失时返回 None（不编造内容）。"""
    if solution.get("type") == "fix_applied":
        tool_name = solution.get("tool_name")
        if not tool_name:
            return None
        line = f"应用修复（{tool_name}）"
        input_summary = solution.get("input_summary")
        if input_summary:
            line += f"：{input_summary}"
        return line
    if solution.get("type") == "test_fixed":
        test_name = solution.get("test_name")
        if not test_name:
            return None
        return f"测试 {test_name} 通过"
    return None


def _build_episode_lesson_candidate(episode_data: EpisodeData) -> tuple[str, str] | None:
    """从 episode 信号构造 (标题, 正文)。

    正文组织「目标 / 遇到的问题 / 应用的解决 / 经验教训」几段，
    全部使用 problems/solutions/lessons 里的真实字段值；
    过滤后无有效问题或解决行时返回 None。
    """
    problem_lines = [line for line in (_describe_problem(p) for p in episode_data.problems) if line]
    solution_lines = [
        line for line in (_describe_solution(s) for s in episode_data.solutions) if line
    ]
    if not problem_lines or not solution_lines:
        return None

    goal = (episode_data.goal or "").strip()
    # 标题从 goal 或会话摘要截断生成，保证不超过配置上限
    title_base = goal or (episode_data.summary or "").strip() or "会话调试记录"
    title = f"调试解决：{title_base}"[: settings.memory_title_max_length]

    parts: list[str] = []
    if goal:
        parts.append(f"## 目标\n{goal}")
    parts.append("## 遇到的问题\n" + "\n".join(f"- {line}" for line in problem_lines))
    parts.append("## 应用的解决\n" + "\n".join(f"- {line}" for line in solution_lines))
    if episode_data.lessons:
        parts.append("## 经验教训\n" + "\n".join(f"- {lesson}" for lesson in episode_data.lessons))
    return title, "\n\n".join(parts) + "\n"


async def _generate_episode_candidate(
    db_session: AsyncSession,
    ctx: dict[str, Any],
    episode: Episode,
    episode_data: EpisodeData,
) -> bool:
    """按规则从 episode 的「失败→修复」信号生成一条 lesson 候选。

    幂等：client_write_id 固定为 "episode-{episode.id}"，同一 episode
    重复执行不会重复生成。校验拒绝（ContentFormatError 等）时记
    warning 并跳过，绝不中断任务。返回是否新建。
    """
    built = _build_episode_lesson_candidate(episode_data)
    if built is None:
        return False
    title, content = built

    try:
        candidate, _similar, created = await create_candidate(
            db_session,
            workspace_id=episode.workspace_id,
            title=title,
            content=content,
            type="lesson",
            source="episode",
            confidence=0.5,
            importance=0.5,
            client_write_id=f"episode-{episode.id}",
        )
        if created:
            # 生成的候选天然来源于该 episode，显式挂上关联
            candidate.episode_id = episode.id
        await db_session.commit()
    except ContentFormatError as exc:
        await db_session.rollback()
        logger.warning("Episode %s lesson candidate rejected: %s", episode.id, exc)
        return False
    except Exception:
        await db_session.rollback()
        logger.warning("Episode %s lesson candidate generation failed", episode.id, exc_info=True)
        return False

    if created:
        queue: TaskQueue | None = ctx.get("queue")
        if queue is not None:
            await queue.enqueue("generate_candidate_embedding", str(candidate.id))
        logger.info("Generated lesson candidate from episode %s", episode.id)
    return created
