"""/v1/system/integrity：只读一致性巡检端点。"""

from __future__ import annotations

import httpx

from scripts import check_integrity


async def test_integrity_returns_report(client: httpx.AsyncClient, monkeypatch) -> None:
    report = {
        "counts": {
            "db_total": 3,
            "db_active": 2,
            "workspaces_db": 1,
            "markdown": 3,
            "meta": 3,
            "index": 2,
            "vectors": 2,
            "workspaces_meta": 1,
        },
        "issues": [],
        "ok": True,
    }
    monkeypatch.setattr(check_integrity, "collect", lambda *_a, **_kw: report)

    response = await client.get("/v1/system/integrity")

    assert response.status_code == 200, response.text
    assert response.json() == report


async def test_integrity_reports_missing_database(client: httpx.AsyncClient, monkeypatch, tmp_path):
    from apps.api.routes import system as system_route

    missing = tmp_path / "cwiki.db"
    monkeypatch.setattr(system_route, "_resolve_data_paths", lambda: (missing, tmp_path))

    response = await client.get("/v1/system/integrity")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error"] == "database_not_found"
