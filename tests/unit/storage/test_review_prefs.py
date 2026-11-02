"""复习偏好文件：默认值、round-trip、clamp 与损坏兜底。"""

from __future__ import annotations

import json
from pathlib import Path

from packages.storage.review_prefs import (
    DEFAULT_DAILY_GOAL,
    load_review_preferences,
    review_prefs_path,
    save_review_preferences,
)


def test_missing_file_returns_default(tmp_path: Path) -> None:
    prefs = load_review_preferences(tmp_path)

    assert prefs.daily_goal == DEFAULT_DAILY_GOAL
    assert prefs.updated_at is None


def test_round_trip_writes_meta_file(tmp_path: Path) -> None:
    saved = save_review_preferences(35, tmp_path)

    path = review_prefs_path(tmp_path)
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["daily_goal"] == 35
    assert payload["updated_at"] == saved.updated_at

    loaded = load_review_preferences(tmp_path)
    assert loaded.daily_goal == 35
    assert loaded.updated_at == saved.updated_at


def test_clamps_out_of_range(tmp_path: Path) -> None:
    assert save_review_preferences(0, tmp_path).daily_goal == 1
    assert save_review_preferences(999, tmp_path).daily_goal == 200


def test_corrupt_file_falls_back_to_default(tmp_path: Path) -> None:
    path = review_prefs_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")

    prefs = load_review_preferences(tmp_path)

    assert prefs.daily_goal == DEFAULT_DAILY_GOAL
