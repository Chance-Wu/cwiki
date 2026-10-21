# Agent 接入指南

面向第一次把 cwiki 接入 Agent 的用户。两条接入路径：**MCP（推荐）** 与 **HTTP API 直连**，二选一或并存（MCP 工具底层同样调用 HTTP API）。接入完成后按第 4 节清单验证。

> 前置条件：后端已启动（`python tasks.py serve`，默认 http://127.0.0.1:5172）。安装依赖见[开发指南](development.md#安装)。

---

## 1. 接入方式概览

| | MCP 接入 | HTTP API 直连 |
|---|---|---|
| 适用场景 | Qoder 等 MCP 宿主 | 任意能发 HTTP 请求的程序 / 自研 Agent |
| 适配层 | `adapters/qoder/`（stdio，`python -m adapters.qoder.mcp_server`） | 无，直接调 API |
| 能力 | 19 个 `memory_*` 工具 + cwiki-save skill + 3 个斜杠命令 | 全部 REST 端点（见 [API 参考](api-reference.md)） |
| 可靠写入 | 客户端本地暂存（`cached: true`），恢复后 `memory_retry_failed` 重试 | 幂等键 `client_write_id`（候选）/ `sequence`（事件） |
| 行为契约 | AGENTS.md 受管区块 + hook 静态提醒 | 由调用方自行约定 |

**推荐路径**：Qoder 用户直接运行 `python scripts/setup.py`（一条命令完成插件注册、MCP 修补、hooks、skill、AGENTS.md 区块与数据库迁移），详见[安装与更新说明](development.md#agent-接入配置)。本文其余部分给出手工配置的最小步骤与其他宿主的接入方式。

---

## 2. 最小 MCP 配置

MCP 服务器以 stdio 方式运行 `python -m adapters.qoder.mcp_server`。最小配置如下（Qoder 的 `.mcp.json` 格式，其他宿主字段类似）：

```json
{
  "mcpServers": {
    "cwiki": {
      "type": "stdio",
      "command": "/绝对路径/到/venv 的 python",
      "args": ["-m", "adapters.qoder.mcp_server"],
      "cwd": "/项目根目录绝对路径",
      "env": {
        "PYTHONPATH": ".",
        "CWIKI_API_URL": "http://127.0.0.1:5172",
        "CWIKI_WORKSPACE": "default",
        "CWIKI_TIMEOUT": "10.0"
      }
    }
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| `command` | 是 | 项目 venv 的 python 绝对路径；用 `python -m` 模块入口，避免 `pip install -e .` 生成的可执行文件被加密软件损坏（见[入口方式](development.md#入口方式)） |
| `cwd` | **是** | 项目根目录绝对路径。**不能省略**：宿主在未知工作目录启动 stdio 子进程时，`python -m` 找不到模块、`PYTHONPATH="."` 也会解析到错误目录，表现为 Qoder 重启后插件**间歇性连接失败或被超时丢弃**（Windows 上尤其高发）。`scripts/setup.py` 修补配置时会自动注入此字段 |
| `env.PYTHONPATH` | 是 | 指向项目根目录，使 `python -m` 能找到项目模块 |
| `env.CWIKI_API_URL` | 否 | 默认 `http://127.0.0.1:5172`。用 `127.0.0.1` 而非 `localhost`，避免 Windows 下 IPv6 `::1` 优先解析带来的连接延迟 |
| `env.CWIKI_WORKSPACE` | 否 | 默认工作区，默认 `default` |
| `env.CWIKI_TIMEOUT` | 否 | API 请求超时秒数，默认 `10.0` |

Qoder 用户的推荐做法仍是 `python scripts/setup.py`：它会修补插件缓存中的 `.mcp.json`（注入 venv python、`cwd`、`PYTHONPATH`），并在全局 `~/.qoder/mcp.json` 注入兜底条目。配置改动后需**完全重启宿主**——插件 MCP 服务器列表只在宿主启动时读取。

19 个工具的完整契约（参数、默认值、严格 schema）见 [MCP 工具参考](../adapters/qoder/README.md#mcp-tools)；写入契约（语义原样保存、类型仅分类）见[记忆系统](memory-system.md#写入契约)。

---

### 2.1 其他宿主（Claude Code / Cursor / Codex / 任意 MCP）

核心入口与 Qoder 相同，只是配置位置不同：

| 能力 | 入口 | 说明 |
|---|---|---|
| MCP | `python -m adapters.mcp` | 与 Qoder 共用同一套工具；env 设置 `CWIKI_WORKSPACE` 绑定项目 |
| Hook | `python -m adapters.hooks <host> <event>` | `host`：`qoder` / `claude` / `cursor`；事件见下表 |
| 捕获 | `POST /v1/integrations/agent/capture` | 任意语言/脚本可直接提交 compact summary、工具失败、会话结束 |

Hook 事件与宿主能力：

| 事件 | Qoder / Claude Code | Cursor |
|---|---|---|
| `session-start` | ✅ 注入提醒 + 补投 spool | ✅ |
| `user-prompt-submit` | ✅ 自动召回（每 prompt） | ❌（`beforeSubmitPrompt` 不能注入 context） |
| `post-compact` | ✅ 捕获 `compact_summary` | ❌（无 summary） |
| `post-tool-failure` | ✅ 捕获脱敏错误 | ✅ |
| `session-end` | ✅ 结束会话 + 补投 | ✅ |

安装器（推荐，先 dry-run 检查将写入的文件）：

```bash
python tasks.py setup-agent --host claude --project /path/to/project --dry-run
python tasks.py setup-agent --host claude --project /path/to/project
python tasks.py setup-agent --host cursor --project /path/to/project
python tasks.py setup-agent --host codex  --project /path/to/project
```

安装器只管理 `cwiki` 配置条目与 `<!-- cwiki:begin -->` 区块，保留用户已有 hooks/MCP/指令；Claude 写 `~/.claude/settings.json` + 项目 `.mcp.json`，Cursor 写项目 `.cursor/{mcp,hooks}.json` 与 `.cursor/rules/cwiki.mdc`，Codex 写 `~/.codex/config.toml` 的托管块与 `AGENTS.md`。

#### 最小配置模板（Claude Code / Cursor / Codex）

Claude Code 与 Cursor 使用 JSON 的 `mcpServers` 结构，区别只在文件位置：

```json
{
  "mcpServers": {
    "cwiki": {
      "type": "stdio",
      "command": "/绝对路径/到/venv 的 python",
      "args": ["-m", "adapters.mcp"],
      "cwd": "/cwiki 项目根目录绝对路径",
      "env": {
        "PYTHONPATH": "/cwiki 项目根目录绝对路径",
        "CWIKI_WORKSPACE": "你的项目名",
        "CWIKI_HOST": "claude"
      }
    }
  }
}
```

- Claude Code：项目根目录 `.mcp.json`；hooks 由安装器写入 `~/.claude/settings.json`。
- Cursor：项目根目录 `.cursor/mcp.json`；hooks 写入 `.cursor/hooks.json`，规则写入 `.cursor/rules/cwiki.mdc`。
- Codex 使用 TOML，写入 `~/.codex/config.toml`：

```toml
[mcp_servers.cwiki]
command = "/绝对路径/到/venv 的 python"
args = ["-m", "adapters.mcp"]
cwd = "/cwiki 项目根目录绝对路径"
env = { PYTHONPATH = "/cwiki 项目根目录绝对路径", CWIKI_WORKSPACE = "你的项目名", CWIKI_HOST = "codex" }
```

`CWIKI_API_URL`（默认 `http://127.0.0.1:5172`）、`CWIKI_TIMEOUT`（默认 `10.0`）可选。推荐直接运行 `python tasks.py setup-agent --host <claude|cursor|codex> --project <项目路径>` 自动生成上述配置并合并 hooks/指令。

### 2.1.1 DeepSeek Harness（dsh）

dsh 是 MCP 宿主，Agent 经 stdio 工具直连 cwiki（无原生 hooks；捕获可由宿主脚本经 capture API 提交）。dsh 连接外部 MCP 只有一条路径：在 profile 的 `~/.dsh/profiles/<profile>/cordis.patch.yml` 里，用官方 `@deepseek-ai/dsh-mcp-client` 桥声明一行 stdio 配置——**它不读 `~/.dsh/mcp.json`**（那是别的宿主约定）。安装器代写这一行：

```bash
python tasks.py setup-dsh --project /path/to/project          # 写入并落 skill
python tasks.py setup-dsh --project /path/to/project --dry-run
python tasks.py setup-dsh --verify                            # 挂载后起 stdio 自检（不经模型）
```

要点（均为实测）：

- 配置条目必须包在 `- insert:` 里；顶层裸条目会被 dsh 当成"按 id 覆盖已有行"，patch 时报 `entry not found` 并被静默丢弃。
- 字段是 `transport: stdio`（dsh 契约），不是 Claude/Codex 的 `type`；`serverName: cwiki` 决定工具名前缀 `mcp__cwiki__<tool>`。
- 写入 `CWIKI_HOST=dsh`、`CWIKI_WORKSPACE=项目名`、`CWIKI_WORKSPACE_DIR=项目路径`。**dsh 不下发 roots、也不导出项目目录 env**（实测只有 `DSH_HOME`/`DSH_PROFILE`/`DSH_SESSION_ID` 等，无 `DSH_PROJECT_DIR`），故工作区归属靠安装器写入的静态 `CWIKI_WORKSPACE`。
- profile 为 `patchReload: live` 时保存即热重载，否则需重启 `dsh`。多 profile 时用 `--profile` 指定（默认取 `$DSH_PROFILE`，其次 `web`）。
- 安装器把 `cwiki-save` skill 落到 `<project>/.dsh/skills/`——dsh 只扫描 `<projectRoot>/.dsh/skills`、`.agents/skills` 等处，仓库内的 `skills/` 不在扫描范围。
- **技能管理（Web「技能管理」页 / `/v1/skills`）已把 dsh 列为一等发布目标**：`config.yaml` 的 `skills.agents` 默认含 `dsh: {skills_dir: ~/.dsh/skills}`，`GET /v1/skills/agents` 会返回它；发布即在 `~/.dsh/skills/<name>` 建指向 `<cwiki>/skills/<name>` 的目录 symlink（无 symlink 权限时回退带 `.cwiki-source.json` 标记的副本），dsh 的扫描器会解引用跟随该链接。
- dsh 的技能名校验比 cwiki 历史规则更严（`^[a-z0-9]+(?:-[a-z0-9]+)*$`）：前导/连续/尾随连字符会被 dsh 以 `invalid skill name` 静默忽略，因此 cwiki 创建/导入时即拒绝这类名字。

### 2.2 导入 Qoder 原生 Auto-Memory

Qoder 自己的 `~/.qoder/memories/**/task_summary_experience/*.md` 可以先导入 cwiki 的「待整理」，再人工整理为正式记忆；不会直接污染知识库。

```bash
# 先看将导入什么（默认 dry-run）
python tasks.py import-qoder-memory --since-days 30

# 确认后写入待整理
python tasks.py import-qoder-memory --since-days 30 --apply
```

导入保留 Markdown 全文与标题，按 `Related files` 推断项目 workspace；无关联文件的进入 `qoder-auto`，由人工整理。

Codex 当前以 MCP + `AGENTS.md` + `~/.codex/skills` 为主，不假设 hooks；无 hooks 时记忆仍可通过 `memory_search` / `memory_save` 使用。具体配置文件位置以各宿主官方文档为准。

## 3. HTTP API 直连

所有接口前缀 `/v1`，单用户本地部署无认证。以下是最小可用的三个动作：写入、检索、事件上报。完整端点见 [API 参考](api-reference.md)。

### 写入一条记忆（进入人工审核）

候选记忆提交后进入两阶段提交流水线，人工审核通过才成为正式记忆：

```bash
curl -X POST http://127.0.0.1:5172/v1/candidates \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "default",
    "title": "示例记忆标题",
    "content": "完整的记忆正文，语义原样保存。",
    "type": "fact",
    "source": "api",
    "client_write_id": "my-unique-id-001"
  }'
```

- `workspace_id` / `title` / `content` / `type` 必填；`workspace_id` 支持工作区名称或 UUID
- `client_write_id` 可选：同一 id 幂等，重复提交不会产生重复候选
- 响应 `201`，含创建的候选、提交时发现的相似记忆（`similar_items`）与建议（`hint`）
- 审核端点为 `POST /v1/reviews`（approve / edit / reject / merge）

### 检索

```bash
curl -X POST http://127.0.0.1:5172/v1/search \
  -H "Content-Type: application/json" \
  -d '{"keyword": "部署步骤", "limit": 10}'
```

- `keyword` 必填；`workspace_id` 可选（名称或 UUID），省略则跨全部工作区检索
- 混合检索 + 上下文组装用 `POST /v1/context`

### 上报 Agent 事件

事件经脱敏后入库，供后续 `memory_checkpoint` 提取候选。注意 `agent` / `session` / `workspace` 必须是 **UUID**：

```bash
curl -X POST http://127.0.0.1:5172/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "agent": "<agent-uuid>",
    "session": "<session-uuid>",
    "workspace": "<workspace-uuid>",
    "event_type": "prompt.submitted",
    "sequence": 0,
    "timestamp": "2026-10-16T00:00:00Z",
    "payload": {}
  }'
```

批量上报用 `POST /v1/events/batch`，body 为 `{"events": [...]}`（1–50 条），同样按 `sequence` 幂等。

---

## 4. 兼容性验证清单

接入后按序验证，全部通过才算接入成功：

1. **后端健康**：`curl http://127.0.0.1:5172/v1/health` 返回 `{"status": "healthy", "database": "ok"}`
2. **MCP 工具注册**（仅 MCP 接入）：宿主中 `tools/list` 返回 19 个 `memory_*` 工具（`memory_search`、`memory_save`、`memory_status`、`memory_types`、`memory_history`、`memory_relations`、`memory_relation_create`、`memory_relation_delete`、`memory_update`、`memory_feedback`、`memory_forget`、`memory_retry_failed`、`memory_checkpoint`、`memory_export`、`memory_import`、`memory_review_due`、`memory_review_submit`、`memory_review_stats`、`memory_tags`）
3. **工作区连通**：调用 `memory_status`，应返回工作区统计与 outbox 积压信息
4. **写入链路**：用 `memory_save`（或 `POST /v1/candidates`）提交一条标注「接入测试」的记忆，然后到 Web 控制台 `http://localhost:5173` 的**待审**页确认候选已出现，审核通过后到**记忆库**页确认可见

> 安装成功不代表运行中的宿主已加载新契约，验证以宿主实际返回为准（`setup.py --check` 返回 `host_verified: false` 也属正常）。重载细节见[开发指南](development.md#重载与验证)。

---

## 5. 故障排查指南

按症状定位，规则式排查、无需人工判断：

### 5.1 MCP 工具全部 Connection failed

先查后端，再查适配器：

```bash
# macOS / Linux：确认 5172 是否在监听
lsof -nP -iTCP:5172 -sTCP:LISTEN

# Windows：等价检查
netstat -ano | findstr :5172
```

- **无输出（未监听）** → 后端没起。启动：`python tasks.py serve`（或 `python tasks.py restart-serve` 强制重启）。多数 Connection failed 都是这一种
- **有监听仍失败** → 查适配器配置：
  - `.mcp.json` 是否缺 `cwd` 字段（见第 2 节，缺 cwd 会导致宿主重启后间歇性连接失败，Windows 尤其）
  - 在 Qoder 中重连 cwiki MCP（或 `manage_mcp` 的 retry 动作重拉适配器）后重试
  - `python -m adapters.qoder.mcp_server` 手动运行，看是否有报错输出

### 5.2 工具列表缺工具（tool not found）

- 开启新会话刷新工具注册表
- 在宿主中执行 MCP 重连 / `manage_mcp retry` 重新拉取适配器
- 安装或更新本地插件后，仅开新会话不够——插件 MCP 服务器列表在宿主启动时确定，需**完全重启 Qoder**

### 5.3 memory_save 返回 `cached: true`

服务当时不可达，内容已在客户端本地暂存，**没有丢**：

- 服务恢复后调用 `memory_retry_failed` 重试投递
- 状态为 `rejected` 的写入不会自动重试，需修正内容后重新提交
- 长期无法连接时，排查思路同 5.1

### 5.4 检索为空或结果不准

- 检查索引文件是否存在：`cwiki-data/vectors.npz` 与 `cwiki-data/index.db`。缺失时只重建索引（无需重新 embedding）：
  ```bash
  python tasks.py rebuild-db --index-only
  ```
- 用一致性对账端点查四方（DB / Markdown / BM25 索引 / 向量索引）计数与孤儿 id：
  ```bash
  curl http://127.0.0.1:5172/v1/consistency
  ```
- 报告中的漂移需人工处理（该端点只读，不做自动修复）；MD 与 `_meta` 之间的不一致可用 `python tasks.py rebuild-db` 从文件层重建

### 5.5 后台任务积压或失败

```bash
# 队列只读快照：各状态计数、最老 pending/running 任务年龄、FAILED 死信明细
curl http://127.0.0.1:5172/v1/task-queue-status

# 先修复失败原因（如 embedding 服务异常），再手动重放死信
curl -X POST http://127.0.0.1:5172/v1/task-queue/retry \
  -H "Content-Type: application/json" \
  -d '{"task_id": "<task-uuid>"}'
```

- FAILED 任务永久保留（死信语义），不会被清理；任务不存在或非 FAILED 返回 `404`
- 重试会重置为 pending 并给新一轮重试预算，**先修原因再重试**，否则会再次失败

---

## 6. 安全边界

- **默认仅监听本机**：`config.yaml` 未配置时 `app.api_host` 默认 `127.0.0.1`，局域网与其他设备无法访问
- **CORS 默认本地源**：默认只允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`（Web 控制台同源）
- **无认证**：单用户本地部署，API 默认信任本地请求（见 `apps/api/auth.py`）。不要把端口暴露到公网或不可信网络
- **内容安全**：MCP 提交时自动检测 Prompt 注入等恶意内容
- **Android / 局域网设备联调**：需临时修改 `config.yaml`——`app.api_host` 改为 `0.0.0.0`，并把设备访问的 origin（如 `http://192.168.x.x:5173`）加入 `app.cors_origins`；**联调结束改回原值**，避免长期暴露。当前注释与默认值见 `config.yaml` 对应条目

---

## 相关文档

- [MCP 工具参考（adapters/qoder）](../adapters/qoder/README.md) — 19 个工具的完整参数契约
- [开发指南 · Agent 接入配置](development.md#agent-接入配置) — setup.py 全流程、更新与内容保护、重载与验证
- [API 参考](api-reference.md) — 20 个路由模块全量端点
- [记忆系统 · 写入契约](memory-system.md#写入契约) — memory_save / memory_checkpoint 的行为约定
- [Git 同步指南](git-sync.md) — 多设备数据同步与重建
