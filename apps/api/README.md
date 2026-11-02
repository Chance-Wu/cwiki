# apps/api — FastAPI 服务

HTTP 入口层：路由聚合、应用生命周期、依赖注入与鉴权。业务逻辑在 `packages/memory`、`packages/retrieval`、`packages/storage`。

## 入口

- `apps/api/main.py`：`create_app()` 工厂 + `lifespan`；模块级 `app = create_app()`；Typer CLI（`serve`、`rebuild-index`）
- 启动：`python tasks.py serve`（等价于 `uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 5172`）
- 端口与监听地址读取 `config.yaml` 的 `app.api_host` / `app.api_port`，默认 `127.0.0.1:5172`；`app.auth_token` 非空时启用 Bearer 鉴权

## 生命周期（lifespan）

1. 初始化数据库（`init_db`）与磁盘持久化的任务队列（`task_queue_startup`）
2. 启动 `PeriodicScheduler`：自动整合、复习提醒、`_meta` 周期导出（重启后按上次导出时间追赶）、自动关系发现与过期关系清理，均可在 `config.yaml` 关闭
3. 初始化 `FileStore` + `MemoryIndexer`，后台 `sync_all()` 同步 Markdown 索引，随后预热 BM25 / embedding 缓存
4. 非回环地址监听且未配置 token 时输出安全告警

## 路由（均自带 `/v1` 前缀）

| 领域 | 模块 |
|------|------|
| 记忆与候选 | `events`、`candidates`、`reviews`、`memories/`（crud / detail / relations / tags）、`memory_quality`、`memory_status`、`notes`、`file_memories`、`markdown_export` |
| 检索 | `search`、`context` |
| 组织与 Agent | `workspaces`、`agents`、`agent_sessions`、`agent_capture` |
| 复习与学习 | `spaced_review`、`weekly_review` |
| 系统与运维 | `health`、`system`、`task_queue`、`config`、`data_io`、`skills` |

`routes/_skill_scanner.py`、`routes/_skill_publisher.py` 提供 skills 扫描与发布的内部逻辑，不单独注册路由。

## 共享设施

- `deps.py`：`get_db`（请求出口统一 commit）、`FileStore` / `MemoryIndexer` 单例、当前 Agent 身份
- `auth.py`：可选的 Bearer token 校验
- `file_sync.py`：记忆路由共享的文件同步工具
- `routes/memories/_router.py`、`_shared.py`：memories 子路由的共享 router 与辅助函数

## 约定

- 新增路由模块自行声明 `/v1` 前缀，并在 `create_app()` 中 `include_router`
- 业务异常抛 `packages/domain/errors.py` 的 `AppError` 子类，由应用级处理器统一映射
- 接口清单见 [docs/api-reference.md](../../docs/api-reference.md)；测试在 `tests/api/`
