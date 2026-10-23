"""本地只读索引：API 不可用时的 search / curated 降级。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from adapters.mcp.local_index import (
    build_local_context,
    head,
    local_available,
    reset_cache,
    search_local,
)

SCHEMA = """
CREATE TABLE workspace (id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE memory (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    confidence REAL NOT NULL DEFAULT 0.5,
    importance REAL NOT NULL DEFAULT 0.5,
    version INTEGER NOT NULL DEFAULT 1,
    valid_to TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    tags JSON,
    is_permanent INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
"""


def _insert(db: Path, **row: object) -> None:
    defaults: dict[str, object] = {
        "status": "active",
        "confidence": 0.5,
        "importance": 0.5,
        "version": 1,
        "valid_to": None,
        "usage_count": 0,
        "tags": "[]",
        "is_permanent": 0,
        "updated_at": "2026-10-23 00:00:00",
    }
    defaults.update(row)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            INSERT INTO memory (id, workspace_id, title, content, type, status,
                                confidence, importance, version, valid_to,
                                usage_count, tags, is_permanent, updated_at)
            VALUES (:id, :workspace_id, :title, :content, :type, :status,
                    :confidence, :importance, :version, :valid_to,
                    :usage_count, :tags, :is_permanent, :updated_at)
            """,
            defaults,
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "cwiki.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO workspace (id, name) VALUES (?, ?)",
            [("w1", "web"), ("w2", "backend")],
        )
        conn.commit()
    finally:
        conn.close()
    _insert(
        path,
        id="m1",
        workspace_id="w1",
        title="Redis 集群槽位重均衡",
        content="redis-cli --cluster rebalance 必须跳过 0-slot 节点，否则报 CLUSTERDOWN。",
        type="lesson",
        confidence=0.9,
        tags='["redis", "ops"]',
    )
    _insert(
        path,
        id="m2",
        workspace_id="w2",
        title="Spring Boot 事务边界",
        content="同类方法内部调用 @Transactional 不生效，需要走代理或拆类。",
        type="convention",
        confidence=0.4,
        tags='["java", "spring"]',
    )
    _insert(
        path,
        id="m3",
        workspace_id="w1",
        title="归档的旧记忆",
        content="Redis 旧版本配置说明。",
        type="fact",
        status="archived",
    )
    reset_cache()
    return path


def test_search_returns_active_memory_with_normalized_score(db_path: Path):
    data = search_local("redis 槽位", workspace="web", db_path=db_path)
    assert data["available"] is True
    assert data["source"] == "local"
    assert [item["id"] for item in data["results"]] == ["m1"]
    assert 0 < data["results"][0]["score"] <= 1
    assert data["insufficient"] is False


def test_archived_memory_is_excluded(db_path: Path):
    data = search_local("redis", workspace="web", db_path=db_path)
    assert {item["id"] for item in data["results"]} == {"m1"}


def test_workspace_filter_and_unknown_workspace(db_path: Path):
    scoped = search_local("Transactional", workspace="backend", db_path=db_path)
    assert [item["id"] for item in scoped["results"]] == ["m2"]

    unknown = search_local("redis", workspace="nope", db_path=db_path)
    assert unknown["available"] is True
    assert unknown["results"] == []
    assert unknown["reason"] == "unknown_workspace"


def test_type_confidence_and_tags_filters(db_path: Path):
    assert search_local("Redis", memory_type="fact", db_path=db_path)["results"] == []
    assert search_local("Spring", min_confidence=0.8, db_path=db_path)["results"] == []
    assert [
        item["id"]
        for item in search_local("redis", tags=["redis", "ops"], db_path=db_path)["results"]
    ] == ["m1"]
    assert search_local("redis", tags=["ops", "missing"], db_path=db_path)["results"] == []


def test_missing_database_reports_unavailable(tmp_path: Path):
    data = search_local("redis", db_path=tmp_path / "missing.db")
    assert data["available"] is False
    assert data["reason"] == "database_not_found"
    assert local_available(tmp_path / "missing.db") is False


def test_cache_refreshes_after_new_write(db_path: Path):
    assert search_local("幂等键", db_path=db_path)["results"] == []
    _insert(
        db_path,
        id="m4",
        workspace_id="w2",
        title="幂等键设计",
        content="client_write_id 由内容哈希生成，重复提交返回已有候选。",
        type="pattern",
        updated_at="2026-10-23 01:00:00",
    )
    assert [item["id"] for item in search_local("幂等键", db_path=db_path)["results"]] == ["m4"]


def test_build_local_context_respects_item_limit(db_path: Path):
    data = build_local_context(
        workspace="web",
        query="redis",
        max_items=1,
        max_tokens=500,
        db_path=db_path,
    )
    assert data["source"] == "local"
    assert len(data["items"]) == 1
    assert "Redis" in data["context"]


def test_recall_uses_local_index_without_api(monkeypatch, db_path: Path):
    from adapters.hooks import recall

    monkeypatch.setenv("CWIKI_DB_PATH", str(db_path))
    monkeypatch.setenv("CWIKI_HOOK_RECALL_CACHE", str(db_path.parent / "recall-cache"))

    def _api_must_not_run(*_args, **_kwargs):
        raise AssertionError("API fallback should not run when the DB is readable")

    monkeypatch.setattr(recall, "_search", _api_must_not_run)
    text = recall.build_context("redis 槽位 重均衡", "web")
    assert "Redis" in text
    assert "<memory" in text


def test_recall_does_not_call_api_when_local_has_no_match(monkeypatch, db_path: Path):
    from adapters.hooks import recall

    monkeypatch.setenv("CWIKI_DB_PATH", str(db_path))
    monkeypatch.setenv("CWIKI_HOOK_RECALL_CACHE", str(db_path.parent / "recall-cache-2"))

    def _api_must_not_run(*_args, **_kwargs):
        raise AssertionError("API fallback should not run when the DB is readable")

    monkeypatch.setattr(recall, "_search", _api_must_not_run)
    assert recall.build_context("今天天气不错适合散步", "web") == ""


def test_head_selects_permanent_types_and_tags(db_path: Path):
    _insert(
        db_path,
        id="m5",
        workspace_id="w2",
        title="永久口径",
        content="这条被人工 pin 住，必须常驻。",
        type="lesson",
        is_permanent=1,
        importance=0.9,
    )
    _insert(
        db_path,
        id="m6",
        workspace_id="w2",
        title="用户偏好",
        content="回答尽量简洁。",
        type="feedback",
    )
    _insert(
        db_path,
        id="m7",
        workspace_id="w2",
        title="打标签的约定",
        content="所有接口返回统一结构。",
        type="fact",
        tags='["pinned"]',
    )
    data = head(
        "backend",
        types=("feedback",),
        tags=("pinned",),
        include_permanent=True,
        max_items=8,
        max_chars=2000,
        db_path=db_path,
    )
    ids = {item["id"] for item in data["items"]}
    assert {"m5", "m6", "m7"} <= ids
    assert "m2" not in ids
    assert data["items"][0]["id"] == "m5"


def test_head_respects_budget_and_workspace(db_path: Path):
    _insert(
        db_path,
        id="m8",
        workspace_id="w2",
        title="长偏好",
        content="很长的偏好正文。" * 100,
        type="feedback",
    )
    data = head("backend", types=("feedback",), max_items=1, max_chars=260, db_path=db_path)
    assert data["available"] is True
    assert data["items"][0]["truncated"] is True
    assert len(data["text"]) <= 260
    assert head("nope", types=("feedback",), db_path=db_path)["items"] == []


def test_build_session_head_follows_policy(monkeypatch, db_path: Path):
    from adapters.hooks import recall
    from packages.domain.config import agent_policy_config as policy

    _insert(
        db_path,
        id="m9",
        workspace_id="w2",
        title="用户偏好",
        content="回答尽量简洁。",
        type="feedback",
    )
    monkeypatch.setenv("CWIKI_DB_PATH", str(db_path))
    monkeypatch.setattr(policy, "always_inject_enabled", True)
    monkeypatch.setattr(policy, "always_inject_types", ("feedback",))
    monkeypatch.setattr(policy, "always_inject_tags", ())
    monkeypatch.setattr(policy, "always_inject_permanent", True)
    monkeypatch.setattr(policy, "always_inject_max_items", 8)
    monkeypatch.setattr(policy, "always_inject_max_chars", 2000)

    text = recall.build_session_head("backend")
    assert "用户偏好" in text
    monkeypatch.setattr(policy, "always_inject_enabled", False)
    assert recall.build_session_head("backend") == ""


def test_must_save_hint_from_policy(monkeypatch):
    from adapters.hooks import recall
    from packages.domain.config import agent_policy_config as policy

    monkeypatch.setattr(policy, "must_save_types", ("feedback", "rule"))
    monkeypatch.setattr(policy, "must_save_keywords", ("以后",))
    hint = recall.must_save_hint()
    assert "feedback" in hint and "以后" in hint
    monkeypatch.setattr(policy, "must_save_types", ())
    monkeypatch.setattr(policy, "must_save_keywords", ())
    assert recall.must_save_hint() == ""
