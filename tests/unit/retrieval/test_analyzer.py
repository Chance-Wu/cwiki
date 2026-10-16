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
