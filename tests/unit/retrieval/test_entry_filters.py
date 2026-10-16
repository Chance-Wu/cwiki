"""apply_entry_filters 单元测试：组装器入口的三档（none/demote/hard）过滤。

覆盖三类判定（stale / confidence / relevance_floor）× 三种档位的行为、
事件元组（(memory_id, stage, reason)）、判定优先级（stale > confidence >
relevance）、confidence 缺键不误杀、demote 返回副本不改输入。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.retrieval.context.filters import (
    CONFIDENCE_DEMOTE_FACTOR,
    RELEVANCE_DEMOTE_FACTOR,
    apply_entry_filters,
)
from packages.retrieval.ranking.temporal import STALE_DEMOTE_FACTOR

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _mem(
    mem_id: str,
    score: float,
    *,
    valid_to: datetime | None = None,
    confidence: float | None = 0.8,
) -> dict:
    item: dict = {"id": mem_id, "score": score, "content": f"内容 {mem_id}"}
    if valid_to is not None:
        item["valid_to"] = valid_to
    if confidence is not None:
        item["confidence"] = confidence
    return item


def _expired() -> datetime:
    return NOW - timedelta(days=1)


class TestStaleFilter:
    def test_hard_removes_expired(self):
        items = [_mem("old", 0.9, valid_to=_expired()), _mem("fresh", 0.8)]

        result, events = apply_entry_filters(items, stale_mode="hard", now=NOW)

        assert [m["id"] for m in result] == ["fresh"]
        assert events == [("old", "stale", "expired")]

    def test_demote_reduces_score_and_keeps(self):
        items = [_mem("old", 0.9, valid_to=_expired()), _mem("fresh", 0.8)]

        result, events = apply_entry_filters(items, stale_mode="demote", now=NOW)

        assert result[0]["id"] == "old"
        assert result[0]["score"] == 0.9 * STALE_DEMOTE_FACTOR
        assert result[1] == items[1]
        assert events == [("old", "stale", "expired_demoted")]

    def test_none_keeps_everything(self):
        items = [_mem("old", 0.9, valid_to=_expired())]

        result, events = apply_entry_filters(items, stale_mode="none", now=NOW)

        assert result == items
        assert events == []

    def test_valid_to_none_not_stale(self):
        items = [_mem("open", 0.9, valid_to=None)]

        result, events = apply_entry_filters(items, stale_mode="hard", now=NOW)

        assert result == items
        assert events == []


class TestConfidenceFilter:
    def test_hard_removes_low_confidence(self):
        items = [_mem("weak", 0.9, confidence=0.2), _mem("solid", 0.8, confidence=0.9)]

        result, events = apply_entry_filters(items, confidence_mode="hard", confidence_floor=0.3)

        assert [m["id"] for m in result] == ["solid"]
        assert events == [("weak", "confidence", "below_confidence_floor")]

    def test_demote_reduces_score(self):
        items = [_mem("weak", 0.9, confidence=0.2)]

        result, events = apply_entry_filters(items, confidence_mode="demote", confidence_floor=0.3)

        assert result[0]["score"] == 0.9 * CONFIDENCE_DEMOTE_FACTOR
        assert events == [("weak", "confidence", "low_confidence_demoted")]

    def test_missing_confidence_key_not_judged(self):
        # 合成条目（如评测夹具的注入条目）常无 confidence 键，不误杀
        items = [{"id": "syn", "score": 0.9, "content": "合成"}]

        result, events = apply_entry_filters(items, confidence_mode="hard", confidence_floor=0.3)

        assert result == items
        assert events == []

    def test_floor_zero_disables(self):
        items = [_mem("weak", 0.9, confidence=0.1)]

        result, events = apply_entry_filters(items, confidence_mode="hard", confidence_floor=0.0)

        assert result == items
        assert events == []


class TestRelevanceFilter:
    def test_hard_removes_low_score(self):
        items = [_mem("junk", 0.42), _mem("hit", 0.75)]

        result, events = apply_entry_filters(items, relevance_mode="hard", relevance_floor=0.5)

        assert [m["id"] for m in result] == ["hit"]
        assert events == [("junk", "relevance_floor", "below_relevance_floor")]

    def test_demote_reduces_score(self):
        items = [_mem("junk", 0.42)]

        result, events = apply_entry_filters(items, relevance_mode="demote", relevance_floor=0.5)

        assert result[0]["score"] == 0.42 * RELEVANCE_DEMOTE_FACTOR
        assert events == [("junk", "relevance_floor", "low_relevance_demoted")]

    def test_boundary_equal_floor_kept(self):
        # score == floor 达到下限，不剔除
        items = [_mem("edge", 0.5)]

        result, events = apply_entry_filters(items, relevance_mode="hard", relevance_floor=0.5)

        assert result == items
        assert events == []


class TestPriorityAndStacking:
    def test_stale_hard_short_circuits_later_judgments(self):
        # hard stale 即删：不再产生 confidence/relevance 事件
        items = [_mem("bad", 0.9, valid_to=_expired(), confidence=0.1)]

        result, events = apply_entry_filters(
            items,
            stale_mode="hard",
            confidence_mode="hard",
            confidence_floor=0.3,
            relevance_mode="hard",
            relevance_floor=0.5,
            now=NOW,
        )

        assert result == []
        assert events == [("bad", "stale", "expired")]

    def test_confidence_hard_short_circuits_relevance(self):
        items = [_mem("bad", 0.4, confidence=0.1)]

        result, events = apply_entry_filters(
            items,
            confidence_mode="hard",
            confidence_floor=0.3,
            relevance_mode="hard",
            relevance_floor=0.5,
        )

        assert result == []
        assert events == [("bad", "confidence", "below_confidence_floor")]

    def test_stale_demote_still_judged_by_relevance_hard(self):
        # 过期且低分的条目：stale demote 记事件后仍进入 relevance 判定，
        # 被 relevance hard 拦截（ctx-019 泄漏路径的回归用例）
        items = [_mem("old_junk", 0.32, valid_to=_expired())]

        result, events = apply_entry_filters(
            items,
            stale_mode="demote",
            relevance_mode="hard",
            relevance_floor=0.5,
            now=NOW,
        )

        assert result == []
        assert ("old_junk", "stale", "expired_demoted") in events
        assert ("old_junk", "relevance_floor", "below_relevance_floor") in events

    def test_demote_factors_stack_across_stages(self):
        # 过期 + 低置信 + 低相关全命中 demote：三个因子连乘
        items = [_mem("bad", 0.9, valid_to=_expired(), confidence=0.1)]

        result, events = apply_entry_filters(
            items,
            stale_mode="demote",
            confidence_mode="demote",
            confidence_floor=0.3,
            relevance_mode="demote",
            relevance_floor=0.5,
            now=NOW,
        )

        expected = 0.9 * STALE_DEMOTE_FACTOR * CONFIDENCE_DEMOTE_FACTOR * RELEVANCE_DEMOTE_FACTOR
        assert result[0]["score"] == pytest.approx(expected)
        assert len(events) == 3

    def test_demote_does_not_mutate_input(self):
        # demote 返回副本：调用方持有的原列表分数不变
        items = [_mem("weak", 0.9, confidence=0.1)]

        apply_entry_filters(items, confidence_mode="demote", confidence_floor=0.3)

        assert items[0]["score"] == 0.9


class TestModeValidation:
    def test_invalid_mode_falls_back_to_none(self):
        items = [_mem("old", 0.9, valid_to=_expired())]

        result, events = apply_entry_filters(items, stale_mode="bogus", now=NOW)

        assert result == items
        assert events == []

    def test_all_inactive_returns_copy_of_input(self):
        # 全部档位关闭时直接返回输入副本，不做任何判定
        items = [_mem("a", 0.9)]

        result, events = apply_entry_filters(items)

        assert result == items
        assert result is not items
        assert events == []
