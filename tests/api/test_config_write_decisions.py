"""写入决策配置端点的读取、持久化与校验测试。"""

from __future__ import annotations

import httpx
import pytest
import yaml

from apps.api.routes import config as config_routes
from packages.domain import config as domain_config
from packages.domain.config import agent_policy_config, settings


@pytest.fixture
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """把 config.yaml 指向临时文件，并隔离全局配置。"""
    real_config = domain_config.CONFIG_PATH
    real_local = domain_config.LOCAL_CONFIG_PATH
    target = tmp_path / "config.yaml"
    target.write_text(
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
    monkeypatch.setattr(domain_config, "CONFIG_PATH", target)
    monkeypatch.setattr(domain_config, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    monkeypatch.setattr(config_routes, "CONFIG_PATH", target)
    monkeypatch.setattr(domain_config, "_yaml_config", domain_config._yaml_config)
    monkeypatch.setattr(settings, "write_policy", settings.write_policy)
    monkeypatch.setattr(agent_policy_config, "write_decisions", agent_policy_config.write_decisions)
    domain_config.reload_yaml_config()
    settings.reload()
    agent_policy_config.reload()
    try:
        yield target
    finally:
        # 路由 PUT 会把临时配置 reload 进全局单例（如 debug=False）；
        # 先指回真实配置并重载，否则会泄漏到后续用例
        domain_config.CONFIG_PATH = real_config
        domain_config.LOCAL_CONFIG_PATH = real_local
        config_routes.CONFIG_PATH = real_config
        domain_config.reload_yaml_config()
        settings.reload()
        agent_policy_config.reload()


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


async def test_get_default_write_decisions(client: httpx.AsyncClient, isolated_config) -> None:
    response = await client.get("/v1/config/write-decisions")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enabled"] is False
    assert data["default_action"] == "write"
    assert data["rules"] == []
    assert data["preview"] == ""
    assert data["storage_path"] == str(isolated_config)
    assert data["limits"] == {
        "max_rules": 30,
        "max_description": 300,
        "max_examples": 5,
        "max_example_chars": 120,
        "max_match_values": 20,
        "max_keyword_values": 40,
        "max_regex_values": 20,
        "max_match_value_chars": 100,
        "max_hint_chars": 800,
    }


async def test_put_persists_and_reloads(client: httpx.AsyncClient, isolated_config) -> None:
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

    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    decisions = stored["agent_policy"]["write_decisions"]
    assert decisions["enabled"] is True
    assert decisions["default_action"] == "write"
    assert decisions["rules"][0]["match"]["keyword"] == ["现在几点", "确认一下"]

    fetched = await client.get("/v1/config/write-decisions")
    assert fetched.status_code == 200
    assert fetched.json()["rules"] == data["rules"]


async def test_put_roundtrips_regex_match(
    client: httpx.AsyncClient, isolated_config
) -> None:
    pattern = r"(?i)password\s*[=:]\s*[A-Za-z0-9]{6,}"
    payload = _payload()
    payload["rules"][0]["match"]["regex"] = [pattern]

    response = await client.put("/v1/config/write-decisions", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["rules"][0]["match"]["regex"] == [pattern]

    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    stored_match = stored["agent_policy"]["write_decisions"]["rules"][0]["match"]
    assert stored_match["regex"] == [pattern]

    fetched = await client.get("/v1/config/write-decisions")
    assert fetched.json()["rules"][0]["match"]["regex"] == [pattern]


async def test_put_preserves_other_local_config_keys(
    client: httpx.AsyncClient, isolated_config
) -> None:
    isolated_config.write_text(
        yaml.safe_dump(
            {"app": {"debug": True}, "agent_policy": {"always_inject": {"enabled": True}}},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    response = await client.put("/v1/config/write-decisions", json=_payload())

    assert response.status_code == 200, response.text
    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert stored["app"]["debug"] is True
    assert stored["agent_policy"]["always_inject"]["enabled"] is True
    assert stored["agent_policy"]["write_decisions"]["enabled"] is True


async def test_duplicate_rule_ids_rejected(client: httpx.AsyncClient, isolated_config) -> None:
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
        # 非法正则会整条规则被跳过，PUT 按“部分规则无法解析”拒绝
        lambda payload: payload["rules"][0]["match"].update({"regex": ["(unclosed"]}),
    ],
)
async def test_invalid_payload_rejected(client: httpx.AsyncClient, isolated_config, mutate) -> None:
    payload = _payload()
    mutate(payload)

    response = await client.put("/v1/config/write-decisions", json=payload)

    assert response.status_code == 422


async def test_preview_returns_budget_for_draft(client: httpx.AsyncClient, isolated_config) -> None:
    response = await client.post("/v1/config/write-decisions/preview", json=_payload())

    assert response.status_code == 200, response.text
    data = response.json()
    assert "一次性状态查询不写入" in data["preview"]
    assert data["length"] == len(data["preview"]) <= data["max_chars"] == 800
    assert data["total_rules"] == 2
    assert data["shown_rules"] == 2
    assert data["truncated"] is False
    assert data["skipped_rules"] == 0


async def test_preview_filters_by_simulated_workspace(
    client: httpx.AsyncClient, isolated_config
) -> None:
    payload = _payload()
    payload["rules"][0]["match"]["workspace"] = ["cwiki"]
    payload["rules"][1]["match"]["workspace"] = ["other"]

    response = await client.post(
        "/v1/config/write-decisions/preview",
        json={**payload, "workspace": "cwiki"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert "一次性状态查询不写入" in data["preview"]
    assert "已有记忆需要补充时更新" not in data["preview"]
    assert data["total_rules"] == 1


async def test_preview_skips_invalid_draft_rules(
    client: httpx.AsyncClient, isolated_config
) -> None:
    payload = _payload()
    payload["rules"].append({"id": "", "action": "write", "match": {}})

    response = await client.post("/v1/config/write-decisions/preview", json=payload)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_rules"] == 2
    assert data["skipped_rules"] == 1
