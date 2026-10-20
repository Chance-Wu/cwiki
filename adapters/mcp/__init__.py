"""宿主无关的 cwiki MCP server 核心。

与 adapters.qoder（Qoder 插件资产 + 兼容 shim）完全独立；任何 MCP 宿主
统一以 ``python -m adapters.mcp`` 启动，工具契约与 outbox 行为一致。
宿主标识经 ``CWIKI_HOST`` 环境变量声明（qoder/claude/cursor/codex…），
未声明时记为 generic。
"""

from adapters.mcp.mcp_server import main

__all__ = ["main"]
