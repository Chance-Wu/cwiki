# packages/protocol — Agent 事件协议

定义 Agent 与 cwiki 之间的事件信封（Agent Event Protocol v1），供事件接入 API 与 hook 适配器共用。

## 内容

- `envelope.py`
  - `EventEnvelope`：事件信封类型（agent / session / workspace / event_type / sequence / timestamp / payload）
  - `redact_envelope_payload`：写入前对 payload 做脱敏

事件经 `apps/api/routes/events.py` 的 `/v1/events` 接入，hook 侧在 `adapters/hooks/` 中构造同一协议的信封。

测试：`tests/api/test_events.py`、`tests/integration/` 下的接入用例。
