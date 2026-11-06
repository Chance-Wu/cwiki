"""记忆使用信号接收端：把"检索命中"与"实际交付使用"分开计量。

背景：检索引擎与 hook 自动召回只写 ``retrieved`` 流水，交付层（注入模型上下文、
被回答引用）没有信号生产者，utility 的 ``retrieval_success`` / ``agent_usage``
两个分量（合计权重 0.55）恒为 0，进化闭环断链。

- ``POST /usage/batch``：宿主 hook / MCP 适配器批量上报交付事件；带 ``record_id``
  时幂等，供离线 spool 补投（重试不重复计量）。
- ``GET /usage/gaps``：列出"检索命中多、交付为零"的记忆，作为召回质量缺口。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory, MemoryUsage

logger = logging.getLogger(__name__)

router = APIRouter(prefix=API_V1_PREFIX, tags=["memory-usage"])

MAX_ITEMS = 50
# 只接受"交付侧"阶段：retrieved 由检索引擎自己写，不允许外部伪造
DELIVERY_STAGES = ("used", "cited")
# record_id 幂等派生用的固定命名空间，跨进程稳定
_RECORD_NAMESPACE = uuid.UUID("3f2a6c18-9d4b-4e7a-8c15-0b6d2e9f4a71")


def usage_id_for(record_id: str, memory_id: uuid.UUID, stage: str) -> uuid.UUID:
    """同一 (record_id, memory_id, stage) 恒定映射到同一主键，重复投递自然去重。

    stage 必须并入键：同一次召回里 used 与 cited 是两个不同信号，
    只按 (record_id, memory_id) 派生会把它们折叠成一条。
    """
    return uuid.uuid5(_RECORD_NAMESPACE, f"{record_id}|{memory_id}|{stage}")


def resolve_session_uuid(raw: str | None) -> uuid.UUID | None:
    """宿主会话 id 是任意字符串；归一为稳定 UUID 以便按会话聚合。"""
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return uuid.uuid5(_RECORD_NAMESPACE, f"session|{raw}")


class UsageEvent(BaseModel):
    """单条交付/引用事件。"""

    memory_id: uuid.UUID
    stage: str = Field(default="used", max_length=32)
    position: int | None = Field(default=None, ge=0, le=200)


class UsageRecord(BaseModel):
    """一次交付批次（例如 hook 对某个 prompt 的召回注入）。

    ``record_id`` 由客户端生成并在重试时保持不变：整批或单条重复投递
    都按派生主键去重，因此离线 spool 可以安全补投。
    """

    events: list[UsageEvent] = Field(min_length=1, max_length=MAX_ITEMS)
    record_id: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)


class UsageBatchRequest(BaseModel):
    """一次提交可含多个批次：spool 补投时逐条按 record_id 幂等。"""

    records: list[UsageRecord] = Field(min_length=1, max_length=MAX_ITEMS)


class UsageBatchResponse(BaseModel):
    accepted: int
    skipped_duplicates: int
    skipped_unknown: int
    rejected_stages: int


@router.post("/usage/batch", response_model=UsageBatchResponse)
async def record_usage_batch(
    body: UsageBatchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> UsageBatchResponse:
    """批量记录交付/引用事件（幂等，静默忽略未知记忆）。

    工作区归属取记忆行自身，调用方不需要传 workspace；未知或已删除的
    memory_id 直接跳过，不阻断整批——spool 补投可能滞后数天。
    """
    accepted = duplicates = unknown = rejected_stages = 0
    seen_in_request: set[tuple[str, str, str]] = set()
    records: list[MemoryUsage] = []

    for record in body.records:
        valid: list[UsageEvent] = []
        for event in record.events:
            if event.stage not in DELIVERY_STAGES:
                rejected_stages += 1
                continue
            key = (record.record_id or "", str(event.memory_id), event.stage)
            if key in seen_in_request:
                duplicates += 1
                continue
            seen_in_request.add(key)
            valid.append(event)
        if not valid:
            continue

        ids = {e.memory_id for e in valid}
        rows = (
            await db.execute(select(Memory.id, Memory.workspace_id).where(Memory.id.in_(ids)))
        ).all()
        known = {str(row[0]): row[1] for row in rows}
        session_uuid = resolve_session_uuid(record.session_id)

        for event in valid:
            workspace_id = known.get(str(event.memory_id))
            if workspace_id is None:
                unknown += 1
                continue
            if record.record_id:
                usage_id = usage_id_for(record.record_id, event.memory_id, event.stage)
                if await db.get(MemoryUsage, usage_id) is not None:
                    duplicates += 1
                    continue
            else:
                usage_id = uuid.uuid4()
            records.append(
                MemoryUsage(
                    id=usage_id,
                    workspace_id=workspace_id,
                    memory_id=event.memory_id,
                    session_id=session_uuid,
                    position=event.position,
                    stage=event.stage,
                )
            )
            accepted += 1

    if records:
        db.add_all(records)
        await db.commit()

    return UsageBatchResponse(
        accepted=accepted,
        skipped_duplicates=duplicates,
        skipped_unknown=unknown,
        rejected_stages=rejected_stages,
    )


@router.get("/usage/gaps")
async def retrieval_gap_report(
    db: Annotated[AsyncSession, Depends(get_db)],
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
    workspace: str | None = Query(None, description="工作区名称或 UUID"),
    min_retrievals: int = Query(5, ge=1, le=1000),
    since_days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """列出"检索命中多、交付为零"的记忆：召回质量缺口。

    ``used``/``cited`` 是交付信号；只有 ``retrieved`` 说明该记忆反复进入候选
    却从未被真正采用（或被上下文预算淘汰）。这是排序与内容质量的可解释入口，
    不代表记忆一定无价值——需要人工或 Agent 判断。
    """
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=since_days)

    delivery_count = func.sum(case((MemoryUsage.stage.in_(DELIVERY_STAGES), 1), else_=0))
    conditions = [Memory.status == "active", MemoryUsage.created_at >= since]
    if workspace:
        ws_uuid = await resolve_workspace(workspace, db)
        conditions.append(Memory.workspace_id == ws_uuid)

    stmt = (
        select(
            Memory.id,
            Memory.title,
            Memory.type,
            func.count(MemoryUsage.id),
            func.coalesce(delivery_count, 0),
        )
        .join(MemoryUsage, MemoryUsage.memory_id == Memory.id)
        .where(*conditions)
        .group_by(Memory.id, Memory.title, Memory.type)
        .having(func.coalesce(delivery_count, 0) == 0)
        .order_by(func.count(MemoryUsage.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    gaps = [
        {
            "memory_id": str(row[0]),
            "title": row[1],
            "type": row[2],
            "retrievals": int(row[3]),
        }
        for row in rows
        if int(row[3]) >= min_retrievals
    ]
    return {
        "window_days": since_days,
        "min_retrievals": min_retrievals,
        "total": len(gaps),
        "items": gaps,
    }
