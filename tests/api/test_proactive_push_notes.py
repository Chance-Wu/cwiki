"""
从 tests/api/test_p2_modules.py 按主题拆出的测试：TestNoteSummarization、TestProactivePush。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock


class TestNoteSummarization:
    """笔记智能摘要测试（P4-39）。"""

    def test_extract_keywords_chinese(self):
        from adapters.mcp.content_processing import extract_keywords

        texts = [
            "配置 database_connection 参数",
            "database_connection 超时问题",
            "优化 database_connection 连接池",
        ]
        keywords = extract_keywords(texts)
        assert "database_connection" in keywords

    def test_extract_keywords_english(self):
        from adapters.mcp.content_processing import extract_keywords

        texts = [
            "AuthService handles authentication",
            "AuthService token refresh logic",
        ]
        keywords = extract_keywords(texts)
        assert "authservice" in keywords

    def test_extract_keywords_filters_stopwords(self):
        from adapters.mcp.content_processing import extract_keywords

        texts = ["这是一个关于配置数据库的测试"]
        keywords = extract_keywords(texts)
        for sw in ["的", "是", "一个", "关于"]:
            assert sw not in keywords

    def test_extract_keywords_empty_input(self):
        from adapters.mcp.content_processing import extract_keywords

        assert extract_keywords([]) == []
        assert extract_keywords([""]) == []

    def test_summarize_notes_by_type_groups(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "auth token fix", "signal_type": "issue", "formalized": False},
            {"content": "auth middleware update", "signal_type": "issue", "formalized": False},
            {"content": "use snake_case naming", "signal_type": "convention", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert len(summaries) == 2
        issue_summary = next(s for s in summaries if s["signal_type"] == "issue")
        assert issue_summary["count"] == 2
        assert "auth" in issue_summary["keywords"]

    def test_summarize_notes_excludes_formalized(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "already done", "signal_type": "fact", "formalized": True},
            {"content": "pending item", "signal_type": "fact", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert len(summaries) == 1
        assert summaries[0]["count"] == 1

    def test_summarize_notes_empty(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        assert _summarize_notes_by_type([]) == []

    def test_summarize_notes_sorted_by_count_desc(self):
        from adapters.qoder.mcp_server import _summarize_notes_by_type

        notes = [
            {"content": "one", "signal_type": "fact", "formalized": False},
            {"content": "two", "signal_type": "issue", "formalized": False},
            {"content": "three", "signal_type": "issue", "formalized": False},
            {"content": "four", "signal_type": "issue", "formalized": False},
        ]
        summaries = _summarize_notes_by_type(notes)
        assert summaries[0]["signal_type"] == "issue"
        assert summaries[0]["count"] == 3
        assert summaries[1]["signal_type"] == "fact"
        assert summaries[1]["count"] == 1


class TestProactivePush:
    """P3-32：基于会话关键词的主动记忆推送。"""

    async def test_empty_keywords_returns_empty(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        result = await proactive_memory_push(
            conversation_keywords=[],
            workspace_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            db=db,
        )
        assert result == []
        db.execute.assert_not_called()

    async def test_filters_already_pushed(self):
        from apps.api.routes.context import proactive_memory_push

        ws_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        mem_id = uuid.uuid4()

        db = AsyncMock()

        pushed_result = MagicMock()
        pushed_result.all.return_value = [(mem_id,)]

        search_result_mock = MagicMock()
        search_result_mock.all.return_value = []

        db.execute = AsyncMock(side_effect=[pushed_result, search_result_mock])

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(mem_id),
                        "title": "Already pushed",
                        "content": "This was already pushed",
                        "score": 0.8,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=ws_id,
                session_id=sess_id,
                db=db,
            )
            assert result == []
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_pushes_new_memories(self):
        from apps.api.routes.context import proactive_memory_push

        ws_id = uuid.uuid4()
        sess_id = uuid.uuid4()
        mem_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.add_all = MagicMock()

        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(mem_id),
                        "title": "Test Memory",
                        "content": "Some relevant content here for testing",
                        "score": 0.75,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test", "keyword"],
                workspace_id=ws_id,
                session_id=sess_id,
                db=db,
            )
            assert len(result) == 1
            assert result[0].memory_id == mem_id
            assert result[0].title == "Test Memory"
            assert result[0].relevance == 0.75
            assert "test" in result[0].push_reason
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_filters_low_score(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(
            return_value={
                "memories": [
                    {
                        "id": str(uuid.uuid4()),
                        "title": "Low Score",
                        "content": "Not relevant enough",
                        "score": 0.3,
                        "status": "active",
                    },
                ],
            }
        )

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                db=db,
            )
            assert result == []
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_respects_max_items(self):
        from apps.api.routes.context import proactive_memory_push

        db = AsyncMock()
        db.add = MagicMock()
        db.add_all = MagicMock()
        pushed_result = MagicMock()
        pushed_result.all.return_value = []
        db.execute = AsyncMock(return_value=pushed_result)

        memories = [
            {
                "id": str(uuid.uuid4()),
                "title": f"Memory {i}",
                "content": f"Content {i} for testing",
                "score": 0.8 - i * 0.05,
                "status": "active",
            }
            for i in range(5)
        ]

        mock_engine = AsyncMock()
        mock_engine.retrieve = AsyncMock(return_value={"memories": memories})

        import apps.api.routes.context as ctx_module

        original = ctx_module.get_retrieval_engine
        ctx_module.get_retrieval_engine = lambda: mock_engine

        try:
            result = await proactive_memory_push(
                conversation_keywords=["test"],
                workspace_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                db=db,
                max_items=2,
            )
            assert len(result) == 2
        finally:
            ctx_module.get_retrieval_engine = original

    async def test_proactive_push_record_model_exists(self):
        from packages.domain.models import ProactivePushRecord

        assert ProactivePushRecord.__tablename__ == "proactive_push_record"
        assert hasattr(ProactivePushRecord, "session_id")
        assert hasattr(ProactivePushRecord, "memory_id")
        assert hasattr(ProactivePushRecord, "relevance_score")
        assert hasattr(ProactivePushRecord, "keywords")

    async def test_proactive_push_schema_exists(self):
        from packages.domain.schemas import (
            ProactivePushItem,
            ProactivePushRequest,
            ProactivePushResponse,
        )

        req = ProactivePushRequest(
            workspace_id=str(uuid.uuid4()),
            session_id=uuid.uuid4(),
            keywords=["test"],
        )
        assert req.keywords == ["test"]
        assert req.max_items == 3

        item = ProactivePushItem(
            memory_id=uuid.uuid4(),
            title="Test",
            snippet="snippet",
            relevance=0.8,
            push_reason="reason",
        )
        assert item.relevance == 0.8

        resp = ProactivePushResponse(items=[item], total=1)
        assert resp.total == 1

    async def test_feature_flag_gates_endpoint(self):
        from packages.domain.config import ParasiticEvolutionConfig

        config = ParasiticEvolutionConfig()
        assert hasattr(config, "proactive_push_enabled")
        assert config.proactive_push_enabled is True
