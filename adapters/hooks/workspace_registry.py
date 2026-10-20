"""hook → MCP 的当前工作区同步（按宿主隔离）。

MCP server 由宿主在启动时拉起，静态 env 只反映启动那一刻的项目；
宿主切换项目、或一个宿主进程服务多个项目时，只有 hook 拿得到
"现在"的 cwd。hook 每次触发都调用 refresh()，MCP 下一次工具调用
即解析到新工作区——不需要重启。

注册表按宿主分文件（current-workspace-<host>.json）：Qoder 在
learning-os 写的值不会影响 Claude 在别的项目的归属——多宿主并存时
"最后触发 hook 的项目"只污染同宿主，不会跨宿主串区。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_STATE_DIR = Path(os.environ.get("CWIKI_STATE_DIR", "~/.cwiki/state")).expanduser()

_HOST_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def registry_path(host: str) -> Path:
    safe = _HOST_SAFE_RE.sub("-", host or "generic").strip("-.") or "generic"
    return _STATE_DIR / f"current-workspace-{safe}.json"


def refresh(workspace: str, host: str) -> None:
    """写入宿主当前项目工作区；失败静默（绝不阻塞 hook）。

    workspace 为 default 时表示"没推导出项目"，不覆盖已有有效值。
    双写：per-host 文件是权威；同时写旧版共享文件（host 字段照旧），
    让尚未重启的旧 MCP 进程（只读共享文件）保持归属正确——共享文件的
    host 校验由读取端兜底，跨宿主串扰只残留于这一过渡窗口。
    """
    if not workspace or workspace == "default":
        return
    payload = json.dumps({"workspace": workspace, "host": host, "updated_at": time.time()})
    try:
        path = registry_path(host)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
        legacy = _STATE_DIR / "current-workspace.json"
        tmp2 = legacy.with_suffix(".tmp")
        tmp2.write_text(payload, encoding="utf-8")
        tmp2.replace(legacy)
    except OSError:
        pass
