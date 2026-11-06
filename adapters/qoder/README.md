# cwiki-qoder

cwiki 的 Qoder 插件——为 AI Agent 提供持久记忆基础设施。

## 功能

cwiki-qoder 将 cwiki 集成进 Qoder 的 Agent 生命周期：

- **自动召回** — `UserPromptSubmit` 读取本地 SQLite 索引，注入一小段有界记忆上下文；仅在本地 DB 不可读时才调用 API
- **捕获** — `PostCompact` 保存宿主摘要，`PostToolUseFailure` 保存脱敏后的失败信息，`SessionEnd` 关闭 Agent 会话；瞬时的网络/DNS/超时错误与工具协议误用会在进入收件箱前被丢弃，构建/测试/业务失败则保留
- **人工审核** — 捕获的笔记整理为候选，经审批后成为已验证知识
- **本地优先读取** — `memory_search` 命中强本地 BM25 结果时直接返回，不调用 API；本地弱命中/空命中回落到混合检索，连接失败或 5xx 时降级回本地。`semantic` 始终 API 优先。仅写入必须依赖 API

## 安装

1. 在仓库根目录运行安装脚本：

```sh
python scripts/setup.py
```

脚本会通过 `qodercli plugins install` 安装本地插件（插件缓存缺失时自动执行），从源码刷新缓存的插件内容（skills、commands、manifest），用当前 venv 的 python 与项目根路径修补缓存中的 `.mcp.json` 和 `hooks/hooks.json`，在 `~/.qoder/settings.json` 中启用 `cwiki-qoder@local`（使 hooks 生效，并清理过时的裸键/市场键），向全局 `~/.qoder/mcp.json` 注入 cwiki 兜底条目，同步 `AGENTS.md` 并安装 `cwiki-save` skill。Hooks 与 MCP 均使用 `python -m` 模块方式，`PYTHONPATH` 指向项目根，避免 `pip install -e .` 生成的可执行文件被文件加密软件破坏。

该插件工作流依赖 Qoder CLI（`brew install qoderai/qoder/qodercli` 或 `npm install -g @qoder-ai/qodercli`）。缺少 CLI 时脚本会告警，插件 MCP/hooks 保持不生效，但全局 `mcp.json` 兜底仍可提供 MCP。安装后需重启 Qoder：插件配置（MCP 服务器与 hooks）只在宿主启动时读取，失败状态会缓存至重启。

也可以改用 Qoder 的插件工作流手动加载 `adapters/qoder`。`hooks/hooks.json` 由 `qoder` HostProfile 生成（有测试校验），并非已安装的全局设置；`setup.py` 会用绝对解释器路径重新生成缓存副本。`cwiki-save` 需单独安装/加载，并确认宿主确实加载了当前 skill、插件与 MCP 工具 schema；必要时重新加载/重连或新开会话。

2. 使用 MCP 工具时，在仓库根目录另开终端启动 API：

```sh
python tasks.py serve
```

Hooks 采用 fail-open：API 不可用时，捕获记录写入本地暂存（spool），在下次 session-start/session-end/drain 时投递。读取不依赖 API：搜索与召回使用 `cwiki-data/cwiki.db` 的只读 SQLite 索引（可用 `CWIKI_DB_PATH` 覆盖路径）。强本地 BM25 命中直接返回；弱命中回落到混合检索，API 连接失败时降级为纯关键词排序。

## Hook 协议

Hooks 使用 `adapters/hooks` 中的宿主无关运行时，遵循 [Qoder CLI hooks 协议](https://docs.qoder.com/cli/hooks)。每个命令从 stdin 读取一个 UTF-8 JSON 对象（≤1 MiB），校验原生 `hook_event_name`，即使输入非法也以 0 退出。宿主差异（原生事件名、项目环境变量、召回模式、捕获集合、上下文结构）在 `adapters/hooks/profiles.py` 中以每宿主一个 `HostProfile` 声明；新增宿主只需注册一个 profile。

| 命令 | 事件 | 行为 |
|---|---|---|
| `python -m adapters.hooks qoder session-start` | `SessionStart` | 提醒 + 必须保存提示 + always_inject 头部（本地 SQLite）+ 暂存投递 |
| `python -m adapters.hooks qoder user-prompt-submit` | `UserPromptSubmit` | 本地召回（≤3 条记忆、≤1200 字符、不留痕）：优先 SQLite BM25，回落 API 语义检索 |
| `python -m adapters.hooks qoder pre-tool-use` | `PreToolUse`（匹配 `mcp_call\|mcp__.*`） | 确定性 workspace 归属：通过 `updatedInput` 从调用所在会话的 `cwd` 注入 `workspace_name`（不覆盖显式参数；不作用于 `memory_search`） |
| `python -m adapters.hooks qoder post-compact` | `PostCompact` | 将 `compact_summary` 存为完整捕获笔记 |
| `python -m adapters.hooks qoder post-tool-failure` | `PostToolUseFailure` | 保存脱敏后的失败信息（跳过用户中断） |
| `python -m adapters.hooks qoder session-end` | `SessionEnd` | 关闭会话，投递暂存 |
| `python -m adapters.hooks qoder drain` | 手动 | 将暂存刷入 `/v1/integrations/agent/capture` |

默认不读取对话记录；prompt 仅用于本地检索，不写入日志或检索追踪。`adapters/qoder/hooks.py` 保留为旧安装配置的兼容垫片；新安装使用 `adapters/hooks`。

## 配置

`config.yaml` 的 `agent_policy` 控制 Agent 侧策略：

```yaml
agent_policy:
  always_inject:   # SessionStart 常驻注入（本地 DB，不依赖 API）
    enabled: true
    types: [feedback, rule]
    tags: [pinned]
    include_permanent: true
    max_items: 8
    max_chars: 1200
  write_decisions: # 结构化写入决策：SessionStart 注入 + memory_save 服务端复核
    enabled: true
    default_action: write
    rules:
      - id: must-save-signals
        action: write
        description: 用户纠正、明确偏好、强制规则必须记录
        examples: ["不要这样做，改用 X"]
        match:
          type: [feedback, rule]
          keyword: ["以后", "不要再", "必须", "约定"]
```

写入决策（`write/skip/update`，优先级 skip > update > write）决定“是否写入/更新”；写入后的自动生效/人工审核/拒绝由 `memory.write_policy` 管理；命中结果随候选持久化，并在 `memory_save` 响应中以 `policy` / `decision` 字段回显。把一条记忆设为常驻：`memory_update(memory_id=..., is_permanent=true, permanent_reason="...")`。

环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PYTHONPATH` | 项目根目录 | 由 hooks/MCP 配置设置，使 `python -m` 无需 `pip install -e .` 即可找到项目模块 |
| `CWIKI_API_URL` | `http://127.0.0.1:5172` | cwiki API 基础地址（避免 Windows 下 localhost→`::1` 解析延迟） |
| `CWIKI_WORKSPACE` | `default` | 默认 workspace 名称或 UUID |
| `CWIKI_TIMEOUT` | `10.0` | API 请求超时（秒） |

## 可用命令

| 命令 | 说明 |
|---|---|
| `/memory-status` | 查看 cwiki 集成状态与统计 |
| `/memory-search <query>` | 搜索相关记忆 |
| `/memory-review` | 审核待处理的候选记忆 |
| `/memory-pin` | 将记忆标记为永久，会话开始时注入 |

## MCP 工具

共 21 个工具：

| 工具 | 说明 |
|---|---|
| `memory_search` | 搜索记忆或获取精选上下文 |
| `memory_save` | 提交记忆候选等待人工审核（可选标签） |
| `memory_status` | 查看 workspace 统计与 outbox 积压 |
| `memory_tags` | 列出标签及使用次数，或按标签过滤记忆（AND 逻辑） |
| `memory_types` | 查看可用记忆类型 |
| `memory_history` | 查看生命周期事件或内容版本历史 |
| `memory_relations` | 查询记忆关系 |
| `memory_relation_create` | 创建两条记忆之间的关系 |
| `memory_relation_delete` | 删除记忆关系 |
| `memory_update` | 更新已有记忆（支持标签） |
| `memory_feedback` | 标记记忆为有用/无用/过时/错误 |
| `memory_forget` | 物理删除错误或不需要的记忆（不可恢复） |
| `memory_retry_failed` | 重试失败的记忆写入 |
| `memory_checkpoint` | 从已采集的事件/笔记中提取候选 |
| `memory_export` | 导出 workspace 数据 |
| `memory_import` | 导入 workspace 数据 |
| `memory_review_due` | 获取到期需复习的记忆 |
| `memory_review_submit` | 提交复习质量评分 |
| `memory_review_stats` | 获取复习统计与趋势 |
| `memory_conflicts` | 列出记忆冲突（open/resolved/all） |
| `memory_conflict_resolve` | 记录冲突裁决并关闭冲突（不改正文） |

- `memory_search` 默认 `curated=false`；仅该模式使用 `mode`（默认 `hybrid`，或 `semantic`）与 `filters`（`type` 指定记忆类型，`min_confidence` 指定最低置信度 0.0–1.0）。`limit` 默认 10（1–100）；普通搜索沿用后端上限范围。省略 `workspace_name` 时跨全部 workspace 搜索；传入则限定单个 workspace。
- `curated=true` 时返回原始 `get_context` 结果，包含 `context`、`items` 与可选的 `_hints`。`limit` 取代 `max_items`，取值 1–50；`max_tokens` 为 100–20000（默认 5000），可选的 `project` 上下文过滤器保留。`max_tokens` 与 `project` 仅作用于 curated 上下文。Curated 上下文始终按 workspace 组装：省略 `workspace_name` 时回落到默认 workspace。
- `memory_history` 默认 `view="lifecycle"`；`view="content"` 返回已存储的内容版本历史，而非当前记忆正文。其 `limit` 为 1–50（默认 10），仅作用于 content 视图。
- 工具 schema 严格（`additionalProperties: false`）：未知参数名会被拒绝。workspace 参数为 `workspace_name`（名称或 UUID），由 `memory_search`、`memory_save`、`memory_checkpoint`、`memory_status`、`memory_tags`、`memory_export`、`memory_import`、`memory_review_due`、`memory_review_submit` 与 `memory_review_stats` 支持；`memory_update`、`memory_types`、`memory_relations`、`memory_relation_create`、`memory_relation_delete`、`memory_history` 与 `memory_retry_failed` 不接受 workspace 参数；`memory_conflicts` 与 `memory_conflict_resolve` 为全局工具、不接受 workspace 参数；`memory_feedback` 接受 `workspace_name` 限定范围；`memory_forget` 按全局唯一 `memory_id` 删除，`workspace_name` 仅作兼容字段。

后端 API 仍然可用。提取策略仍由 `cwiki-save` 负责；提醒类 hooks 不提供检查点事件/笔记。

## Skills

| Skill | 说明 |
|---|---|
| `memory-recall` | 引导 Agent 在开工前先查询 cwiki |

## 架构

```
Qoder Agent
  |
  |-- hooks (SessionStart / UserPromptSubmit / PreToolUse / PostCompact / PostToolUseFailure / SessionEnd)
  |     |
  |     v
  |   python -m adapters.hooks -> additionalContext + 暂存捕获 -> Qoder Agent
  |
  |-- MCP (stdio)
        |
        v
      python -m adapters.qoder.mcp_server
        |-- 读：local_index -> cwiki-data/cwiki.db (mode=ro, BM25)
        |        强命中 -> 直接返回；弱命中 -> API 混合检索
        |-- 写：cwiki API（端口 5172）/v1/candidates
```
