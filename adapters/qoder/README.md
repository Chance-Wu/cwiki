# cwiki-qoder

Qoder plugin for cwiki - persistent memory infrastructure for AI agents.

## What it does

cwiki-qoder integrates cwiki into the Qoder agent lifecycle:

- **Auto recall** - `UserPromptSubmit` reads the local SQLite index and injects a small, bounded memory context; it only calls the API when the local DB is unreadable
- **Capture** - `PostCompact` stores the host summary, `PostToolUseFailure` stores redacted failures, and `SessionEnd` closes the agent session; transient network/DNS/timeout errors and tool-protocol misuse are dropped before entering the inbox, while build/test/business failures are kept
- **Human review** - Captured notes are organized into candidates and go through approval before becoming verified knowledge
- **Local-first reads** - `memory_search` returns a strong local BM25 hit without calling the API; weak/empty local hits fall through to hybrid retrieval, and connection failures or 5xx degrade back to local. `semantic` stays API-first. Only writes always require the API

## Installation

1. From the repository root, run the setup script:

```sh
python scripts/setup.py
```

This installs the local plugin via `qodercli plugins install` (auto-run when the plugin cache is missing), refreshes cached plugin content (skills, commands, manifest) from source, patches the cached `.mcp.json` and `hooks/hooks.json` with the current venv python and project root, enables `cwiki-qoder@local` in `~/.qoder/settings.json` (so hooks take effect, cleaning stale bare/marketplace keys), injects a fallback cwiki entry into the global `~/.qoder/mcp.json`, syncs `AGENTS.md` and installs the `cwiki-save` skill. Hooks and MCP both use `python -m` module mode with `PYTHONPATH` pointing to the project root, avoiding `pip install -e .` generated executables that can be damaged by file encryption software.

The plugin workflow requires the Qoder CLI (`brew install qoderai/qoder/qodercli` or `npm install -g @qoder-ai/qodercli`). Without it, setup warns and the plugin MCP/hooks stay inactive, while the global `mcp.json` fallback still provides MCP. Restart Qoder after installation: plugin configs (MCP servers and hooks) are only read at host startup, and failed state is cached until restart.

Alternatively, manually load `adapters/qoder` using Qoder's plugin workflow. `hooks/hooks.json` is generated from the `qoder` HostProfile (checked by tests), not an installed global setting; `setup.py` regenerates the cache copy with absolute interpreter paths. Install/load `cwiki-save` separately and verify the host actually loaded the current skill, plugin and MCP tool schemas; reload/reconnect or start a new session as needed.

2. For MCP tools, start the API in a separate terminal from the repository root:

```sh
python tasks.py serve
```

Hooks are fail-open: when the API is unavailable, capture records are written to a local spool and delivered on the next session-start/session-end/drain. Reads do not depend on the API: search and recall use a read-only SQLite index at `cwiki-data/cwiki.db` (`CWIKI_DB_PATH` overrides the path). A strong local BM25 hit is returned directly; weak hits fall through to hybrid retrieval, and API connection failures degrade to keyword-only ranking.

## Hook protocol

Hooks use the host-neutral runtime in `adapters/hooks` and follow the [Qoder CLI hooks protocol](https://docs.qoder.com/cli/hooks). Each command reads one UTF-8 JSON object from stdin (≤1 MiB), validates the native `hook_event_name`, and exits 0 even on invalid input. Host differences (native event names, project env vars, recall mode, capture set, context shape) are declared in one `HostProfile` per host in `adapters/hooks/profiles.py`; adding a host means registering a single profile.

| Command | Event | Behavior |
|---|---|---|
| `python -m adapters.hooks qoder session-start` | `SessionStart` | Reminder + must-save hint + always_inject head (local SQLite) + spool drain |
| `python -m adapters.hooks qoder user-prompt-submit` | `UserPromptSubmit` | Local recall (≤3 memories, ≤1200 chars, no trace): SQLite BM25 first, API semantic fallback |
| `python -m adapters.hooks qoder pre-tool-use` | `PreToolUse` (matcher `mcp_call\|mcp__.*`) | Deterministic workspace attribution: inject `workspace_name` from the call's session `cwd` via `updatedInput` (never overrides explicit params; not applied to `memory_search`) |
| `python -m adapters.hooks qoder post-compact` | `PostCompact` | Store `compact_summary` as a full capture note |
| `python -m adapters.hooks qoder post-tool-failure` | `PostToolUseFailure` | Store redacted failure (skip user interrupts) |
| `python -m adapters.hooks qoder session-end` | `SessionEnd` | Close session, drain spool |
| `python -m adapters.hooks qoder drain` | manual | Flush spool to `/v1/integrations/agent/capture` |

No transcript is read by default; prompts are used only for local retrieval and are not written to logs or retrieval traces. `adapters/qoder/hooks.py` remains as a compatibility shim for older installed configs; new installs use `adapters/hooks`.

## Configuration

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

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `PYTHONPATH` | Project root | Set by hooks/MCP config so `python -m` can find project modules without `pip install -e .` |
| `CWIKI_API_URL` | `http://127.0.0.1:5172` | cwiki API base URL（避免 Windows 下 localhost→`::1` 解析延迟） |
| `CWIKI_WORKSPACE` | `default` | Default workspace name or UUID |
| `CWIKI_TIMEOUT` | `10.0` | API request timeout in seconds |

## Available commands

| Command | Description |
|---|---|
| `/memory-status` | Show cwiki integration status and stats |
| `/memory-search <query>` | Search for relevant memories |
| `/memory-review` | Review pending candidate memories |
| `/memory-pin` | Mark a memory as permanent so it is injected at session start |

## MCP tools

19 tools:

| Tool | Description |
|---|---|
| `memory_search` | Search memories or retrieve curated context |
| `memory_save` | Submit a memory candidate for human review (optional tags) |
| `memory_status` | Show workspace statistics and outbox backlog |
| `memory_tags` | List tags with usage counts, or filter memories by tags (AND logic) |
| `memory_types` | View available memory types |
| `memory_history` | View lifecycle events or content version history |
| `memory_relations` | Query memory relationships |
| `memory_relation_create` | Create a relationship between two memories |
| `memory_relation_delete` | Delete a memory relationship |
| `memory_update` | Update an existing memory (supports tags) |
| `memory_feedback` | Mark a memory useful/not_useful/outdated/wrong |
| `memory_forget` | Archive a wrong or unwanted memory (restorable) |
| `memory_retry_failed` | Retry failed memory writes |
| `memory_checkpoint` | Extract candidates from collected events/notes |
| `memory_export` | Export workspace data |
| `memory_import` | Import workspace data |
| `memory_review_due` | Get memories due for review |
| `memory_review_submit` | Submit review quality score |
| `memory_review_stats` | Get review statistics and trends |

- `memory_search` defaults to `curated=false`; only this mode uses `mode` (`hybrid` by default, or `semantic`) and `filters` (`type` for memory type, `min_confidence` for minimum confidence 0.0–1.0). `limit` defaults to 10 (1–100); regular search retains the backend limit range. Omitting `workspace_name` searches across all workspaces; pass it to scope recall to one workspace.
- With `curated=true`, search returns the original `get_context` result, including `context`, `items` and optional `_hints`. `limit` replaces `max_items` and accepts 1–50; `max_tokens` is 100–20000 (default 5000), and the optional `project` context filter is preserved. `max_tokens` and `project` apply only to curated context. Curated context is always assembled per workspace: an omitted `workspace_name` falls back to the default workspace.
- `memory_history` defaults to `view="lifecycle"`; `view="content"` returns stored content version history, not the current memory body. Its `limit` is 1–50 (default 10) and applies only to the content view.
- Tool schemas are strict (`additionalProperties: false`): unknown parameter names are rejected. The workspace parameter is `workspace_name` (name or UUID), supported by `memory_search`, `memory_save`, `memory_checkpoint`, `memory_status`, `memory_tags`, `memory_export`, `memory_import`, `memory_review_due`, `memory_review_submit` and `memory_review_stats`; `memory_update`, `memory_types`, `memory_relations`, `memory_relation_create`, `memory_relation_delete`, `memory_history` and `memory_retry_failed` take no workspace parameter; `memory_feedback` and `memory_forget` accept `workspace_name` for scoping.

Backend APIs remain available. Extraction strategy stays in `cwiki-save`; reminder hooks do not supply checkpoint events/notes.

## Skills

| Skill | Description |
|---|---|
| `memory-recall` | Guides the agent to consult cwiki before starting work |

## Architecture

```
Qoder Agent
  |
  |-- hooks (SessionStart only)
  |     |
  |     v
  |   python -m adapters.hooks -> static additionalContext -> Qoder Agent
  |                                      (no collection or API calls)
  |
  |-- MCP (stdio)
        |
        v
      python -m adapters.qoder.mcp_server
        |-- read:  local_index -> cwiki-data/cwiki.db (mode=ro, BM25)
        |          strong hit -> return; weak hit -> API hybrid
        |-- write: cwiki API (port 5172) /v1/candidates
```
