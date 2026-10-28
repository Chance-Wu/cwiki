# cwiki Retrieval Benchmark

## 目录结构

```
benchmarks/
├── datasets/
│   ├── retrieval/              # 检索评测黄金数据集（按 workspace 分文件）
│   │   ├── gold.jsonl          # 默认数据集
│   │   └── eval-fixture.jsonl  # 合成夹具数据集（97 条记忆，CI 回归用）
│   └── context/
│       └── gold.jsonl          # 上下文组装评测数据集（26 查询，含负例与矛盾对）
├── evaluators/
│   ├── retrieval.py            # IR 指标计算
│   └── context.py              # 上下文组装四指标计算
├── fixtures/
│   └── generate_fixture.py     # 合成评测夹具生成器（固定种子，可逐字节复现）
├── failures/                   # 失败案例库（JSONL，修复后保留作回归参照）
├── performance/
│   └── perf_runner.py          # 大规模延迟基准（10K-1M 规模）
├── runners/
│   ├── retrieval_runner.py     # 检索 Pipeline 对比运行器
│   ├── context_runner.py       # 上下文组装运行器
│   └── compare_reports.py      # 基线门槛对比（CI 回归用）
├── reports/                    # 输出报告目录（baseline.json 为 CI 回归门槛）
└── README.md
```

## 评测指标

### 检索（retrieval_runner）

| 指标 | 说明 |
|------|------|
| Recall@K | Top-K 中命中的相关 Memory 占全部相关 Memory 的比例 |
| Precision@K | Top-K 中相关 Memory 的占比 |
| MRR | 第一个相关结果的排名倒数 |
| NDCG@10 | 考虑等级排序的归一化折损累积增益 |
| Useful@10 | Top-10 中 relevance >= 2 的 Memory 占比 |

相关性等级：0 = 不相关，1 = 弱相关，2 = 相关，3 = 直接有用。

### 上下文组装（context_runner）

| 指标 | 说明 |
|------|------|
| Selection Recall | 期望入选的记忆被成功选中的比例 |
| Negative Exclusion | 期望排除的负例（跨主题干扰/过时/重复）被成功排除的比例 |
| Budget Compliance | 组装结果不超 token 预算的比例 |
| Conflict Warning Recall | 期望告警的矛盾对被成功检出的比例 |

## Pipeline 对比

| Pipeline | 说明 |
|----------|------|
| baseline_bm25 | 纯 BM25 关键词检索 |
| baseline_vector | 纯向量余弦相似度 |
| hybrid_rrf | BM25 + Vector → RRF 融合 |
| hybrid_rrf_rerank | RRF + 多信号 Rerank |
| full_pipeline | RRF + Rerank + Diversity |

## 运行

```bash
# 运行全部 pipeline（默认数据集，主库全部 workspace）
python -m benchmarks.runners.retrieval_runner

# 合成夹具上运行（CI 回归同款，先重新生成夹具保证可复现）
python -m benchmarks.fixtures.generate_fixture
python -m benchmarks.runners.retrieval_runner \
  --db-url sqlite+aiosqlite:///benchmarks/fixtures/eval_fixture.db \
  --workspace-name eval-fixture

# 运行单个 pipeline / 指定数据集
python -m benchmarks.runners.retrieval_runner --pipeline hybrid_rrf
python -m benchmarks.runners.retrieval_runner --dataset path/to/gold.jsonl

# 上下文组装评测（直连组装器，验证选择/排除/预算/冲突四指标）
python -m benchmarks.runners.context_runner

# 性能基准（10K 规模 100 查询）
python -m benchmarks.performance.perf_runner --scale 10000 --queries 100
```

### 真实查询导出（人工标注）

把运行期 `retrieval_trace` 中的真实查询聚合后，连同 BM25 + 向量双路候选池导出，
供人工标注相关性：

```bash
# 单个 workspace
python scripts/export_eval_queries.py --workspace cwiki \
  --output benchmarks/labeling/cwiki.jsonl

# 全部 workspace（固定写入 benchmarks/labeling/，不随当前目录漂移）
python scripts/export_eval_queries.py --all-workspaces
```

标注完成后按 `query_id/query/memory_id/relevance` 回填到
`datasets/retrieval/{workspace}.jsonl`。`benchmarks/labeling/` 为本地中间产物，不入库。

## 基线回归（CI 门槛）

`benchmarks/reports/baseline.json` 记录各管线在 eval-fixture 夹具上的门槛值（容差 3%）。
对比器逐指标检查，任一指标下降超容差退出码 1：

```bash
python -m benchmarks.runners.compare_reports --current benchmarks/reports/eval-fixture
```

CI 的 `benchmark` job（.github/workflows/ci.yml）每次推送自动执行：固定种子重新生成夹具 → 跑 5 条管线 → 对比门槛 → 上传报告 artifact。指标回退时 job 变红。

W3 回归报告（rerank 归一化修复与相关性下限过滤的定值依据）：[reports/w3-regression-report.md](reports/w3-regression-report.md)。

## 目标

```
Recall@10 >= 0.80
Useful@10 >= 0.60
p95 retrieval < 700ms（10K 规模 SLA；实测全管线 p95 约 4ms）
```

## 数据集格式

`datasets/retrieval/*.jsonl` 每行一条评判：

```json
{
  "query_id": "q001",
  "query": "database connection pooling configuration",
  "memory_id": "uuid-of-memory",
  "relevance": 3
}
```

同一 `query_id` 可有多条不同 `memory_id` 的评判。

`datasets/context/gold.jsonl` 每行一条组装场景（查询 + 候选池定义 + 期望入选/排除 + 期望矛盾对），
池中条目可内联 `content` 合成重复/矛盾/干扰样本，或引用夹具 DB 的记忆 id。

## 重复检测黄金集

```
python -m benchmarks.runners.duplicate_runner             # 词面通道（确定性，CI 门槛）
python -m benchmarks.runners.duplicate_runner --semantic  # embedding 语义通道（改写句）
```

- `datasets/duplicates/gold.jsonl`：24 对近原文重复/同领域不同事实，正类 = exact 或 possible；
  词面通道回归门槛见 `reports/duplicate_baseline.json`，由 `tests/unit/memory/test_duplicate_golden.py`
  以 3% 容差守护。
- `datasets/duplicates/gold_semantic.jsonl`：9 对改写/同义表达，需本地 embedding 模型可用；
  运行结果写入 `reports/duplicate-semantic-report.json`，不做 CI 门槛（依赖模型版本）。
