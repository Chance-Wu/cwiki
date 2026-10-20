"""版本号统一为 pyproject.toml 权威源。

改动前四套版本号互不同步：
  pyproject.toml                 0.1.0  ← 权威源（唯一事实）
  packages/domain/schemas/common.py  APP_VERSION = "0.3.0"  ← /v1/health
  apps/api/main.py                version="0.4.1"           ← /openapi.json
  adapters/qoder/.qoder-plugin/plugin.json  "0.1.0"        ← serverInfo + 缓存路径

改动后：
  - 新增 packages/domain/version.py，app_version() 读 importlib.metadata，
    缺失时回落 pyproject.toml 解析（源码分发无 dist-info 的场景）
  - common.py APP_VERSION / main.py FastAPI(version=) 改为调用 app_version()
  - plugin.json 保持 0.1.0 作为「插件资产版本」：它决定 Qoder 插件缓存路径
    （scripts/setup.py:154 plugin_cache_dir），与包版本解耦；
    _plugin_version() 改为优先读包版本，缺失回落 plugin.json
"""

from __future__ import annotations

import functools
import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from pathlib import Path

# 回落基准：仓库根目录下的 pyproject.toml
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT_PATH = _PROJECT_ROOT / "pyproject.toml"

# 元数据与 pyproject 均不可读时的最终兜底
_FALLBACK_VERSION = "0.0.0"


def _version_from_pyproject() -> str | None:
    """从 pyproject.toml 的 [project] version 读取；缺失或解析失败返回 None。"""
    try:
        data = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    version = data.get("project", {}).get("version", "")
    return version if isinstance(version, str) and version else None


@functools.cache
def app_version() -> str:
    """返回 cwiki 的权威版本号。

    权威源是 ``pyproject.toml`` 的 ``[project] version``。优先经
    ``importlib.metadata`` 读取（已安装的 dist-info 与之同步），
    未安装或 dist-info 损坏时直接解析 ``pyproject.toml``，
    两者都不可读才回落 ``0.0.0``。

    用法::

        from packages.domain.version import app_version
        FastAPI(version=app_version())

    不要在此函数之外硬编码版本号——历史上曾因四处各自维护
    （0.1.0 / 0.3.0 / 0.4.1）导致 serverInfo、health、openapi
    三个口径互相矛盾，排查时无法判断连的是哪个版本。
    """
    try:
        return _dist_version("cwiki")
    except PackageNotFoundError:
        pass
    return _version_from_pyproject() or _FALLBACK_VERSION
