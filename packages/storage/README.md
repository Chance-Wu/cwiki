# packages/storage — 文件与索引存储

三层存储的实现：Markdown（人类可读）、`_meta/` JSON（反馈/用途/复习等侧车数据）、SQLite 索引与 numpy 向量索引。SQLite 与索引均可从 Markdown + `_meta` 重建。

## 模块

| 模块 | 职责 |
|------|------|
| `config.py` | 文件存储配置（`memory_dir`、索引路径、向量文件等），从 `config.yaml` 加载 |
| `file_store.py` | Markdown 记忆文件读写，YAML frontmatter，损坏/空文件显式告警 |
| `meta_store.py` | `MetaStore`：按 memory_id 存取的 `_meta/{id}.json` 关系数据与工作区元数据 |
| `meta_export.py` | `_meta` 导出的共享实现（单条增量重写、工作区快照） |
| `export_state.py` | 最近一次全量导出的时间戳，供周期任务重启后追赶 |
| `indexer.py` | 异步索引器：Markdown → SQLite 全文索引与向量索引同步 |
| `md_sync.py` | Markdown → DB 单条同步：手改 MD 后把正文/标题/类型/标签/状态写回主库 |
| `index_health.py` | 派生索引健康检查（向量文件配对、维度/模型、index.db 覆盖），供 doctor 与 rebuild-db 复用 |
| `vector_index.py` | 基于 numpy 的向量索引（`vectors.npz` + `vectors.json`） |
| `rebuilder.py` | `DatabaseRebuilder`：从 Markdown + `_meta` 重建 `cwiki.db`，恢复候选、审核留痕、版本与复习史 |
| `consistency.py` | 运行时只读对账：DB / Markdown / index.db / vectors 四份载体比对 |
| `review_prefs.py` | 复习偏好存取（`_meta/_review_prefs.json`，随数据仓库跨设备同步） |
| `git_version.py` | 记忆文件的 Git 版本集成 |

## 数据目录

默认 `cwiki-data/`（由 `config.yaml` 的 `storage.memory_dir` 决定）：

```
cwiki-data/
├── {workspace}/{type}/{id前8位}_{标题}.md
├── _meta/{memory_id}.json
├── _meta/_workspaces.json
├── _meta/_review_prefs.json
├── cwiki.db
├── index.db
└── vectors.npz / vectors.json
```

## 相关命令

```bash
python tasks.py rebuild-db   # 从 MD + _meta 重建数据库（索引可跳过重建）
python tasks.py recompute    # 重算派生字段
python tasks.py doctor       # 四层一致性巡检
python scripts/verify_rebuild.py
```

测试：`tests/unit/storage/`、`tests/integration/test_check_integrity.py`。
