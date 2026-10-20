#!/usr/bin/env python3
"""Qoder 兼容 shim：MCP 核心已迁至 adapters.mcp.mcp_server。

旧安装配置（插件缓存 .mcp.json / 全局 ~/.qoder/mcp.json）指向
``python -m adapters.qoder.mcp_server``；本 shim 保持该入口可用，
并把宿主标识固定为 qoder。monkeypatch 属性直达核心模块。
"""

from __future__ import annotations

import os

# 旧入口显式声明宿主为 qoder；用户 env 已设 CWIKI_HOST 时尊重之
os.environ.setdefault("CWIKI_HOST", "qoder")

from adapters.mcp import mcp_server as _core

__file__ = _core.__file__
__all__ = [name for name in dir(_core) if not name.startswith("_")]
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

if __name__ == "__main__":
    _core.main()
