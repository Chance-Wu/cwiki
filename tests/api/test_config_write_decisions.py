"""写入决策配置端点的读取、持久化与校验测试。"""

from __future__ import annotations

import httpx
import pytest
import yaml

from apps.api.routes import config as config_routes
from packages.domain import config as domain_config
from packages.domain.config import agent_policy_config, settings


@pytest.fixture
def isolated_local_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """把 config.local.yaml 指向临时文件，并隔离全局配置。"""
    local = tmp_path / "config.local.yaml"
    local.write_text(
        yaml.safe_dump(
            {
                "agent_policy": {
                    "write_decisions": {
                        "enabled": False,
                        "default_action": "write",
                        "rules": [],
                    }
                }
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(domain_config, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(config_routes, "LOCAL_CONFIG_PATH", local)
    monkeypatch.setattr(domain_config, "_yaml_config", domain_config._yaml_config)
    monkeypatch.setattr(settings, "write_policy", settings.write_policy)
    monkeypatch.setattr(agent_policy_config, "write_decisions", agent_policy_config.write_decisions)
    domain_config.reload_yaml_config()
    settings.reload()
    agent_policy_config.reload()
    return local


def _payload() -> dict:
    return {
        "enabled": True,
        "default_action": "write",
        "rules": [
            {
                "id": "skip-one-off",
                "action": "skip",
                "description": "一次性状态查询不写入",
                "examples": ["现在几点", "确认一下"],
                "match": {"keyword": ["现在几点", "确认一下"]},
            },
            {
                "id": "update-existing",
                "action": "update",
                "description": "已有记忆需要补充时更新",
                "examples": ["补充一下这个结论"],
                "match": {"type": ["decision", "lesson"]},
            },
        ],
    }


async def test_get_default_write_decisions(
    client: httpx.AsyncClient, isolated_local_config
) -> None:
    response = await client.get("/v1/config/write-decisions")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enabled"] is False
    assert data["default_action"] == "write"
    assert data["rules"] == []
    assert data["preview"] == ""
    assert data["storage_path"] == str(isolated_local_config)


async def test_put_persists_and_reloads(client: httpx.AsyncClient, isolated_local_config) -> None:
    response = await client.put("/v1/config/write-decisions", json=_payload())

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enabled"] is True
    assert data["default_action"] == "write"
    assert [rule["id"] for rule in data["rules"]] == ["skip-one-off", "update-existing"]
    assert "一次性状态查询不写入" in data["preview"]
    assert "未命中：写入" in data["preview"]

    policy = agent_policy_config.write_decisions
    assert policy.enabled is True
    assert policy.default_action == "write"
    assert [rule.id for rule in policy.rules] == ["skip-one-off", "update-existing"]

    stored = yaml.safe_load(isolated_local_config.read_text(encoding="utf-8"))
    decisions = stored["agent_policy"]["write_decisions"]
    assert decisions["enabled"] is True
    assert decisions["default_action"] == "write"
    assert decisions["rules"][0]["match"]["keyword"] == ["现在几点", "确认一下"]

    fetched = await client.get("/v1/config/write-decisions")
    assert fetched.status_code == 200
    assert fetched.json()["rules"] == data["rules"]


async def test_put_preserves_other_local_config_keys(
    client: httpx.AsyncClient, isolated_local_config
) -> None:
    isolated_local_config.write_text(
        yaml.safe_dump(
            {"app": {"debug": True}, "agent_policy": {"always_inject": {"enabled": True}}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    response = await client.put("/v1/config/write-decisions", json=_payload())

    assert response.status_code == 200, response.text
    stored = yaml.safe_load(isolated_local_config.read_text(encoding="utf-8"))
    assert stored["app"]["debug"] is True
    assert stored["agent_policy"]["always_inject"]["enabled"] is True
    assert stored["agent_policy"]["write_decisions"]["enabled"] is True


async def test_duplicate_rule_ids_rejected(
    client: httpx.AsyncClient, isolated_local_config
) -> None:
    payload = _payload()
    payload["rules"].append({**payload["rules"][0], "action": "write"})

    response = await client.put("/v1/config/write-decisions", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["rules"][0].update({"action": "delete"}),
        lambda payload: payload["rules"][0].update({"action": "review"}),
        lambda payload: payload.update({"default_action": "block"}),
        lambda payload: payload.update({"default_action": "review"}),
        lambda payload: payload["rules"][0].update({"examples": ["x" * 121]}),
        lambda payload: payload["rules"][0].update({"description": "x" * 301}),
    ],
)
async def test_invalid_payload_rejected(
    client: httpx.AsyncClient, isolated_local_config, mutate
) -> None:
    payload = _payload()
    mutate(payload)

    response = await client.put("/v1/config/write-decisions", json=payload)

    assert response.status_code == 422
