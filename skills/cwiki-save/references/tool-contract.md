# cwiki 工具契约（19 个）

**所有工具 schema 均为 `additionalProperties: false`，传入未列出的键会被直接拒绝。**
工作区默认自动绑定 Agent 当前项目（宿主 hook 实时同步）；`workspace_name` 仅在明确要跨项目操作时才传。

## 用途分组

- 检索：`memory_search`（含 curated 上下文组装与 tags 过滤）
- 写入：`memory_save` / `memory_update` / `memory_feedback` / `memory_forget`
- 状态：`memory_status` / `memory_types` / `memory_tags`
- 检查点与恢复：`memory_checkpoint` / `memory_retry_failed`
- 关系与历史：`memory_relations` / `memory_relation_create` / `memory_relation_delete` / `memory_history`
- 复习：`memory_review_due` / `memory_review_submit` / `memory_review_stats`
- 运维：`memory_export` / `memory_import`

## 参数速查

| 工具 | 必填 | 可选 | 接收 workspace_name |
|------|------|------|:---:|
| `memory_search` | `keyword` 或 `query`（二选一） | `limit`(非 curated 1–100，curated 1–50，默认 10)、`mode`(hybrid/semantic)、`curated`、`max_tokens`(100–20000)、`project`、`filters`(`type`/`min_confidence`/`tags`，tags 为 AND) | ✓ |
| `memory_save` | `title`(≤80 字符)、`content`(≥20 字符) | `type`、`tags`、`is_permanent`、`permanent_reason` | ✓ |
| `memory_update` | `memory_id` | `content`、`title`、`tags`、`expected_version`、`confidence`、`importance`、`reason`、`is_permanent`、`permanent_reason` | ✗ |
| `memory_feedback` | `memory_id`、`feedback_type` | `reason` | ✓ |
| `memory_forget` | `memory_id` | `reason` | ✓ |
| `memory_history` | `memory_id` | `view`(lifecycle/content)、`limit`(1–50，仅 content 视图) | ✗ |
| `memory_relations` | `memory_id` | `depth`(1–3，默认 1) | ✗ |
| `memory_relation_create` | `memory_id`、`target_memory_id`、`relation_type` | `confidence`(0–1，默认 1.0) | ✗ |
| `memory_relation_delete` | `memory_id`、`relation_id` | — | ✗ |
| `memory_checkpoint` | `trigger_reason` | `dry_run`、`event_session_id` | ✓ |
| `memory_status` | — | — | ✓ |
| `memory_types` | — | `type`(过滤) | ✗ |
| `memory_tags` | — | `tags`(过滤，AND)、`limit`(1–100，默认 20) | ✓ |
| `memory_retry_failed` | —（无任何参数） | — | ✗ |
| `memory_review_due` | — | `limit`(1-100，默认 20) | ✓ |
| `memory_review_submit` | `memory_id`、`quality`(0-5) | — | ✓ |
| `memory_review_stats` | — | — | ✓ |
| `memory_export` | — | `entities` | ✓ |
| `memory_import` | `data` | `strategy`(skip/overwrite/rename) | ✓ |

## 常见调用形态

```text
memory_search(keyword="业务关键词", limit=5)                                  # 跨全部工作区搜索
memory_save(title="主题", content="完整正文…", type="lesson")                  # 自动写入当前项目
memory_update(memory_id="<id>", content="新正文…", reason="补充边界条件")
```

## 约定

- 标注 ✗ 的工具不接收工作区参数：`memory_id` 全局唯一，不需要工作区限定。
- `keyword` 与 `query` 等价，传其一即可。
- 省略 `workspace_name` 的 `memory_search` 跨全部工作区；`curated=true` 时回落默认工作区。
- `curated=true` 固定走上下文组装：忽略 `mode` 与 `filters`，`limit` 限 1–50，`project`/`max_tokens` 仅此时生效。
- `memory_checkpoint.trigger_reason` 枚举见 SKILL.md「检查点与结束前回顾」。
- `memory_relation_create.relation_type`：`related` / `supports` / `contradicts` / `supersedes` / `refines`。
- `memory_feedback.feedback_type`：`useful` / `not_useful` / `outdated` / `wrong`。
