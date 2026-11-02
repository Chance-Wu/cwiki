# apps 应用层

三个可运行应用。业务能力来自 `packages/`，三者通过 HTTP API 与进程内任务队列协作。

| 目录 | 职责 | 常用命令 |
|------|------|----------|
| [api](api/README.md) | FastAPI 服务（默认 `127.0.0.1:5172`）：REST API、应用生命周期、后台任务队列 | `python tasks.py serve` |
| [web](web/README.md) | React 18 + Vite 控制台（开发 `:5173`，生产预览 `:4173`） | `python tasks.py web` / `preview` |
| [worker](worker/README.md) | 后台任务实现：评分、embedding、去重、整合、复习提醒、`_meta` 导出 | 随 API 进程内 TaskQueue 运行；`python tasks.py worker` 手动加工 episode |

`python tasks.py start` 一次性启动前后端；`python tasks.py restart` 释放端口后重启。

依赖方向：`apps/*` → `packages/*`；`adapters/*` 通过 HTTP API 写入、可直连只读 SQLite 读取，不反向依赖业务应用。
