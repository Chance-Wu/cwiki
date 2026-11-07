# packages/protocol — Agent 事件协议

定义 Agent 与 cwiki 之间的事件信封（Agent Event Protocol v1），供事件接入 API 与 hook 适配器共用。

## 内容

- `envelope.py`
  - `EventEnvelope`：事件信封类型（`protocol_version` / `event_id` / `event_type` / `agent` / `session` / `workspace` / `project` / `sequence` / `timestamp` / `payload` / `metadata`）
  - `redact_envelope_payload`：返回脱敏后的 payload 字典（不修改原信封）

事件经 `apps/api/routes/events.py` 的 `/v1/events` 接入，hook 侧在 `adapters/hooks/` 中构造同一协议的信封。

测试：`tests/api/test_events.py`、`tests/integration/` 下的接入用例。
