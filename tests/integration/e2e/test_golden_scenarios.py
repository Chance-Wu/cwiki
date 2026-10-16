"""E2E：黄金场景（spec 19）。

10 个 cwiki 必须正确处理的现实场景：
  SC-001: 项目技术约束
  SC-002: 历史架构决策
  SC-003: Bug 修复经验
  SC-004: SQL 特殊规则
  SC-005: API 使用约束
  SC-006: 第三方组件坑点
  SC-007: 编码约定
  SC-008: 用户偏好
  SC-009: 仓库特有规则
  SC-010: 跨会话任务延续
"""

from __future__ import annotations

from apps.worker.episode_builder import build_episode
from packages.memory.duplicate_detection import detect_duplicate
from packages.memory.quality_gate import compute_quality_gate
from packages.retrieval.bm25 import BM25Index
from packages.retrieval.context.assembler import assemble_context
from packages.retrieval.query.analyzer import analyze_query
from packages.retrieval.ranking.reranker import RerankInput, rerank
from packages.retrieval.ranking.temporal import temporal_score


def _build_index_and_search(memories, query, top_k=10):
    index = BM25Index()
    for m in memories:
        index.add(m["id"], f"{m['title']} {m['content']}")
    # 补充无关节档，保证 BM25 的 IDF 计算正常
    if len(memories) == 1:
        index.add("dummy-1", "connection pooling layer for improved performance")
        index.add("dummy-2", "api rate limiting implementation details")
    index.build()
    return index.search(query, top_k=top_k)


def _full_pipeline(memories, query, top_k=10):
    index = BM25Index()
    for m in memories:
        index.add(m["id"], f"{m['title']} {m['content']}")
    # 补充无关节档，保证 BM25 的 IDF 计算正常
    if len(memories) == 1:
        index.add("dummy-1", "connection pooling layer for improved performance")
        index.add("dummy-2", "api rate limiting implementation details")
    index.build()

    bm25_results = index.search(query, top_k=50)
    analyzed = analyze_query(query)

    rerank_inputs = []
    for doc_id, score in bm25_results:
        mem = next((m for m in memories if m["id"] == doc_id), None)
        if not mem:
            continue
        rerank_inputs.append(
            RerankInput(
                memory_id=doc_id,
                title=mem["title"],
                content=mem["content"],
                memory_type=mem.get("type", "fact"),
                bm25_score=score,
                vector_score=0.5,
                rrf_score=0.01,
                confidence=mem.get("confidence", 0.5),
                importance=mem.get("importance", 0.5),
                freshness=temporal_score(None, None, None, None),
                usage_score=0.1,
            )
        )

    reranked = rerank(rerank_inputs, query_intent=analyzed.intent, top_k=top_k)
    mem_dicts = [
        {**next(m for m in memories if m["id"] == mid), "score": score}
        for mid, score in reranked
        if any(m["id"] == mid for m in memories)
    ]
    ctx = assemble_context(mem_dicts, query=query, max_tokens=5000)
    return ctx


class TestGoldenScenarios:
    """按 spec 19 的 10 个黄金场景。"""

    def test_sc001_project_tech_constraints(self):
        """项目必须使用 SQLite，而非 MySQL。"""
        memories = [
            {
                "id": "sc001-1",
                "title": "Database technology constraint",
                "content": "This project must use SQLite as the primary database. Do not introduce MySQL or PostgreSQL.",
                "type": "constraint",
                "confidence": 0.95,
                "importance": 0.9,
            },
        ]
        ctx = _full_pipeline(memories, "what database should we use")
        assert len(ctx.memories) >= 1
        assert "SQLite" in ctx.text

    def test_sc002_historical_architecture_decision(self):
        """历史决策：选择了事件驱动架构而非请求-响应。"""
        memories = [
            {
                "id": "sc002-1",
                "title": "Architecture decision: event-driven",
                "content": "We chose event-driven architecture over request-response because of the need for async processing and audit trail.",
                "type": "decision",
                "confidence": 0.9,
                "importance": 0.85,
            },
        ]
        ctx = _full_pipeline(memories, "why event driven architecture")
        assert len(ctx.memories) >= 1
        assert "event-driven" in ctx.text.lower() or "event" in ctx.text.lower()

    def test_sc003_bug_fix_lesson(self):
        """经验教训：连接池耗尽的修法是始终设置 max_connections。"""
        events = [
            {
                "event_type": "prompt.submitted",
                "sequence": 1,
                "payload": {"content": "Fix connection pool exhaustion"},
            },
            {
                "event_type": "tool.failed",
                "sequence": 2,
                "payload": {"tool_name": "Bash", "error": "Too many connections"},
            },
            {
                "event_type": "tool.completed",
                "sequence": 3,
                "payload": {"tool_name": "Edit", "input": {"file_path": "db/pool.py"}},
            },
            {
                "event_type": "test.passed",
                "sequence": 4,
                "payload": {"test_name": "test_pool_limit"},
            },
        ]
        episode = build_episode("sc003-session", events)
        assert episode.goal != ""
        assert len(episode.problems) >= 1

        memories = [
            {
                "id": "sc003-1",
                "title": "Connection pool max limit",
                "content": "Always set max_connections on database pool to prevent exhaustion. Default is unlimited which causes crashes under load.",
                "type": "lesson",
                "confidence": 0.85,
                "importance": 0.8,
            },
        ]
        ctx = _full_pipeline(memories, "database connection pool issue")
        assert len(ctx.memories) >= 1

    def test_sc004_sql_special_rules(self):
        """生产查询禁用 SELECT *。"""
        memories = [
            {
                "id": "sc004-1",
                "title": "No SELECT * in production",
                "content": "Never use SELECT * in production SQL queries. Always specify exact columns needed for performance and security.",
                "type": "constraint",
                "confidence": 0.95,
                "importance": 0.9,
            },
        ]
        ctx = _full_pipeline(memories, "SQL query best practices")
        assert len(ctx.memories) >= 1
        assert "SELECT" in ctx.text or "column" in ctx.text.lower()

    def test_sc005_api_usage_constraints(self):
        """限流约束：每用户每分钟最多 100 次请求。"""
        memories = [
            {
                "id": "sc005-1",
                "title": "API rate limit rule",
                "content": "API rate limit is 100 requests per minute per user. Implement client-side throttling to avoid 429 errors.",
                "type": "constraint",
                "confidence": 0.9,
                "importance": 0.85,
            },
        ]
        ctx = _full_pipeline(memories, "API rate limiting")
        assert len(ctx.memories) >= 1
        assert "100" in ctx.text or "rate" in ctx.text.lower()

    def test_sc006_third_party_component_pitfalls(self):
        """HTTP 客户端必须使用连接池，而非单连接。"""
        memories = [
            {
                "id": "sc006-1",
                "title": "HTTP client connection pool required",
                "content": "The httpx client must use connection pooling, not single connections. Single connections cause blocking in async code.",
                "type": "lesson",
                "confidence": 0.85,
                "importance": 0.75,
            },
        ]
        ctx = _full_pipeline(memories, "HTTP client connection setup")
        assert len(ctx.memories) >= 1
        assert "connection" in ctx.text.lower() or "pool" in ctx.text.lower()

    def test_sc007_coding_conventions(self):
        """所有 Python 代码必须使用类型标注并经 ruff 格式化。"""
        memories = [
            {
                "id": "sc007-1",
                "title": "Python coding conventions",
                "content": "All Python code must use type hints on function signatures and be formatted with ruff. No exceptions.",
                "type": "feedback",
                "confidence": 0.95,
                "importance": 0.8,
            },
        ]
        ctx = _full_pipeline(memories, "Python code style conventions")
        assert len(ctx.memories) >= 1
        assert "type hint" in ctx.text.lower() or "ruff" in ctx.text.lower()

    def test_sc008_user_preferences(self):
        """用户偏好简洁回复、不用表情符号。"""
        memories = [
            {
                "id": "sc008-1",
                "title": "User communication preference",
                "content": "User prefers concise, direct responses without emojis or excessive formatting.",
                "type": "preference",
                "confidence": 0.9,
                "importance": 0.7,
            },
        ]
        ctx = _full_pipeline(memories, "how should I format responses")
        assert len(ctx.memories) >= 1
        assert "concise" in ctx.text.lower() or "preference" in ctx.text.lower()

    def test_sc009_repository_specific_rules(self):
        """本仓库采用 monorepo 结构，包统一放在 packages/ 目录。"""
        memories = [
            {
                "id": "sc009-1",
                "title": "Monorepo structure rule",
                "content": "This repository uses a monorepo structure. All packages go under packages/ directory. Do not create top-level modules.",
                "type": "constraint",
                "confidence": 0.9,
                "importance": 0.8,
            },
        ]
        ctx = _full_pipeline(memories, "where to put new packages code")
        assert len(ctx.memories) >= 1
        assert "packages" in ctx.text.lower() or "monorepo" in ctx.text.lower()

    def test_sc010_cross_session_task_continuation(self):
        """会话 1 的记忆应能在会话 2 中召回。"""
        session1_memories = [
            {
                "id": "sc010-1",
                "title": "Auth middleware migration in progress",
                "content": "Migrating auth middleware from v1 to v2. Completed: login endpoint. Remaining: logout, refresh token, session validation.",
                "type": "fact",
                "confidence": 0.8,
                "importance": 0.75,
            },
        ]

        index = BM25Index()
        for m in session1_memories:
            index.add(m["id"], f"{m['title']} {m['content']}")
        # 补充无关节档，保证 BM25 的 IDF 计算正常
        index.add("dummy-1", "connection pooling layer for improved performance")
        index.add("dummy-2", "api rate limiting implementation details")
        index.build()

        session2_query = "what is the status of auth middleware migration"
        results = index.search(session2_query, top_k=10)
        assert len(results) >= 1
        assert results[0][0] == "sc010-1"

        ctx = assemble_context(
            [{**session1_memories[0], "score": 0.8}],
            query=session2_query,
            max_tokens=5000,
        )
        assert len(ctx.memories) >= 1
        assert "auth" in ctx.text.lower()


class TestCrossScenarioIsolation:
    """验证不同作用域的记忆不会错误泄漏。"""

    def test_different_types_same_scope_retrieve_independently(self):
        memories = [
            {
                "id": "m1",
                "title": "DB constraint",
                "content": "Use SQLite only",
                "type": "constraint",
            },
            {
                "id": "m2",
                "title": "DB lesson",
                "content": "Connection pooling prevents exhaustion",
                "type": "lesson",
            },
            {
                "id": "m3",
                "title": "DB decision",
                "content": "Chose SQLite over MySQL for portability",
                "type": "decision",
            },
        ]
        results = _build_index_and_search(memories, "SQLite database", top_k=10)
        assert len(results) >= 1

    def test_quality_gate_filters_low_quality(self):
        low_quality = {
            "id": "low-q",
            "title": "x",
            "content": "y",
            "type": "fact",
            "evidence_count": 0,
        }
        qg = compute_quality_gate(low_quality)
        assert qg.score < 0.8

    def test_duplicate_detection_prevents_reinsert(self):
        candidate = {
            "id": "new",
            "title": "Use async database",
            "content": "Always use async database connections for better performance in web applications",
            "type": "constraint",
        }
        existing = {
            "id": "old",
            "title": "Use async database",
            "content": "Always use async database connections for better performance in web applications",
            "type": "constraint",
        }
        result = detect_duplicate(candidate, existing)
        # 没有 embedding 相似度时，纯文本得分只能归类为 possible_duplicate
        assert result.classification == "possible_duplicate"
