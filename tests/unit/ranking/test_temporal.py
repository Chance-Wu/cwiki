"""时态过滤纯函数测试（apply_stale_filter 三档行为）。"""

from datetime import UTC, datetime, timedelta

from packages.retrieval.ranking.temporal import (
    STALE_DEMOTE_FACTOR,
    apply_stale_filter,
    is_stale_item,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _mem(mid: str, score: float, valid_to: datetime | None = None) -> dict:
    return {"id": mid, "score": score, "valid_to": valid_to}


class TestIsStaleItem:
    def test_expired_valid_to(self):
        item = _mem("1", 0.9, NOW - timedelta(days=1))
        assert is_stale_item(item, NOW) is True

    def test_future_valid_to_not_stale(self):
        item = _mem("1", 0.9, NOW + timedelta(days=1))
        assert is_stale_item(item, NOW) is False

    def test_missing_valid_to_not_stale(self):
        # 无有效期约束的记忆不受过期过滤影响
        assert is_stale_item({"id": "1", "score": 0.9}, NOW) is False

    def test_naive_valid_to_treated_as_utc(self):
        # naive datetime 按 UTC 处理，与 temporal_score 的口径一致
        item = _mem("1", 0.9, (NOW - timedelta(days=1)).replace(tzinfo=None))
        assert is_stale_item(item, NOW) is True


class TestApplyStaleFilter:
    def test_none_keeps_everything(self):
        # none 档 = 现状：过期项保留且分数不动（temporal_score 已给底分参与排序）
        items = [
            _mem("stale", 0.9, NOW - timedelta(days=1)),
            _mem("fresh", 0.8, NOW + timedelta(days=1)),
        ]
        result = apply_stale_filter(items, mode="none", now=NOW)
        assert [m["id"] for m in result] == ["stale", "fresh"]
        assert result[0]["score"] == 0.9

    def test_demote_multiplies_stale_score_only(self):
        items = [
            _mem("stale", 0.9, NOW - timedelta(days=1)),
            _mem("fresh", 0.8, NOW + timedelta(days=1)),
            _mem("no-expiry", 0.7),
        ]
        result = apply_stale_filter(items, mode="demote", now=NOW)
        scores = {m["id"]: m["score"] for m in result}
        assert len(result) == 3
        assert scores["stale"] == 0.9 * STALE_DEMOTE_FACTOR
        assert scores["fresh"] == 0.8
        assert scores["no-expiry"] == 0.7
        # 不修改输入元素（返回副本）
        assert items[0]["score"] == 0.9

    def test_hard_drops_stale_items(self):
        items = [
            _mem("stale", 0.9, NOW - timedelta(days=1)),
            _mem("fresh", 0.8, NOW + timedelta(days=1)),
        ]
        result = apply_stale_filter(items, mode="hard", now=NOW)
        assert [m["id"] for m in result] == ["fresh"]

    def test_invalid_mode_raises(self):
        try:
            apply_stale_filter([], mode="unknown", now=NOW)
        except ValueError as e:
            assert "unknown" in str(e)
        else:
            raise AssertionError("无效 mode 应抛 ValueError")
