"""共享的日期时间工具。"""

from __future__ import annotations

from datetime import UTC, datetime


def days_since(dt: datetime, now: datetime | None = None) -> float:
    """计算 *now*（默认当前 UTC 时间）与 *dt* 之间的小数天数。

    无时区信息的 datetime 视为 UTC。
    """
    if now is None:
        now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (now - dt).total_seconds() / 86400
