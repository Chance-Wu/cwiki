"""合成评测夹具生成器。

以固定种子生成一个自包含的评测数据库（eval_fixture.db）与黄金数据集
（datasets/retrieval/eval-fixture.jsonl），覆盖：

- 8 个主题、约 100 条真实风格中文记忆
- 负例三类：过时（valid_to 已过但 status=active）、矛盾（MemoryConflict 对）、
  无关（跨主题干扰项判 0）；另含被取代对（archived + supersedes 关系）
- 每条核心记忆 1-2 条查询，判定按标签重叠度分级（3/2/1/0）

用法：
    python -m benchmarks.fixtures.generate_fixture

夹具 DB 与数据集均可再生（内容与 UUID 确定，embedding 由本地模型确定性计算），
用于检索基线、回归门槛（CI）与上下文组装评测。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base
from packages.domain.models import Memory, Workspace
from packages.domain.models.memory import MemoryConflict, MemoryRelation
from packages.domain.text_utils import format_memory_for_embedding
from packages.retrieval.embedding import get_embedding_service

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent
DB_PATH = FIXTURES_DIR / "eval_fixture.db"
DATASET_PATH = FIXTURES_DIR.parent / "datasets" / "retrieval" / "eval-fixture.jsonl"
META_PATH = FIXTURES_DIR / "fixture_meta.json"

WORKSPACE_NAME = "eval-fixture"
NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# 词条定义：key 为稳定标识（决定 UUID）；stale=过时但 active；archived=已归档；
# conflict_with=与其矛盾的词条 key；supersedes=其取代的旧词条 key。
CORPUS: list[dict] = [
    # ---------------- Redis ----------------
    {
        "key": "redis-slot-principle",
        "title": "Redis Cluster 16384 slot 分布原理与 CRC16 键路由",
        "content": (
            "Redis Cluster 把键空间划分为 16384 个 slot，每个键经 CRC16(key) mod 16384 "
            "定位到 slot，slot 再分配给各主节点。键带 hash tag {user:1} 时只对花括号内部分 "
            "做 CRC16，可强制多键落到同一 slot 以支持 MSET/事务。集群最小规模建议 3 主 3 从。"
        ),
        "type": "fact",
        "tags": ["redis", "cluster", "slot"],
        "queries": ["Redis Cluster 的 slot 是怎么分配的", "hash tag 让多键落到同一个 slot"],
    },
    {
        "key": "redis-failover-rebalance",
        "title": "Redis Cluster 节点故障恢复与 slot 重新均衡完整流程",
        "content": (
            "节点故障后：先 cluster nodes 确认 FAIL 状态，从节点自动 failover 升主；"
            "若需手工介入，对从节点执行 cluster failover。slot 均衡优先用 redis-cli "
            "--cluster rebalance 目标为空 slot 补齐，再按权重迁移；单 slot 迁移用 reshard，"
            "迁移过程中目标节点需先 cluster setslot importing 源节点 setslot migrating。"
        ),
        "type": "procedure",
        "tags": ["redis", "cluster", "failover"],
        "queries": ["Redis 集群节点挂了怎么恢复", "Redis slot 重新均衡的完整步骤"],
    },
    {
        "key": "redis-rebalance-skip-zero-slot",
        "title": "redis-cli rebalance 跳过 0-slot 节点，必须用 reshard",
        "content": (
            "踩坑：redis-cli --cluster rebalance 在某节点持有 0 个 slot 时会直接跳过它，"
            "不为其分配任何 slot。要让新节点承担负载必须逐 slot 用 reshard 手工迁移，"
            "或先用 rebalance 的 --cluster-use-empty-masters 参数。生产扩容前先在测试集群验证。"
        ),
        "type": "lesson",
        "tags": ["redis", "cluster", "slot"],
        "queries": ["rebalance 为什么不给新节点分 slot"],
    },
    {
        "key": "redis-persistence-compare",
        "title": "Redis 持久化 RDB 与 AOF 对比及选择",
        "content": (
            "RDB 是某时刻全量二进制快照，文件小恢复快，但两次快照间数据会丢；AOF 追加每条写命令，"
            "配合 everysec 最多丢 1 秒。4.0 起可用混合持久化（aof-use-rdb-preamble）：AOF 重写时"
            "前半段写 RDB 全量、后半段追加增量命令，兼顾恢复速度与数据安全。缓存场景可只开 RDB，"
            "数据重要场景开混合持久化。"
        ),
        "type": "fact",
        "tags": ["redis", "persistence"],
        "queries": ["RDB 和 AOF 怎么选", "Redis 混合持久化是什么"],
    },
    {
        "key": "redis-aof-rewrite-memory",
        "title": "AOF 重写期间内存翻倍风险与应对",
        "content": (
            "bgrewriteaof 由子进程执行，fork 时 COW 可能导致内存接近翻倍；重写缓冲区在主线程"
            "持续累积新写入，大流量下也会放大内存。应对：单机 maxmemory 预留 40% 余量，"
            "重写放在低峰期，监控 info persistence 的 aof_rewrite_buffer 长度，超限告警。"
        ),
        "type": "lesson",
        "tags": ["redis", "persistence", "memory"],
        "queries": ["AOF 重写内存翻倍怎么办"],
    },
    {
        "key": "redis-expire-policy",
        "title": "Redis 过期删除策略：惰性删除 + 定期采样",
        "content": (
            "过期键不会被主动精准删除：访问时惰性检查过期（惰性删除），后台每 100ms 随机采样"
            "20 个带 TTL 的键，过期比例超 25% 则继续下一轮（定期删除）。因此大量 key 同一时刻"
            "过期仍会短暂残留。主动清理用 SCAN 匹配后 del，禁止 keys *。"
        ),
        "type": "fact",
        "tags": ["redis", "expire"],
        "queries": ["Redis 过期 key 是什么时候被删掉的"],
    },
    {
        "key": "redis-bigkey-scan",
        "title": "Redis 大 key 扫描与删除的渐进式方案",
        "content": (
            "扫描用 redis-cli --bigkeys 或 SCAN 遍历 + memory usage 采样，不要用 keys。"
            "删除大集合必须渐进：HSCAN/SSCAN 分批取成员逐批 DEL 字段，或用 UNLINK 异步释放；"
            "直接 DEL 百万元素集合会阻塞主线程数秒，引发批量超时。"
        ),
        "type": "procedure",
        "tags": ["redis", "bigkey", "ops"],
        "queries": ["大 key 怎么安全删除", "怎么扫描 Redis 里的 bigkey"],
    },
    {
        "key": "redis-cache-naming",
        "title": "缓存 key 命名规范：project:module:business:id",
        "content": (
            "团队约定缓存 key 统一为 project:module:business:id 四段冒号分隔，例如 "
            "scrm:member:profile:1048。禁止拼接中文与空格；TTL 必须显式设置，禁止裸 key "
            "不过期。批量失效靠按业务段前缀 SCAN 删除，不靠 keys 命令。"
        ),
        "type": "convention",
        "tags": ["redis", "cache", "convention"],
        "queries": ["缓存 key 命名规范是什么"],
    },
    {
        "key": "redis-cache-avalanche",
        "title": "缓存雪崩、穿透、击穿的区分与防护",
        "content": (
            "雪崩是大量 key 同时过期或 Redis 整体不可用：TTL 加随机抖动、多级缓存、集群高可用。"
            "穿透是查询不存在的数据打穿到 DB：布隆过滤器或空值缓存短 TTL。击穿是热 key 过期瞬间"
            "高并发回源：互斥锁重建（setnx）或逻辑过期不删物理 key。三者症状相似但手段不同。"
        ),
        "type": "lesson",
        "tags": ["redis", "cache"],
        "queries": ["缓存穿透和击穿有什么区别", "缓存雪崩怎么防"],
    },
    {
        "key": "redis-eviction-policy",
        "title": "Redis 内存淘汰策略 allkeys-lru 与 volatile-lru 对比",
        "content": (
            "内存达到 maxmemory 后按策略淘汰：allkeys-lru 对全部键近似 LRU（采样池 5 个取最旧），"
            "volatile-lru 只淘汰带 TTL 的键。LFU 变体按访问频率，适合热点明显的读缓存。"
            "若部分键是必须保留的业务状态（无 TTL），只能用 allkeys-lru + is_permanent 语义之外"
            "自行持久化，否则用 volatile 系列。"
        ),
        "type": "fact",
        "tags": ["redis", "memory", "eviction"],
        "queries": ["maxmemory 淘汰策略选哪个"],
    },
    {
        "key": "redis-cluster-vs-sentinel",
        "title": "决策：生产缓存统一用 Redis Cluster 而非哨兵",
        "content": (
            "决定：新项目缓存一律 Redis Cluster（3 主 3 从起），不再使用主从 + Sentinel。"
            "原因：数据量增长后哨兵单主容量有限，Cluster 水平扩容成本低；多业务共用时 slot "
            "隔离天然避免互相影响。代价是部分命令（跨 slot mget）需要 hash tag 或客户端拆分。"
        ),
        "type": "decision",
        "tags": ["redis", "cluster", "decision"],
        "queries": ["为什么用 Cluster 不用哨兵"],
    },
    {
        "key": "redis-sentinel-legacy",
        "title": "旧方案：Redis 主从 + Sentinel 自动切换部署（已废弃）",
        "content": (
            "旧部署采用一主两从 + 3 个 Sentinel 节点，quorum=2 自动故障转移，客户端通过 "
            "Sentinel 发现主节点地址。该方案在 2024 年 Q3 起被 Redis Cluster 方案取代，"
            "存量服务逐步迁移完毕。新项目禁止再使用 Sentinel。"
        ),
        "type": "reference",
        "tags": ["redis", "cluster", "deploy"],
        "stale": True,
    },
    {
        "key": "redis-slowlog",
        "title": "Redis 慢查询 slowlog 定位流程",
        "content": (
            "slowlog-log-slower-than 默认 10ms，生产建议调到 1ms~3ms 便于提前发现。"
            "slowlog get 10 查看最近慢命令，关注命令名与 key 名；配合 latency monitor "
            "(latency-monitor-threshold=100) 区分是慢命令还是 fork/swap 抖动。"
            "常见元凶：keys、大集合 HGETALL、误用 O(N) 命令。"
        ),
        "type": "procedure",
        "tags": ["redis", "ops", "monitoring"],
        "queries": ["Redis 慢命令怎么排查"],
    },
    {
        "key": "redis-prod-persistence-must",
        "title": "约束：生产环境必须开启持久化（RDB+AOF 混合）",
        "content": (
            "生产环境部署约束：Redis 必须开启持久化，统一采用 RDB+AOF 混合模式"
            "（aof-use-rdb-preamble yes），appendfsync everysec。禁止以纯缓存名义关闭持久化——"
            "重启丢数据后业务方按缓存语义重建的假设从未成立过，历史上两次事故均因此扩级。"
        ),
        "type": "constraint",
        "tags": ["redis", "persistence", "deploy"],
        "queries": ["生产环境持久化怎么配置"],
    },
    {
        "key": "redis-prod-persistence-off",
        "title": "观点：纯缓存场景可以关闭持久化（与团队约束矛盾）",
        "content": (
            "另一种声音：如果 Redis 只做缓存、后端 DB 是事实源，可以关闭持久化"
            "（save '' 且 appendonly no），重启后由业务预热重建，省去 fork 抖动。"
            "该观点与'生产环境必须开启持久化'的团队约束矛盾，尚未被采纳，"
            "仅作决策背景记录。"
        ),
        "type": "opinion",
        "tags": ["redis", "persistence", "deploy"],
        "conflict_with": "redis-prod-persistence-must",
    },
    {
        "key": "redis-pipeline-batch",
        "title": "Redis pipeline 与 mget 的批量优化",
        "content": (
            "N 次独立往返的命令合并为 pipeline 一次发送，网络 RTT 从 N 次降为 1 次，"
            "批量读写场景吞吐可提升一个数量级。注意 pipeline 不是事务：中间某条失败"
            "其余照常执行，需要原子性用 MULTI/EXEC（同样有 cluster 下跨 slot 限制）。"
            "单批建议控制在几百条以内，避免阻塞其他客户端。"
        ),
        "type": "lesson",
        "tags": ["redis", "performance"],
        "queries": ["pipeline 批量执行有什么好处"],
    },
    {
        "key": "redis-memory-fragmentation",
        "title": "Redis 内存碎片率与 activedefrag",
        "content": (
            "info memory 的 mem_fragmentation_ratio = used_memory_rss/used_memory，"
            "大于 1.5 说明碎片明显（频繁修改不同长度 value 的典型后果）。4.0+ 可开 "
            "activedefrag 在线整理，代价是 CPU；也可按低峰 restart。碎片率小于 1 "
            "反而危险：说明使用了 swap，先查系统内存再谈 Redis 调优。"
        ),
        "type": "fact",
        "tags": ["redis", "memory", "monitoring"],
        "queries": ["内存碎片率怎么解读"],
    },
    # ---------------- SQLite ----------------
    {
        "key": "sqlite-wal-principle",
        "title": "SQLite WAL 模式原理：读写并发与 checkpoint",
        "content": (
            "WAL 模式把写入追加到 -wal 文件，读操作直接读主库文件不阻塞写，实现读写并发。"
            "数据真正落回主库发生在 checkpoint：默认每 1000 页自动触发。TRUNCATE 模式在 "
            "checkpoint 后把 wal 文件截断为 0，确保提交的 .db 文件包含全部数据且无 -wal 残留，"
            "是单文件分发/同步场景的必选参数。"
        ),
        "type": "fact",
        "tags": ["sqlite", "wal"],
        "queries": ["WAL 模式的原理是什么", "wal checkpoint TRUNCATE 什么时候用"],
    },
    {
        "key": "sqlite-locking",
        "title": "SQLite 锁类型与 busy_timeout 处理",
        "content": (
            "SQLite 回滚日志模式有 SHARED/RESERVED/PENDING/EXCLUSIVE 四级锁，写是库级排他的。"
            "并发冲突报 SQLITE_BUSY，正确做法是设置 busy_timeout 让其内部重试等待，"
            "而不是应用层立刻报错。WAL 模式下读写不互斥，只剩写写冲突。"
            "排查工具：sqlite3 .db 'PRAGMA lock_status'（部分构建支持）与 dbstat。"
        ),
        "type": "fact",
        "tags": ["sqlite", "locking"],
        "queries": ["database is locked 怎么处理"],
    },
    {
        "key": "sqlite-wal-checkpoint-residue",
        "title": "WAL checkpoint TRUNCATE 确保同步时无 -wal 残留",
        "content": (
            "Git 同步 SQLite 前必须执行 PRAGMA wal_checkpoint(TRUNCATE)，否则提交的 .db "
            "缺最近写入、残留的 -wal 文件在部分平台还可能内容漂移。checkpoint 后校验："
            "wal 文件应为 0 字节；PRAGMA wal_checkpoint 返回 busy=0。同步脚本将此作为"
            "硬性前置步骤，未清空则中止本次 pull/export。"
        ),
        "type": "lesson",
        "tags": ["sqlite", "wal", "sync"],
        "queries": ["同步 SQLite 前为什么要 wal_checkpoint"],
    },
    {
        "key": "sqlite-fts5-cjk",
        "title": "SQLite FTS5 全文索引与中文分词方案",
        "content": (
            "FTS5 默认 unicode61 分词器按空格切词，中文整句会成为一个 token 无法命中。"
            "方案一：写入前用 jieba 分词后以空格拼接存列；方案二：自定义 trigram 分词"
            "（FTS5 tokenize='trigram'）支持子串匹配但索引膨胀明显。中文场景推荐方案一，"
            "查询同样先分词再 MATCH。"
        ),
        "type": "fact",
        "tags": ["sqlite", "fts", "cjk"],
        "queries": ["FTS5 怎么支持中文搜索"],
    },
    {
        "key": "sqlite-batch-insert",
        "title": "SQLite 事务批量提交性能优化",
        "content": (
            "逐条 autocommit 插入 1 万行可能要数十秒（每条独立 fsync），包进单事务可降到亚秒级。"
            "进一步优化：PRAGMA synchronous=OFF（仅构建期）、journal_mode=WAL 减少锁窗口、"
            "prepared statement 复用。注意单事务别包过大（数十万行）导致内存峰值与锁持有过久。"
        ),
        "type": "lesson",
        "tags": ["sqlite", "performance"],
        "queries": ["SQLite 批量插入很慢怎么优化"],
    },
    {
        "key": "sqlite-corruption-recovery",
        "title": "SQLite 数据库损坏检测与恢复步骤",
        "content": (
            "检测：PRAGMA integrity_check 全量校验（大库用 quick_check）。损坏信号包括 "
            "'database disk image is malformed' 与 integrity_check 报错。恢复顺序：先备份三件套"
            "（.db/-wal/-shm），尝试 .recover 命令导出可救数据到新库；有 MD+_meta 事实源时"
            "优先从源重建而不是修库。禁止对损坏库直接写入。"
        ),
        "type": "procedure",
        "tags": ["sqlite", "recovery"],
        "queries": ["SQLite 报 malformed 怎么恢复"],
    },
    {
        "key": "sqlite-pragma-sync",
        "title": "PRAGMA synchronous 三档对性能与可靠性的影响",
        "content": (
            "synchronous 控制 fsync 策略：FULL 每次提交都 fsync，最安全最慢；NORMAL 在 WAL "
            "模式下只在 checkpoint 时 fsync，正常运行不会丢已提交事务（仅断电可能丢最近 "
            "checkpoint 之后的部分）；OFF 完全不等 fsync。本地工具型应用 WAL + NORMAL 是"
            "性能与安全的平衡点。"
        ),
        "type": "fact",
        "tags": ["sqlite", "pragma"],
        "queries": ["synchronous 参数怎么设置"],
    },
    {
        "key": "sqlite-sync-normal-safe",
        "title": "结论：WAL 模式下 synchronous=NORMAL 足够安全",
        "content": (
            "实测与官方文档一致：WAL + synchronous=NORMAL 时事务提交只写 wal 不 fsync，"
            "应用崩溃不丢事务（数据已在 OS 页缓存，进程退出不影响），只有操作系统断电/宕机"
            "才可能丢最后一段 wal。对单机知识库这类可重建数据，NORMAL 完全够用，"
            "FULL 的 fsync 开销不值得。"
        ),
        "type": "fact",
        "tags": ["sqlite", "pragma", "wal"],
        "queries": ["WAL 下 NORMAL 会丢事务吗"],
    },
    {
        "key": "sqlite-sync-normal-unsafe",
        "title": "观点：synchronous=NORMAL 存在丢事务风险需谨慎",
        "content": (
            "注意：synchronous=NORMAL 在 WAL 模式下事务提交不做 fsync，wal 内容停留在 "
            "OS 页缓存；断电时已提交事务可能丢失。若业务把 commit 当作持久化承诺"
            "（例如同步前最后一步写入），应临时切换 FULL 提交关键事务，或在同步流程中"
            "显式 wal_checkpoint 后再分发文件。"
        ),
        "type": "constraint",
        "tags": ["sqlite", "pragma", "wal"],
        "conflict_with": "sqlite-sync-normal-safe",
    },
    {
        "key": "sqlite-rollback-journal-legacy",
        "title": "旧经验：rollback journal 模式下的调优（已被 WAL 取代）",
        "content": (
            "2023 年之前的经验：默认 journal 模式下删除热日志依赖 journal_size_limit 控制"
            "文件膨胀，写并发差需要长 busy_timeout。自全量切换 WAL 模式后这些调优不再适用，"
            "仅作历史参考。"
        ),
        "type": "reference",
        "tags": ["sqlite", "wal", "journal"],
        "stale": True,
    },
    {
        "key": "sqlite-vacuum-shrink",
        "title": "SQLite 空间回收：auto_vacuum 与 VACUUM 时机",
        "content": (
            "删除行后文件不自动缩小：VACUUM 全量重建文件回收空间（需要 2 倍磁盘余量与独占锁），"
            "auto_vacuum=INCREMENTAL 可增量回收。建议在低峰期手工 VACUUM，或把重建"
            "（dump → 新库）作为日常维护手段，顺带消除碎片。VACUUM 后所有索引统计清零，"
            "重要查询前跑一次 ANALYZE。"
        ),
        "type": "fact",
        "tags": ["sqlite", "performance", "maintenance"],
        "queries": ["删了数据文件为什么不变小"],
    },
    # ---------------- 检索 ----------------
    {
        "key": "retrieval-bm25-formula",
        "title": "BM25 算法公式推导与参数 k1、b 的作用",
        "content": (
            "BM25 打分：score = IDF(qi) * f(qi,D)*(k1+1) / (f(qi,D) + k1*(1-b+b*|D|/avgdl))。"
            "k1 控制词频饱和（越大越允许高频词继续加分，常用 1.2~2.0）；b 控制文档长度归一化"
            "（b=1 完全按长度惩罚，b=0 不惩罚，常用 0.75）。中文短查询场景 b 调低到 0.3~0.5 "
            "往往更稳。"
        ),
        "type": "fact",
        "tags": ["retrieval", "bm25"],
        "queries": ["BM25 公式推导", "BM25 参数 k1 b 怎么调"],
    },
    {
        "key": "retrieval-idf-small-corpus",
        "title": "IDF 变体与小语料多词搜索问题",
        "content": (
            "标准 IDF = ln((N-df+0.5)/(df+0.5)+1)。小语料下若查询词出现在多数文档，IDF 趋近 0 "
            "导致多词查询打分坍缩（所有文档分数接近）。rank-bm25 的默认公式在语料 < 几百条时"
            "该问题明显；改用 ln(1 + (N-df+0.5)/(df+0.5)) 并对负值截断可显著缓解。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "bm25", "idf"],
        "queries": ["小语料 BM25 多词查询打分失真"],
    },
    {
        "key": "retrieval-custom-bm25-decision",
        "title": "决策：自定义 BM25 替换 rank-bm25",
        "content": (
            "决定用约 300 行自研 BM25（修复 IDF 公式 + 集成 CJK 分词 + 内容指纹缓存）替换 "
            "rank-bm25 依赖。动机：rank-bm25 的 BM25Okapi IDF 公式在小语料多词查询下打分坍缩，"
            "且不支持按需重建增量更新。自研版保持接口最小（add/build/search），测试对齐 "
            "trec_eval 参考实现。"
        ),
        "type": "decision",
        "tags": ["retrieval", "bm25", "decision"],
        "queries": ["为什么自己写 BM25 不用 rank-bm25"],
    },
    {
        "key": "retrieval-cjk-tokenize",
        "title": "CJK 分词对 BM25 的影响与 n-gram 方案",
        "content": (
            "中文按字 bigram 切分是免词典的稳妥方案：召回稳定、实现简单，代价是索引膨胀约 2 倍。"
            "jieba 等词典分词精度更高但新词/专有名词（如 Qoder、驿氪）易切碎，需要自定义词典。"
            "混合做法：词典分词 + 未登录词回退 bigram。BM25 对分词粒度敏感，切换分词器必须"
            "全量重建索引。"
        ),
        "type": "fact",
        "tags": ["retrieval", "bm25", "cjk"],
        "queries": ["中文分词对 BM25 有什么影响"],
    },
    {
        "key": "retrieval-rrf-fusion",
        "title": "RRF 融合公式与 k=60 经验值",
        "content": (
            "Reciprocal Rank Fusion：score(d) = Σ 1/(k + rank_i(d))，把多路召回的排名融合，"
            "k 越大各路权重越平（默认 60 来自论文，实际 20~100 差异不大）。RRF 只用排名不用"
            "原始分数，天然规避 BM25 分数与余弦相似度不可比的问题，是多路融合的首选基线。"
        ),
        "type": "fact",
        "tags": ["retrieval", "rrf", "hybrid"],
        "queries": ["RRF 融合是怎么算的", "多路召回分数怎么融合"],
    },
    {
        "key": "retrieval-vector-cosine",
        "title": "向量检索：余弦相似度与向量归一化",
        "content": (
            "文本语义检索常用余弦相似度 = dot(a,b)/(|a||b|)，只看方向不看模长。若入库前统一"
            "L2 归一化，余弦退化为点积，可用矩阵乘法批量加速（numpy 一行）。注意 fastembed "
            "输出的向量未强制归一化，相似度计算时必须显式除以模长，否则长文本得分系统性偏高。"
        ),
        "type": "fact",
        "tags": ["retrieval", "vector", "embedding"],
        "queries": ["余弦相似度怎么算", "向量检索为什么要归一化"],
    },
    {
        "key": "retrieval-hybrid-complement",
        "title": "混合检索中 BM25 与向量互补的典型场景",
        "content": (
            "BM25 强在精确词匹配（错误码 1048、命令名 wal_checkpoint、专有名词），向量强在"
            "同义改写（'闪退'≈'异常退出'）。典型失败案例：纯向量检索把 'SQLite 锁' 检到 "
            "'分布式锁'；纯 BM25 搜 '数据库很慢' 找不到 '查询延迟优化'。因此生产检索一律"
            "双路召回 + RRF，单路仅作基线对照。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "hybrid", "bm25"],
        "queries": ["为什么需要混合检索"],
    },
    {
        "key": "retrieval-metrics",
        "title": "检索指标 Recall@K、MRR、NDCG@10 的含义与选择",
        "content": (
            "Recall@K 衡量前 K 找回多少相关文档（多答案任务看它）；MRR 看第一个相关文档的排名"
            "倒数（单答案问答）；NDCG@10 引入分级相关性与位置折扣（0-3 档相关性时最有区分度）。"
            "Useful@K = 前 K 中相关（≥2 档）占比，直接对应'喂给 Agent 的上下文有效浓度'。"
            "评估集每查询至少 3 条判定才稳定。"
        ),
        "type": "fact",
        "tags": ["retrieval", "eval"],
        "queries": ["Recall 和 NDCG 有什么区别", "检索指标怎么选"],
    },
    {
        "key": "retrieval-rerank-weights",
        "title": "多信号重排权重调优经验",
        "content": (
            "重排权重初版：RRF 0.38 / confidence 0.13 / importance 0.16 / freshness 0.13 / "
            "usage 0.08 / intent 0.12。调优教训：usage 权重超过 0.15 会让热门记忆霸榜，"
            "冷门新记忆永无出头之日；freshness 对'事实类'记忆要弱（长期有效），对'状态类'"
            "要强，所以按意图自适应调整比全局固定好。每次调权必须跑基线回归。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "rerank"],
        "queries": ["重排权重怎么调", "usage 权重过高有什么问题"],
    },
    {
        "key": "retrieval-query-negation",
        "title": "查询意图识别与否定词处理",
        "content": (
            "查询分析阶段抽取 key_terms、短语、实体与否定词。含否定词（'不要'、'排除'、'禁用'）"
            "的查询，对包含被否定对象的文档施加惩罚而非加分；'怎么避免 X' 类查询的目标文档"
            "常同时包含 X 与规避手段，靠否定惩罚压低'直接使用 X'的文档。意图分为 factual/"
            "procedural/troubleshooting 等，影响重排的 type 偏好。"
        ),
        "type": "fact",
        "tags": ["retrieval", "query"],
        "queries": ["否定词在检索里怎么处理"],
    },
    {
        "key": "retrieval-diversity-filter",
        "title": "多样性过滤避免同类型记忆霸榜",
        "content": (
            "前 K 全是同 type（如同为 fact）会让上下文信息面狭窄。多样性过滤限制每 type "
            "最多 N 条（如 3），其余位置留给其他类型。副作用：若某个 type 天然高度相关，"
            "截断会损失 Recall；因此只在 full_pipeline 末端启用，且 max_per_type 设宽松值，"
            "用评测确认 Recall@10 不回退再上线。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "diversity"],
        "queries": ["多样性过滤是什么"],
    },
    {
        "key": "retrieval-keyword-only-legacy",
        "title": "旧方案：纯关键词 LIKE 检索（已被混合检索取代）",
        "content": (
            "2023 年初版用 SQL LIKE '%词%' 做检索，无相关性排序、无分词、超过 1 万条后"
            "全表扫描延迟不可接受。同年替换为 BM25 + 向量混合检索。该条目仅记录演进历史，"
            "方案本身已废弃。"
        ),
        "type": "reference",
        "tags": ["retrieval", "legacy"],
        "stale": True,
    },
    {
        "key": "retrieval-stale-detection",
        "title": "过时记忆的时间信号与下沉策略",
        "content": (
            "过时判定信号：valid_to 早于当前时间、被 supersedes 关系指向、内容含明确废弃词"
            "（'已废弃'、'旧方案'）。处理用下沉（temporal_score 给 0.1 底分）而非硬过滤："
            "部分查询就是来找历史方案的（'当年为什么用哨兵'），硬过滤会伤害这类回溯查询，"
            "下沉让它们仍可被找到只是排名靠后。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "temporal", "stale"],
        "queries": ["过时的记忆怎么处理"],
    },
    {
        "key": "retrieval-context-budget",
        "title": "上下文组装的 Token 预算与压缩档位",
        "content": (
            "上下文组装不是把召回全塞给模型：先按 CJK 感知估算 Token，预算档位 500/1000/"
            "2000/4000/8000。超预算逐级压缩：单条裁剪（每条≤预算 25%）、段落级截断、"
            "相似条目合并（余弦≥0.85）、最后降级只保留最高优先级。压缩必须保头尾"
            "（结论与适用范围），中段细节可牺牲。"
        ),
        "type": "fact",
        "tags": ["retrieval", "context", "assembly"],
        "queries": ["上下文超预算了怎么压缩"],
    },
    {
        "key": "retrieval-relevant-but-not-useful",
        "title": "区分'相关'与'该进上下文'：组装层的取舍",
        "content": (
            "检索相关 ≠ 应该进上下文。组装层要额外考虑：时间有效性（过期事实降权）、"
            "置信度（低置信标注'未验证'）、冲突未决（成对出现时附加矛盾警告而非只给一方）、"
            "重复信息（同结论多来源只留最完整一条）。'找到 50 条相关记忆但塞 8 条最有用的'"
            "比'塞 20 条相关'对下游任务效果更好。"
        ),
        "type": "lesson",
        "tags": ["retrieval", "context", "assembly"],
        "queries": ["相关记忆都要放进上下文吗"],
    },
    # ---------------- Embedding ----------------
    {
        "key": "embedding-bge-model",
        "title": "BAAI/bge-small-zh-v1.5 模型特性与 512 维输出",
        "content": (
            "bge-small-zh-v1.5 是北京智源开源的中文小模型：33M 参数、输出 512 维、"
            "支持 512 token 上下文，CPU 推理单条约毫秒级，适合本地部署。输入建议加"
            "指令前缀 '为这个句子生成表示以用于检索相关文章：'（bge 系列训练约定），"
            "中文检索任务上效果优于同量级 multilingual 模型。"
        ),
        "type": "fact",
        "tags": ["embedding", "model"],
        "queries": ["bge-small-zh 是什么模型", "embedding 模型怎么选"],
    },
    {
        "key": "embedding-fastembed-onnx",
        "title": "fastembed 本地 ONNX 推理的优势",
        "content": (
            "fastembed 不依赖 PyTorch，直接跑量化 ONNX 权重：安装体积小、冷启动快、"
            "CPU 上吞吐稳定，模型首次下载后离线可用。相比 sentence-transformers "
            "省去 torch 依赖（数 GB），代价是可调参数少（不能 fine-tune 推理配置）。"
            "对本地单机记忆系统，推理可控性与体积优势远大于灵活性损失。"
        ),
        "type": "fact",
        "tags": ["embedding", "fastembed", "model"],
        "queries": ["为什么用 fastembed"],
    },
    {
        "key": "embedding-fallback-observe",
        "title": "embedding 服务降级识别与外部观测",
        "content": (
            "本地模型加载失败时 embedding 服务静默降级（is_fallback=True，返回 None），"
            "检索只剩 BM25 单路，效果劣化但流程不报错——这类'静默半瘫'最危险。观测手段："
            "/v1/metrics 暴露 provider 状态与 vector_count；调用方在写入候选时若 embedding "
            "为 None 记录 warning 日志；运维看板对 vector 占比低于 90% 告警。"
        ),
        "type": "issue",
        "tags": ["embedding", "fallback", "monitoring"],
        "queries": ["embedding 模型挂了怎么发现"],
    },
    {
        "key": "embedding-dual-write",
        "title": "embedding 双写架构：单一任务规范写入 + 恢复信号链",
        "content": (
            "向量写入有并发陷阱：两个任务同时为同一记忆生成 embedding，后写者可能用旧内容"
            "覆盖新内容。架构约束：每个记忆的 embedding 生成由单一任务独占（generate_embedding "
            "任务按 memory_id 去重入队），写入用乐观锁（WHERE version=?），失败即回队列重试。"
            "文件侧 vectors.npz 由该任务统一更新，带版本守卫防止旧数据回写。"
        ),
        "type": "pattern",
        "tags": ["embedding", "architecture"],
        "queries": ["embedding 双写架构是什么"],
    },
    {
        "key": "embedding-index-corruption",
        "title": "向量索引损坏检测与重建流程",
        "content": (
            "vectors.npz 损坏信号：加载时 shape 不一致、行数与 DB 记忆数不等、出现 NaN。"
            "启动时做轻量校验（行数 + 范数分布），不一致触发只重建索引（不重算 embedding，"
            "从 DB 的 embedding 列恢复，数秒完成）；npz 彻底丢失才需要调模型全量重算。"
            "重建完成后校验行数与 cosine 邻居抽样一致。"
        ),
        "type": "lesson",
        "tags": ["embedding", "index", "recovery"],
        "queries": ["向量索引坏了怎么重建"],
    },
    {
        "key": "embedding-dedup-threshold",
        "title": "语义相似度阈值与重复检测的多信号设计",
        "content": (
            "重复检测不能只看单一余弦阈值：0.90 以上大概率重复，0.75~0.90 灰色地带必须引入"
            "第二信号（BM25 词重叠、标题相似、时间接近、来源相同）做加权判定。纯阈值方案的"
            "两类错误：同义改写被判不重复（堆积）、主题相似但结论不同的记忆被误合并（丢信息）。"
            "阈值调整必须跑标注好的去重评测集。"
        ),
        "type": "lesson",
        "tags": ["embedding", "dedup"],
        "queries": ["重复检测阈值怎么定"],
    },
    {
        "key": "embedding-dedup-threshold-enough",
        "title": "观点：相似度 0.85 单阈值判重复已足够",
        "content": (
            "实践观点：对规范写入的记忆库，内容来源可控，余弦相似度 >0.85 即可判重复、"
            "0.75~0.85 判待复核，多信号加权是过度设计，增加排查成本却收益有限。"
            "先用单阈值上线，误判率可接受就不加复杂度。"
        ),
        "type": "opinion",
        "tags": ["embedding", "dedup"],
        "conflict_with": "embedding-dedup-threshold",
    },
    {
        "key": "embedding-batch-embedding",
        "title": "批量 embedding 的吞吐优化",
        "content": (
            "逐条调 generate_embedding 会反复触发 tokenize 开销；批接口把多条文本一次"
            "送入 ONNX，吞吐提升 3~5 倍。重建索引时按 64~128 条分批，批间让出事件循环"
            "避免阻塞 API。注意批接口对空列表要直接返回空，且保持与单条相同的输入前缀"
            "处理，否则批量与单条生成的向量不一致。"
        ),
        "type": "lesson",
        "tags": ["embedding", "performance"],
        "queries": ["embedding 批量生成怎么优化"],
    },
    # ---------------- 任务队列 ----------------
    {
        "key": "task-retry-backoff-dlq",
        "title": "异步任务重试：指数退避 + 死信模式",
        "content": (
            "任务失败重试用指数退避（1s/2s/4s，上限 3 次），避免瞬时故障下的无效重试风暴。"
            "超过重试上限的任务进死信状态：保留任务体与错误信息、不再自动调度、"
            "可人工检查后重新入队。没有死信的队列会把失败静默丢弃，问题累积到用户可见才爆发。"
        ),
        "type": "pattern",
        "tags": ["taskqueue", "retry"],
        "queries": ["任务重试策略怎么设计", "指数退避是什么"],
    },
    {
        "key": "task-crash-recovery",
        "title": "任务落盘后、执行前崩溃的恢复语义",
        "content": (
            "可靠性边界：任务入队即落盘（PENDING 状态持久化到磁盘 JSON，2 秒周期原子写），"
            "执行前进程崩溃则重启后从磁盘恢复 PENDING 任务重新调度；执行成功但确认前崩溃"
            "会重复执行一次，因此任务必须幂等（副作用以 DB 唯一约束或状态检查兜底）。"
            "RUNNING 状态崩溃的任务不落盘，靠启动时按 DB 现状对账补齐。"
        ),
        "type": "lesson",
        "tags": ["taskqueue", "recovery"],
        "queries": ["队列崩溃后任务会丢吗"],
    },
    {
        "key": "task-idempotency-key",
        "title": "幂等键 client_write_id 防重复副作用",
        "content": (
            "客户端为每次写入生成唯一 client_write_id（重试时复用同一 ID），服务端以 "
            "(workspace_id, client_write_id) 唯一约束落库：网络超时后客户端重试不会产生"
            "重复候选。这是'至少一次投递'模型下保证'恰好一次效果'的标准手段，"
            "所有写入口（MCP/API）必须携带。"
        ),
        "type": "fact",
        "tags": ["taskqueue", "idempotency"],
        "queries": ["client_write_id 是干什么的"],
    },
    {
        "key": "task-inproc-queue-boundary",
        "title": "进程内 asyncio.Queue + 磁盘持久化的边界",
        "content": (
            "个人单机场景不需要 Redis/Celery：asyncio.Queue + PENDING 落盘 + DB 对账已覆盖"
            "崩溃恢复。边界明确：不支持多进程消费（worker 与 API 同进程）、不支持跨机、"
            "吞吐受单进程限制（够用）。引入分布式队列的触发条件是出现多实例部署需求，"
            "在那之前保持简单。"
        ),
        "type": "lesson",
        "tags": ["taskqueue", "architecture"],
        "queries": ["为什么不用 Celery"],
    },
    {
        "key": "task-lease-reconciliation",
        "title": "任务租约与 RUNNING 状态崩溃对账",
        "content": (
            "RUNNING 任务崩溃后会'消失'（内存态丢失）。两种兜底：租约制（执行前登记租约时间，"
            "后台扫描超期租约重置为 PENDING）或对账制（启动时扫描 DB 中应有而未见结果的任务"
            "重新入队）。当前实现对账制：recover_orphaned_candidates 按候选状态判断哪些任务"
            "未完成，简单直接，代价是恢复粒度只能到任务级别而非精确断点。"
        ),
        "type": "fact",
        "tags": ["taskqueue", "lease", "recovery"],
        "queries": ["RUNNING 状态的任务崩了怎么办"],
    },
    {
        "key": "task-graceful-shutdown",
        "title": "优雅关闭：10 秒排空 + 剩余任务落盘",
        "content": (
            "收到 SIGTERM 后：停止接新任务，给在跑任务 10 秒完成窗口，超时未完成的任务"
            "状态回滚为 PENDING 并触发一次同步落盘，然后退出。没做优雅关闭的进程被 "
            "kill 时，正在执行一半的任务既不在内存也不在磁盘，只能靠下次启动对账兜底，"
            "恢复窗口变长。"
        ),
        "type": "pattern",
        "tags": ["taskqueue", "shutdown"],
        "queries": ["进程关闭时任务怎么处理"],
    },
    {
        "key": "task-pending-dedup",
        "title": "PENDING 去重防止重复入队",
        "content": (
            "同一任务（如为同一候选评分）重复入队不仅浪费，还会并发写同一行引发竞态。"
            "入队前按任务键查 PENDING 集合，已存在则跳过（幂等入队）。注意去重键要包含"
            "参数（memory_id 而非任务类型），且只对 PENDING 去重——RUNNING/FAILED 的"
            "重入队是合法恢复路径。"
        ),
        "type": "lesson",
        "tags": ["taskqueue", "dedup"],
        "queries": ["重复入队怎么防"],
    },
    {
        "key": "task-infinite-retry-legacy",
        "title": "旧策略：失败任务无限重试（已废弃）",
        "content": (
            "早期版本对失败任务无限重试，遇到永久性错误（如 embedding 模型文件损坏）时"
            "任务在队列里永久打转，日志刷屏且阻塞后续任务。2025 年改为最多 3 次指数退避后"
            "进死信。该策略已废弃，仅记录演进。"
        ),
        "type": "reference",
        "tags": ["taskqueue", "retry", "legacy"],
        "stale": True,
    },
    {
        "key": "task-queue-observability",
        "title": "任务队列可观测性：积压与失败率指标",
        "content": (
            "队列健康两个核心指标：积压深度（PENDING 数量与最老任务年龄）和失败率"
            "（最近 1 小时 FAILED/总数）。积压持续增长说明消费速度跟不上生产（常见于 "
            "embedding 模型降级），失败率突增说明下游依赖故障。指标通过只读 snapshot "
            "端点暴露，面板对最老任务年龄 >5 分钟告警。"
        ),
        "type": "lesson",
        "tags": ["taskqueue", "monitoring"],
        "queries": ["队列积压怎么监控"],
    },
    {
        "key": "task-priority-ordering",
        "title": "任务优先级：审核链路任务优先于后台演化",
        "content": (
            "同一队列内任务分优先级：用户可见链路（候选评分、embedding 生成）优先于"
            "后台演化（自动合并、健康分重算）。否则批量后台任务涌入时，用户刚提交的"
            "候选要等几分钟才评分，审核体验明显劣化。实现：入队时带 priority，"
            "消费按优先级 + FIFO 取任务。"
        ),
        "type": "lesson",
        "tags": ["taskqueue", "priority"],
        "queries": ["队列任务怎么排优先级"],
    },
    # ---------------- 工程实践 ----------------
    {
        "key": "eng-fastapi-depends-yield",
        "title": "FastAPI 依赖注入与 yield 清理模式",
        "content": (
            "用 yield 的依赖在请求结束后执行清理（关闭会话），异常时也能保证执行。"
            "注意：yield 前的代码在请求开始时运行，异常会跳过 yield 后清理除非包 try/finally；"
            "依赖的缓存（use_cache=True 默认）意味着同一请求内多次注入共享同一实例——"
            "对 DB 会话是期望行为，对每次需要新实例的资源要显式 use_cache=False。"
        ),
        "type": "fact",
        "tags": ["engineering", "fastapi"],
        "queries": ["FastAPI yield 依赖怎么用"],
    },
    {
        "key": "eng-pydantic-v2-validate",
        "title": "Pydantic v2 的 model_validate 与构造差异",
        "content": (
            "v2 中 Model(**data) 走 validate，但 dict 里的额外字段默认报错（v1 是忽略）；"
            "从 ORM 对象构造用 model_validate(obj, from_attributes=True)（v1 的 orm_mode "
            "改名）。字段别名 populate_by_name 默认关闭，API 收 alias 发 camelCase 时"
            "要注意响应 model_dump(by_alias=True)。升级坑集中在这些默认值变化。"
        ),
        "type": "lesson",
        "tags": ["engineering", "pydantic"],
        "queries": ["Pydantic v2 迁移有什么坑"],
    },
    {
        "key": "eng-alembic-vs-createall",
        "title": "Alembic 迁移与 create_all 的边界",
        "content": (
            "create_all 只建缺失的表，不改已有表结构——开发期方便，生产必须 Alembic："
            "任何列变更都走迁移脚本，可重放、可回滚、可审查。新库初始化可用 alembic "
            "upgrade head 一步到位。约定：迁移脚本一旦合入主线禁止修改（只追加新迁移），"
            "避免多设备迁移图分叉。"
        ),
        "type": "fact",
        "tags": ["engineering", "alembic"],
        "queries": ["什么时候用 Alembic 什么时候 create_all"],
    },
    {
        "key": "eng-mypy-strict-conventions",
        "title": "mypy strict 下的类型标注约定",
        "content": (
            "全库 strict 模式约定：所有函数签名显式标注；可选参数用 | None 不用 Optional；"
            "第三方无 stub 的依赖补 mypy override ignore_missing_imports；禁止 type: ignore "
            "裸压制（必须带错误码注释原因）。async 函数返回 AsyncGenerator 时标注用"
            " collections.abc.AsyncGenerator。新代码 CI 不过 mypy 不许合入。"
        ),
        "type": "convention",
        "tags": ["engineering", "typing"],
        "queries": ["mypy strict 有什么约定"],
    },
    {
        "key": "eng-asyncio-taskgroup",
        "title": "asyncio 任务组与异常传播语义",
        "content": (
            "Python 3.11 TaskGroup 比 gather 语义更安全：任一子任务抛异常会取消其余任务并"
            "抛 ExceptionGroup。注意嵌套异常捕获要 except* 而非 except；gather(return_exceptions=True) "
            "适合'允许部分失败'的场景，TaskGroup 适合'全有或全无'。并发上限用 Semaphore "
            "包装任务体，不要依赖 TaskGroup 自身的并发控制（它不限制并发数）。"
        ),
        "type": "fact",
        "tags": ["engineering", "asyncio"],
        "queries": ["TaskGroup 和 gather 的区别"],
    },
    {
        "key": "eng-aiosqlite-staticpool",
        "title": "aiosqlite + StaticPool 的单连接语义",
        "content": (
            "SQLite 异步访问用 StaticPool（单连接复用）避免多连接写锁竞争；代价是所有"
            "查询在同一连接上串行——长查询会阻塞后续查询。不要在请求路径上跑重分析查询；"
            "WAL 模式下读写不互斥但仍共享这一个连接。批量操作显式开事务，避免每条语句"
            "隐式事务的额外开销。"
        ),
        "type": "lesson",
        "tags": ["engineering", "sqlite", "asyncio"],
        "queries": ["aiosqlite 为什么要用 StaticPool"],
    },
    {
        "key": "eng-ruff-config",
        "title": "ruff lint + format 双职责配置约定",
        "content": (
            "ruff 同时承担 lint（E/F/I/B/UP 等规则集）与 format（替代 black/isort）。"
            "配置约定：行宽 100；lint 排除 migrations 目录；import 排序 I001 必须开；"
            "格式化与 lint 分开跑（ruff format 只管格式，规则不叠加）。pre-commit 与 CI "
            "跑同一份 pyproject 配置，避免本地与远端规则漂移。"
        ),
        "type": "convention",
        "tags": ["engineering", "ruff"],
        "queries": ["ruff 配置有什么约定"],
    },
    {
        "key": "eng-pytest-asyncio-auto",
        "title": "pytest asyncio_mode=auto 的注意事项",
        "content": (
            "asyncio_mode=auto 让 async 测试函数无需 @pytest.mark.asyncio 装饰，但注意："
            "fixture 也自动包 event loop，跨测试共享的异步资源（如引擎）要在 "
            "session 级 fixture 手动管理生命周期；每个测试默认新 loop，模块级连接池会"
            "绑定到已关闭的 loop 导致 'attached to a different loop' 报错。"
            "DB 测试用独立的内存库 fixture 而不是复用全局 engine。"
        ),
        "type": "lesson",
        "tags": ["engineering", "pytest"],
        "queries": ["pytest 异步测试报 different loop 怎么回事"],
    },
    {
        "key": "eng-sqlalchemy-expire-commit",
        "title": "SQLAlchemy async session 的 expire_on_commit 陷阱",
        "content": (
            "默认 expire_on_commit=True：commit 后访问属性会触发懒刷新，async 上下文里"
            "这是同步 IO，直接报 MissingGreenlet 错误。async 应用约定 expire_on_commit=False，"
            "提交后对象属性保持可用。代价是 commit 后别的会话改了数据本会话看不到旧值——"
            "需要最新数据时显式 refresh。"
        ),
        "type": "lesson",
        "tags": ["engineering", "sqlalchemy", "asyncio"],
        "queries": ["MissingGreenlet 报错怎么解决"],
    },
    {
        "key": "eng-requests-legacy",
        "title": "旧模式：requests 同步调用（已全面异步化）",
        "content": (
            "2024 年之前后端用 requests 同步调外部接口，在 FastAPI 异步路由里直接调用会"
            "阻塞事件循环，当时用线程池绕过。现已全面迁移 httpx.AsyncClient，"
            "requests 依赖已从 requirements 移除。此条目仅记录历史。"
        ),
        "type": "reference",
        "tags": ["engineering", "asyncio", "legacy"],
        "stale": True,
    },
    {
        "key": "eng-uvicorn-reload-prod",
        "title": "uvicorn 开发 reload 与生产模式的差异",
        "content": (
            "开发用 --reload（文件变更自动重启，多进程 watcher 内存翻倍属正常）；生产禁止 "
            "reload，worker 数按 CPU 定（SQLite 单写者场景 1 个 worker 即可，多了反而写锁竞争）。"
            "优雅关闭依赖 uvicorn 的 timeout-graceful-shutdown 设置，要与任务队列的排空窗口"
            "对齐（队列 10 秒排空则 uvicorn 至少给 12 秒）。"
        ),
        "type": "fact",
        "tags": ["engineering", "fastapi", "deploy"],
        "queries": ["uvicorn 生产模式要注意什么"],
    },
    # ---------------- 业务决策 ----------------
    {
        "key": "biz-member-registration",
        "title": "决策：新会员注册链路落库方案（1048→1、200→0）",
        "content": (
            "新会员注册改为注册链路直接落库：CRM 状态 1048 收敛为 1（正式会员），"
            "返回码 200 收敛为 0（成功）。仅 external 渠道传值时才走旧状态映射，"
            "内部调用一律新语义。上线前需要下游 3 个消费方同步改映射表，"
            "灰度两周按渠道逐步放量。"
        ),
        "type": "decision",
        "tags": ["business", "member", "decision"],
        "queries": ["新会员注册落库方案是什么"],
    },
    {
        "key": "biz-member-prefilter",
        "title": "注册前置精简查询校验规则（200/1048 放行）",
        "content": (
            "注册前置校验精简：手机号命中 200（已注册）与 1048（待激活）直接放行进入"
            "激活流程，其余状态码阻断并提示。目的是砍掉注册页对 CRM 的二次查询（平均 "
            "180ms）。注意 1048 放行后必须带原会员 ID 进入激活，否则会建重复档案。"
        ),
        "type": "decision",
        "tags": ["business", "member", "validation"],
        "queries": ["注册前置校验怎么放行"],
    },
    {
        "key": "biz-yike-outbound",
        "title": "驿氪出站接口对接约束（1308 取消券核销）",
        "content": (
            "对接驿氪出站接口约束：所有出站请求带时间戳 + 签名（HMAC-SHA256），时间戳容差 "
            "5 分钟；1308 场景（取消券核销）必须幂等——同核销单号重复推送只生效一次，"
            "以我方核销流水表唯一约束兜底。对方接口无沙箱，联调只能灰度环境小流量验证。"
        ),
        "type": "convention",
        "tags": ["business", "integration", "convention"],
        "queries": ["驿氪接口对接有什么约束"],
    },
    {
        "key": "biz-content-template",
        "title": "决策：自由内容系统模板从固定分段改为可选维度",
        "content": (
            "自由内容系统的模板机制重构：从固定三段（头图/正文/尾部）改为可选维度组合"
            "（每个维度独立启用与排序），商家可按需拼装。旧模板数据迁移时把三段映射为"
            "三个默认启用的维度，保证存量页面渲染不变。新模板 ID 规则 T{version}-{seq}。"
        ),
        "type": "decision",
        "tags": ["business", "content", "decision"],
        "queries": ["内容系统模板为什么重构"],
    },
    {
        "key": "biz-coupon-1308-flow",
        "title": "1308 取消券核销的完整流程与补偿",
        "content": (
            "取消券核销（1308）流程：接收推送 → 校验签名与时间戳 → 核销流水幂等检查 → "
            "冲减核销记录 → 回写状态。补偿机制：回写失败进重试队列（退避 3 次），"
            "超过后转人工对账表。月度对账以驿氪侧对账文件为准，差异行人工核对后"
            "用管理端补偿接口修正。"
        ),
        "type": "fact",
        "tags": ["business", "coupon"],
        "queries": ["1308 取消核销的流程是什么"],
    },
    {
        "key": "biz-contract-extend",
        "title": "拓展合同、补充合同与子合同的覆盖逻辑区分",
        "content": (
            "三类合同的覆盖语义不同：拓展合同继承主合同条款但可新增条目；补充合同只能"
            "修改主合同明确允许的字段（价格、期限），其余字段强制继承；子合同完全独立"
            "生成，只引用主合同 ID 不继承内容。生成逻辑按类型走不同模板分支，"
            "曾因混淆补充与子合同导致条款丢失，修复后加了继承字段 diff 测试。"
        ),
        "type": "lesson",
        "tags": ["business", "contract"],
        "queries": ["补充合同和子合同有什么区别"],
    },
    {
        "key": "biz-apollo-priority",
        "title": "Apollo bootstrap 配置优先级高于本地 application.yml",
        "content": (
            "Apollo 接入采用 bootstrap 模式：启动阶段拉取的远端配置优先级高于本地 "
            "application.yml，本地文件只作为 Apollo 不可用时的兜底。坑：bootstrap 拉取"
            "失败会静默用本地值，环境间差异（如数据库地址）不易发现——上线检查清单必须"
            "包含启动日志中 Apollo 版本号的核对。"
        ),
        "type": "fact",
        "tags": ["business", "apollo", "config"],
        "queries": ["Apollo 配置和本地 yml 谁优先"],
    },
    {
        "key": "biz-apollo-namespace",
        "title": "Apollo 命名空间与灰度发布实践",
        "content": (
            "公共配置放公共命名空间（common-db、common-mq），应用私有配置放私有命名空间；"
            "灰度发布用 Apollo 的灰度实例功能按机器 IP 分批生效。注意公共 namespace 修改"
            "影响所有引用方，变更必须走审批并在公告群提前通知。回滚靠发布历史一键回退，"
            "灰度未全量前禁止删旧配置项。"
        ),
        "type": "fact",
        "tags": ["business", "apollo"],
        "queries": ["Apollo 灰度发布怎么用"],
    },
    {
        "key": "biz-member-status-codes",
        "title": "会员状态码 200/1048 语义速查",
        "content": (
            "CRM 会员状态码语义：200=已注册正式会员；1048=已注册待激活；1=正常在册；"
            "0=注销。1048 用户完成激活后转 1，激活有效期 30 天，过期回 200 需重新走激活。"
            "对接新系统时不要硬编码状态码，统一走映射表，CRM 侧新增码位时映射表加默认"
            "阻断策略。"
        ),
        "type": "lesson",
        "tags": ["business", "member", "api"],
        "queries": ["1048 状态码是什么意思"],
    },
    {
        "key": "biz-outbound-signature",
        "title": "出站接口签名与时间戳容差约定",
        "content": (
            "所有第三方出站接口统一签名约定：参数按 key 字典序拼接 + appSecret 做 "
            "HMAC-SHA256，时间戳参与签名且服务端校验容差 5 分钟（防重放）。时间戳用秒级；"
            "容器环境必须开启 NTP 校时——曾因宿主机时钟漂移 7 分钟导致整批请求签名失败。"
        ),
        "type": "convention",
        "tags": ["business", "integration", "security"],
        "queries": ["出站接口签名怎么做的"],
    },
    {
        "key": "biz-tenant-id-passing",
        "title": "多租户请求中 tenant_id 的传递约定",
        "content": (
            "约定：租户上下文不依赖调用方显式传参，由网关注入请求头 X-Tenant-Id，"
            "后端中间件解析后放入 contextvar，Repository 层统一拼查询条件。"
            "禁止业务代码直接读请求头取租户（容易漏）；禁止把 tenant_id 放进 URL "
            "路径（缓存键爆炸且越权风险）。跨服务调用必须透传该头。"
        ),
        "type": "convention",
        "tags": ["business", "integration", "security"],
        "queries": ["租户 ID 怎么传递"],
    },
    {
        "key": "biz-gray-release-checklist",
        "title": "灰度发布检查清单（业务系统）",
        "content": (
            "灰度前检查：DB 变更向前兼容（新旧代码可同时跑）、回滚方案演练过、"
            "监控面板与告警就位、依赖方通知确认。灰度中观察：错误率、核心接口 P95、"
            "业务对账差异。放量节奏 1% → 10% → 50% → 100%，每档至少观察一个业务高峰。"
            "任何异常先回滚再排查，禁止带病放量。"
        ),
        "type": "procedure",
        "tags": ["business", "decision", "ops"],
        "queries": ["灰度发布要检查什么"],
    },
    # ---------------- 部署运维 ----------------
    {
        "key": "ops-docker-multistage",
        "title": "Docker 镜像多阶段构建瘦身流程",
        "content": (
            "Python 镜像多阶段构建：builder 阶段装依赖并编译（用系统镜像带 gcc），"
            "runtime 阶段只拷贝 site-packages 与代码，基础镜像 python:3.12-slim。"
            "瘦身要点：合并 RUN 层清理 apt 缓存、.dockerignore 排除 .venv 与测试数据、"
            "pip 用 --no-cache-dir。典型效果从 1.2GB 降到 280MB。"
        ),
        "type": "procedure",
        "tags": ["ops", "docker"],
        "queries": ["Docker 镜像怎么瘦身"],
    },
    {
        "key": "ops-github-tuna-mirror",
        "title": "GitHub 大文件下载走 TUNA 镜像",
        "content": (
            "国内环境 GitHub 大文件（模型权重、release 资产）直连经常超时或只有 KB 级速度。"
            "方案：gitclone 场景用 ghproxy 前缀；原始文件用 TUNA 的 gh 镜像；"
            "超过 100MB 的模型优先找 huggingface 镜像站（hf-mirror.com）设置 "
            "HF_ENDPOINT 后 hf download。下载后校验 sha256 再进制品库。"
        ),
        "type": "lesson",
        "tags": ["ops", "network"],
        "queries": ["GitHub 下载慢怎么办"],
    },
    {
        "key": "ops-ci-layers",
        "title": "CI 流水线分层：lint → typecheck → test → build",
        "content": (
            "CI 分层约定：lint（ruff，秒级）最先跑快速失败；typecheck（mypy strict）与 "
            "test（pytest）并行；全绿后才 build 镜像。缓存策略：pip 依赖按 lock 文件哈希"
            "缓存、前端 node_modules 按 package-lock 缓存。评测类任务（检索基准）单独 "
            "job 可选触发，不阻塞常规 PR——但合入主线的改动必须跑过一次。"
        ),
        "type": "fact",
        "tags": ["ops", "ci"],
        "queries": ["CI 流水线怎么分层"],
    },
    {
        "key": "ops-port-occupied",
        "title": "端口占用排查与强制释放流程",
        "content": (
            "端口被占排查：lsof -i :5172 找 PID（macOS/Linux 通用），确认进程身份后再 kill。"
            "服务重启脚本内置'强制释放端口'步骤：先健康检查探测残留进程，仅当确认是本项目"
            "残留（进程命令行匹配项目路径）才 kill -9。误杀风险场景：端口被无关服务占用时"
            "应报错让人工处理而不是强杀。"
        ),
        "type": "procedure",
        "tags": ["ops", "port"],
        "queries": ["端口被占了怎么排查"],
    },
    {
        "key": "ops-backup-drill",
        "title": "数据库备份与恢复演练步骤",
        "content": (
            "备份策略：每日凌晨全量备份（sqlite 三件套一起拷贝）保留 30 天，备份后跑一次 "
            "integrity_check。恢复演练每季度一次：取两周前备份在新环境恢复 → 跑冒烟测试 → "
            "记录恢复耗时。没演练过的备份等于没有备份——曾发现备份只拷了 .db 漏了 -wal，"
            "恢复后少最后 6 小时数据，从此备份脚本改为 checkpoint 后单文件拷贝。"
        ),
        "type": "procedure",
        "tags": ["ops", "backup", "recovery"],
        "queries": ["备份恢复怎么演练"],
    },
    {
        "key": "ops-wal-sidecar-files",
        "title": "WAL 临时侧车文件（*.db-wal/*.db-shm）不参与同步",
        "content": (
            "SQLite WAL 模式运行时会产生 .db-wal 与 .db-shm 侧车文件：前者是未 checkpoint "
            "的写入，后者是共享内存索引。两者都是运行时状态，跨设备分发无意义甚至有害"
            "（错配的 wal 会导致 malformed），.gitignore 必须排除。同步前 checkpoint "
            "TRUNCATE 清空 wal，是唯一安全的分发形态。"
        ),
        "type": "lesson",
        "tags": ["ops", "sqlite", "sync"],
        "queries": ["db-wal 文件要不要提交"],
    },
    {
        "key": "ops-ftp-deploy-legacy",
        "title": "旧流程：FTP 手工部署（已被 CI 取代）",
        "content": (
            "2022 年及以前的部署方式：本地打包 → FTP 上传服务器 → 手工重启 Tomcat。"
            "曾发生上传中断导致半包部署、多人同时上传互相覆盖。2023 年迁移到 CI 流水线"
            "制品化部署后废止。保留此条目作为演进记录与警示。"
        ),
        "type": "reference",
        "tags": ["ops", "deploy", "legacy"],
        "stale": True,
    },
    {
        "key": "ops-alert-thresholds",
        "title": "监控告警阈值设定经验",
        "content": (
            "阈值设定原则：先观察一周基线再定阈值，告警阈值取基线 P95 的 1.5 倍起步；"
            "宁可少量误报也不要漏报关键路径（DB 不可用、队列积压）；每条告警必须写"
            "处理手册链接。经验值：API P95 > 500ms 告警、队列最老任务 > 5 分钟告警、"
            "磁盘 > 80% 告警。告警泛滥时优先砍低价值告警而不是调高阈值硬压。"
        ),
        "type": "lesson",
        "tags": ["ops", "monitoring"],
        "queries": ["告警阈值怎么定"],
    },
    {
        "key": "ops-embed-model-cache",
        "title": "embedding 模型文件的缓存与离线分发",
        "content": (
            "fastembed 模型权重（~100MB）首次运行时下载到本地缓存目录；CI 与新环境"
            "首次跑会拉模型导致超时或失败。方案：缓存目录按模型名哈希做 actions/cache；"
            "离线环境用制品库预置模型目录并设置 HF_HOME 指向。升级模型版本必须全量"
            "重算向量——新旧向量不可混用（维度或语义空间不一致会静默劣化检索）。"
        ),
        "type": "lesson",
        "tags": ["ops", "embedding", "ci"],
        "queries": ["CI 里 embedding 模型怎么缓存"],
    },
    {
        "key": "ops-log-rotation",
        "title": "日志轮转与磁盘保护的配置约定",
        "content": (
            "服务日志必须配置轮转：按大小 100MB 保留 10 份，或按天保留 30 天，"
            "避免长跑进程把磁盘写满拖垮整机。容器环境输出 stdout 交给收集器，"
            "本地部署用 logrotate 或 logging RotatingFileHandler。曾发生日志把根分区"
            "写满导致 SQLite 写入失败，从此磁盘使用率告警阈值定在 80% 且日志目录"
            "单独分区。"
        ),
        "type": "convention",
        "tags": ["ops", "monitoring", "maintenance"],
        "queries": ["日志把磁盘写满怎么办"],
    },
    {
        "key": "ops-time-sync",
        "title": "服务器时钟同步：签名与排序的隐性依赖",
        "content": (
            "分布式签名校验、日志排序、缓存 TTL 都依赖系统时钟。约定：所有服务器开 "
            "NTP/chrony 同步；对时间敏感的接口在告警日志里带上本机与对端时间差；"
            "跨机事件排序不要用本地时间戳拼接，用数据库序列或全局 ID。"
            "容器宿主机漂移会传染所有容器，排障先查宿主机时钟。"
        ),
        "type": "lesson",
        "tags": ["ops", "network", "monitoring"],
        "queries": ["时钟不同步会有什么问题"],
    },
    # ---------------- 被取代对（archived + supersedes） ----------------
    {
        "key": "retrieval-dedup-v1",
        "title": "重复检测 v1：仅标题相似度（已归档）",
        "content": (
            "v1 方案只比较标题编辑距离判断重复，正文不同的同名记忆被大量误合并。"
            "已被 v2 多信号方案取代并归档。"
        ),
        "type": "reference",
        "tags": ["retrieval", "dedup"],
        "archived": True,
        "superseded_by": "retrieval-dedup-v2",
    },
    {
        "key": "retrieval-dedup-v2",
        "title": "重复检测 v2：四路加权相似度",
        "content": (
            "v2 重复检测在提交时执行四路加权相似度：标题语义（0.4）+ 正文余弦（0.3）+ "
            "BM25 词重叠（0.2）+ 关键实体匹配（0.1），综合分 >0.85 判重复、>0.60 判待复核。"
            "相比 v1 仅标题比较，误合并率显著下降。评测集含同义改写、增量补充、"
            "范围差异、真实矛盾四类样本。"
        ),
        "type": "pattern",
        "tags": ["retrieval", "dedup"],
        "queries": ["重复检测 v2 是怎么算的"],
    },
    {
        "key": "ops-monitor-v1",
        "title": "监控方案 v1：cron 脚本邮件告警（已归档）",
        "content": (
            "v1 用 cron 每五分钟跑 shell 脚本检查进程存活，异常发邮件。无指标曲线、"
            "无历史数据。已被 v2 指标暴露 + 面板告警方案取代。"
        ),
        "type": "reference",
        "tags": ["ops", "monitoring"],
        "archived": True,
        "superseded_by": "ops-monitor-v2",
    },
    {
        "key": "ops-monitor-v2",
        "title": "监控方案 v2：指标端点 + 面板告警",
        "content": (
            "v2 通过 /v1/metrics 暴露结构化指标（检索延迟分位数、队列深度、embedding "
            "状态、错误计数），外部面板拉取并按阈值告警。相比 v1 的进程存活检查，"
            "能发现'活着但病着'的半瘫状态。指标口径变更需同步更新告警规则。"
        ),
        "type": "pattern",
        "tags": ["ops", "monitoring"],
        "queries": ["监控 v2 的指标有哪些"],
    },
]


def _stable_hash(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)


def entry_uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"eval-fixture:{key}")


def build_fixture() -> dict:
    """生成评测 DB 与黄金数据集，返回统计信息。"""
    now = datetime.now(UTC).replace(tzinfo=None)

    if DB_PATH.exists():
        DB_PATH.unlink()
    for sidecar in (f"{DB_PATH}-wal", f"{DB_PATH}-shm"):
        Path(sidecar).unlink(missing_ok=True)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _run() -> dict:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        embedding_svc = get_embedding_service()

        async with session_maker() as db:
            ws = Workspace(id=entry_uuid("workspace"), name=WORKSPACE_NAME)
            db.add(ws)
            await db.flush()

            # 词条 → 记忆行
            memories: dict[str, Memory] = {}
            for e in CORPUS:
                h = _stable_hash(e["key"])
                created = now - timedelta(days=h % 380)
                status = "archived" if e.get("archived") else "active"
                valid_to = None
                if e.get("stale"):
                    valid_to = now - timedelta(days=30 + h % 90)
                memories[e["key"]] = Memory(
                    id=entry_uuid(e["key"]),
                    workspace_id=ws.id,
                    title=e["title"],
                    content=e["content"],
                    type=e["type"],
                    source="benchmark",
                    status=status,
                    confidence=round(0.60 + (h % 35) / 100, 2),
                    importance=round(0.55 + (h % 40) / 100, 2),
                    version=1,
                    valid_from=created,
                    valid_to=valid_to,
                    usage_count=h % 40,
                    last_used_at=now - timedelta(days=h % 60) if h % 3 else None,
                    created_at=created,
                    updated_at=created,
                )
                db.add(memories[e["key"]])
            await db.flush()

            # embedding（active 记忆全部生成，批处理）
            texts = [
                format_memory_for_embedding(m.title, m.content)
                for m in memories.values()
                if m.status == "active"
            ]
            keys = [k for k, m in memories.items() if m.status == "active"]
            vectors = await embedding_svc.generate_embeddings_batch(texts)
            if vectors is None or len(vectors) != len(texts):
                raise RuntimeError("批量 embedding 生成失败或数量不符")
            for key, vec in zip(keys, vectors, strict=True):
                if vec is None:
                    raise RuntimeError(f"embedding 为空: {key}")
                memories[key].embedding = list(vec)
            await db.flush()

            # 矛盾对 → MemoryConflict
            conflict_pairs = 0
            for e in CORPUS:
                if e.get("conflict_with"):
                    db.add(
                        MemoryConflict(
                            id=entry_uuid(f"conflict:{e['key']}"),
                            workspace_id=ws.id,
                            memory_id=memories[e["conflict_with"]].id,
                            candidate_id=None,
                            conflict_type="contradiction",
                            description=f"评测夹具矛盾对: {e['conflict_with']} vs {e['key']}",
                            status="open",
                        )
                    )
                    conflict_pairs += 1

            # 被取代对 → supersedes 关系（新 supersedes 旧）
            relations = 0
            for e in CORPUS:
                if e.get("superseded_by"):
                    db.add(
                        MemoryRelation(
                            id=entry_uuid(f"relation:{e['superseded_by']}"),
                            source_memory_id=memories[e["superseded_by"]].id,
                            target_memory_id=memories[e["key"]].id,
                            relation_type="supersedes",
                            confidence=0.95,
                        )
                    )
                    relations += 1
            await db.commit()

        await engine.dispose()
        return {"conflict_pairs": conflict_pairs, "relations": relations}

    stats = asyncio.run(_run())

    # 黄金数据集：按标签重叠度分级判定
    dataset_lines = build_gold_dataset()
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATASET_PATH, "w") as f:
        f.writelines(json.dumps(line, ensure_ascii=False) + "\n" for line in dataset_lines)

    queries = {line["query_id"] for line in dataset_lines}
    judgments = len(dataset_lines)
    meta = {
        "workspace": WORKSPACE_NAME,
        "entries": len(CORPUS),
        "active": sum(1 for e in CORPUS if not e.get("archived")),
        "stale": sum(1 for e in CORPUS if e.get("stale")),
        "archived": sum(1 for e in CORPUS if e.get("archived")),
        "conflict_pairs": stats["conflict_pairs"],
        "supersedes_relations": stats["relations"],
        "queries": len(queries),
        "judgments": judgments,
        "generated_at": now.isoformat(),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


def build_gold_dataset() -> list[dict]:
    """按标签重叠度构造判定：目标 3；共享≥2 标签 2；共享 1 标签 1（截前 3）；
    过时/矛盾对 0；跨主题采样 3 条 0。"""
    import random

    lines: list[dict] = []
    rng = random.Random(42)

    for e in CORPUS:
        if e.get("stale") or e.get("archived") or e.get("conflict_with"):
            continue
        for qi, query in enumerate(e["queries"]):
            qid = f"{e['key']}-q{qi + 1}"
            judgments: dict[str, int] = {e["key"]: 3}
            grade1_candidates: list[str] = []

            for other in CORPUS:
                if other["key"] == e["key"] or other.get("archived"):
                    continue
                shared = set(e["tags"]) & set(other["tags"])
                if not shared:
                    continue
                if other.get("stale") or other.get("conflict_with"):
                    # 过时与矛盾条目即便同主题也判 0（负例）
                    judgments[other["key"]] = 0
                elif len(shared) >= 2:
                    judgments[other["key"]] = 2
                else:
                    grade1_candidates.append(other["key"])

            for key in sorted(grade1_candidates)[:3]:
                judgments[key] = 1

            # 跨主题无关负例：采样 3 条无共享标签的条目
            no_shared = [
                o["key"]
                for o in CORPUS
                if not o.get("archived")
                and o["key"] != e["key"]
                and not (set(e["tags"]) & set(o["tags"]))
            ]
            for key in rng.sample(no_shared, min(3, len(no_shared))):
                judgments.setdefault(key, 0)

            for key, grade in judgments.items():
                lines.append(
                    {
                        "query_id": qid,
                        "query": query,
                        "memory_id": str(entry_uuid(key)),
                        "relevance": grade,
                    }
                )

    lines.sort(key=lambda x: (x["query_id"], -x["relevance"], x["memory_id"]))
    return lines


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    meta = build_fixture()
    print(json.dumps(meta, ensure_ascii=False, indent=2))
