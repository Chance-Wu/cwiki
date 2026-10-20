"""Qoder 兼容 shim：HTTP client 核心已迁至 adapters.mcp.client。"""

from adapters.mcp.client import CwikiClient, MemoryUpdateUncertainError  # noqa: F401
