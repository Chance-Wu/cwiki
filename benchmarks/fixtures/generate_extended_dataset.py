"""扩展评测集生成器（W4-02）。

在原始 eval-fixture.jsonl（101 查询，回归基线，保持不变）之外，生成
eval-fixture-extended.jsonl：12 类定向查询，覆盖原始集未覆盖的失败模式
（精确关键词、同义改写、历史决策、时间敏感、被取代、冲突事实、无相关探针、
困难负例、工作区隔离、弱标题匹配、中英混合）。

与原始集的关系：
- 引用同一夹具 DB（eval_fixture.db）的确定性 UUID（entry_uuid(key)）
- 每行额外携带 category / note 注记字段（load_gold_dataset 忽略未知字段）
- 负例探针（category=C8/C9/C10）judgments 仅含 0 分干扰项或 1 分弱相关干扰，
  评测器将其隔离出主指标平均，单独统计误召回

用法：
    python -m benchmarks.fixtures.generate_extended_dataset
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.fixtures.generate_fixture import entry_uuid

DATASET_PATH = (
    Path(__file__).parent.parent / "datasets" / "retrieval" / "eval-fixture-extended.jsonl"
)

# (query_id, query, [(词条 key, relevance)], note)
# relevance 沿用 0-3 分级：3=直接有用 2=相关 1=弱相关 0=不相关
QUERIES: list[tuple[str, str, list[tuple[str, int]], str]] = [
    # ---- C1 精确关键词：命令名/数字/参数名精确匹配，BM25 预期优势区 ----
    (
        "C1-q1",
        "wal_checkpoint TRUNCATE 在什么场景必须执行",
        [("sqlite-wal-checkpoint-residue", 3), ("sqlite-wal-principle", 2)],
        "命令名精确匹配；标题含 checkpoint 但正文才有 TRUNCATE 语义",
    ),
    (
        "C1-q2",
        "Redis Cluster 的 16384 个 slot 是怎么编号的",
        [("redis-slot-principle", 3)],
        "数字+术语精确匹配",
    ),
    (
        "C1-q3",
        "busy_timeout 设多少合适",
        [("sqlite-locking", 3)],
        "参数名精确匹配；query 比标题短得多",
    ),
    (
        "C1-q4",
        "mem_fragmentation_ratio 高于多少说明碎片严重",
        [("redis-memory-fragmentation", 3)],
        "指标名精确匹配，仅存在于正文",
    ),
    # ---- C2 同义改写：与记忆用词无表面重叠，向量预期优势区 ----
    (
        "C2-q1",
        "数据库文件把记录删了之后体积还是很大，怎么收缩",
        [("sqlite-vacuum-shrink", 3)],
        "同义改写：收缩≈VACUUM，表面词零重叠",
    ),
    (
        "C2-q2",
        "Redis 重启之后数据会不会丢",
        [("redis-persistence-compare", 3), ("redis-prod-persistence-must", 2)],
        "同义改写：会不会丢≈持久化",
    ),
    (
        "C2-q3",
        "Python 服务的 Docker 镜像有什么办法变小",
        [("ops-docker-multistage", 3)],
        "同义改写：变小≈多阶段构建瘦身",
    ),
    # ---- C3 历史决策：决策背景与演进脉络 ----
    (
        "C3-q1",
        "当初为什么决定放弃 Sentinel 改用 Cluster",
        [("redis-cluster-vs-sentinel", 3), ("redis-sentinel-legacy", 1)],
        "决策类记忆作主答案；被取代的旧方案作弱相关历史背景",
    ),
    (
        "C3-q2",
        "重复检测的方案是怎么一步步演进的",
        [("retrieval-dedup-v2", 3)],
        "v1 已归档不可检索，历史由 v2 正文承载；正确行为是返回 v2 而非空",
    ),
    # ---- C4 多条件组合：单查询命中多条不同侧面记忆 ----
    (
        "C4-q1",
        "SQLite 写入又慢磁盘空间又涨，一起排查",
        [("sqlite-batch-insert", 3), ("sqlite-vacuum-shrink", 2)],
        "两条件各对应一条记忆，考察多答案召回",
    ),
    (
        "C4-q2",
        "删 Redis 大 key 时怎么既不阻塞又防止雪崩",
        [("redis-bigkey-scan", 3), ("redis-cache-avalanche", 2)],
        "渐进删除 + 雪崩防护两个侧面",
    ),
    # ---- C5 时间敏感：正确答案依赖记忆的时间有效性 ----
    (
        "C5-q1",
        "现在生产环境还允许用 Sentinel 部署吗",
        [("redis-cluster-vs-sentinel", 3), ("redis-sentinel-legacy", 1)],
        "现行决策是主答案；stale 旧方案含时间线但应降权，考察过期记忆处理",
    ),
    (
        "C5-q2",
        "WAL 模式出来之前 SQLite 的锁和 journal 是怎么调优的",
        [("sqlite-rollback-journal-legacy", 2), ("sqlite-locking", 1)],
        "明确问历史：stale 记忆反而是正确答案，考察 stale 过滤是否过度拦截",
    ),
    # ---- C6 被取代：查询语义命中已归档 v1，应返回取代它的 v2 ----
    (
        "C6-q1",
        "标题相似度判重复的方案是什么，阈值多少",
        [("retrieval-dedup-v2", 3)],
        "查询措辞命中已归档 v1（仅标题比较）；归档记忆不可检索，正确行为是返回 v2",
    ),
    (
        "C6-q2",
        "现在的监控告警是怎么做的，用什么指标",
        [("ops-monitor-v2", 3)],
        "monitor v1（cron 邮件）已归档；应返回 v2 指标端点方案",
    ),
    # ---- C7 冲突事实：矛盾对双方都应召回（冲突警告由 context 层负责）----
    (
        "C7-q1",
        "生产环境 Redis 可以关闭持久化吗",
        [("redis-prod-persistence-must", 3), ("redis-prod-persistence-off", 2)],
        "矛盾对：团队约束（must）与少数派观点（off）都要召回，漏掉任一方都是失败",
    ),
    (
        "C7-q2",
        "WAL 模式下 synchronous=NORMAL 会不会丢事务",
        [("sqlite-sync-normal-safe", 3), ("sqlite-sync-normal-unsafe", 2)],
        "矛盾对：结论相反的两条事实，考察检索层不做单边过滤",
    ),
    # ---- C8 无相关探针：夹具内不存在答案，理想行为是空结果 ----
    (
        "C8-q1",
        "Kubernetes HPA 自动扩缩容策略怎么配",
        [("ops-docker-multistage", 0), ("ops-ci-layers", 0)],
        "负例探针：部署运维主题相近但均不相关；判定仅含 0 分干扰项",
    ),
    (
        "C8-q2",
        "React Hooks 里 useReducer 怎么用",
        [("eng-pydantic-v2-validate", 0), ("biz-content-template", 0)],
        "负例探针：前端主题，夹具仅有后端校验/模板词条",
    ),
    (
        "C8-q3",
        "红烧肉怎么炖才能肥而不腻",
        [("ops-backup-drill", 0), ("biz-coupon-1308-flow", 0)],
        "负例探针：完全无关查询，考察是否强行返回噪声",
    ),
    # ---- C9 困难负例：含 1 分弱相关干扰项，误召回探针指标在此生效 ----
    (
        "C9-q1",
        "Redis 分布式锁怎么实现",
        [("redis-cache-avalanche", 1), ("redis-pipeline-batch", 0)],
        "困难负例：夹具只有 setnx 缓存互斥锁（弱相关干扰），无分布式锁专题；返回干扰项记误召回",
    ),
    (
        "C9-q2",
        "MySQL 主从复制延迟怎么解决",
        [("redis-sentinel-legacy", 1), ("sqlite-wal-principle", 0)],
        "困难负例：'一主两从'复制拓扑是弱相关干扰，夹具无 MySQL 内容",
    ),
    (
        "C9-q3",
        "Kafka 消息堆积怎么处理",
        [("task-retry-backoff-dlq", 1), ("task-priority-ordering", 0)],
        "困难负例：任务队列重试/死信语义相近（弱相关干扰），夹具无 Kafka",
    ),
    # ---- C10 工作区隔离：其他真实工作区的话题在夹具工作区不存在 ----
    (
        "C10-q1",
        "MCP stdio 插件连接失败怎么排查",
        [("ops-port-occupied", 0), ("eng-uvicorn-reload-prod", 0)],
        "隔离探针：真实 cwiki 工作区话题，eval-fixture 工作区无此记忆；考察跨工作区泄漏",
    ),
    (
        "C10-q2",
        "受控表单组件在 React 里怎么写",
        [("biz-content-template", 0), ("eng-pydantic-v2-validate", 0)],
        "隔离探针：前端话题不在夹具内；干扰项为业务模板/校验词条",
    ),
    # ---- C11 长内容/弱标题：查询词仅在正文出现，标题无信号 ----
    (
        "C11-q1",
        "except* 和 except 在异常捕获上有什么区别",
        [("eng-asyncio-taskgroup", 3)],
        "except* 仅在正文，标题是'任务组与异常传播语义'；考察标题弱匹配",
    ),
    (
        "C11-q2",
        "aof_rewrite_buffer 长度告警怎么配",
        [("redis-aof-rewrite-memory", 3)],
        "aof_rewrite_buffer 仅在正文；标题讲内存翻倍",
    ),
    (
        "C11-q3",
        "bge 模型的指令前缀要不要加",
        [("embedding-bge-model", 3)],
        "指令前缀细节仅在正文；标题只含模型名",
    ),
    # ---- C12 中英混合：英文术语 + 中文提问 ----
    (
        "C12-q1",
        "fastembed 的 ONNX 权重能离线用吗",
        [("embedding-fastembed-onnx", 3)],
        "中英混合；离线≈冷启动/下载一次",
    ),
    (
        "C12-q2",
        "bge-small-zh 输出的向量是多少维",
        [("embedding-bge-model", 3)],
        "中英混合；维度数仅在正文",
    ),
    (
        "C12-q3",
        "向量做 L2 归一化之后余弦相似度就等于点积了吗",
        [("retrieval-vector-cosine", 3)],
        "中英混合：L2/点积/余弦术语混排",
    ),
]

CATEGORY_DESC = {
    "C1": "精确关键词",
    "C2": "同义改写",
    "C3": "历史决策",
    "C4": "多条件组合",
    "C5": "时间敏感",
    "C6": "被取代旧记忆",
    "C7": "冲突事实",
    "C8": "无相关探针",
    "C9": "困难负例",
    "C10": "工作区隔离",
    "C11": "弱标题匹配",
    "C12": "中英混合",
}


def build_extended_dataset() -> dict:
    lines: list[dict] = []
    for qid, query, judgments, note in QUERIES:
        category = qid.split("-")[0]
        for key, relevance in judgments:
            lines.append(
                {
                    "query_id": qid,
                    "query": query,
                    "memory_id": str(entry_uuid(key)),
                    "relevance": relevance,
                    "category": category,
                    "note": note,
                }
            )

    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET_PATH, "w") as f:
        f.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)

    queries = {qid for qid, _, _, _ in QUERIES}
    by_cat: dict[str, int] = {}
    for qid in queries:
        by_cat[qid.split("-")[0]] = by_cat.get(qid.split("-")[0], 0) + 1
    stats = {
        "dataset": str(DATASET_PATH),
        "queries": len(queries),
        "judgment_lines": len(lines),
        "by_category": {CATEGORY_DESC[c]: n for c, n in sorted(by_cat.items())},
        "negative_probes": by_cat.get("C8", 0) + by_cat.get("C9", 0) + by_cat.get("C10", 0),
    }
    return stats


if __name__ == "__main__":
    import pprint

    pprint.pprint(build_extended_dataset())
