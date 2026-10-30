"""写入策略配置端点的读取、持久化与校验测试。"""

from __future__ import annotations

import httpx
import pytest
import yaml

from apps.api.routes import config as config_routes
from packages.domain import config as domain_config
from packages.domain.config import settings


@pytest.fixture
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """把 config.yaml 指向临时文件，并确保测试后恢复全局配置。"""
    real_config = domain_config.CONFIG_PATH
    real_local = domain_config.LOCAL_CONFIG_PATH
    target = tmp_path / "config.yaml"
    target.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(domain_config, "CONFIG_PATH", target)
    monkeypatch.setattr(domain_config, "LOCAL_CONFIG_PATH", tmp_path / "config.local.yaml")
    monkeypatch.setattr(config_routes, "CONFIG_PATH", target)
    # monkeypatch 记录原引用，teardown 时自动还原，避免测试规则泄漏到其他用例
    monkeypatch.setattr(domain_config, "_yaml_config", domain_config._yaml_config)
    monkeypatch.setattr(settings, "write_policy", settings.write_policy)
    domain_config.reload_yaml_config()
    settings.reload()
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


def _payload() -> dict:
    return {
        "enabled": True,
        "rules": [
            {
                "id": "pinned-auto",
                "action": "auto",
                "reason": "用户指定长期保留",
                "match": {
                    "workspace": ["cwiki"],
                    "type": ["decision", "lesson"],
                    "tags": ["pinned"],
                    "keyword": ["必须保留", "ECONNRESET"],
                },
            }
        ],
    }


async def test_get_default_write_policy(client: httpx.AsyncClient, isolated_config) -> None:
    response = await client.get("/v1/config/write-policy")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enabled"] is False
    assert data["rules"] == []
    assert data["storage_path"] == str(isolated_config)
    # limits 字段返回服务端硬限制
    assert data["limits"]["max_rules"] == 50
    assert data["limits"]["max_match_values"] == 20
    assert data["limits"]["max_keyword_values"] == 40
    assert data["limits"]["max_regex_values"] == 20
    assert data["limits"]["max_match_value_chars"] == 100


async def test_put_persists_rules_and_reloads_settings(
    client: httpx.AsyncClient, isolated_config
) -> None:
    response = await client.put("/v1/config/write-policy", json=_payload())

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["enabled"] is True
    assert data["rules"][0]["id"] == "pinned-auto"
    assert data["rules"][0]["match"]["keyword"] == ["必须保留", "ECONNRESET"]
    assert "limits" in data

    # 运行时配置已重载，规则对后续写入立即生效
    assert settings.write_policy.enabled is True
    (rule,) = settings.write_policy.rules
    assert rule.id == "pinned-auto"
    assert rule.action == "auto"

    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    stored_rule = stored["memory"]["write_policy"]["rules"][0]
    assert stored["memory"]["write_policy"]["enabled"] is True
    assert stored_rule["id"] == "pinned-auto"
    assert stored_rule["match"]["tags"] == ["pinned"]

    fetched = await client.get("/v1/config/write-policy")
    assert fetched.status_code == 200
    assert fetched.json()["rules"] == data["rules"]


async def test_put_preserves_other_local_config_keys(
    client: httpx.AsyncClient, isolated_config
) -> None:
    isolated_config.write_text(
        yaml.safe_dump({"app": {"debug": True}}, allow_unicode=True),
        encoding="utf-8",
    )

    response = await client.put("/v1/config/write-policy", json=_payload())

    assert response.status_code == 200, response.text
    stored = yaml.safe_load(isolated_config.read_text(encoding="utf-8"))
    assert stored["app"]["debug"] is True
    assert stored["memory"]["write_policy"]["enabled"] is True


async def test_duplicate_rule_ids_rejected(client: httpx.AsyncClient, isolated_config) -> None:
    payload = _payload()
    payload["rules"].append({**payload["rules"][0], "action": "review"})

    response = await client.put("/v1/config/write-policy", json=payload)

    assert response.status_code == 422


async def test_invalid_action_rejected(client: httpx.AsyncClient, isolated_config) -> None:
    payload = _payload()
    payload["rules"][0]["action"] = "delete"

    response = await client.put("/v1/config/write-policy", json=payload)

    assert response.status_code == 422
