"""packages.retrieval.query.analyzer 增强功能测试。"""

from packages.retrieval.query.analyzer import analyze_query


class TestSynonymExpansion:
    def test_chinese_synonym(self):
        result = analyze_query("如何部署应用")
        assert "deploy" in result.expanded_terms or "上线" in result.expanded_terms

    def test_english_synonym_via_chinese_key(self):
        result = analyze_query("如何部署应用")
        assert "deploy" in result.expanded_terms

    def test_english_query_reverse_maps_to_chinese(self):
        result = analyze_query("how to deploy the app")
        assert "部署" in result.expanded_terms

    def test_english_token_reverse_mapping(self):
        result = analyze_query("config settings")
        assert "配置" in result.expanded_terms or "设置" in result.expanded_terms

    def test_no_synonym_for_absent_term(self):
        result = analyze_query("今天天气怎么样")
        assert result.expanded_terms == []

    def test_max_eight_expanded(self):
        result = analyze_query("部署配置错误优化检索缓存")
        assert len(result.expanded_terms) <= 8

    def test_no_duplicate_expansion(self):
        result = analyze_query("部署和发布有什么区别")
        seen = set(result.expanded_terms)
        assert len(seen) == len(result.expanded_terms)


class TestIntentConfidence:
    def test_high_confidence_with_multiple_matches(self):
        result = analyze_query("这个规则规范约定必须遵守")
        assert result.intent == "project_rule"
        assert result.confidence > 0.5

    def test_low_confidence_with_single_match(self):
        result = analyze_query("这里有个规则")
        assert result.intent == "project_rule"
        assert result.confidence <= 0.5

    def test_zero_confidence_for_unknown(self):
        result = analyze_query("今天吃了火锅")
        assert result.intent == "unknown"
        assert result.confidence == 0.0

    def test_confidence_capped_at_one(self):
        result = analyze_query("怎么如何步骤流程操作指南")
        assert result.confidence <= 1.0


class TestEnhancedIntentKeywords:
    def test_lesson_with_pitfall(self):
        result = analyze_query("这是一个pitfall")
        assert result.intent == "lesson"

    def test_decision_with_tradeoff(self):
        result = analyze_query("tradeoff between speed and quality")
        assert result.intent == "decision"

    def test_constraint_with_maximum(self):
        result = analyze_query("maximum 100 connections")
        assert result.intent == "constraint"

    def test_procedure_with_guide(self):
        result = analyze_query("guide for setting up CI")
        assert result.intent == "procedure"


class TestEnhancedEntities:
    def test_fastapi_entity(self):
        result = analyze_query("FastAPI 路由怎么配置")
        assert "FastAPI" in result.entities

    def test_bm25_entity(self):
        result = analyze_query("BM25 和 RRF 的区别")
        assert "BM25" in result.entities
        assert "RRF" in result.entities

    def test_sqlalchemy_entity(self):
        result = analyze_query("SQLAlchemy async session")
        assert "SQLAlchemy" in result.entities


class TestQuestionDetection:
    def test_chinese_question_mark(self):
        result = analyze_query("怎么部署？")
        assert result.is_question is True

    def test_english_question_mark(self):
        result = analyze_query("how to deploy?")
        assert result.is_question is True

    def test_how_keyword(self):
        result = analyze_query("如何配置数据库")
        assert result.is_question is True

    def test_non_question(self):
        result = analyze_query("数据库配置方案")
        assert result.is_question is False


class TestToDict:
    def test_includes_new_fields(self):
        result = analyze_query("如何部署应用")
        d = result.to_dict()
        assert "expanded_terms" in d
        assert "confidence" in d
        assert isinstance(d["expanded_terms"], list)
        assert isinstance(d["confidence"], float)


class TestHistoricalQueryDetection:
    def test_before_phrase_detected(self):
        # 评测集 C5-q2 原文："X 出来之前" 明确问历史
        result = analyze_query("WAL 模式出来之前 SQLite 的锁和 journal 是怎么调优的")
        assert result.is_historical_query is True

    def test_evolution_detected(self):
        # 评测集 C3-q2 原文："演进" 指向方案变迁史
        result = analyze_query("重复检测的方案是怎么一步步演进的")
        assert result.is_historical_query is True

    def test_current_affairs_not_historical(self):
        # 评测集 C5-q1 原文：问现行状态，不是历史
        result = analyze_query("现在生产环境还允许用 Sentinel 部署吗")
        assert result.is_historical_query is False

    def test_sequencing_bu_not_historical(self):
        # "之前"表流程顺序而非历史指向，宽匹配会误伤
        result = analyze_query("检索之前先做分词处理")
        assert result.is_historical_query is False

    def test_english_historical_detected(self):
        assert (
            analyze_query("what did we use to store vectors historically?").is_historical_query
            is True
        )

    def test_plain_query_not_historical(self):
        assert (
            analyze_query("Redis Cluster 的 16384 个 slot 是怎么编号的").is_historical_query
            is False
        )


class TestNegationExtraction:
    def test_alternative_question_not_negation(self):
        # "X 不 X" 疑问式不是否定——实测"要不要加"曾提取出否定"加"，
        # 正文含该词的 gold 记忆被 negation_penalty 沉底（C11-q3 根因）
        assert analyze_query("bge 模型的指令前缀要不要加").negations == []
        assert analyze_query("配置要不要改").negations == []
        assert analyze_query("需不需要开 WAL").negations == []
        assert analyze_query("包不包括测试环境").negations == []

    def test_real_negation_kept(self):
        assert analyze_query("不要用 root 跑服务").negations == ["用"]
        assert analyze_query("结果不需要包含历史版本").negations == ["包含历史版本"]
        assert analyze_query("排除已归档的记忆").negations == ["已归档的记忆"]
