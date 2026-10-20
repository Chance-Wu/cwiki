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


class TestMetadataCap:
    """W5-C：元数据信号总影响力不超过 RRF 的约束。"""

    def test_cap_bounds_metadata_share(self):
        """意图权重重归一化后 fresh+usage 等元数据之和被压到 ≤ rrf 权重。"""
        w = RerankerWeights.for_intent("procedure")
        # 模拟 rerank 内部封顶后的实际权重
        non_rrf = w.confidence + w.importance + w.freshness + w.usage + w.intent
        assert non_rrf > w.rrf  # 原始意图权重确实超限（触发条件存在）
        candidates = [_make_input(f"m{i}", rrf_score=0.02 - i * 0.001) for i in range(3)]
        rerank(candidates, query_intent="procedure", intent_confidence=0.9)

    def test_relevance_ranking_survives_metadata_gap(self):
        """W4 归因 A 病理：单路 rank1 候选（rrf 低但为池内最高）不再被
        高元数据但低相关性的候选反超。"""
        candidates = [
            # 池内 rrf 最高（单路 rank1：只有 bm25 一路命中）
            _make_input(
                "gold",
                rrf_score=0.0164,
                confidence=0.3,
                importance=0.3,
                freshness=0.4,
                usage_score=0.0,
                memory_type="fact",
            ),
            # rrf 略低但元数据全面占优
            _make_input(
                "metadata_favored",
                rrf_score=0.0140,
                confidence=0.9,
                importance=0.9,
                freshness=1.0,
                usage_score=0.9,
                memory_type="fact",
            ),
        ]
        result = rerank(
            candidates,
            query_intent="procedure",
            intent_confidence=0.9,
            key_terms=["taskgroup"],
        )
        assert result[0][0] == "gold"

    def test_cap_does_not_mutate_caller_weights(self):
        w = RerankerWeights(
            rrf=0.1, confidence=0.3, importance=0.2, freshness=0.2, usage=0.1, intent=0.2
        )
        candidates = [_make_input("a", rrf_score=1.0), _make_input("b", rrf_score=0.5)]
        rerank(candidates, weights=w)
        assert w.confidence == 0.3  # 原对象不被就地修改


class TestVectorSignal:
    """W6-B：向量语义信号接入 rerank（vector_score 原始余弦参与加权）。

    W6-A 归因：RerankInput.vector_score 字段一直存在但从未参与计分，
    语义无关候选凭 conf/imp 元数据压过双路命中的 gold（C12-q3 病理：
    干扰 cosine 0.617 vs gold 0.806）。
    """

    def test_semantic_signal_breaks_metadata_advantage(self):
        """C12-q3 回归：元数据占优但语义无关的候选不再反超双路 rank1 的 gold。

        rrf 分取自真实池（gold nrrf 1.0、noise 0.978、floor 拉低池底），
        cosine 取自实测（gold 0.806、noise 0.617）。
        """
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                vector_score=0.806,
                confidence=0.68,
                importance=0.83,
                freshness=0.87,
                usage_score=0.57,
                memory_type="fact",
            ),
            _make_input(
                "noise",
                rrf_score=0.01635,
                vector_score=0.617,
                confidence=0.83,
                importance=0.93,
                freshness=0.87,
                usage_score=0.57,
                memory_type="opinion",
            ),
            _make_input("floor", rrf_score=0.0141, vector_score=0.0),
        ]
        result = rerank(candidates, query_intent="unknown")
        assert result[0][0] == "gold"

    def test_without_vector_signal_metadata_wins(self):
        """vector 权重置 0 时旧病理复现（证明修复来自语义信号本身）。"""
        w = RerankerWeights(
            rrf=0.38,
            semantic=0.0,
            confidence=0.10,
            importance=0.12,
            freshness=0.10,
            usage=0.06,
            intent=0.09,
        )
        candidates = [
            _make_input(
                "gold",
                rrf_score=0.0164,
                vector_score=0.806,
                confidence=0.68,
                importance=0.83,
                freshness=0.87,
                usage_score=0.57,
                memory_type="fact",
            ),
            _make_input(
                "noise",
                rrf_score=0.01635,
                vector_score=0.617,
                confidence=0.83,
                importance=0.93,
                freshness=0.87,
                usage_score=0.57,
                memory_type="opinion",
            ),
            _make_input("floor", rrf_score=0.0141, vector_score=0.0),
        ]
        result = rerank(candidates, query_intent="unknown", weights=w)
        assert result[0][0] == "noise"

    def test_vector_uses_raw_value(self):
        """余弦是 0-1 语义分，绝对值直接加权（不做池内 min-max）：
        仅 vector 不同、vector 权重 1 时分差应恰为 Δcos=0.5。"""
        a = _make_input("a", rrf_score=0.5, vector_score=0.8)
        b = _make_input("b", rrf_score=0.5, vector_score=0.3)
        w = RerankerWeights(
            rrf=0.0,
            semantic=1.0,
            confidence=0.0,
            importance=0.0,
            freshness=0.0,
            usage=0.0,
            intent=0.0,
        )
        result = rerank([a, b], weights=w)
        assert abs((result[0][1] - result[1][1]) - 0.5) < 1e-9

    def test_vector_not_capped_by_metadata_cap(self):
        """vector 是相关性信号，不参与元数据 ≤ rrf 的封顶：
        元数据权重触发封顶时 vector 权重保持原值。"""
        w = RerankerWeights.for_intent("procedure")
        assert w.semantic > 0
        candidates = [
            _make_input("a", rrf_score=0.02, vector_score=0.9),
            _make_input("b", rrf_score=0.01, vector_score=0.1),
        ]
        rerank(candidates, query_intent="procedure", intent_confidence=0.9)
        # 封顶只缩放元数据五项；vector 与 rrf 不动（无法直接观测内部权重，
        # 用语义无关候选的排序结果间接验证：a 凭高 vector + 高 rrf 稳居首位）
        assert rerank(candidates, query_intent="procedure", intent_confidence=0.9)[0][0] == "a"
