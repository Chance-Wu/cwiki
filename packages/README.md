# packages 领域与能力层

不依赖 `apps/` 的核心实现。`apps/api`、`apps/worker` 与 `adapters/` 都复用这里的领域模型、记忆业务与检索/存储能力。

| 包 | 职责 | 关键入口 |
|----|------|----------|
| [domain](domain/README.md) | ORM 模型、Pydantic schema、配置、数据库、任务队列、写入决策/策略、通用工具 | `packages.domain.config`、`packages.domain.models`、`packages.domain.task_queue` |
| [memory](memory/README.md) | 记忆业务：候选复核、质量门控、评分、去重、健康、复习、关系、演化指标 | `packages.memory.service` |
| [retrieval](retrieval/README.md) | 混合检索与上下文组装：BM25、向量、RRF、重排、多样性、压缩 | `packages.retrieval.engine` |
| [storage](storage/README.md) | Markdown / `_meta` / 索引 / 向量文件存储与重建、一致性对账 | `packages.storage.file_store`、`indexer`、`rebuilder` |
| [protocol](protocol/README.md) | Agent Event Protocol v1 事件信封与脱敏 | `packages.protocol.envelope` |

约定：

- 依赖方向保持 `apps → packages`；`packages` 内以 `domain` 为公共基础，避免跨包循环依赖
- 配置统一来自 `config.yaml`（`packages/domain/config.py`、`packages/storage/config.py`），不引入环境变量配置
- 版本号唯一来源是 `pyproject.toml`，代码统一调用 `packages.domain.version.app_version()`
