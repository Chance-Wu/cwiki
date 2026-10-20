"""数据导入/导出端点。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db, resolve_workspace
from packages.domain.config import API_V1_PREFIX
from packages.domain.export_import import (
    export_data,
    export_to_zip,
    import_data,
    parse_import_data,
)

router = APIRouter(prefix=f"{API_V1_PREFIX}/data", tags=["data"])


@router.post("/export", response_model=None)
async def export_workspace(
    db: Annotated[AsyncSession, Depends(get_db)],
    body: dict[str, Any] | None = None,
    workspace_id: str | None = Query(None, min_length=1, description="工作区（名称或 UUID）"),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> JSONResponse | StreamingResponse:
    """将工作区数据导出为 JSON。

    请求体（可选）：
    - format: "json"（默认）或 "zip"（Markdown 打包）
    - entities: 要导出的实体类型列表（默认全部）
    """
    resolved_ws_id = await resolve_workspace(workspace_id, db)

    fmt = "json"
    entities = None
    if body:
        fmt = body.get("format", "json")
        entities = body.get("entities")

    data = await export_data(db, resolved_ws_id, entities)

    if fmt == "zip":
        zip_bytes = export_to_zip(data)
        return StreamingResponse(
            iter([zip_bytes]),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=cwiki_export.zip"},
        )

    return JSONResponse(content=data)


@router.post("/import")
async def import_workspace(
    file: UploadFile,
    db: Annotated[AsyncSession, Depends(get_db)],
    workspace_id: str | None = Query(None, min_length=1, description="目标工作区"),
    strategy: str = Query("skip", description="冲突策略: skip, overwrite, rename"),
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """从 JSON 文件或 ZIP 包导入数据。

    上传 .json 或 .zip 文件，数据将导入到目标工作区。

    冲突策略：
    - skip: 跳过已存在条目（默认）
    - overwrite: 用导入数据覆盖已有条目
    - rename: 以新 ID 导入（新旧并存）
    """
    if strategy not in ("skip", "overwrite", "rename"):
        raise HTTPException(400, detail=f"Invalid strategy: {strategy}")

    resolved_ws_id = await resolve_workspace(workspace_id, db)

    raw = await file.read()
    if not raw:
        raise HTTPException(400, detail="Empty file")

    # 100 MB 上限，防止超大文件耗尽内存
    _MAX_IMPORT_SIZE = 100 * 1024 * 1024
    if len(raw) > _MAX_IMPORT_SIZE:
        raise HTTPException(413, detail=f"File too large: {len(raw)} bytes (max 100 MB)")

    try:
        data = parse_import_data(raw, file.content_type)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e

    results, touched_memory_ids = await import_data(db, data, resolved_ws_id, strategy)
    await db.commit()

    # 导入是外部输入边界：事务提交后把 DB 状态镜像到 MD + 索引 + 向量，
    # 与常规写入路径同一机制。单条失败只记日志不阻塞整批（见 file_sync 契约）。
    if touched_memory_ids:
        from sqlalchemy import select

        from apps.api.file_sync import sync_memory_to_file
        from apps.api.routes.search import invalidate_search_cache
        from packages.domain.models import Memory

        for memory_id in touched_memory_ids:
            # commit 后重新加载，避免沿用 flush 前的过期实例
            memory = (
                await db.execute(select(Memory).where(Memory.id == memory_id))
            ).scalar_one_or_none()
            if memory is not None:
                await sync_memory_to_file(memory, db, save_index=True)
        invalidate_search_cache()

    return {
        "status": "ok",
        "workspace_id": str(resolved_ws_id),
        "strategy": strategy,
        "results": results,
    }
