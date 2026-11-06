"""SessionStart 复习到期提示：只读本地 DB、每日去重、异常静默。"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from adapters.hooks import review_hint


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "cwiki.db"
    con = sqlite3.connect(path)
    con.executescript(
        """
        create table workspace (id text primary key, name text);
        create table memory (id text primary key, workspace_id text, title text,
                             status text default 'active');
        create table review_schedule (id text primary key, memory_id text,
                                      workspace_id text, next_review text,
                                      suspended_at text);
        """
    )
    ws = str(uuid.uuid4())
    con.execute("insert into workspace values (?, 'cwiki')", (ws,))
    now = datetime.now(UTC).replace(tzinfo=None)
    due = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    future = (now + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    for index, (next_review, status, suspended) in enumerate(
        [
            (due, "active", None),
            (due, "active", None),
            (future, "active", None),
            (due, "deprecated", None),
            (due, "active", due),
        ]
    ):
        mid = str(uuid.uuid4())
        con.execute(
            "insert into memory (id, workspace_id, title, status) values (?,?,?,?)",
            (mid, ws, f"到期记忆 {index}", status),
        )
        con.execute(
            "insert into review_schedule (id, memory_id, workspace_id, next_review, suspended_at)"
            " values (?,?,?,?,?)",
            (str(uuid.uuid4()), mid, ws, next_review, suspended),
        )
    con.commit()
    con.close()
    return path


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    monkeypatch.setenv("CWIKI_DB_PATH", str(db_path))
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(tmp_path / "hook-state"))
    monkeypatch.setenv("CWIKI_HOOK_RECALL_CACHE", str(tmp_path / "recall-cache"))


def test_lists_due_excluding_future_inactive_and_suspended() -> None:
    hint = review_hint.due_hint("cwiki", "qoder")
    # 只有 2 条到期 active 未暂停：未来的、deprecated 的、已暂停的都不算
    assert "2 条记忆已到复习窗口" in hint
    assert "memory_review_due" in hint


def test_hint_is_empty_for_unknown_workspace() -> None:
    assert review_hint.due_hint("ghost", "qoder") == ""


def test_hint_shown_once_per_day_per_workspace() -> None:
    assert review_hint.due_hint("cwiki", "qoder") != ""
    assert review_hint.due_hint("cwiki", "qoder") == ""
    # 其他工作区独立计数
    assert review_hint.due_hint("cwiki", "dsh") != ""


def test_hint_returns_when_due_count_changes(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert review_hint.due_hint("cwiki", "qoder") != ""
    assert review_hint.due_hint("cwiki", "qoder") == ""
    # 复习后到期数变化：应重新提示一次
    con = sqlite3.connect(db_path)
    future = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=4)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    con.execute(
        "update review_schedule set next_review = ? where suspended_at is null"
        " and next_review <= datetime('now')",
        (future,),
    )
    con.commit()
    con.close()
    assert review_hint.due_hint("cwiki", "qoder") == ""


def test_missing_db_is_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CWIKI_DB_PATH", str(tmp_path / "nope.db"))
    assert review_hint.due_hint("cwiki", "qoder") == ""


def test_broken_db_is_silent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database")
    monkeypatch.setenv("CWIKI_DB_PATH", str(bad))
    assert review_hint.due_hint("cwiki", "qoder") == ""


def test_enabled_follows_config_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.domain.config import parasitic_evolution_config

    monkeypatch.setattr(parasitic_evolution_config, "review_reminders_enabled", True)
    assert review_hint.enabled() is True
    monkeypatch.setattr(parasitic_evolution_config, "review_reminders_enabled", False)
    assert review_hint.enabled() is False
