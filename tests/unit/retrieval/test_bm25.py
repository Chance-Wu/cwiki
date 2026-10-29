"""packages.retrieval.bm25 测试。"""

from packages.retrieval.bm25 import BM25Index


class TestBM25Index:
    def test_add_and_search(self):
        idx = BM25Index()
        idx.add("doc1", "connection pooling database")
        idx.add("doc2", "unit testing pytest")
        idx.add("doc3", "logging monitoring alerts")
        idx.add("doc4", "cache redis performance")
        results = idx.search("database pooling")
        ids = [r[0] for r in results]
        assert "doc1" in ids

    def test_search_empty_index(self):
        idx = BM25Index()
        assert idx.search("anything") == []

    def test_remove(self):
        idx = BM25Index()
        idx.add("doc1", "hello world")
        idx.add("doc2", "foo bar")
        idx.add("doc3", "baz qux")
        idx.add("doc4", "alpha beta")
        idx.remove("doc1")
        results = idx.search("hello")
        ids = [r[0] for r in results]
        assert "doc1" not in ids

    def test_clear(self):
        idx = BM25Index()
        idx.add("doc1", "hello world")
        idx.clear()
        assert idx.search("hello") == []

    def test_rebuild_on_search_after_add(self):
        idx = BM25Index()
        idx.add("doc1", "alpha beta")
        idx.add("doc2", "gamma delta")
        idx.add("doc3", "alpha gamma")
        idx.add("doc4", "epsilon zeta")
        idx.add("doc5", "theta iota")
        idx.add("doc6", "kappa lambda")
        # 增量更新保持索引有效
        assert idx._built is True

        results = idx.search("alpha")
        assert idx._built is True
        assert len(results) == 2

    def test_no_rebuild_on_consecutive_search(self):
        idx = BM25Index()
        idx.add("doc1", "alpha beta")
        idx.add("doc2", "gamma delta")
        idx.add("doc3", "alpha gamma")
        idx.add("doc4", "epsilon zeta")
        idx.search("alpha")
        assert idx._built is True

        idx.search("beta")
        assert idx._built is True

    def test_add_keeps_index_valid(self):
        """增量 add() 无需重建即保持索引可检索。"""
        idx = BM25Index()
        idx.add("doc1", "alpha beta")
        idx.add("doc2", "gamma delta")
        idx.add("doc3", "alpha gamma")
        idx.add("doc4", "epsilon zeta")
        idx.search("alpha")
        assert idx._built is True

        idx.add("doc5", "gamma delta")
        # 增量添加后索引仍有效
        assert idx._built is True

        # 搜索结果反映新增文档
        results = idx.search("gamma")
        ids = [r[0] for r in results]
        assert "doc5" in ids

    def test_mixed_language_tokenization(self):
        idx = BM25Index()
        idx.add("doc1", "数据库 database 连接池 pool 配置 config")
        idx.add("doc2", "服务器 server 部署 deploy 监控 monitor")
        idx.add("doc3", "日志 logging 告警 alert 通知 notify")
        idx.add("doc4", "缓存 cache 性能 performance 优化 optimize")
        results = idx.search("database pool")
        ids = [r[0] for r in results]
        assert "doc1" in ids

    def test_top_k_limit(self):
        idx = BM25Index()
        for i in range(20):
            idx.add(f"doc{i}", f"common keyword doc{i}")
        results = idx.search("common", top_k=5)
        assert len(results) <= 5

    def test_zero_score_excluded(self):
        idx = BM25Index()
        idx.add("doc1", "alpha beta")
        idx.add("doc2", "gamma delta")
        idx.add("doc3", "epsilon zeta")
        idx.add("doc4", "theta iota")
        results = idx.search("alpha")
        for _, score in results:
            assert score > 0

    def test_pure_chinese_search(self):
        idx = BM25Index()
        idx.add("doc1", "数据库连接池配置方法")
        idx.add("doc2", "服务器部署与监控")
        idx.add("doc3", "日志收集和告警通知")
        idx.add("doc4", "缓存性能优化方案")
        results = idx.search("数据库")
        ids = [r[0] for r in results]
        assert "doc1" in ids

    def test_chinese_tokenization(self):
        tokens = BM25Index._tokenize("数据库连接池")
        assert len(tokens) >= 2
        assert "数据库" in tokens


def test_add_accepts_precomputed_tokens():
    """预计算 token 与内部分词结果一致（local_index 复用分词的分支）。"""
    manual = BM25Index()
    manual.add("doc-1", "数据库 连接池 配置", "标题")
    manual.build()

    precomputed = BM25Index()
    content_tokens = precomputed._tokenize("数据库 连接池 配置")
    title_tokens = precomputed._tokenize("标题")
    precomputed.add("doc-1", "", "标题", tokens=content_tokens, title_tokens=title_tokens)
    precomputed.build()

    assert precomputed._documents == manual._documents
    assert precomputed.search("数据库", top_k=5) == manual.search("数据库", top_k=5)
