"""召回交付信号：hook 注入后落 spool、批量补投、后端幂等。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from adapters.hooks import recall, usage


@pytest.fixture
def hook_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "hook-state"
    monkeypatch.setenv("CWIKI_HOOK_STATE_DIR", str(root))
    monkeypatch.setenv("CWIKI_HOOK_RECALL_CACHE", str(tmp_path / "recall-cache"))
    return root


def _records(host: str = "qoder") -> list[dict[str, Any]]:
    return [record for _, record in usage.load(host, namespace=usage.NAMESPACE)]


def test_store_writes_usage_namespaced_record(hook_state: Path) -> None:
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    usage.store(
        host="qoder",
        session_id="sess-1",
        workspace="cwiki",
        prompt="wal checkpoint 顺序是什么",
        memory_ids=ids,
    )
    records = _records()
    assert len(records) == 1
    record = records[0]
    assert record["session_id"] == "sess-1"
    assert [e["memory_id"] for e in record["events"]] == ids
    assert all(e["stage"] == "used" for e in record["events"])
    assert [e["position"] for e in record["events"]] == [0, 1]
    assert record["record_id"]


def test_usage_namespace_isolated_from_capture(hook_state: Path) -> None:
    """usage 记录不得被 capture 的投递读到（否则会被发到 capture 端点）。"""
    from adapters.hooks import capture, spool

    usage.store(
        host="dsh",
        session_id="s",
        workspace="w",
        prompt="p" * 10,
        memory_ids=[str(uuid.uuid4())],
    )
    assert spool.load("dsh", namespace=usage.NAMESPACE)
    assert spool.load("dsh") == []
    assert capture.load("dsh") == []


def test_record_id_stable_per_session_but_differs_across_sessions(hook_state: Path) -> None:
    mid = str(uuid.uuid4())
    a1 = usage.record_id_for("s1", "prompt", "ws", [mid])
    a2 = usage.record_id_for("s1", "prompt", "ws", [mid])
    b1 = usage.record_id_for("s2", "prompt", "ws", [mid])
    assert a1 == a2
    assert a1 != b1


def test_build_context_reports_delivered_ids(hook_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """注入命中后回调 on_deliver；预算内跳过的条目不在上报列表。"""
    mem_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    payload = {
        "available": True,
        "insufficient": False,
        "results": [
            {
                "id": mem_id,
                "type": "fact",
                "title": "A",
                "content": "正文一",
                "score": 0.9,
                "version": 1,
                "source": "memory",
            },
            {
                "id": other_id,
                "type": "fact",
                "title": "B",
                "content": "正文二",
                # 低于 MIN_SCORE：不注入也不上报
                "score": 0.05,
                "version": 1,
                "source": "memory",
            },
        ],
    }
    monkeypatch.setattr(recall, "_local_search", lambda *_a, **_k: payload)

    seen: list[list[str]] = []
    text = recall.build_context(
        "wal checkpoint 顺序", "cwiki", on_deliver=lambda ids: seen.append(list(ids))
    )
    assert "<memory" in text
    assert seen == [[mem_id]]

    # 缓存命中同样上报：同一会话重复提问仍是真实交付
    seen.clear()
    text2 = recall.build_context(
        "wal checkpoint 顺序", "cwiki", on_deliver=lambda ids: seen.append(list(ids))
    )
    assert text2 == text
    assert seen == [[mem_id]]
    cache_file = next(Path(__import__("os").environ["CWIKI_HOOK_RECALL_CACHE"]).glob("*.txt"))
    assert json.loads(cache_file.read_text(encoding="utf-8"))["ids"] == [mem_id]


def test_build_context_no_match_does_not_report(hook_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recall, "_local_search", lambda *_a, **_k: {"available": True, "results": []}
    )
    called: list[list[str]] = []
    assert recall.build_context("随便说点什么", "cwiki", on_deliver=called.append) == ""
    assert called == []


def test_report_delivery_swallows_callback_errors(
    hook_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "available": True,
        "insufficient": False,
        "results": [
            {
                "id": str(uuid.uuid4()),
                "type": "fact",
                "title": "A",
                "content": "正文",
                "score": 0.9,
                "version": 1,
                "source": "memory",
            }
        ],
    }
    monkeypatch.setattr(recall, "_local_search", lambda *_a, **_k: payload)

    def _boom(_ids: list[str]) -> None:
        raise RuntimeError("上报失败不能影响注入")

    text = recall.build_context("wal checkpoint 顺序", "cwiki", on_deliver=_boom)
    assert "<memory" in text


def test_drain_batches_records_and_clears_on_success(hook_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [str(uuid.uuid4()) for _ in range(2)]
    usage.store(
        host="qoder", session_id="s1", workspace="w", prompt="prompt one", memory_ids=ids
    )
    usage.store(
        host="qoder", session_id="s1", workspace="w", prompt="prompt two", memory_ids=ids[:1]
    )
    posted: list[dict[str, Any]] = []

    def fake_post(records: list[dict[str, Any]]) -> bool:
        posted.extend(records)
        return True

    monkeypatch.setattr(usage, "_post", fake_post)
    result = usage.drain("qoder")
    assert result == {"delivered": 2}
    assert len(posted) == 2
    assert _records() == []


def test_drain_keeps_backlog_when_api_unreachable(hook_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    usage.store(
        host="qoder",
        session_id="s1",
        workspace="w",
        prompt="prompt one",
        memory_ids=[str(uuid.uuid4())],
    )
    monkeypatch.setattr(usage, "_post", lambda _r: False)
    assert usage.drain("qoder") == {"delivered": 0}
    # 未投递的记录留在 spool 里等下次补投
    assert len(_records()) == 1
