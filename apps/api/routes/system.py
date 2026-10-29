"""系统管理端点（重启、一致性巡检等）。"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, require_scope

router = APIRouter(tags=["system"])

# apps/api/routes/system.py -> parents[3] 才是仓库根（此前后少一层，指向 apps/）
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class RestartResponse(BaseModel):
    restarting: bool
    message: str


def _resolve_data_paths() -> tuple[Path, Path]:
    from packages.domain.config import settings
    from packages.storage import config as storage_config

    db_path = Path(settings.database_url.partition(":///")[2])
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    memory_dir = Path(storage_config.memory_dir)
    if not memory_dir.is_absolute():
        memory_dir = PROJECT_ROOT / memory_dir
    return db_path, memory_dir


@router.get("/v1/system/integrity")
async def system_integrity(
    _identity: Annotated[AgentIdentity | None, Depends(get_current_agent)] = None,
) -> dict[str, Any]:
    """只读三层一致性巡检，与 `python tasks.py doctor` 同源（不含端口探测）。"""
    from scripts.check_integrity import collect

    db_path, memory_dir = _resolve_data_paths()
    if not db_path.is_file():
        return {"ok": False, "error": "database_not_found", "db_path": str(db_path)}
    return await asyncio.to_thread(collect, db_path, memory_dir, check_port=False)


@router.post("/v1/system/restart", response_model=RestartResponse)
async def restart_service(
    _identity: Annotated[AgentIdentity, Depends(require_scope("system:write"))],
) -> RestartResponse:
    """启动独立 watcher 进程：结束当前进程并通过 tasks.py 重启服务。

    重启信号处理：不在本进程内自杀后重启，而是派生分离的
    watcher 进程——先等本端点响应返回，再杀旧进程并拉起新进程，
    避免 uvicorn 被杀时请求响应丢失。
    """
    watcher = PROJECT_ROOT / "scripts" / "restart_watcher.py"
    # ASYNC220：阻塞调用 subprocess.Popen 是刻意的——响应返回前必须确保 watcher 已派生
    subprocess.Popen(  # noqa: ASYNC220
        [sys.executable, str(watcher), str(os.getpid()), str(PROJECT_ROOT)],
        cwd=str(PROJECT_ROOT),
        creationflags=(
            (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
            if os.name == "nt"
            else 0
        ),
        start_new_session=os.name != "nt",
    )
    return RestartResponse(restarting=True, message="服务正在重启…")
