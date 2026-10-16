"""上下文冲突检测测试。"""

from packages.retrieval.context.conflict import ConflictReference, detect_conflicts


class TestConflictDetection:
    def test_no_conflicts_when_no_overlap(self):
        memories = [
            {"id": "1", "content": "use SQLite for the database"},
            {"id": "2", "content": "React is the frontend framework"},
        ]
        conflicts = detect_conflicts(memories)
        assert len(conflicts) == 0

    def test_detects_contradiction(self):
        memories = [
            {
                "id": "1",
                "content": "you must always enable caching",
                "version": 1,
                "updated_at": "2025-01-01",
            },
            {
                "id": "2",
                "content": "you should never enable caching",
                "version": 2,
                "updated_at": "2025-06-01",
            },
        ]
        conflicts = detect_conflicts(memories, overlap_threshold=0.2)
        assert len(conflicts) == 1
        assert conflicts[0].memory_id_a == "1"
        assert conflicts[0].memory_id_b == "2"

    def test_no_conflict_when_below_overlap(self):
        memories = [
            {"id": "1", "content": "must enable feature X"},
            {"id": "2", "content": "completely different text that never mentions the same things"},
        ]
        conflicts = detect_conflicts(memories, overlap_threshold=0.4)
        assert len(conflicts) == 0

    def test_conflict_reference_to_dict(self):
        ref = ConflictReference(
            memory_id_a="a",
            memory_id_b="b",
            version_a=1,
            version_b=2,
            updated_at_a="2025-01-01",
            updated_at_b="2025-06-01",
        )
        d = ref.to_dict()
        assert d["memory_id_a"] == "a"
        assert d["version_a"] == 1

    def test_empty_list(self):
        assert detect_conflicts([]) == []

    def test_chinese_contradiction(self):
        memories = [
            {"id": "1", "content": "必须使用 MySQL 做主数据库", "version": 1},
            {"id": "2", "content": "禁止使用 MySQL 做主数据库", "version": 2},
        ]
        conflicts = detect_conflicts(memories, overlap_threshold=0.3)
        assert len(conflicts) == 1


class TestSignalTokenPrefilter:
    """粗筛改用 signal_tokens（ASCII 词 + CJK 二元组）后的行为。"""

    def test_cjk_contradiction_survives_prefilter(self):
        # ctx-2026-001：真实风格中文矛盾对——换措辞导致 run 级重叠仅约 0.07，
        # 旧分词在 0.4 阈值下被拦截；信号分词下重叠约 0.30，默认阈值 0.18 应放行
        memories = [
            {
                "id": "1",
                "content": "生产环境部署约束：Redis 必须开启持久化，统一采用 "
                "RDB+AOF 混合模式，appendfsync everysec。禁止以纯缓存名义关闭"
                "持久化，重启丢数据后业务方按缓存语义重建的假设从未成立过。",
                "version": 1,
            },
            {
                "id": "2",
                "content": "另一种声音：如果 Redis 只做缓存、后端 DB 是事实源，"
                "可以关闭持久化，重启后由业务预热重建。该观点与生产环境必须开启"
                "持久化的团队约束矛盾，尚未被采纳，仅作决策背景记录。",
                "version": 2,
            },
        ]
        conflicts = detect_conflicts(memories)
        assert len(conflicts) == 1
        assert {conflicts[0].memory_id_a, conflicts[0].memory_id_b} == {"1", "2"}

    def test_english_contradiction_default_threshold(self):
        # 英文矛盾对在默认阈值下行为不回退（原本高重叠，信号分词不会降低它）
        memories = [
            {"id": "1", "content": "you must always enable caching"},
            {"id": "2", "content": "you should never enable caching"},
        ]
        conflicts = detect_conflicts(memories)
        assert len(conflicts) == 1

    def test_unrelated_pairs_still_filtered(self):
        # 无关对信号重叠远低于阈值，粗筛仍能拦截，不产生误告警
        memories = [
            {"id": "1", "content": "节点故障后先 cluster nodes 确认 FAIL 状态"},
            {"id": "2", "content": "Redis Cluster 把键空间划分为 16384 个 slot"},
        ]
        assert detect_conflicts(memories) == []

    def test_safety_claim_pair_detected(self):
        # ctx-2026-001 同源的"不丢 vs 可能丢"安全性主张矛盾（ctx-012 型）
        memories = [
            {
                "id": "1",
                "content": "WAL + synchronous=NORMAL 时事务提交只写 wal 不 fsync，"
                "应用崩溃不丢事务，NORMAL 完全够用。",
            },
            {
                "id": "2",
                "content": "synchronous=NORMAL 在 WAL 模式下事务提交不做 fsync，"
                "断电时已提交事务可能丢失，关键事务应切换 FULL。",
            },
        ]
        conflicts = detect_conflicts(memories)
        assert len(conflicts) == 1
