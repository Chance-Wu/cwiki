"""版本号统一为 pyproject.toml 权威源的单元测试。

背景：历史上四处各自维护版本号（pyproject 0.1.0 / APP_VERSION 0.3.0 /
FastAPI 0.4.1 / plugin.json 0.1.0），导致 serverInfo、/v1/health、
/openapi.json 三个口径互相矛盾，宿主无法判断连的是哪个版本。
现由 packages.domain.version.app_version() 单点提供。

覆盖：
- 正常路径读 importlib.metadata（与 pyproject 同步）
- 回落路径 1：元数据缺失（未安装）→ 解析 pyproject.toml
- 回落路径 2：元数据与 pyproject 均不可读 → 0.0.0
- 消费方（HealthResponse 默认值、MCP serverInfo）拿到的是同一值
"""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError

import pytest

from packages.domain.version import _FALLBACK_VERSION, _version_from_pyproject, app_version


class TestAppVersion:
    def test_reads_package_metadata(self):
        """正常路径：dist-info 存在时返回其版本（与 pyproject 同步）。"""
        version = app_version()
        assert version
        assert version != _FALLBACK_VERSION

    def test_matches_pyproject_toml(self):
        """权威源一致性：metadata 与 pyproject 解析结果必须相同。

        这条是整个改动的核心断言——若有人只改 pyproject 而没重装
        （或只重装没改 pyproject），两者会分叉，测试立刻暴露。
        """
        assert app_version() == _version_from_pyproject()

    def test_falls_back_to_pyproject_when_metadata_missing(self, monkeypatch):
        """未安装 / dist-info 损坏时解析 pyproject.toml，不抛异常。"""
        monkeypatch.setattr(
            "packages.domain.version._dist_version",
            lambda _name: (_ for _ in ()).throw(PackageNotFoundError("cwiki")),
        )
        app_version.cache_clear()
        try:
            assert app_version() == _version_from_pyproject()
        finally:
            app_version.cache_clear()

    def test_falls_back_to_zero_when_both_sources_unavailable(self, monkeypatch):
        """元数据与 pyproject 双缺失时回落 0.0.0，绝不抛异常。"""
        monkeypatch.setattr(
            "packages.domain.version._dist_version",
            lambda _name: (_ for _ in ()).throw(PackageNotFoundError("cwiki")),
        )
        monkeypatch.setattr("packages.domain.version._version_from_pyproject", lambda: None)
        app_version.cache_clear()
        try:
            assert app_version() == _FALLBACK_VERSION
        finally:
            app_version.cache_clear()

    def test_result_is_cached(self):
        """functools.cache 生效：重复调用返回同一对象级结果。"""
        assert app_version() is app_version()


class TestPyprojectParsing:
    def test_version_from_pyproject_is_non_empty_string(self):
        version = _version_from_pyproject()
        assert isinstance(version, str)
        assert version

    def test_returns_none_when_file_missing(self, monkeypatch, tmp_path):
        """pyproject 不存在时返回 None（交由上层兜底），不抛异常。"""
        monkeypatch.setattr("packages.domain.version._PYPROJECT_PATH", tmp_path / "absent.toml")
        assert _version_from_pyproject() is None

    def test_returns_none_when_toml_malformed(self, monkeypatch, tmp_path):
        """pyproject 内容非法时返回 None，不抛 TOMLDecodeError。"""
        bad = tmp_path / "pyproject.toml"
        bad.write_text("this is [ not valid toml", encoding="utf-8")
        monkeypatch.setattr("packages.domain.version._PYPROJECT_PATH", bad)
        assert _version_from_pyproject() is None

    def test_returns_none_when_version_absent(self, monkeypatch, tmp_path):
        """[project] 表存在但无 version 字段时返回 None。"""
        empty = tmp_path / "pyproject.toml"
        empty.write_text('[project]\nname = "cwiki"\n', encoding="utf-8")
        monkeypatch.setattr("packages.domain.version._PYPROJECT_PATH", empty)
        assert _version_from_pyproject() is None


class TestConsumers:
    def test_health_response_default_uses_app_version(self):
        """HealthResponse.version 默认值取权威源，schema 层不再有字面量。"""
        from packages.domain.schemas.common import APP_VERSION, HealthResponse

        assert APP_VERSION == app_version()
        assert HealthResponse.model_fields["version"].default == app_version()

    @pytest.mark.parametrize("metadata_missing", [False, True])
    def test_mcp_server_info_version_matches_app_version(self, metadata_missing, monkeypatch):
        """MCP initialize 的 serverInfo.version 与 app_version() 一致。

        metadata_missing=True 时同时验证 plugin.json 回落路径仍给出同一值
        （当前 pyproject 与 plugin.json 同为 0.1.0，故两路都等于 app_version）。
        """
        from adapters.mcp.mcp_server import _plugin_version

        expected = app_version()
        if metadata_missing:
            monkeypatch.setattr(
                "packages.domain.version._dist_version",
                lambda _name: (_ for _ in ()).throw(PackageNotFoundError("cwiki")),
            )
            app_version.cache_clear()
        try:
            assert _plugin_version() == expected
        finally:
            app_version.cache_clear()

    def test_plugin_json_remains_plugin_asset_version(self):
        """plugin.json 的 version 是插件资产版本，与包版本解耦、不得删除。

        它决定 Qoder 插件缓存路径（scripts/setup.py plugin_cache_dir），
        即使将来与包版本数值不同也必须保留该字段。
        """
        from adapters.mcp.mcp_server import _PLUGIN_JSON_PATH

        data = json.loads(_PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
        assert isinstance(data.get("version"), str)
        assert data["version"]
