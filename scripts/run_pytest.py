"""Pytest 包装脚本：处理被加密的 entry_points.txt 文件。

亿赛通加密软件会加密 site-packages 中的 entry_points.txt 文件，导致 pytest
在扫描已安装包的插件时抛出 UnicodeDecodeError。此脚本在导入 pytest 前
patch importlib.metadata，跳过无法读取的文件。

Usage:
    python scripts/run_pytest.py [pytest args...]
"""

import sys


def _patch_metadata():
    """给 importlib.metadata 打补丁，跳过无法读取的 entry_points.txt。"""
    import importlib.metadata

    # 直接 patch 具体实现类 PathDistribution（而非其来源基类）
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

    import pytest

    sys.exit(pytest.main(sys.argv[1:]))


if __name__ == "__main__":
    main()
