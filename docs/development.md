# 开发指南

## 环境要求

- Python >= 3.11
- Node.js >= 18（前端开发）

## 安装

```bash
# 安装依赖（pip editable 安装）
python tasks.py install

# Agent 接入配置（注册 MCP Server、更新 AGENTS.md、安装 skill）
python tasks.py setup
```

---

## 启动服务

### 一键启动（推荐）

```bash
python tasks.py start
# 或直接调用底层脚本
python start.py
```

同时启动后端 + 前端，按 Ctrl+C 停止所有服务。

**启动流程：**

`python tasks.py start` 会先执行同步预检（步骤 1-3），再交由 `start.py` 启动服务：

1. 依次 `git pull --rebase` 代码仓库与数据仓库（失败不阻塞：离线或本地有未 sync 的改动时继续启动）
2. 检测 `cwiki-data/cwiki.db` 缺失时自动从 MD + `_meta/` 重建（索引文件在且一致时跳过 embedding 重建；review_schedule 已从 `_meta/` 恢复时跳过 recompute）
3. 检测索引文件（`index.db`/`vectors.npz`/`vectors.json`）缺失时只重建索引（不重建 DB，失败不阻塞）
4. 检查 npm 和 Python 依赖
5. 读取 `config.yaml` 获取端口配置（默认 API: 5172, Web: 5173）
6. 确保存储目录 `cwiki-data/` 存在（独立数据仓库，已在根仓库 `.gitignore` 中忽略）
7. 检查端口占用情况：
   - 端口空闲 → 继续启动
   - 端口有健康服务 → 提示已运行，建议用 `restart`
   - 端口被占用但无响应 → 自动释放（杀僵尸进程）
8. 检查前端 `node_modules`，缺失时自动 `npm install`
9. 启动后端（uvicorn --reload）和前端（npm run dev）
10. Windows 下使用 Job Object 管理进程树，确保 Ctrl+C 能清理所有子进程

> 直接运行 `python start.py` 会跳过步骤 1-3 的同步预检，仅启动服务；多设备场景建议使用 `python tasks.py start`。

### 一键重启

```bash
python tasks.py restart
# 或
python start.py --restart
```

强制释放端口后重启，适用于端口被旧进程占用的情况。

### 分别启动

| 终端 | 命令 | 说明 |
|------|------|------|
| 后端 API | `python tasks.py serve` | 端口 5172 |
| 前端界面 | `python tasks.py web` | 端口 5173 |

**重启单个服务：**

```bash
python tasks.py restart-serve   # 强制重启 API
python tasks.py restart-web     # 强制重启前端
```

### 服务地址

- API: http://127.0.0.1:5172（可在 config.yaml 的 `app.api_port` 修改；用 `127.0.0.1` 而非 `localhost`，避免 Windows 下 IPv6 `::1` 优先解析带来的连接延迟）
- Web: http://localhost:5173

### 后台常驻服务（serve_backend.py）

`serve_backend.py` 是供计划任务（如 Windows Task Scheduler `cwiki-backend`）开机自启调用的常驻服务包装器，用 `pythonw serve_backend.py` 运行（无控制台窗口）。

**核心特性：**

- **幂等**：端口已有健康服务时直接退出 0，不会起第二个实例
- **自愈**：子进程异常退出且端口空闲时，指数退避重启（5s → 60s 封顶）
- **让位**：重启时发现端口被外部接管（如 `tasks.py restart-serve`），退出 0 让位
- **日志**：仅写 `cwiki-data/serve_backend.log`（pythonw 下无控制台）

**进程生命周期管理：**

| 平台 | 机制 | 说明 |
|------|------|------|
| Windows | Job Object (`KILL_ON_JOB_CLOSE`) | 父进程结束时系统自动终止子进程树 |
| Unix | `start_new_session=True` + `killpg` | 子进程成为新进程组组长，信号可回收全部 worker |
| 全平台 | SIGTERM/SIGINT 信号处理器 | 收到信号后优雅关闭：SIGTERM → 等待 5s → SIGKILL |
| 全平台 | `atexit` 安全网 | 父进程任何退出路径都确保子进程被回收 |

**管理命令：**

```bash
# Windows 计划任务
schtasks /run /tn cwiki-backend      # 手动启动
schtasks /end /tn cwiki-backend      # 停止

# 代码更新后重启（推荐）
python tasks.py restart-serve         # 强制释放端口后重启
```

> 不传 `--reload`、不读 `settings.debug`——代码更新后用 `python tasks.py restart-serve` 重启服务。

---

## Agent 接入配置

在项目根目录运行（bash / PowerShell 通用）：

```text
python scripts/setup.py
```

### setup.py 完成事项

1. 通过 `qodercli plugins install` 安装本地插件 `cwiki-qoder@local`（缓存缺失时自动执行；未安装 qodercli 时告警并继续）
2. 修补插件缓存中的 `.mcp.json` 与 `hooks/hooks.json`，注入当前 venv 的 python 绝对路径与项目根目录
3. 在 `~/.qoder/settings.json` 的 `enabledPlugins` 中启用 `cwiki-qoder@local`，并清理裸名 / 旧市场键等无法解析的残留条目
4. 向全局 `~/.qoder/mcp.json` 注入 cwiki 服务器作为兜底（保留其他服务器）
5. 更新 `~/.qoder/AGENTS.md` 的 cwiki 受管区块，保留区块外的用户内容
6. 安装 `cwiki-save` skill（软链接 → 复制 fallback）
7. 运行 Alembic 迁移初始化或升级数据库
8. 询问是否启动 API 服务

> 插件交付依赖 Qoder CLI（`brew install qoderai/qoder/qodercli` 或 `npm install -g @qoder-ai/qodercli`）；缺失时插件 MCP 与 hooks 不生效，全局 mcp.json 仍可兜底 MCP。

### 更新与内容保护

- cwiki 区块由 `<!-- cwiki:begin -->` 和 `<!-- cwiki:end -->` 标记；重跑 setup 仅替换该区块
- 可识别的无标记旧 cwiki 区块会迁移到受管区块；迁移前备份为 `AGENTS.md.cwiki-*.bak`
- 标记不完整时拒绝更新，不改写原文件；需先人工检查标记
- AGENTS 保留工具契约；提取策略由 [cwiki-save skill](../skills/cwiki-save/SKILL.md) 独占维护

### 单独同步与只读诊断

只更新规则、不改数据库时使用：

```text
python scripts/setup.py --sync-instructions   # 同步 AGENTS.md 区块、skill、插件启用与全局 mcp.json
python scripts/setup.py --check               # 只读诊断（不启动 MCP、不投递记忆）
```

> `--check` 返回 `host_verified: false`；即使返回 `ok`，也必须核对宿主实际加载结果。

### Hook 与提醒

插件中的 `cwiki-hook` 只在会话开始与用户输入时注入静态保存提醒：

- 不读取 transcript、不上传 prompt 或工具输出、不阻塞用户
- `setup.py` 自动在 `enabledPlugins` 中启用 `cwiki-qoder@local`，使 hooks 在新会话中生效
- 提醒不等于自动采集：事件和笔记为空时，`memory_checkpoint` 无法恢复完整对话

### 重载与验证

安装成功不代表运行中的宿主已加载新契约：

1. **完全重启 Qoder**：hooks 与 skill 随新会话刷新，但插件 MCP 服务器列表在宿主启动时确定——安装或更新本地插件后，仅开新会话不够，需完全退出并重新打开 Qoder
2. **MCP 重连**：更新 MCP 代码后，在 Qoder 中重连 cwiki MCP；以 `tools/list` 返回为准
3. **新会话**：开启新会话以重新加载 AGENTS 与 skill
4. **API 重载**：后端代码更新后需单独确认自动重载完成或重启 API

> `memory_save` 应描述为正文语义原样保存（仅做空白规范化）、类型仅分类；`memory_checkpoint` 应明确只检查有限的已采集事件与笔记。完整写入契约见[记忆系统](memory-system.md#写入契约)。

### 数据库迁移升级

升级已有数据库时，先备份，再运行 `python tasks.py migrate-up` 应用工作区名称唯一索引（`024_workspace_name_unique`）。若发现重名，迁移会停止并列出冲突，不会自动合并或删改数据。

> 仅重启服务或执行 `--sync-instructions` 不会应用此迁移。

---

## 常用命令

### 服务管理

```bash
python tasks.py start              # 一键启动前后端
python tasks.py restart            # 一键重启（强制释放端口）
python tasks.py serve              # 仅启动 API
python tasks.py restart-serve      # 仅重启 API
python tasks.py web                # 仅启动前端
python tasks.py restart-web        # 仅重启前端
```

### 数据库迁移

```bash
python tasks.py migrate-init       # 初始化数据库
python tasks.py migrate-up         # 应用待执行迁移
python tasks.py migrate-down       # 回退最近一次迁移
python tasks.py migrate-create "描述"  # 生成新迁移
```

### Git 同步与数据重建

```bash
python cwiki-data/sync.py          # 数据同步（数据仓库自管）：WAL checkpoint → 无改动时跳过导出与 commit；有改动时 导出 MD + _meta → commit；随后 pull 远端 → push
python tasks.py migrate-to-git     # 首次迁移：SQLite 全量导出为 MD + _meta
python tasks.py rebuild-db         # 从 MD + _meta 重建数据库（索引文件在且一致时跳过 embedding 重建；review_schedule 已恢复时跳过 recompute）
python tasks.py rebuild-db --force-index   # 强制重建向量索引（即使索引文件已存在且一致）
python tasks.py rebuild-db --index-only    # 只重建向量索引（不重建 DB，用于索引缺失自愈）
python tasks.py recompute          # 重算派生字段（SM-2 调度等，无条件执行）
```

> 详见 [Git 同步指南](git-sync.md)。数据同步由数据仓库自带的 `cwiki-data/sync.py` 管理（随数据仓库版本化），代码侧不再提供同步入口；`sync.py` 在独立数据仓库中提交 `cwiki-data/` 全部内容（MD + `_meta/` + `cwiki.db` + 索引文件）。DB 为二进制不可合并，冲突时可删除后经 `rebuild-db` 从 MD + `_meta/` 重建。

### 索引与 Worker

```bash
# 重建索引（通过 API 调用，需先启动服务）
curl -X POST http://127.0.0.1:5172/v1/file-memories/rebuild-index

python tasks.py worker             # 手动回填历史事件为 Episode
```

### 代码质量

```bash
python tasks.py lint               # 代码检查（ruff check + format --check）
python tasks.py format             # 代码格式化（ruff check --fix + format）
python tasks.py test               # 运行测试（通过 scripts/run_pytest.py 包装）
```

> 查看所有命令：`python tasks.py help`

**测试运行器说明：** `scripts/run_pytest.py` 是 pytest 的包装脚本，在导入 pytest 前 patch `importlib.metadata`，跳过被加密软件损坏的 `entry_points.txt` 文件，避免 `UnicodeDecodeError`。直接使用 `python -m pytest` 可能因亿赛通加密软件干扰而失败。

---

## 入口方式

**项目不使用 `entry_points` / `console_scripts`。** `pip install -e .` 会在 `site-packages` 生成 `entry_points.txt`，亿赛通加密软件会加密这些文件导致 `UnicodeDecodeError`。所有入口统一通过 `python -m` 模块方式启动：

| 入口 | 说明 |
|------|------|
| `python tasks.py serve` | 启动 API 服务（含后台任务） |
| `python serve_backend.py` | 后台常驻服务（计划任务自启，幂等+自愈+让位） |
| `python tasks.py test` | 运行测试（通过 `scripts/run_pytest.py` 包装，自动跳过损坏的 entry_points） |
| `python -m adapters.qoder.mcp_server` | MCP Server 入口（Qoder 插件，需设置 `PYTHONPATH`） |
| `python -m adapters.qoder.hooks <command>` | Qoder 静态记忆提醒（不采集正文、不调用 API） |

**为什么不用 `pip install -e .` 的 console_scripts？**
- 亿赛通加密软件会加密 `site-packages` 中的 `entry_points.txt` 文件
- pytest 在扫描已安装包的插件时会读取这些文件，导致 `UnicodeDecodeError`
- `scripts/run_pytest.py` 通过 patch `importlib.metadata.Distribution.read_text` 跳过损坏文件
- 长期方案：避免依赖任何 `entry_points.txt`，全部使用 `python -m` 模块入口

---

## 配置

通过项目根目录的 `config.yaml` 统一配置（不使用环境变量）。

### 基础配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `database.url` | `sqlite+aiosqlite:///./cwiki-data/cwiki.db` | 数据库连接 |
| `storage.memory_dir` | `./cwiki-data` | Markdown 记忆文件存储目录 |
| `app.api_host` / `app.api_port` | `0.0.0.0` / `5172` | API 监听地址 |
| `app.embedding_model` | `BAAI/bge-small-zh-v1.5` | Embedding 模型（fastembed 本地 ONNX） |
| `app.embedding_dimensions` | `512` | Embedding 向量维度 |

### 检索配置（`retrieval`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `bm25_top_k` / `vector_top_k` | `50` | 各路召回数量 |
| `reranker_*_weight` | 见 config.yaml | Rerank 信号权重（总和 1.0） |

### Feature Flags（`parasitic_evolution`）

P0-P4 分级开关，控制各阶段功能启用。详见 `config.yaml`。

### MCP 适配器环境变量

Qoder MCP 适配器另有独立环境变量：`CWIKI_API_URL`、`CWIKI_WORKSPACE`、`CWIKI_TIMEOUT`（见 `adapters/qoder/README.md`）。API 为单用户本地部署，不做 token 认证（见 `apps/api/auth.py`）。

---

## 共享辅助函数

新增代码前先确认对应能力是否已有共享实现，避免再复制一份：

| 位置 | 提供 | 说明 |
|------|------|------|
| `scripts/port_utils.py` | `port_is_free`, `ensure_port_free`, `force_kill_port` 等 | 跨平台端口管理；供 `start.py` 和 `tasks.py` 共享使用 |
| `packages/domain/time_utils.py` | `days_since(dt, now=None)` | 天数差计算；naive datetime 视为 UTC |
| `apps/api/deps.py` | `get_or_404`（支持 `options` 参数传入 `defer()` / `noload()`）、`execute_paginated`（count + data 并行查询）、`apply_optional_filters` | 路由层通用的取记录、分页、可选过滤 |
| `packages/retrieval/engine.py` | `_ensure_candidate`、`_content_fingerprint`、`_build_index` | 候选池初始化；BM25 索引指纹缓存 |

### 脚本架构

启动相关脚本采用分层设计，避免重复代码：

```
tasks.py          # 任务注册器，提供统一 CLI 入口
    ↓ 调用
start.py          # 一键启动逻辑（进程管理、依赖检查、配置读取）
    ↓ 共享
scripts/port_utils.py  # 端口管理工具（port_is_free / force_kill_port 等）

serve_backend.py  # 后台常驻服务（计划任务自启，幂等+自愈+让位）
    ↓ 共享
scripts/port_utils.py  # 同上端口工具
```

- `tasks.py`：任务注册框架，所有命令通过 `@task("name")` 装饰器注册
- `start.py`：专注服务启动，支持 `--restart` 强制重启模式
- `serve_backend.py`：后台常驻包装器，信号处理 + atexit 安全网确保子进程回收，Windows 用 Job Object、Unix 用 `killpg` 管理进程树
- `scripts/port_utils.py`：跨平台端口管理，Windows 用 netstat + taskkill，Unix 用 lsof + fuser

> **数据类 `to_dict` 约定**：纯 dataclass 用 `dataclasses.asdict`（递归转换、深拷贝叶子值）；需要四舍五入浮点时用 `{k: round(v, 4) if isinstance(v, float) else v for k, v in asdict(self).items()}`；有字段排除或改名的保持手写实现。
