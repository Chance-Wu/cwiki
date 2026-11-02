"""最近一次全量导出（MD + ``_meta``）的时间戳。

周期导出原本是“启动后先睡满间隔”：进程每次重启都会重置计时，频繁重启
时导出可能永远轮不到。把最近导出时间落在设备本地状态目录，启动时据此
计算剩余等待时间，过期立即补一次。

只记录设备本地时间：导出是本地 DB 的状态，不应通过数据仓库同步到其他
设备，否则会把另一台设备的“已导出”误判为本机状态。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 可被测试替换（与 task_queue 的持久化路径同一约定：设备本地状态目录）
_STATE_PATH = Path.home() / ".cwiki" / "state" / "meta_export.json"


def state_path() -> Path:
    return _STATE_PATH


def read_last_export() -> datetime | None:
    """读取最近一次成功导出的时间；缺失/损坏时返回 None。"""
    path = state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("last_export_at") if isinstance(data, dict) else None
        if not raw:
            return None
        parsed = datetime.fromisoformat(str(raw))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (OSError, ValueError):
        logger.warning("Failed to read export state %s", path, exc_info=True)
        return None


def record_export(at: datetime | None = None) -> None:
    """记录一次成功导出（原子写，失败不抛出）。"""
    path = state_path()
    timestamp = at or datetime.now(UTC)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "last_export_at": timestamp.astimezone(UTC).isoformat(),
                        "recorded_at": datetime.now(UTC).isoformat(),
                    },
                    f,
                    ensure_ascii=False,
                )
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        # 状态文件只影响“启动时是否补导出”，写失败不能影响导出本身
        logger.warning("Failed to record export state %s", path, exc_info=True)


def seconds_until_due(interval_hours: float, now: datetime | None = None) -> float:
    """距离下次导出到期的秒数；从未导出或已逾期返回 0。"""
    if interval_hours <= 0:
        return 0.0
    last = read_last_export()
    if last is None:
        return 0.0
    current = now or datetime.now(UTC)
    elapsed = (current - last).total_seconds()
    return max(0.0, interval_hours * 3600 - elapsed)


def export_due(interval_hours: float, now: datetime | None = None) -> bool:
    return seconds_until_due(interval_hours, now=now) <= 0.0


def clear_state() -> None:
    """测试辅助：删除状态文件。"""
    state_path().unlink(missing_ok=True)


__all__ = [
    "clear_state",
    "export_due",
    "read_last_export",
    "record_export",
    "seconds_until_due",
    "state_path",
]
