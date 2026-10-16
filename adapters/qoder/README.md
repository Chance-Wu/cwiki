# cwiki-qoder

Qoder plugin for cwiki - persistent memory infrastructure for AI agents.

## What it does

cwiki-qoder integrates cwiki into the Qoder agent lifecycle:

- **Local reminders** - SessionStart adds static context reminding the agent to consult cwiki as needed; it does not capture prompts, transcripts, tool calls or errors, and does not guarantee automatic saving
- **Human review** - Candidate memories submitted through MCP go through approval before becoming verified knowledge
- **MCP recall** - Verified memories can be retrieved when the API and MCP connection are available

## Installation

1. From the repository root, run the setup script:

```sh
python scripts/setup.py
```

This installs the local plugin via `qodercli plugins install` (auto-run when the plugin cache is missing), refreshes cached plugin content (skills, commands, manifest) from source, patches the cached `.mcp.json` and `hooks/hooks.json` with the current venv python and project root, enables `cwiki-qoder@local` in `~/.qoder/settings.json` (so hooks take effect, cleaning stale bare/marketplace keys), injects a fallback cwiki entry into the global `~/.qoder/mcp.json`, syncs `AGENTS.md` and installs the `cwiki-save` skill. Hooks and MCP both use `python -m` module mode with `PYTHONPATH` pointing to the project root, avoiding `pip install -e .` generated executables that can be damaged by file encryption software.

The plugin workflow requires the Qoder CLI (`brew install qoderai/qoder/qodercli` or `npm install -g @qoder-ai/qodercli`). Without it, setup warns and the plugin MCP/hooks stay inactive, while the global `mcp.json` fallback still provides MCP. Restart Qoder after installation: plugin configs (MCP servers and hooks) are only read at host startup, and failed state is cached until restart.

Alternatively, manually load `adapters/qoder` using Qoder's plugin workflow. `hooks/hooks.json` is the repository's plugin distribution configuration, not an installed global setting. Install/load `cwiki-save` separately and verify the host actually loaded the current skill, plugin and MCP tool schemas; reload/reconnect or start a new session as needed.

2. For MCP tools, start the API in a separate terminal from the repository root:

```sh
python tasks.py serve
```

The reminder hook itself needs neither the API nor a network connection.

## Reminder hook protocol

The hook follows the [official Qoder CLI hooks protocol](https://docs.qoder.com/cli/hooks). It reads one UTF-8 JSON object from stdin, limited to 1 MiB. Common fields are `session_id`, `transcript_path`, `cwd` and `hook_event_name`; SessionStart can also supply `source`/`model`.

Only `hook_event_name` is used to validate the command/event pair. Other fields are ignored: no prompt echo, transcript reads, network requests, application file writes or stdin interpolation into context. The CLI emits ASCII-safe JSON with `hookSpecificOutput.hookEventName` and a static `hookSpecificOutput.additionalContext`, then exits 0. Empty/invalid JSON, non-object input, duplicate keys, oversized input and mismatched events produce only a short sanitized stderr diagnostic and exit 0 (fail-open), never exit 2 to block a user.

| Command | Required `hook_event_name` | Reminder |
|---|---|---|
| `python -m adapters.qoder.hooks session-start` | `SessionStart` | 会话开始或话题切换时检索相关记忆；出现用户纠正、调试转折、技术决策等信号时提交 |

To test the reminder manually, run from the repository root with JSON on stdin:

```sh
python -B -m adapters.qoder.hooks session-start
```

`-B` disables Python bytecode cache writes. The command accepts `{"hook_event_name":"SessionStart"}`. This command only tests the reminder; it does not register hooks with Qoder. Reminder execution is not evidence of transcript/event collection, completed extraction or successful memory delivery; those remain separate agent/MCP operations.

## Configuration

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

## MCP tools

14 tools:

| Tool | Description |
|---|---|
| `memory_search` | Search memories or retrieve curated context |
| `memory_save` | Submit a memory candidate for human review |
| `memory_status` | Show workspace statistics and outbox backlog |
| `memory_types` | View available memory types |
| `memory_history` | View lifecycle events or content version history |
| `memory_relations` | Query memory relationships |
| `memory_update` | Update an existing memory |
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
- Tool schemas are strict (`additionalProperties: false`): unknown parameter names are rejected. The workspace parameter is `workspace_name` (name or UUID), supported by `memory_search`, `memory_save`, `memory_checkpoint`, `memory_status`, `memory_export`, `memory_import`, `memory_review_due`, `memory_review_submit` and `memory_review_stats`; `memory_update`, `memory_types`, `memory_relations`, `memory_history` and `memory_retry_failed` take no workspace parameter.

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
  |   python -m adapters.qoder.hooks -> static additionalContext -> Qoder Agent
  |                                      (no collection or API calls)
  |
  |-- MCP (stdio)
        |
        v
      python -m adapters.qoder.mcp_server -> cwiki API (port 5172)
                                              /v1/context, /v1/search, /v1/candidates
```
