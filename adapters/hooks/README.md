# adapters/hooks — Hook 运行时

宿主无关的 hook 实现。每个命令从 stdin 读取一个 UTF-8 JSON 对象（≤1 MiB），校验原生 `hook_event_name`，即使输入非法也以 0 退出（fail-open）。

## 命令

```bash
python -m adapters.hooks <host> <command>
```

| 命令 | 对应事件 | 行为 |
|------|----------|------|
| `session-start` | `SessionStart` | 固定提醒 + 写入决策摘要 + always_inject 头部（本地 SQLite）+ spool 投递 |
| `user-prompt-submit` | `UserPromptSubmit` | 本地召回（≤3 条、≤1200 字符、不留痕），SQLite BM25 优先，回落 API |
| `pre-tool-use` | `PreToolUse` | 为 cwiki MCP 调用注入 `workspace_name`（来自会话 `cwd`，不覆盖显式参数） |
| `post-compact` | `PostCompact` | 把压缩摘要存为捕获笔记 |
| `post-tool-failure` | `PostToolUseFailure` | 保存脱敏后的失败信息（跳过用户中断） |
| `session-end` | `SessionEnd` | 关闭会话、投递 spool、写入决策收尾审计 |
| `drain` | 手动 | 将 spool 刷入 `/v1/integrations/agent/capture` |

## 模块

| 模块 | 职责 |
|------|------|
| `cli.py` | 命令入口：解析 stdin 事件并分发 |
| `profiles.py` | `HostProfile`：事件名、项目目录环境变量、召回模式、捕获集合、输出形状 |
| `envelope.py` | hook 事件归一化结构 |
| `recall.py` | 自动召回：本地检索 + 紧凑上下文注入 |
| `decisions.py` | SessionStart 写入决策注入与 SessionEnd 收尾审计 |
| `capture.py` | 捕获记录写入与 capture API 投递 |
| `spool.py` | 捕获的本地 spool（API 不可用时暂存） |
| `workspace_inject.py` | PreToolUse 的确定性 workspace 归属 |
| `workspace_registry.py` | hook → MCP 的当前工作区同步（按宿主隔离） |

## 环境变量

`CWIKI_API_URL`、`CWIKI_STATE_DIR`、`CWIKI_HOOK_STATE_DIR`、`CWIKI_HOOK_RECALL_CACHE`；写入决策观察窗口可用 `CWIKI_WRITE_WATCH_*` 覆盖。

默认不读取对话记录；prompt 仅用于本地检索，不写入日志或检索追踪。

测试：`tests/adapter/`（fail-open、捕获落盘、workspace 注入、host profile）与 `tests/integration/test_memory_hooks.py`。
