"""召回总闸 retrieval.auto_recall_enabled：关闭后两条自动注入都不生效。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from adapters.hooks import recall
from packages.domain.config import agent_policy_config as policy
from packages.domain.config import settings

PROMPT = "wal checkpoint 的执行顺序是什么"


@pytest.fixture
def recall_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(tmp_path / "hook-state"))
    monkeypatch.setenv("CWIKI_HOOK_RECALL_CACHE", str(tmp_path / "recall-cache"))


def _search_payload() -> dict[str, Any]:
    return {
        "available": True,
        "insufficient": False,
        "results": [
            {
                "id": str(uuid.uuid4()),
                "type": "fact",
                "title": "WAL 顺序",
                "content": "checkpoint 要先落日志再截断",
                "score": 0.9,
                "version": 1,
                "source": "memory",
            }
        ],
    }


@pytest.fixture
def search_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """记录两条检索通路是否被触达，用于证明总闸拦在检索之前。"""
    calls: list[str] = []

    def _local(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls.append("local")
        return _search_payload()

    def _http(*_a: Any, **_k: Any) -> dict[str, Any]:
        calls.append("http")
        return _search_payload()

    monkeypatch.setattr(recall, "_local_search", _local)
    monkeypatch.setattr(recall, "_search", _http)
    return calls


@pytest.fixture
def head_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """常驻注入通路可用：把总闸的影响与 always_inject 自身开关区分开。"""
    from adapters.mcp import local_index

    monkeypatch.setattr(policy, "always_inject_enabled", True)
    monkeypatch.setattr(
        local_index, "head", lambda *_a, **_k: {"available": True, "text": "永久记忆正文"}
    )


def test_per_prompt_recall_injects_when_enabled(recall_state, search_calls, monkeypatch):
    monkeypatch.setattr(settings, "auto_recall_enabled", True, raising=False)
    assert "<memory" in recall.build_context(PROMPT, "cwiki")
    assert search_calls == ["local"]


def test_per_prompt_recall_disabled_skips_search(recall_state, search_calls, monkeypatch):
    monkeypatch.setattr(settings, "auto_recall_enabled", False, raising=False)
    assert recall.build_context(PROMPT, "cwiki") == ""
    assert search_calls == []


def test_session_head_injects_when_enabled(recall_state, head_available, monkeypatch):
    monkeypatch.setattr(settings, "auto_recall_enabled", True, raising=False)
    assert "永久记忆正文" in recall.build_session_head("cwiki")


def test_session_head_disabled_skips_always_inject(recall_state, head_available, monkeypatch):
    monkeypatch.setattr(settings, "auto_recall_enabled", False, raising=False)
    assert recall.build_session_head("cwiki") == ""


def test_recall_stays_on_when_flag_unreadable(recall_state, search_calls, monkeypatch):
    """hook 是 fail-open 的：读不到总闸也不能顺手把召回关掉。"""
    import packages.domain.config as domain_config

    class _BrokenSettings:
        @property
        def auto_recall_enabled(self) -> bool:
            raise RuntimeError("配置不可读")

    monkeypatch.setattr(domain_config, "settings", _BrokenSettings())
    assert "<memory" in recall.build_context(PROMPT, "cwiki")
    assert search_calls == ["local"]
