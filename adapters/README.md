# adapters 接入层

把 cwiki 能力接到各类 Agent 宿主：MCP 工具、hook 生命周期、Qoder 插件资产。适配器不直接访问业务实现，读路径可直连只读 SQLite，写入统一走 HTTP API（`/v1/candidates` 等）。

| 目录 | 职责 | 入口 |
|------|------|------|
| [mcp](mcp/README.md) | 宿主无关的 MCP server 核心：19 个记忆工具、本地只读检索、写前 Outbox | `python -m adapters.mcp` |
| [hooks](hooks/README.md) | 宿主无关的 hook 运行时：会话提醒、自动召回、捕获、spool 投递 | `python -m adapters.hooks <host> <command>` |
| [qoder](qoder/README.md) | Qoder 插件资产（`.mcp.json`、hooks、skills、commands）与兼容 shim | `python scripts/setup.py` |

宿主差异（事件名、项目目录环境变量、输出形状）集中在 `hooks/profiles.py` 的 `HostProfile` 声明；新增宿主只需注册一个 profile 与 MCP 环境变量。

适配器自身的连接参数可用环境变量覆盖（`CWIKI_API_URL`、`CWIKI_WORKSPACE`、`CWIKI_DB_PATH`、`CWIKI_HOST` 等），业务配置仍统一在 `config.yaml`。
