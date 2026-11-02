"""系统计划任务入口：每日导出一次 MD + ``_meta``。

不依赖 API 进程存活时长：Windows 由 `cwiki-meta-export` 计划任务调用
（见 ``scripts/install_meta_export_task.py``），常以 pythonw 运行、
没有控制台，因此把 stdout/stderr 与日志统一追加到
``~/.cwiki/state/meta_export.log``。

用法::

    python scripts/meta_export_daily.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 配置里的 memory_dir / database_url 都是相对项目根目录的路径，
# 计划任务的默认工作目录不是项目根，必须先切换。
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import patch_metadata

patch_metadata()

LOG_PATH = Path.home() / ".cwiki" / "state" / "meta_export.log"


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8", buffering=1) as log_file:
        sys.stdout = log_file
        sys.stderr = log_file
        logging.basicConfig(
            stream=log_file,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        logger = logging.getLogger("cwiki.meta_export_daily")

        from scripts.migrate_to_git import migrate_to_git

        try:
            stats = asyncio.run(migrate_to_git())
        except Exception:
            logger.exception("Daily meta export failed")
            return 1

        logger.info(
            "Daily meta export done: memories=%s meta=%s workspaces=%s errors=%s",
            stats.get("memory_count"),
            stats.get("meta_count"),
            stats.get("workspace_count"),
            stats.get("errors"),
        )
        return 0 if stats.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
