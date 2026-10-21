"""系统管理端点（重启等）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.auth import AgentIdentity
from apps.api.deps import require_scope

router = APIRouter(tags=["system"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class RestartResponse(BaseModel):
    restarting: bool
    message: str


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
