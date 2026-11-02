# apps/worker — 后台任务

后台任务的实现与注册。任务由 `packages/domain/task_queue.py` 的磁盘持久化队列调度，API 进程的 lifespan 会启动队列；任务失败按退避重试，耗尽后保留为死信。

## 任务模块（`tasks/`）

| 模块 | 任务 | 说明 |
|------|------|------|
| `episode.py` | `finalize_episode` | 会话结束把事件流加工成 episode，并提取 lesson 候选 |
| `candidate_review.py` | `score_candidate` | 候选价值评分与自动生效判定 |
| `embedding.py` | `generate_embedding`、`generate_candidate_embedding`、`batch_generate_embeddings` | 记忆/候选向量生成与批量补齐（DB 列与 `vectors.npz` 双写） |
| `dedup_check.py` | `dedup_check` | 候选去重检查 |
| `maintenance.py` | `check_review_reminders`、`periodic_meta_export`、`auto_discover_relations`、`prune_stale_relations` | 复习提醒、`_meta` 周期导出、关系发现与过期关系清理 |

包根 `tasks/__init__.py` 重导出全部任务并提供 `register_tasks(queue)` 与 `recover_orphaned_candidates(queue)`（服务崩溃后补齐缺向量 / 缺评分的候选与记忆）。

## 辅助实现

- `episode_builder.py`：事件流 → episode 的构建逻辑
- `scoring.py`：候选质量评分与优先级分类
- `dedup.py`：候选去重流水线
- `run_worker.py`：手动批处理脚本，为未生成 episode 的会话补建 episode（并发上限 4）

## 运行

```bash
python tasks.py worker   # 等价于 python -m apps.worker.run_worker
```

日常无需单独启动：`python tasks.py serve` / `start` 启动 API 时队列随之运行。

测试见 `tests/worker/`（评分快照、自动审核状态机、episode 回填等）。
