# cwiki Agent 指引

## 项目定位

cwiki 是个人知识工作台与 Agent 记忆基础设施。核心闭环：**存储 → 检索 → 进化**——知识持续积累、去重、合并、升级，让每次对话建立在已有且进化过的知识之上。

> 你是本项目的开发助手，应当以身作则，主动使用记忆工具。

### 边界约束

对于 cwiki，只围绕三个结果展开：

1. 记得准： Agent 写入的记忆完整、可信、有来源，能够正确更新而不是不断堆积。
2. 找得准： 面对真实任务，能够在低延迟和有限 Token 预算内找出最有价值的记忆。
3. 用得稳： 多会话、多设备和后台任务异常不会导致数据丢失、状态混乱或不可恢复的错误合并。

- **单用户本地部署**：不做多用户、团队协作、SaaS 服务或复杂权限系统
- **多设备 Git 同步**：支持同一用户通过 GitHub 私有仓库在多台设备间同步数据（cwiki-data/ + config.yaml），SQLite 随库同步，且可随时从 MD + _meta 重建
- **聚焦核心闭环**：功能围绕记忆的存储、检索、去重、合并、演化，不做社交/协作/花哨功能
- **质量优先**：记忆价值以真实信息的完整性和可复用性为准，不以条数、篇幅衡量
- **技术克制**：不引入非必要依赖，不为了用新技术而重构

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+, FastAPI, SQLAlchemy (async), aiosqlite, Pydantic v2 |
| 前端 | React 18, Vite, TypeScript, Tailwind CSS, Radix UI, Framer Motion, TanStack Query |
| 检索 | 自定义 BM25 (CJK) + 向量余弦 + RRF 融合 + 多信号重排, fastembed (本地 ONNX embedding) |
| 工程 | Alembic (迁移), ruff (lint + format), mypy (strict), pytest (asyncio_mode=auto) |

## 项目结构

三层架构：`apps/`（api + web + worker）、`packages/`（domain + memory + retrieval + storage + protocol）、`adapters/qoder/`（MCP 服务器）。辅助：`skills/`、`scripts/`、`docs/`、`migrations/`、`tests/`、`benchmarks/`。

## 开发命令

所有命令通过 `python tasks.py <命令>` 跨平台运行。常用：`start`/`restart`（全栈）、`serve`/`web`（单端）、`test`/`lint`/`format`、`install`、`setup`。迁移：`migrate-init`/`migrate-up`/`migrate-down`/`migrate-create "描述"`。数据维护：`migrate-to-git`、`rebuild-db`、`recompute`。数据同步由数据仓库自管：`python cwiki-data/sync.py`。完整列表：`python tasks.py help`。

> `restart` 强制释放端口后重启（端口被占用时使用）。服务热重启：`curl -X POST http://127.0.0.1:5172/v1/system/restart`

## 项目特有约定

- 数据库统一使用 `cwiki-data/cwiki.db`，Markdown 记忆文件目录为 `./cwiki-data/`（由 `config.yaml` 的 `storage.memory_dir` 决定），不要引用 `memorywiki`
- 配置统一走 `config.yaml`，不要引入环境变量配置（MCP 适配器自身的连接参数除外）
- workspace 是唯一的组织维度；project/scope 概念已移除
- 完整说明见 [记忆系统](docs/memory-system.md)和[开发指南](docs/development.md#agent-接入配置)

## Git 同步

**双仓库布局**：代码仓库（`cwiki.git`）与数据仓库（`cwiki-data.git`）彼此独立，`cwiki-data/` 目录内自带 `.git`，被根仓库 `.gitignore` 忽略。数据整体位于 `cwiki-data/`（Markdown + `_meta/` JSON + SQLite `cwiki.db`），随数据仓库多设备同步；SQLite 亦可随时从 MD + _meta 完整重建（workspace 表由 `_meta/_workspaces.json` 精确恢复，含无记忆的空 workspace）。数据仓库自带同步工具 `cwiki-data/sync.py`（随数据仓库版本化分发）；代码侧（tasks.py）不提供数据同步入口。

- **同步媒介**：两个 GitHub 私有仓库——代码 `cwiki.git`、数据 `cwiki-data.git`
- **数据仓库内容**：cwiki-data/（MD + _meta + cwiki.db + index.db + vectors.npz + vectors.json）
- **代码仓库内容**：代码资源、config.yaml、docs 等（不含 cwiki-data/）
- **不同步**：config.local.yaml（设备本地）；`*.db-wal`/`*.db-shm`/`*.db-journal`（WAL 临时侧车，由 `cwiki-data/.gitignore` 排除）
- **日常使用**：数据同步在数据仓库内自管——`python cwiki-data/sync.py`（WAL checkpoint → 导出 MD → **在数据仓库内** commit → pull 远端 → push；无本地变化时跳过导出与 commit）；`python tasks.py start` 仅 pull 代码仓库 + 检测重建（DB 缺失→完整重建，索引文件缺失→只重建索引），不触碰数据仓库
- **WAL checkpoint**：sync 前自动执行 `PRAGMA wal_checkpoint(TRUNCATE)`，确保提交的 .db 含全部数据且无 -wal 残留
- **重建轻量化**：`rebuild-db` 在索引文件（index.db + vectors.npz + vectors.json）存在且索引行数与记忆数一致时跳过 embedding 重建（`--force-index` 强制重建，`--index-only` 只修索引）；`_meta` 已恢复 review_schedule 时跳过 recompute
- **运行中拉取更新**：服务运行中 pull 到新 DB 后不会自动加载，需 `python tasks.py restart`（restart 前自动 pull 代码仓库；数据更新由 `python cwiki-data/sync.py` 拉取）
- **冲突处理**：Markdown 文件 git 原生合并；_meta/ 按 memory_id 分文件，冲突罕见；cwiki.db 为二进制不可合并——任选一端，或删本地 DB 从 MD + _meta 重建兜底（索引文件仍在时重建无需重新 embedding，数秒完成）；命令在数据仓库内执行（`git -C cwiki-data ...`）
- **旧单仓库设备迁移**：一次性为 cwiki-data 建独立仓库并让根仓库移除索引，步骤见 docs/git-sync.md「从单仓库迁移」

详见 [docs/git-sync.md](docs/git-sync.md)。
