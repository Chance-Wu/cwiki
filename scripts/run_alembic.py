"""Alembic 包装脚本：处理被加密的 entry_points.txt 文件。

亿赛通加密软件会加密 site-packages 中的 entry_points.txt 文件，导致 alembic
在扫描插件时抛出 UnicodeDecodeError。此脚本在导入 alembic 前 patch
importlib.metadata，跳过无法读取的文件。

Usage:
    python scripts/run_alembic.py [alembic args...]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.common import ensure_venv_interpreter, patch_metadata

ensure_venv_interpreter(ROOT)


def main() -> None:
    patch_metadata()

    from alembic.config import main as alembic_main

    sys.exit(alembic_main())


if __name__ == "__main__":
    main()
