"""引擎侧候选过滤测试：rerank 后的 hard 档早删行为。

职责划分（W3-T3 定案）：engine 只做 hard 早删——被剔除的候选不再占用
多样性名额、不进 utility 聚合；demote/none 档统一由组装器入口
（apply_entry_filters）处理，避免同一候选被连乘两次惩罚因子。
本文件直接对 RetrievalEngine._apply_candidate_filters 做单元断言；
档位与阈值经 monkeypatch 注入，不依赖 config.yaml 实际值。
组装器入口全档过滤的行为在 test_entry_filters.py 中单独覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from packages.domain.config import settings
from packages.retrieval.engine import RetrievalEngine


def _mem(valid_to: datetime | None = None, confidence: float = 0.8) -> SimpleNamespace:
    return SimpleNamespace(valid_to=valid_to, confidence=confidence)


def _patch(
    monkeypatch,
    *,
    stale: str = "none",
    conf: str = "none",
    rel: str = "none",
    conf_floor: float = 0.3,
    rel_floor: float = 0.5,
) -> None:
    monkeypatch.setattr(settings, "stale_filter_mode", stale)
    monkeypatch.setattr(settings, "confidence_floor_mode", conf)
    monkeypatch.setattr(settings, "relevance_floor_mode", rel)
    monkeypatch.setattr(settings, "confidence_floor", conf_floor)
    monkeypatch.setattr(settings, "relevance_floor", rel_floor)


class TestHardOnlyEarlyRemoval:
    def test_all_demote_passes_through(self, monkeypatch):
        # demote 档不在这里降分——组装器入口统一处理，避免双重连乘
        _patch(monkeypatch, stale="demote", conf="demote", rel="demote")
        expired = datetime.now(UTC) - timedelta(days=1)
        mem_map = {
            "old": _mem(valid_to=expired, confidence=0.1),
            "weak": _mem(confidence=0.1),
            "solid": _mem(),
        }
        items = [("old", 0.9), ("weak", 0.45), ("solid", 0.8)]

        result = RetrievalEngine()._apply_candidate_filters(items, mem_map)

        assert result == items

    def test_all_none_passes_through(self, monkeypatch):
        _patch(monkeypatch, stale="none", conf="none", rel="none")
        expired = datetime.now(UTC) - timedelta(days=1)
        mem_map = {"old": _mem(valid_to=expired, confidence=0.1), "b": _mem()}

        result = RetrievalEngine()._apply_candidate_filters([("old", 0.9), ("b", 0.5)], mem_map)

        assert result == [("old", 0.9), ("b", 0.5)]

    def test_stale_hard_removes_expired(self, monkeypatch):
        _patch(monkeypatch, stale="hard")
        expired = datetime.now(UTC) - timedelta(days=1)
        mem_map = {"old": _mem(valid_to=expired), "fresh": _mem()}

        result = RetrievalEngine()._apply_candidate_filters([("old", 0.9), ("fresh", 0.8)], mem_map)

        assert [mid for mid, _ in result] == ["fresh"]

    def test_confidence_hard_removes_low_confidence(self, monkeypatch):
        _patch(monkeypatch, conf="hard", conf_floor=0.3)
        mem_map = {"weak": _mem(confidence=0.2), "solid": _mem(confidence=0.8)}

        result = RetrievalEngine()._apply_candidate_filters(
            [("weak", 0.9), ("solid", 0.8)], mem_map
        )

        assert [mid for mid, _ in result] == ["solid"]

    def test_relevance_hard_removes_low_score(self, monkeypatch):
        _patch(monkeypatch, rel="hard", rel_floor=0.5)
        mem_map = {"junk": _mem(), "hit": _mem()}

        result = RetrievalEngine()._apply_candidate_filters(
            [("junk", 0.42), ("hit", 0.75)], mem_map
        )

        assert [mid for mid, _ in result] == ["hit"]

    def test_relevance_floor_equal_boundary_kept(self, monkeypatch):
        # 边界语义：score == floor 视为达到下限，不剔除（与 < 判定一致）
        _patch(monkeypatch, rel="hard", rel_floor=0.5)
        mem_map = {"edge": _mem()}

        result = RetrievalEngine()._apply_candidate_filters([("edge", 0.5)], mem_map)

        assert result == [("edge", 0.5)]

    def test_floor_zero_disables_confidence_and_relevance(self, monkeypatch):
        # floor <= 0 等价关闭该过滤：mode 即使为 hard 也不生效
        _patch(monkeypatch, conf="hard", rel="hard", conf_floor=0.0, rel_floor=0.0)
        mem_map = {"weak": _mem(confidence=0.1), "junk": _mem()}

        result = RetrievalEngine()._apply_candidate_filters([("weak", 0.2), ("junk", 0.1)], mem_map)

        assert result == [("weak", 0.2), ("junk", 0.1)]

    def test_invalid_mode_falls_back_to_none(self, monkeypatch):
        # 非法档位告警并按 none 处理——配置错误不阻断检索
        _patch(monkeypatch, stale="bogus", conf="bogus", rel="bogus")
        expired = datetime.now(UTC) - timedelta(days=1)
        mem_map = {"old": _mem(valid_to=expired, confidence=0.1)}

        result = RetrievalEngine()._apply_candidate_filters([("old", 0.9)], mem_map)

        assert result == [("old", 0.9)]

    def test_entry_missing_from_mem_map_passes_through(self, monkeypatch):
        # mem_map 缺失的条目（防御边界）不参与判定，原样保留
        _patch(monkeypatch, stale="hard", conf="hard", rel="hard")

        result = RetrievalEngine()._apply_candidate_filters([("ghost", 0.9)], {})

        assert result == [("ghost", 0.9)]

    def test_hard_removal_preserves_order(self, monkeypatch):
        # 剔除后保持原有排名顺序，不做重排
        _patch(monkeypatch, stale="hard", rel="hard", rel_floor=0.5)
        expired = datetime.now(UTC) - timedelta(days=1)
        mem_map = {
            "old": _mem(valid_to=expired),
            "junk": _mem(),
            "a": _mem(),
            "b": _mem(),
        }
        items = [("old", 0.9), ("a", 0.8), ("junk", 0.3), ("b", 0.6)]

        result = RetrievalEngine()._apply_candidate_filters(items, mem_map)

        assert result == [("a", 0.8), ("b", 0.6)]
