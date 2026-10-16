"""packages.retrieval.ranking.reranker 可配置权重测试。"""

from packages.retrieval.ranking.reranker import RerankerWeights, RerankInput, _intent_bonus, rerank


def _make_input(memory_id: str, **kwargs) -> RerankInput:
    defaults = {
        "title": "test",
        "content": "test content",
        "memory_type": "fact",
    }
    defaults.update(kwargs)
    return RerankInput(memory_id=memory_id, **defaults)


class TestRerank:
    def test_basic_ranking(self):
        candidates = [
            _make_input("a", rrf_score=0.9, confidence=0.9, importance=0.9),
            _make_input("b", rrf_score=0.1, confidence=0.1, importance=0.1),
        ]
        result = rerank(candidates)
        assert result[0][0] == "a"
        assert result[1][0] == "b"

    def test_top_k(self):
        candidates = [_make_input(f"m{i}", rrf_score=float(i) / 10) for i in range(10)]
        result = rerank(candidates, top_k=3)
        assert len(result) == 3

    def test_empty_candidates(self):
        assert rerank([]) == []

    def test_high_rrf_score_wins(self):
        candidates = [
            _make_input("a", rrf_score=1.0),
            _make_input("b", rrf_score=0.0),
        ]
        result = rerank(candidates)
        assert result[0][0] == "a"

    def test_configurable_weights(self):
        candidates = [
            _make_input("a", rrf_score=1.0, usage_score=0.0),
            _make_input("b", rrf_score=0.0, usage_score=1.0),
        ]
        w = RerankerWeights(
            rrf=0.0,
            confidence=0.0,
            importance=0.0,
            freshness=0.0,
            usage=1.0,
            intent=0.0,
        )
        result = rerank(candidates, weights=w)
        assert result[0][0] == "b"


class TestIntentBonus:
    def test_unknown_intent(self):
        assert _intent_bonus("fact", "unknown") == 0.5

    def test_matching_type(self):
        assert _intent_bonus("procedure", "procedure") == 1.0

    def test_no_match_is_neutral(self):
        """类型不匹配给中性 0.5 而非惩罚基线：意图来自查询关键词分析，
        可靠性有限，重罚会让低置信信号产生高置信影响（W3-T4 修复）。"""
        assert _intent_bonus("fact", "procedure") == 0.5
        assert _intent_bonus("reference", "fact") == 0.5

    def test_partial_match(self):
        assert _intent_bonus("rule", "project_rule") == 1.0
        assert _intent_bonus("constraint", "project_rule") == 0.8


class TestRerankSignalSemantics:
    """W3-T4 回归：元数据信号用原始值而非池内 min-max 归一。

    旧行为对 0-1 绝对分做池内重标定，池内最小值被强拉到 0（即使绝对值
    0.85），而 RRF 头部名次间微小差距归一后被压平，元数据反而主导排序，
    把元数据恰好是池内最小值的相关记忆挤下去（W1 基线 MRR 0.5643 vs
    hybrid_rrf 0.9284 的系统性劣化）。
    """

    def test_metadata_pool_min_not_crushed(self):
        """元数据为池内最小值但绝对值高的记忆不再被压到元数据零分。

        rrf 分取自真实 RRF 头部量级（1/61、1/62、1/63、1/71）。
        修复前 gold 的元数据经 min-max 全部归零，被 noise1 反超。
        """
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                confidence=0.85,
                importance=0.85,
                freshness=0.85,
                usage_score=0.85,
                memory_type="fact",
            ),
            _make_input(
                "noise1",
                rrf_score=0.0161,
                confidence=0.90,
                importance=0.90,
                freshness=0.90,
                usage_score=0.90,
                memory_type="fact",
            ),
            _make_input(
                "noise2",
                rrf_score=0.0158,
                confidence=0.88,
                importance=0.88,
                freshness=0.88,
                usage_score=0.88,
                memory_type="fact",
            ),
            # 拉低 rrf 池内最小值但不参与元数据最小值竞争
            _make_input(
                "floor",
                rrf_score=0.0141,
                confidence=0.86,
                importance=0.86,
                freshness=0.86,
                usage_score=0.86,
                memory_type="fact",
            ),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_metadata_absolute_values_used(self):
        """元数据直接用原始值：仅 confidence 不同且 conf 权重为 1 时，
        分差应恰为 Δconf=0.5（池内 min-max 语义下会是 1.0）。"""
        a = _make_input("a", rrf_score=0.5, confidence=0.9)
        b = _make_input("b", rrf_score=0.5, confidence=0.4)
        w = RerankerWeights(
            rrf=0.0, confidence=1.0, importance=0.0, freshness=0.0, usage=0.0, intent=0.0
        )
        result = rerank([a, b], weights=w)
        assert abs((result[0][1] - result[1][1]) - 0.5) < 1e-9

    def test_rrf_still_minmax_normalized(self):
        """rrf 名次分无量纲，仍走池内 min-max：元数据完全一致时排序由
        rrf 归一分决定，保持单调。"""
        candidates = [
            _make_input("a", rrf_score=0.0164),
            _make_input("b", rrf_score=0.0080),
            _make_input("c", rrf_score=0.0020),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert [mid for mid, _ in result] == ["a", "b", "c"]

    def test_rrf_head_gap_not_flattened_by_metadata(self):
        """rrf 头部与元数据轻度劣势的正例：元数据不再经归一放大，
        rrf 主导地位恢复（设计注释「RRF 主导、元数据微调」）。"""
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                confidence=0.68,
                importance=0.83,
                freshness=1.0,
                usage_score=0.28,
                memory_type="fact",
            ),
            _make_input(
                "noise",
                rrf_score=0.0141,
                confidence=0.91,
                importance=0.92,
                freshness=1.0,
                usage_score=0.37,
                memory_type="fact",
            ),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_intent_misjudgment_neutral_for_unmatched_types(self):
        """意图被误判时，正例与干扰类型都不匹配意图 → intent 无区分，
        排序仍由 rrf 主导，不再因重罚翻转。"""
        candidates = [
            _make_input("gold", rrf_score=0.0164, memory_type="fact"),
            _make_input("noise", rrf_score=0.0161, memory_type="reference"),
        ]
        # 查询被误判为 procedure：fact 与 reference 都拿中性 0.5
        result = rerank(candidates, query_intent="procedure")
        assert result[0][0] == "gold"
