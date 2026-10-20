"""Qoder 兼容 shim：Write-Ahead Outbox 核心已迁至 adapters.mcp.outbox。

使用 ``from adapters.qoder import outbox as outbox_module`` 的测试会经
本模块取到 mcp 核心（re-export 后 ``__name__`` 为 shim，monkeypatch
属性仍会落在 shim 上）。为保 monkeypatch 直达核心，这里直接把核心模块
绑定到同名属性，使 ``setattr(outbox_module, ...)`` 与 ``__file__``
都与核心一致。
"""

from adapters.mcp import outbox as _core

__file__ = _core.__file__
__all__ = [name for name in dir(_core) if not name.startswith("_")]
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)
