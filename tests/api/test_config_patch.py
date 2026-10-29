"""运行时配置 PATCH 的边界校验测试。"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from apps.api.routes import config as config_routes
from packages.domain import config as domain_config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 PATCH 读写的 config.yaml 指向临时副本，避免改动仓库文件。"""
    target = tmp_path / "config.yaml"
    target.write_text(
        Path(config_routes.CONFIG_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_routes, "CONFIG_PATH", target)
    monkeypatch.setattr(domain_config, "CONFIG_PATH", target)
    monkeypatch.setattr(domain_config, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    return target


async def _current_section(client: httpx.AsyncClient, section: str) -> dict:
    response = await client.get("/v1/config")
    assert response.status_code == 200, response.text
    return response.json()[section]


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("memory", "title_max_length", 0),
        ("memory", "consolidate_threshold", 1.5),
        ("memory", "priority_high_threshold", -0.1),
        ("performance", "context_token_budget", 10),
        ("performance", "dedup_top_k", 0),
        ("retrieval", "bm25_weight", -1.0),
        ("parasitic_evolution", "auto_merge_threshold", 2.0),
    ],
)
async def test_patch_rejects_out_of_range(
    client: httpx.AsyncClient,
    isolated_config: Path,
    section: str,
    field: str,
    value: float,
) -> None:
    payload = await _current_section(client, section)
    payload[field] = value
    before = isolated_config.read_text(encoding="utf-8")

    response = await client.patch("/v1/config", json={section: payload})

    assert response.status_code == 422, response.text
    assert isolated_config.read_text(encoding="utf-8") == before


async def test_patch_accepts_in_range_and_persists(
    client: httpx.AsyncClient, isolated_config: Path
) -> None:
    payload = await _current_section(client, "memory")
    payload["title_max_length"] = 120

    response = await client.patch("/v1/config", json={"memory": payload})

    assert response.status_code == 200, response.text
    assert "memory.title_max_length" in response.json()["changed_fields"]
    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert stored["memory"]["title_max_length"] == 120


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("memory", "duplicate_exact_threshold", 1.5),
        ("memory", "submit_dedup_scan_limit", 0),
        ("parasitic_evolution", "auto_relation_threshold", 2.0),
        ("parasitic_evolution", "auto_relation_max_per_memory", 0),
        ("parasitic_evolution", "relation_auto_edge_ttl_days", -1),
        ("mcp", "max_retries", 11),
        ("mcp", "retry_backoff_seconds", -1),
        ("scheduler", "relation_ttl_check_interval_hours", -1),
    ],
)
async def test_patch_rejects_out_of_range_p3_fields(
    client: httpx.AsyncClient,
    isolated_config: Path,
    section: str,
    field: str,
    value: float,
) -> None:
    payload = await _current_section(client, section)
    payload[field] = value

    response = await client.patch("/v1/config", json={section: payload})

    assert response.status_code == 422, response.text


async def test_config_exposes_p3_sections(client: httpx.AsyncClient, isolated_config: Path) -> None:
    response = await client.get("/v1/config")
    assert response.status_code == 200, response.text
    data = response.json()

    assert "auto_create_workspace" in data["memory"]
    assert "duplicate_exact_threshold" in data["memory"]
    assert "submit_dedup_cross_workspace" in data["memory"]
    assert "auto_relation_enabled" in data["parasitic_evolution"]
    assert "relation_auto_edge_ttl_days" in data["parasitic_evolution"]
    assert set(data["mcp"]) == {"max_retries", "retry_backoff_seconds"}
    assert set(data["scheduler"]) >= {
        "auto_relation_interval_hours",
        "relation_ttl_check_interval_hours",
    }


async def test_patch_persists_mcp_and_scheduler(
    client: httpx.AsyncClient, isolated_config: Path
) -> None:
    mcp_payload = await _current_section(client, "mcp")
    mcp_payload["max_retries"] = 3
    scheduler_payload = await _current_section(client, "scheduler")
    scheduler_payload["relation_ttl_check_interval_hours"] = 12

    response = await client.patch(
        "/v1/config", json={"mcp": mcp_payload, "scheduler": scheduler_payload}
    )

    assert response.status_code == 200, response.text
    changed = set(response.json()["changed_fields"])
    assert "mcp.max_retries" in changed
    assert "scheduler.relation_ttl_check_interval_hours" in changed
    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert stored["mcp"]["max_retries"] == 3
    assert stored["scheduler"]["relation_ttl_check_interval_hours"] == 12
