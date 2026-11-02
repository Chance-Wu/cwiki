"""复习偏好（跨设备）：存于 ``cwiki-data/_meta/_review_prefs.json``。

放在数据仓库的 `_meta` 下而非 config.yaml：偏好属于学习数据，随
`cwiki-data/` 多设备同步；`_` 前缀文件不会被记忆侧车清理或重建导入。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from packages.storage import config as storage_config

DEFAULT_DAILY_GOAL = 20
MIN_DAILY_GOAL = 1
MAX_DAILY_GOAL = 200


@dataclass
class ReviewPreferences:
    daily_goal: int = DEFAULT_DAILY_GOAL
    updated_at: str | None = None


def clamp_daily_goal(value: float | str | None) -> int:
    try:
        goal = int(value) if value is not None else DEFAULT_DAILY_GOAL
    except (TypeError, ValueError):
        goal = DEFAULT_DAILY_GOAL
    return max(MIN_DAILY_GOAL, min(MAX_DAILY_GOAL, goal))


def review_prefs_path(meta_dir: str | Path | None = None) -> Path:
    base = Path(meta_dir) if meta_dir is not None else Path(storage_config.memory_dir)
    return base / "_meta" / "_review_prefs.json"


def load_review_preferences(meta_dir: str | Path | None = None) -> ReviewPreferences:
    path = review_prefs_path(meta_dir)
    if not path.is_file():
        return ReviewPreferences()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ReviewPreferences()
    if not isinstance(data, dict):
        return ReviewPreferences()
    return ReviewPreferences(
        daily_goal=clamp_daily_goal(data.get("daily_goal")),
        updated_at=str(data["updated_at"]) if data.get("updated_at") else None,
    )


def save_review_preferences(
    daily_goal: int,
    meta_dir: str | Path | None = None,
) -> ReviewPreferences:
    path = review_prefs_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    prefs = ReviewPreferences(
        daily_goal=clamp_daily_goal(daily_goal),
        updated_at=datetime.now(UTC).isoformat(),
    )
    payload = json.dumps(
        {"daily_goal": prefs.daily_goal, "updated_at": prefs.updated_at},
        ensure_ascii=False,
        indent=2,
    )
    fd, tmp_name = tempfile.mkstemp(suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return prefs
