# adapters/mcp — 宿主无关 MCP server

以 stdio 传输提供 cwiki 的 19 个记忆工具。任何 MCP 宿主统一用 `python -m adapters.mcp` 启动；宿主标识由 `CWIKI_HOST` 声明（`qoder` / `claude` / `cursor` / `codex` …），未声明记为 `generic`。

## 读写策略

- **读**：`memory_search` 默认先查本地只读 SQLite（`local_index.py`，进程内 BM25）；强命中直接返回，弱命中回落 API 混合检索，API 连接失败或 5xx 时降级为本地关键词排序
- **写**：`memory_save` 等写入先落 Write-Ahead Outbox（`outbox.py`、`outbox_manager.py`），再提交 API；失败自动重试，耗尽后保留原文待人工处理
- `semantic` 模式始终 API 优先；仅写入必须依赖 API

## 模块

| 模块 | 职责 |
|------|------|
| `mcp_server.py` | MCP 服务器主体：工具分发、workspace 解析、参数校验 |
| `tool_definitions.py` | 19 个工具的 JSON Schema（严格模式，未知参数拒绝） |
| `transport.py` | stdio 传输与 git 信息辅助 |
| `client.py` | cwiki REST API 的异步 HTTP 客户端 |
| `local_index.py` | 只读 SQLite + 进程内 BM25 的本地检索 |
| `outbox.py` / `outbox_manager.py` | 崩溃安全的写前日志、提交与状态摘要 |
| `checkpoint_manager.py` | 检查点（从事件/笔记提取候选）逻辑 |
| `signal_engine.py` | 记忆提取的信号检测规则 |
| `content_processing.py` | 自动标题、关键词提取与响应格式化 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CWIKI_API_URL` | `http://127.0.0.1:5172` | cwiki API 地址 |
| `CWIKI_WORKSPACE` | 由项目目录推导 | 显式 workspace 名称或 UUID，优先于目录推导 |
| `CWIKI_DB_PATH` | `config.yaml` 的数据库路径 | 本地只读索引使用的 DB 路径 |
| `CWIKI_HOST` | `generic` | 宿主标识 |
| `CWIKI_TIMEOUT` | `10.0` | API 请求超时（秒） |
| `CWIKI_STATE_DIR` | `~/.cwiki/state` | 动态 workspace 注册表等状态目录 |

## 参考

- 工具清单与参数细节：[adapters/qoder/README.md](../qoder/README.md#mcp-工具)
- 写入契约：[docs/memory-system.md](../../docs/memory-system.md)
- 测试：`tests/adapter/`、`tests/integration/test_mcp_stdio.py`
