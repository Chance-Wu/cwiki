"""跨脚本公共工具 — 消除 start.py / run_alembic.py / run_pytest.py 等的重复代码。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def ensure_venv_interpreter(project_root: Path) -> None:
    """当前解释器不是项目 .venv 时，改用 .venv 解释器重跑当前脚本。

    系统 python（macOS 自带 3.9 / Homebrew 3.15 等）版本可能达标但没有项目
    依赖（uvicorn 等），直接运行会在启动子进程时报 ``No module named uvicorn``。
    统一切换到 .venv 解释器，保证 sys.executable 及其子进程都拿到完整依赖。
    """
    if os.environ.get("CWIKI_VENV_REEXEC") == "1":
        return
    if os.name == "nt":
        # pythonw 调用时保持无窗口语义，重执行也用 pythonw.exe
        exe = (
            "pythonw.exe"
            if Path(sys.executable).name.lower().startswith("pythonw")
            else "python.exe"
        )
        venv_python = project_root / ".venv" / "Scripts" / exe
    else:
        venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        if sys.version_info < (3, 11):  # noqa: UP036
            sys.exit(f"Python {sys.version.split()[0]} 不受支持，需要 3.11+；请先创建项目 .venv")
        return
    venv_root = (project_root / ".venv").resolve()
    exe = Path(sys.executable)
    # .venv 下的 python 常是符号链接（uv 创建），resolve 后会指到 uv 管理目录，
    # 因此未解析路径与解析路径都要比对。
    if exe.is_relative_to(venv_root) or exe.resolve().is_relative_to(venv_root):
        return
    env = {**os.environ, "CWIKI_VENV_REEXEC": "1"}
    sys.exit(subprocess.run([str(venv_python), *sys.argv], env=env, check=False).returncode)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 *override* 到 *base* 的深拷贝上。"""
    import copy

    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_app_config(project_root: Path) -> dict:
    """加载 config.yaml 并以 config.local.yaml 深合并覆盖；yaml 不可用时返回 {}。"""
    try:
        import yaml
    except ImportError:
        return {}
    config: dict = {}
    base = project_root / "config.yaml"
    local = project_root / "config.local.yaml"
    if base.exists():
        config = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
    if local.exists():
        local_cfg = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
        if local_cfg:
            config = _deep_merge(config, local_cfg)
    return config


def patch_metadata() -> None:
    """Patch importlib.metadata to skip encrypted entry_points.txt files.

    亿赛通等加密软件会加密 site-packages 中的 entry_points.txt，
    导致 alembic / pytest 扫描插件时抛出 UnicodeDecodeError。
    """
    import importlib.metadata

    _cls = importlib.metadata.PathDistribution
    _original_read_text = _cls.read_text

    def _safe_read_text(self, filename):
        try:
            return _original_read_text(self, filename)
        except (UnicodeDecodeError, OSError):
            return ""

    _cls.read_text = _safe_read_text


def print_message(message: str = "") -> None:
    """安全打印 — Windows 重定向输出可能使用 GBK/ASCII，不让装饰符号导致中断。"""
    encoding = sys.stdout.encoding or "utf-8"
    print(message.encode(encoding, errors="replace").decode(encoding))
