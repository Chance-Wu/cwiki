"""上下文去重步骤测试。"""

from packages.retrieval.context.dedup import deduplicate


class TestDeduplicate:
    def test_empty_list(self):
        assert deduplicate([]) == []

    def test_no_duplicates(self):
        memories = [
            {"id": "1", "content": "use SQLite for persistence", "score": 0.9},
            {"id": "2", "content": "React frontend framework", "score": 0.8},
        ]
        result = deduplicate(memories)
        assert len(result) == 2

    def test_exact_duplicates_keeps_higher_score(self):
        memories = [
            {"id": "1", "content": "use SQLite for persistence", "score": 0.7},
            {"id": "2", "content": "use SQLite for persistence", "score": 0.9},
        ]
        result = deduplicate(memories)
        assert len(result) == 1
        assert result[0]["id"] == "2"

    def test_near_duplicates_above_threshold(self):
        memories = [
            {"id": "1", "content": "use SQLite for the main database", "score": 0.9},
            {"id": "2", "content": "use SQLite for the main database storage", "score": 0.8},
        ]
        result = deduplicate(memories, threshold=0.7)
        assert len(result) == 1
        assert result[0]["id"] == "1"

    def test_below_threshold_keeps_both(self):
        memories = [
            {"id": "1", "content": "use SQLite for persistence", "score": 0.9},
            {"id": "2", "content": "completely different topic about React", "score": 0.8},
        ]
        result = deduplicate(memories, threshold=0.8)
        assert len(result) == 2

    def test_multiple_duplicates(self):
        memories = [
            {"id": "1", "content": "use SQLite for persistence", "score": 0.9},
            {"id": "2", "content": "use SQLite for persistence", "score": 0.7},
            {"id": "3", "content": "use SQLite for persistence", "score": 0.5},
            {"id": "4", "content": "React frontend framework", "score": 0.8},
        ]
        result = deduplicate(memories)
        assert len(result) == 2
        ids = {m["id"] for m in result}
        assert "1" in ids
        assert "4" in ids

    def test_empty_content(self):
        memories = [
            {"id": "1", "content": "", "score": 0.9},
            {"id": "2", "content": "", "score": 0.8},
        ]
        result = deduplicate(memories)
        assert len(result) == 2


class TestSignalTokenDedup:
    """去重改用 signal_tokens（ASCII 词 + CJK 二元组）后的行为。"""

    def test_paraphrase_duplicate_merged(self):
        # ctx-2026-003：同一知识换措辞——词级 Jaccard 仅约 0.28（旧阈值逃逸），
        # 信号 Jaccard 约 0.32，默认阈值 0.30 应判重并保留高分条目
        memories = [
            {
                "id": "orig",
                "content": "节点故障后：先 cluster nodes 确认 FAIL 状态，从节点自动 "
                "failover 升级为主；若需手工介入，对从节点执行 cluster failover。"
                "slot 均衡优先用 redis-cli --cluster rebalance 目标为空 slot 补齐，"
                "再按权重迁移；单 slot 迁移用 reshard，迁移期间目标节点需先 cluster "
                "setslot importing 源节点 setslot migrating。",
                "score": 0.91,
            },
            {
                "id": "paraphrase",
                "content": "Redis Cluster 节点故障恢复与 slot 重新均衡完整流程：先 "
                "cluster nodes 确认 FAIL，从节点自动 failover 升主；slot 均衡用 "
                "redis-cli --cluster rebalance，单 slot 迁移用 reshard。",
                "score": 0.75,
            },
        ]
        result = deduplicate(memories)
        assert len(result) == 1
        assert result[0]["id"] == "orig"

    def test_normal_pairs_not_merged(self):
        # 同主题但不同知识的正常对（信号重叠 0.05 量级）不应被误伤
        memories = [
            {
                "id": "1",
                "content": "节点故障后：先 cluster nodes 确认 FAIL 状态，从节点自动 failover 升级为主。",
                "score": 0.92,
            },
            {
                "id": "2",
                "content": "Redis Cluster 把键空间划分为 16384 个 slot，每个键经 CRC16 mod 16384 映射到固定节点。",
                "score": 0.66,
            },
        ]
        result = deduplicate(memories)
        assert len(result) == 2

    def test_contradiction_pair_exempt_from_dedup(self):
        # 矛盾对（ctx-025 型，信号 Jaccard 0.436 高于阈值）是互补观点而非重复，
        # 必须双保留供冲突检测告警；否则其中一条被吞，告警随之丢失
        memories = [
            {
                "id": "constraint",
                "content": "部署约束：生产环境必须开启 Redis 持久化，统一 RDB+AOF "
                "混合模式，appendfsync everysec，禁止关闭持久化。",
                "score": 0.82,
            },
            {
                "id": "opinion",
                "content": "部署约束：生产环境禁止开启 Redis 持久化，统一 RDB+AOF "
                "混合模式，改为纯缓存模式由业务预热重建。",
                "score": 0.78,
            },
        ]
        result = deduplicate(memories)
        assert {m["id"] for m in result} == {"constraint", "opinion"}
