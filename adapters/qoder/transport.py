"""Qoder 兼容 shim：stdio 传输已迁至 adapters.mcp.transport。"""

from adapters.mcp.transport import stdin_reader, write_stdout  # noqa: F401
