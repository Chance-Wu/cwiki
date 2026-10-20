"""Markdown 导出：把记忆导出为可回灌、可备份的 Markdown。

导出内容保留 frontmatter（id/title/type/source/confidence/importance/时间/workspace）
与完整正文；不做摘要化，保证“导出即完整”。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.models import Memory, Workspace

router = APIRouter(prefix=API_V1_PREFIX, tags=["export"])


def _frontmatter(meta: dict[str, object]) -> str:
    return (
        "---\n"
        + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=False)
        + "---\n"
    )


@router.get("/export/markdown", response_class=PlainTextResponse)
async def export_markdown(
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    limit: int = Query(5000, ge=1, le=20000),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> PlainTextResponse:
    resolved_ws_id = await resolve_workspace(workspace_id, db) if workspace_id else None
    ws_name = None
    if resolved_ws_id is not None:
        ws_name = await db.scalar(select(Workspace.name).where(Workspace.id == resolved_ws_id))

    stmt = (
        select(Memory)
        .where(Memory.status == "active")
        .order_by(Memory.created_at.asc())
        .limit(limit)
    )
    if resolved_ws_id is not None:
        stmt = stmt.where(Memory.workspace_id == resolved_ws_id)
    memories = (await db.execute(stmt)).scalars().all()

    chunks: list[str] = []
    for memory in memories:
        meta: dict[str, object] = {
            "id": str(memory.id),
            "title": memory.title,
            "type": memory.type,
            "source": memory.source,
            "confidence": memory.confidence,
            "importance": memory.importance,
            "status": memory.status,
            "workspace": ws_name or str(memory.workspace_id),
            "created_at": memory.created_at.isoformat() if memory.created_at else None,
            "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        }
        chunks.append(_frontmatter(meta) + f"\n# {memory.title}\n\n{memory.content.strip()}\n")

    body = "\n\n".join(chunks) if chunks else ""
    filename = f"cwiki-{ws_name or 'all'}-{datetime.now(UTC).strftime('%Y%m%d')}.md"
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
