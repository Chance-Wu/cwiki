# packages/retrieval — 检索与上下文

混合检索与上下文组装。对外主入口是 `engine.py` 的 `get_retrieval_engine()`。

## 检索流水线

`engine.py` 串起完整管线：

1. 查询分析（`query/analyzer.py`）
2. 召回：BM25（`bm25.py`，自研实现，IDF 用 `log(1 + N/n)` 避免小语料负分）+ 向量（`embedding.py`，本地 ONNX / fastembed）
3. RRF 融合
4. 多信号重排（`ranking/reranker.py`）、时态处理（`ranking/temporal.py`）、多样性过滤（`ranking/diversity.py`）
5. 结果返回，附带可解释的过滤原因与检索追踪

`semantic` 模式只走向量召回，过滤与重排阶段保持一致。

## 上下文组装（`context/`）

| 模块 | 步骤 |
|------|------|
| `assembler.py` | 完整上下文流水线：去重 → 冲突检测 → 优先级排序 → 预算控制 → 压缩 |
| `dedup.py` | 移除重复记忆 |
| `conflict.py` | 标记相互矛盾的记忆 |
| `priority.py` | 按类型优先级排序，随查询意图调整 |
| `filters.py` | 候选三档过滤（none / demote / hard）：过期、低置信、低相关 |
| `compression.py` | L1–L5 上下文压缩 |
| `token_counter.py` | CJK 感知的 token 估算与预算约束 |

## 其他

- `embedding.py`：Embedding 服务（懒加载本地模型，失败降级为 hash 向量）
- `optimizer.py`：基于 LLM 的记忆优化服务
- `vector_utils.py`：向量相似度公共工具

## 参考

- 流程与权重：[docs/retrieval.md](../../docs/retrieval.md)
- 评测与回归：[benchmarks/README.md](../../benchmarks/README.md)
- 测试：`tests/unit/retrieval/`、`tests/unit/ranking/`
