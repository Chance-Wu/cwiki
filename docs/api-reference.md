# API 参考

所有接口前缀 `/v1`。单用户本地部署，无认证（`apps/api/auth.py` 默认信任所有本地请求），默认仅监听 127.0.0.1（局域网访问见 `config.yaml` 的 `app.api_host` 注释）。共 20 个路由模块。

## 路由模块总览

| 模块 | 职责 |
|------|------|
| `workspaces` | 工作区 CRUD |
| `agents` | Agent 注册与管理 |
| `agent_sessions` | Agent 会话管理 |
| `events` | 事件上报（支持批量） |
| `candidates` | 候选记忆 CRUD |
| `reviews` | 审核操作（approve / reject / merge） |
| `memories` | 正式记忆 CRUD + 状态更新 |
| `search` | 关键词 / 混合 / 语义检索 |
| `context` | 检索 + 上下文组装 |
| `memory_quality` | 质量评分查询 |
| `memory_status` | 健康度与统计 |
| `notes` | 会话笔记 CRUD |
| `file_memories` | Markdown 文件存储 CRUD + 索引重建 |
| `health` | 健康检查 + 指标汇总 + 一致性对账 |
| `task_queue` | 队列诊断（状态快照 + 死信重试） |
| `config` | 配置读写 |
| `data_io` | 数据导入导出 |
| `skills` | 技能管理 |
| `spaced_review` | 间隔重复复习 |
| `system` | 系统管理（服务重启等） |

---

## 记忆主链路

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/events` | 上报 Agent 事件（支持批量） |
| `GET` | `/v1/candidates` | 候选记忆列表 |
| `POST` | `/v1/reviews` | 提交审核结果（approve / edit / reject / merge） |
| `GET` | `/v1/memories` | 正式记忆列表 |
| `POST` | `/v1/search` | 关键词检索 |
| `POST` | `/v1/context` | 混合检索 + 上下文组装 |

### 乐观并发控制

`PATCH /v1/memories/{id}` 支持可选 `expected_version`（≥1）。先读取当前记忆的完整正文与版本，修改时带上该版本；若已被更新，返回 `409 / memory_version_conflict`，重新读取并合并后再提交。

- 未提供的字段不变，`content` 是完整替换，历史版本保留修改前的正文
- 客户端遇到超时或 5xx 不自动重复 PATCH，应先确认是否已生效

### 缓存失效

所有记忆写操作（create / update / delete / merge / review）完成后自动失效检索缓存和上下文缓存，确保后续读请求获取最新数据。

### 工作区名称唯一

`POST /v1/workspaces` 遇到同名返回 `409`，响应 `detail.code` 为 `workspace_name_conflict`。已有数据库需应用 `024_workspace_name_unique` 迁移；发现旧重名数据时迁移会停止，不会自动合并或删改工作区。

---

## 反馈与冲突

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/feedback` | 提交记忆反馈 |
| `GET` | `/v1/feedback/{memory_id}` | 查看记忆反馈 |
| `POST` | `/v1/conflicts` | 创建冲突记录 |
| `GET` | `/v1/conflicts` | 冲突列表 |
| `POST` | `/v1/conflicts/{id}/resolve` | 解决冲突 |

---

## 健康监控

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/health` | 健康检查 |
| `GET` | `/v1/consistency` | DB / Markdown / 索引 / 向量四方只读对账报告（`healthy`、各方计数、缺失与孤儿 id 列表、载体错误），发现漂移供人工排查，不做自动修复 |
| `GET` | `/v1/memory-status` | 工作区整体状态 |
| `GET` | `/v1/memory-health/{memory_id}` | 单条记忆健康度 |
| `GET` | `/v1/metrics` | 指标汇总 |

## 任务队列诊断

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/task-queue-status` | 队列只读快照：各状态计数、最老 pending/running 任务年龄、重试统计、FAILED 死信明细（截断 50 条，全量计数保留）。FAILED 任务永久保留不被清理（死信语义），用于诊断积压与失败风暴 |
| `POST` | `/v1/task-queue/retry` | 手动重放死信：body `{"task_id": "..."}`，重置为 pending 并给新一轮重试预算；任务不存在或非 FAILED 返回 404 |

---

## 工作区与组织

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/POST/PUT/DELETE` | `/v1/workspaces` | 工作区 CRUD |
| `GET/POST` | `/v1/agents` | Agent 注册 |
| `GET` | `/v1/agent-sessions` | Agent 会话列表 |
| `GET/PATCH` | `/v1/notes` | 会话笔记 CRUD |
| `GET` | `/v1/memory-quality/{id}` | 质量评分详情 |

## 文件与数据

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/file-memories/rebuild-index` | 重建 SQLite + 向量索引 |
| `GET/POST` | `/v1/data-io/export` | 数据导出 |
| `POST` | `/v1/data-io/import` | 数据导入 |

## 配置与系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET/PUT` | `/v1/config` | 配置读写 |
| `GET/POST/DELETE` | `/v1/skills` | 技能管理 |
| `POST` | `/v1/spaced-review` | 提交复习结果 |
| `POST` | `/v1/system/restart` | 重启服务 |

> 完整路由实现见 `apps/api/routes/` 目录。
