# packages/memory — 记忆业务

记忆生命周期中的业务规则：候选复核、质量与价值评估、去重、健康、复习、关系与演化。数据持久化由 `packages/storage` 负责，异步任务编排在 `apps/worker`。

## 模块

| 模块 | 职责 |
|------|------|
| `service.py` | 记忆服务：候选复核、创建/更新/合并等核心业务逻辑 |
| `merge.py` | 正式记忆合并：标签取并集、关系与证据改挂到目标，保留历史而非物理删除 |
| `evidence.py` | 证据挂接：候选转正/合并/更新时迁移证据并写入 provenance 记录 |
| `quality_gate.py` | 候选质量门控（5 维），决定审核优先级 |
| `utility_score.py` | 记忆效用分计算（多因子） |
| `utility_aggregation.py` | 效用信号批量聚合，供检索引擎与列表 API 共用 |
| `health.py` | 记忆健康度与健康状态 |
| `lifecycle.py` | 生命周期状态转换校验 |
| `duplicate_detection.py` | 重复检测（标题 / 正文 / 关键词 / 向量多信号） |
| `duplicate_scan.py` | 库内全库两两查重（与写入时候选查重互补），只产出判定不改动记忆 |
| `similarity.py` | 共享文本相似度计算 |
| `type_classifier.py` | 基于关键词的轻量记忆类型推断 |
| `entity_extractor.py` | jieba 词性标注 + 正则的实体抽取 |
| `content_security.py` | Prompt 注入等内容安全检测 |
| `conflict_detection.py` | 写入时冲突检测：语义相近且文本矛盾时登记 `MemoryConflict` |
| `auto_relation.py` | 基于向量相似度自动建立记忆关系 |
| `wikilink.py` | 正文 `[[标题]]` 双链同步为 `related` 关系边（按当前正文幂等重建） |
| `reinforcement.py` | 关系的 Hebbian 强化与时间衰减 |
| `spaced_repetition.py` | SM-2 间隔重复算法 |
| `quiz.py` | 复习填空题：确定性出题与判分（与前端 cloze 规则一致） |
| `review_service.py` | 复习调度与掌握度更新 |
| `mastery.py` | 掌握度配置的共享辅助 |
| `evolution_metrics.py` | 演化可观测指标 |
| `memory_gap.py` | 记忆缺口检测 |
| `tag_query.py` | 标签 SQL 查询条件（JSON 数组元素精确匹配，支持中文） |

## 测试

- `tests/unit/memory/`：质量门控、去重、黄金集、健康、生命周期、SM-2、关系强化等
- `tests/unit/domain/test_review_service.py`、`tests/unit/domain/test_rule_match.py`
