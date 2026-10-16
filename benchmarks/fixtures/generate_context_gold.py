"""生成上下文组装评测的黄金数据集。

从检索评测夹具（generate_fixture 的 CORPUS）构造候选池：
目标记忆 + 相关记忆 + 同主题干扰 + 跨主题干扰 + 注入负例
（过时/矛盾对/字面重复/改写重复），并为每条记录声明期望入选/排除
集合与 Token 预算档位。

pool 条目格式：
    {"memory_id": ..., "score": ...}
        —— 从夹具 DB 取该记忆
    {"memory_id": ..., "score": ..., "title": ..., "content": ..., "type": ...}
        —— 合成条目（内联内容），用于字面重复/改写重复/矛盾对注入

用法：
    python -m benchmarks.fixtures.generate_context_gold
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.fixtures.generate_fixture import entry_uuid

DATASET_PATH = Path(__file__).parent.parent / "datasets" / "context" / "gold.jsonl"

# 字面重复副本：与正本仅个别词不同（词级 Jaccard ≥ 0.80 触发组装层去重）
DUP_LITERAL_CONTENT = (
    "节点故障后：先 cluster nodes 确认 FAIL 状态，从节点自动 failover 升级为主；"
    "若需手工介入，对从节点执行 cluster failover。slot 均衡优先用 "
    "redis-cli --cluster rebalance 目标为空 slot 补齐，再按权重迁移；"
    "单 slot 迁移用 reshard，迁移期间目标节点需先 cluster setslot importing "
    "源节点 setslot migrating。"
)

# 改写重复副本：同一知识换措辞（词级 Jaccard 远低于 0.80，
# 当前词面去重无法识别——记录为 W3 语义去重的回归目标）
DUP_PARAPHRASE_CONTENT = (
    "Redis Cluster 节点故障恢复与 slot 重新均衡完整流程：先 cluster nodes 确认 FAIL，"
    "从节点自动 failover 升主；slot 均衡用 redis-cli --cluster rebalance，"
    "单 slot 迁移用 reshard。"
)

# 矛盾机制验证对：run 级 token 重叠 ≥ 0.4 且含显式矛盾词对（必须/禁止），
# 用于验证冲突检测管线本身可用（区别于 ctx-011/012 的真实风格矛盾对，
# 后者当前因 CJK 粗筛拦截而漏报，是 W3 优化目标）
CONTRADICTION_A = (
    "部署约束：生产环境必须开启 Redis 持久化，统一 RDB+AOF 混合模式，"
    "appendfsync everysec，禁止关闭持久化。"
)
CONTRADICTION_B = (
    "部署约束：生产环境禁止开启 Redis 持久化，统一 RDB+AOF 混合模式，改为纯缓存模式由业务预热重建。"
)


def _mem(key: str, score: float) -> dict:
    return {"memory_id": str(entry_uuid(key)), "score": round(score, 2), "key": key}


def _syn(
    key: str,
    score: float,
    title: str,
    content: str,
    mem_type: str = "fact",
) -> dict:
    """合成 pool 条目：内联内容，不查夹具 DB。"""
    return {
        "memory_id": str(entry_uuid(key)),
        "score": round(score, 2),
        "key": key,
        "title": title,
        "content": content,
        "type": mem_type,
    }


def _record(
    qid: str,
    query: str,
    pool: list[dict],
    included: list[str],
    excluded: list[str],
    budget: int = 2000,
    intent: str = "unknown",
    conflict_pairs: list[tuple[str, str]] | None = None,
) -> dict:
    record = {
        "query_id": qid,
        "query": query,
        "intent": intent,
        "budget": budget,
        "pool": [{k: v for k, v in p.items() if k != "key"} for p in pool],
        "expected_included": [str(entry_uuid(k)) for k in included],
        "expected_excluded": [str(entry_uuid(k)) for k in excluded],
        "expected_conflict_pairs": (
            [[str(entry_uuid(a)), str(entry_uuid(b))] for a, b in conflict_pairs]
            if conflict_pairs
            else []
        ),
    }
    return record


def build_records() -> list[dict]:
    records: list[dict] = []

    # ---- A. 标准选择（宽松预算）：目标+相关入选，过时/干扰不依赖预算被排除 ----
    records.append(
        _record(
            "ctx-001",
            "Redis 集群节点挂了怎么恢复",
            [
                _mem("redis-failover-rebalance", 0.92),
                _mem("redis-rebalance-skip-zero-slot", 0.71),
                _mem("redis-slot-principle", 0.66),
                _mem("redis-cluster-vs-sentinel", 0.58),
                _mem("redis-sentinel-legacy", 0.55),  # 过时负例
                _mem("redis-eviction-policy", 0.41),
                _mem("sqlite-vacuum-shrink", 0.35),
            ],
            included=["redis-failover-rebalance", "redis-rebalance-skip-zero-slot"],
            excluded=["redis-sentinel-legacy", "sqlite-vacuum-shrink"],
        )
    )
    records.append(
        _record(
            "ctx-002",
            "WAL 模式读写并发是怎么回事",
            [
                _mem("sqlite-wal-principle", 0.93),
                _mem("sqlite-wal-checkpoint-residue", 0.74),
                _mem("sqlite-locking", 0.68),
                _mem("sqlite-sync-normal-safe", 0.6),
                _mem("sqlite-rollback-journal-legacy", 0.52),  # 过时负例
                _mem("eng-aiosqlite-staticpool", 0.43),
                _mem("task-crash-recovery", 0.33),
            ],
            included=["sqlite-wal-principle", "sqlite-wal-checkpoint-residue"],
            excluded=["sqlite-rollback-journal-legacy", "task-crash-recovery"],
        )
    )
    records.append(
        _record(
            "ctx-003",
            "BM25 参数怎么调",
            [
                _mem("retrieval-bm25-formula", 0.9),
                _mem("retrieval-idf-small-corpus", 0.72),
                _mem("retrieval-custom-bm25-decision", 0.64),
                _mem("retrieval-cjk-tokenize", 0.57),
                _mem("retrieval-keyword-only-legacy", 0.49),  # 过时负例
                _mem("embedding-bge-model", 0.31),
            ],
            included=["retrieval-bm25-formula", "retrieval-idf-small-corpus"],
            excluded=["retrieval-keyword-only-legacy", "embedding-bge-model"],
        )
    )
    records.append(
        _record(
            "ctx-004",
            "embedding 双写怎么防并发冲突",
            [
                _mem("embedding-dual-write", 0.91),
                _mem("embedding-index-corruption", 0.7),
                _mem("embedding-fallback-observe", 0.62),
                _mem("task-crash-recovery", 0.55),
                _mem("embedding-batch-embedding", 0.48),
                _mem("biz-apollo-namespace", 0.28),
            ],
            included=["embedding-dual-write"],
            excluded=["biz-apollo-namespace"],
        )
    )
    records.append(
        _record(
            "ctx-005",
            "任务队列崩溃后任务会丢吗",
            [
                _mem("task-crash-recovery", 0.92),
                _mem("task-lease-reconciliation", 0.75),
                _mem("task-idempotency-key", 0.66),
                _mem("task-graceful-shutdown", 0.6),
                _mem("task-infinite-retry-legacy", 0.5),  # 过时负例
                _mem("eng-asyncio-taskgroup", 0.36),
            ],
            included=["task-crash-recovery", "task-lease-reconciliation"],
            excluded=["task-infinite-retry-legacy", "eng-asyncio-taskgroup"],
        )
    )
    records.append(
        _record(
            "ctx-006",
            "驿氪接口对接要注意什么",
            [
                _mem("biz-yike-outbound", 0.93),
                _mem("biz-outbound-signature", 0.76),
                _mem("biz-coupon-1308-flow", 0.68),
                _mem("biz-tenant-id-passing", 0.52),
                _mem("redis-cache-naming", 0.3),
            ],
            included=["biz-yike-outbound", "biz-outbound-signature"],
            excluded=["redis-cache-naming"],
        )
    )

    # ---- B. 字面重复去重：副本仅个别词不同，必须被词面去重去掉（保留高分正本） ----
    records.append(
        _record(
            "ctx-007",
            "Redis 故障恢复流程",
            [
                _mem("redis-failover-rebalance", 0.92),
                _mem("redis-rebalance-skip-zero-slot", 0.7),
                _syn(
                    "dup:redis-failover-rebalance-literal",
                    0.4,
                    "Redis Cluster 节点故障恢复与 slot 重新均衡流程（副本）",
                    DUP_LITERAL_CONTENT,
                ),
                _mem("redis-slot-principle", 0.55),
            ],
            included=["redis-failover-rebalance"],
            excluded=["dup:redis-failover-rebalance-literal"],
        )
    )

    # ---- C. 紧预算（500）：只保留最高优先级目标，预算必须守住 ----
    records.append(
        _record(
            "ctx-008",
            "SQLite 锁冲突怎么处理",
            [
                _mem("sqlite-locking", 0.9),
                _mem("sqlite-wal-principle", 0.8),
                _mem("sqlite-pragma-sync", 0.62),
                _mem("sqlite-batch-insert", 0.55),
                _mem("sqlite-corruption-recovery", 0.5),
                _mem("sqlite-vacuum-shrink", 0.44),
                _mem("eng-aiosqlite-staticpool", 0.4),
                _mem("ops-wal-sidecar-files", 0.36),
            ],
            included=["sqlite-locking"],
            excluded=["ops-wal-sidecar-files"],
            budget=500,
        )
    )
    records.append(
        _record(
            "ctx-009",
            "缓存三大问题怎么防",
            [
                _mem("redis-cache-avalanche", 0.91),
                _mem("redis-eviction-policy", 0.7),
                _mem("redis-expire-policy", 0.66),
                _mem("redis-cache-naming", 0.58),
                _mem("redis-bigkey-scan", 0.52),
                _mem("redis-persistence-compare", 0.47),
                _mem("redis-pipeline-batch", 0.4),
                _mem("ops-alert-thresholds", 0.3),
            ],
            included=["redis-cache-avalanche"],
            excluded=["ops-alert-thresholds"],
            budget=500,
        )
    )
    records.append(
        _record(
            "ctx-010",
            "灰度发布前要检查什么",
            [
                _mem("biz-gray-release-checklist", 0.93),
                _mem("biz-apollo-namespace", 0.72),
                _mem("ops-ci-layers", 0.6),
                _mem("ops-backup-drill", 0.55),
                _mem("ops-ftp-deploy-legacy", 0.48),  # 过时负例
                _mem("eng-uvicorn-reload-prod", 0.42),
                _mem("biz-coupon-1308-flow", 0.3),
            ],
            included=["biz-gray-release-checklist"],
            excluded=["ops-ftp-deploy-legacy", "biz-coupon-1308-flow"],
            budget=500,
        )
    )

    # ---- D. 矛盾对：正确侧入选 + 期望冲突告警 ----
    # 真实风格矛盾对（观点对立、无显式矛盾词对）——当前 CJK 粗筛拦截漏报，
    # 基线如实记录失败，W3 优化目标
    records.append(
        _record(
            "ctx-011",
            "生产环境持久化怎么配置",
            [
                _mem("redis-prod-persistence-must", 0.9),
                _mem("redis-prod-persistence-off", 0.82),  # 矛盾对（观点侧）
                _mem("redis-persistence-compare", 0.75),
                _mem("redis-aof-rewrite-memory", 0.6),
                _mem("redis-sentinel-legacy", 0.4),
            ],
            included=["redis-prod-persistence-must", "redis-persistence-compare"],
            excluded=["redis-sentinel-legacy"],
            conflict_pairs=[("redis-prod-persistence-must", "redis-prod-persistence-off")],
        )
    )
    records.append(
        _record(
            "ctx-012",
            "AOF 断电会不会丢数据",
            [
                _mem("sqlite-sync-normal-safe", 0.88),
                _mem("sqlite-sync-normal-unsafe", 0.8),  # 矛盾对（谨慎侧）
                _mem("redis-persistence-compare", 0.74),
                _mem("redis-aof-rewrite-memory", 0.65),
                _mem("sqlite-pragma-sync", 0.58),
            ],
            included=["redis-persistence-compare", "sqlite-pragma-sync"],
            excluded=[],
            conflict_pairs=[("sqlite-sync-normal-safe", "sqlite-sync-normal-unsafe")],
        )
    )
    records.append(
        _record(
            "ctx-013",
            "重复检测阈值单靠相似度够不够",
            [
                _mem("embedding-dedup-threshold", 0.86),
                _mem("embedding-dedup-threshold-enough", 0.79),  # 矛盾对（单阈值观点）
                _mem("retrieval-dedup-v2", 0.72),
                _mem("retrieval-vector-cosine", 0.55),
            ],
            included=["embedding-dedup-threshold", "retrieval-dedup-v2"],
            excluded=[],
        )
    )

    # ---- E. 被取代关系：旧版已归档（不应出现在池中，池内新版入选） ----
    records.append(
        _record(
            "ctx-014",
            "重复检测现在是怎么做的",
            [
                _mem("retrieval-dedup-v2", 0.9),
                _mem("retrieval-bm25-formula", 0.6),
                _mem("retrieval-custom-bm25-decision", 0.52),
                _mem("retrieval-vector-cosine", 0.45),
            ],
            included=["retrieval-dedup-v2"],
            excluded=[],
        )
    )

    # ---- F. 意图驱动的类型优先（troubleshooting 意图下 issue/lesson 优先） ----
    records.append(
        _record(
            "ctx-015",
            "端口被占服务起不来怎么排查",
            [
                _mem("ops-port-occupied", 0.89),
                _mem("ops-alert-thresholds", 0.64),
                _mem("ops-docker-multistage", 0.5),
                _mem("ops-log-rotation", 0.46),
                _mem("biz-gray-release-checklist", 0.34),
            ],
            included=["ops-port-occupied"],
            excluded=["biz-gray-release-checklist"],
            intent="procedure",
        )
    )
    records.append(
        _record(
            "ctx-016",
            "注册校验哪些状态码放行",
            [
                _mem("biz-member-prefilter", 0.92),
                _mem("biz-member-status-codes", 0.78),
                _mem("biz-member-registration", 0.7),
                _mem("biz-content-template", 0.4),
                _mem("redis-cache-naming", 0.28),
            ],
            included=["biz-member-prefilter", "biz-member-status-codes"],
            excluded=["biz-content-template", "redis-cache-naming"],
        )
    )
    records.append(
        _record(
            "ctx-017",
            "embedding 模型加载失败怎么发现",
            [
                _mem("embedding-fallback-observe", 0.9),
                _mem("embedding-index-corruption", 0.72),
                _mem("embedding-bge-model", 0.6),
                _mem("ops-embed-model-cache", 0.56),
                _mem("ops-ci-layers", 0.38),
            ],
            included=["embedding-fallback-observe"],
            excluded=["ops-ci-layers"],
        )
    )
    records.append(
        _record(
            "ctx-018",
            "GitHub 下载模型太慢",
            [
                _mem("ops-github-tuna-mirror", 0.91),
                _mem("ops-embed-model-cache", 0.75),
                _mem("ops-docker-multistage", 0.5),
                _mem("ops-time-sync", 0.35),
            ],
            included=["ops-github-tuna-mirror"],
            excluded=["ops-time-sync"],
        )
    )
    records.append(
        _record(
            "ctx-019",
            "Pydantic 升级 v2 踩了什么坑",
            [
                _mem("eng-pydantic-v2-validate", 0.92),
                _mem("eng-fastapi-depends-yield", 0.6),
                _mem("eng-mypy-strict-conventions", 0.5),
                _mem("eng-ruff-config", 0.44),
                _mem("eng-requests-legacy", 0.32),  # 过时负例
            ],
            included=["eng-pydantic-v2-validate"],
            excluded=["eng-requests-legacy"],
        )
    )
    records.append(
        _record(
            "ctx-020",
            "异步测试报 different loop",
            [
                _mem("eng-pytest-asyncio-auto", 0.93),
                _mem("eng-sqlalchemy-expire-commit", 0.66),
                _mem("eng-asyncio-taskgroup", 0.6),
                _mem("eng-aiosqlite-staticpool", 0.52),
                _mem("eng-alembic-vs-createall", 0.3),
            ],
            included=["eng-pytest-asyncio-auto"],
            excluded=["eng-alembic-vs-createall"],
        )
    )
    records.append(
        _record(
            "ctx-021",
            "多路召回分数怎么融合",
            [
                _mem("retrieval-rrf-fusion", 0.9),
                _mem("retrieval-hybrid-complement", 0.74),
                _mem("retrieval-rerank-weights", 0.68),
                _mem("retrieval-vector-cosine", 0.56),
                _mem("retrieval-metrics", 0.48),
                _mem("ops-embed-model-cache", 0.26),
            ],
            included=["retrieval-rrf-fusion", "retrieval-hybrid-complement"],
            excluded=["ops-embed-model-cache"],
        )
    )
    records.append(
        _record(
            "ctx-022",
            "相关记忆全部塞给模型行不行",
            [
                _mem("retrieval-relevant-but-not-useful", 0.91),
                _mem("retrieval-context-budget", 0.8),
                _mem("retrieval-diversity-filter", 0.62),
                _mem("retrieval-stale-detection", 0.55),
                _mem("retrieval-keyword-only-legacy", 0.42),  # 过时负例
            ],
            included=["retrieval-relevant-but-not-useful", "retrieval-context-budget"],
            excluded=["retrieval-keyword-only-legacy"],
        )
    )
    records.append(
        _record(
            "ctx-023",
            "备份恢复怎么做演练",
            [
                _mem("ops-backup-drill", 0.92),
                _mem("sqlite-corruption-recovery", 0.7),
                _mem("ops-wal-sidecar-files", 0.6),
                _mem("sqlite-fts5-cjk", 0.35),
            ],
            included=["ops-backup-drill"],
            excluded=["sqlite-fts5-cjk"],
        )
    )
    records.append(
        _record(
            "ctx-024",
            "容器里时钟不准影响签名校验",
            [
                _mem("ops-time-sync", 0.9),
                _mem("biz-outbound-signature", 0.78),
                _mem("biz-yike-outbound", 0.66),
                _mem("ops-port-occupied", 0.4),
            ],
            included=["ops-time-sync", "biz-outbound-signature"],
            excluded=["ops-port-occupied"],
        )
    )

    # ---- G. 矛盾机制验证：显式矛盾词对 + 高文本重叠，验证冲突检测管线可用 ----
    records.append(
        _record(
            "ctx-025",
            "生产环境 Redis 持久化开不开",
            [
                _mem("redis-persistence-compare", 0.85),
                _syn(
                    "contra:persistence-must",
                    0.82,
                    "约束：生产环境必须开启持久化",
                    CONTRADICTION_A,
                    mem_type="constraint",
                ),
                _syn(
                    "contra:persistence-off",
                    0.78,
                    "观点：生产环境不必开启持久化",
                    CONTRADICTION_B,
                    mem_type="opinion",
                ),
                _mem("redis-aof-rewrite-memory", 0.55),
            ],
            included=["redis-persistence-compare"],
            excluded=[],
            conflict_pairs=[("contra:persistence-must", "contra:persistence-off")],
        )
    )

    # ---- H. 改写重复：同一知识换措辞，词面去重识别不了（W3 语义去重回归目标） ----
    records.append(
        _record(
            "ctx-026",
            "Redis 集群 slot 怎么均衡",
            [
                _mem("redis-failover-rebalance", 0.91),
                _syn(
                    "dup:redis-failover-rebalance-paraphrase",
                    0.75,
                    "Redis Cluster 故障恢复与均衡要点",
                    DUP_PARAPHRASE_CONTENT,
                ),
                _mem("redis-slot-principle", 0.6),
                _mem("redis-cluster-vs-sentinel", 0.45),
            ],
            included=["redis-failover-rebalance"],
            excluded=["dup:redis-failover-rebalance-paraphrase"],
        )
    )

    return records


def main() -> None:
    records = build_records()
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET_PATH, "w") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    print(f"Wrote {len(records)} context gold records to {DATASET_PATH}")


if __name__ == "__main__":
    main()
