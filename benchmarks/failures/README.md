# 检索失败案例库

收集检索效果不佳的真实案例，作为优化迭代的驱动输入。每条案例一个 JSONL 行，
放在本目录（`benchmarks/failures/`），命名按 workspace 分文件（如 `cwiki.jsonl`）。

## 字段说明

```json
{
  "case_id": "cwiki-2026-001",
  "query": "实际查询文本",
  "workspace": "cwiki",
  "pipeline": "full_pipeline",
  "expected_memory_id": "期望命中的记忆 ID（可为空）",
  "expected_rank": "期望名次（如 top3）",
  "actual_rank": "实际名次（未返回为 null）",
  "returned_top3": ["实际返回前三的记忆标题"],
  "failure_type": "miss | low_rank | wrong_order | noise | stale | conflict",
  "notes": "失败原因分析"
}
```

## failure_type 分类

| 类型 | 含义 |
|------|------|
| miss | 相关记忆未被召回（双路都没进前 50） |
| low_rank | 召回了但排名太低（如 20 名开外） |
| wrong_order | 相关记忆排在不相关记忆之后 |
| noise | 高分混入大量无关/低质记忆 |
| stale | 过时记忆排在了现行记忆之前 |
| conflict | 矛盾记忆未被识别/未附加警告 |

## 收集流程

1. 跑基准：`python -m benchmarks.runners.retrieval_runner --all-workspaces`
2. 从 `benchmarks/reports/{workspace}/` 的 per_query 明细中找 Recall@10 < 1 或 MRR 低的查询
3. 人工核对失败原因，按上述格式记录到对应 workspace 文件
4. 每次检索算法改动后复查历史案例是否修复（第 3 周验收：修复 ≥5 例）

## 已知系统性失败（2026-10 基线）

- 夹具基线显示 `hybrid_rrf_rerank` 与 `full_pipeline` 相比 `hybrid_rrf`
  MRR 从 0.93 降至 0.57、NDCG@10 从 0.78 降至 0.51——多信号重排的
  confidence/importance/freshness/usage 信号压过了 RRF 排名信号，
  属 wrong_order 型系统性退化（见 benchmarks/reports/eval-fixture/）。
- 上下文组装三例（context.jsonl，基线见 benchmarks/reports/eval-fixture/context-report.md）：
  ① 真实风格中文矛盾对漏报（CJK run 级 token 粗筛拦截，ctx-2026-001）；
  ② 组装无相关性下限，负例排除率仅 0.33（ctx-2026-002）；
  ③ 改写重复逃过词面去重（ctx-2026-003）。
  机制验证（字面重复去重、显式矛盾词对告警）均通过，失败集中在阈值与分词粒度。
