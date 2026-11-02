"""间隔重复复习端点。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory
from packages.domain.schemas import (
    BatchReviewRequest,
    BatchReviewResultRead,
    ReviewItemRead,
    ReviewPreferencesRead,
    ReviewPreferencesUpdate,
    ReviewQuizRead,
    ReviewQuizResultRead,
    ReviewQuizSubmitRequest,
    ReviewResultRead,
    ReviewStatsRead,
    ReviewSubmitRequest,
    SuspendedReviewRead,
)
from packages.memory.quiz import ClozeQuiz, build_cloze_quiz, score_cloze_quiz
from packages.memory.review_service import get_review_service
from packages.storage.review_prefs import (
    load_review_preferences,
    save_review_preferences,
)

router = APIRouter(prefix=f"{API_V1_PREFIX}/review", tags=["review"])


@router.get("/preferences", response_model=ReviewPreferencesRead)
async def get_review_preferences(
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> ReviewPreferencesRead:
    """读取跨设备复习偏好（当前为每日目标）。"""
    prefs = load_review_preferences()
    return ReviewPreferencesRead(daily_goal=prefs.daily_goal, updated_at=prefs.updated_at)


@router.put("/preferences", response_model=ReviewPreferencesRead)
async def update_review_preferences(
    body: ReviewPreferencesUpdate,
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> ReviewPreferencesRead:
    """更新每日复习目标，写入 ``cwiki-data/_meta/_review_prefs.json``。"""
    prefs = save_review_preferences(body.daily_goal)
    return ReviewPreferencesRead(daily_goal=prefs.daily_goal, updated_at=prefs.updated_at)


@router.get("/due", response_model=list[ReviewItemRead])
async def get_due_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(20, ge=1, le=100),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> list[dict[str, Any]]:
    """获取到期需要复习的记忆。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    return await service.get_due_reviews(db, resolved_ws_id, limit)


async def _load_quiz(
    db: AsyncSession,
    memory_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> tuple[Memory, ClozeQuiz]:
    """加载 active 记忆并生成确定性填空；不返回答案。"""
    stmt = select(Memory).where(
        Memory.id == memory_id,
        Memory.workspace_id == workspace_id,
        Memory.status == "active",
    )
    memory = (await db.execute(stmt)).scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    quiz = build_cloze_quiz(memory.title, memory.content, list(memory.tags or []))
    if quiz is None:
        raise HTTPException(
            status_code=404,
            detail="No cloze quiz available for this memory; use self-rating",
        )
    return memory, quiz


@router.get("/quiz/{memory_id}", response_model=ReviewQuizRead)
async def get_review_quiz(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> ReviewQuizRead:
    """获取一条记忆的填空复习题（只返回挖空后的题干与空格数）。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    memory, quiz = await _load_quiz(db, memory_id, resolved_ws_id)
    return ReviewQuizRead(
        memory_id=memory.id,
        kind="cloze",
        prompt=quiz.prompt,
        blank_count=len(quiz.terms),
    )


@router.post("/quiz/{memory_id}", response_model=ReviewQuizResultRead)
async def submit_review_quiz(
    memory_id: uuid.UUID,
    body: ReviewQuizSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """提交填空答案：后端重新出题并判分，按得分自动映射 SM-2 quality。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    _, quiz = await _load_quiz(db, memory_id, resolved_ws_id)
    score = score_cloze_quiz(quiz, body.answers)
    service = get_review_service()
    try:
        result = await service.submit_review(
            db,
            memory_id,
            score.quality,
            resolved_ws_id,
            quiz={
                "type": "cloze",
                "correct": score.correct,
                "prompt": quiz.prompt,
                "expected": quiz.terms,
                "response": body.answers,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **result,
        "correct": score.correct,
        "matched": score.matched,
        "total": score.total,
        "expected_terms": quiz.terms,
        "quality": score.quality,
    }


@router.post("/{memory_id}", response_model=ReviewResultRead)
async def submit_review(
    memory_id: uuid.UUID,
    body: ReviewSubmitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """提交记忆的复习结果。

    质量评分（0-5）：
    - 5: 完美回忆
    - 4: 犹豫后答对
    - 3: 费力答对
    - 2: 答错，但看答案后想起了
    - 1: 答错，但看到答案觉得眼熟
    - 0: 完全想不起来
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    try:
        result = await service.submit_review(db, memory_id, body.quality, resolved_ws_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/stats", response_model=ReviewStatsRead)
async def get_review_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    tz_offset_minutes: int = Query(
        0,
        ge=-840,
        le=840,
        description="客户端相对 UTC 的分钟偏移（东八区传 480），用于划分本地自然日",
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """获取工作区的复习统计。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    return await service.get_review_stats(db, resolved_ws_id, tz_offset_minutes)


@router.post("/schedule/{memory_id}")
async def schedule_memory_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """把记忆排入间隔重复复习计划。

    通常在记忆被批准后调用，以启动其复习周期。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    result = await service.schedule_memory(db, memory_id, resolved_ws_id)

    if result is None:
        return {"status": "already_scheduled", "memory_id": str(memory_id)}
    return result


@router.post("/undo/{memory_id}")
async def undo_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """撤销记忆最近一次复习。

    把复习计划恢复到上次复习前的状态；无历史可撤销时返回 404。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()
    result = await service.undo_review(db, memory_id, resolved_ws_id)

    if result is None:
        raise HTTPException(status_code=404, detail="No review history to undo")
    return result


@router.get("/suspended", response_model=list[SuspendedReviewRead])
async def list_suspended_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    limit: int = Query(50, ge=1, le=200),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> list[dict[str, Any]]:
    """列出已暂停复习的记忆。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    return await get_review_service().list_suspended(db, resolved_ws_id, limit)


@router.post("/suspend/{memory_id}")
async def suspend_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """暂停某条记忆的复习（移出到期队列）。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    result = await get_review_service().suspend_review(db, memory_id, resolved_ws_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Review schedule not found")
    return result


@router.post("/resume/{memory_id}")
async def resume_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """恢复已暂停的复习，并立即排入到期队列。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    result = await get_review_service().unsuspend_review(db, memory_id, resolved_ws_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Review schedule not found")
    return result


@router.post("/postpone/{memory_id}")
async def postpone_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: int = Query(3, ge=1, le=365, description="推迟天数"),
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """把下次复习推迟指定天数。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    result = await get_review_service().postpone_review(db, memory_id, days, resolved_ws_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Review schedule not found")
    return result


@router.post("/reset/{memory_id}")
async def reset_review(
    memory_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """重置复习进度（回到初始参数并立即进入队列）。"""
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    result = await get_review_service().reset_review(db, memory_id, resolved_ws_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Review schedule not found")
    return result


@router.post("/batch", response_model=BatchReviewResultRead)
async def batch_submit_reviews(
    body: BatchReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(
        None, min_length=1, description="工作区（名称或 UUID），不传则使用 default"
    ),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """一次性提交多条复习结果。

    各条独立处理：某条失败（如记忆不存在）不影响其他条目。
    返回带逐条结果的汇总。
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)
    service = get_review_service()

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for item in body.reviews:
        try:
            result = await service.submit_review(db, item.memory_id, item.quality, resolved_ws_id)
            results.append(
                {
                    "memory_id": item.memory_id,
                    "success": True,
                    "error": None,
                    "result": result,
                }
            )
            succeeded += 1
        except Exception as e:
            # 单条失败只记录，继续处理剩余复习
            results.append(
                {
                    "memory_id": item.memory_id,
                    "success": False,
                    "error": str(e),
                    "result": None,
                }
            )
            failed += 1

    return {
        "results": results,
        "total": len(body.reviews),
        "succeeded": succeeded,
        "failed": failed,
    }
