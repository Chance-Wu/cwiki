"""Alembic 包装脚本：处理被加密的 entry_points.txt 文件。

亿赛通加密软件会加密 site-packages 中的 entry_points.txt 文件，导致 alembic
在扫描插件时抛出 UnicodeDecodeError。此脚本在导入 alembic 前
patch importlib.metadata，跳过无法读取的文件。

Usage:
    python scripts/run_alembic.py [alembic args...]
"""

import sys


def _patch_metadata():
    """给 importlib.metadata 打补丁，跳过无法读取的 entry_points.txt。"""
    import importlib.metadata

    _cls = importlib.metadata.PathDistribution
    _original_read_text = _cls.read_text

    def _safe_read_text(self, filename):
        try:
            return _original_read_text(self, filename)
        except (UnicodeDecodeError, OSError):
            return ""

    _cls.read_text = _safe_read_text


def main():
    _patch_metadata()

    from alembic.config import main as alembic_main

    sys.exit(alembic_main())


if __name__ == "__main__":
    main()
