"""复习偏好 API：每日目标跨设备落盘与校验。"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from packages.storage import review_prefs


async def test_preferences_default_and_round_trip(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(review_prefs.storage_config, "memory_dir", str(tmp_path))

    response = await client.get("/v1/review/preferences")
    assert response.status_code == 200, response.text
    assert response.json()["daily_goal"] == review_prefs.DEFAULT_DAILY_GOAL

    response = await client.put("/v1/review/preferences", json={"daily_goal": 35})
    assert response.status_code == 200, response.text
    assert response.json()["daily_goal"] == 35
    assert review_prefs.review_prefs_path(tmp_path).is_file()

    response = await client.get("/v1/review/preferences")
    assert response.json()["daily_goal"] == 35


async def test_preferences_reject_out_of_range(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(review_prefs.storage_config, "memory_dir", str(tmp_path))

    for value in (0, 201):
        response = await client.put("/v1/review/preferences", json={"daily_goal": value})
        assert response.status_code == 422, response.text
