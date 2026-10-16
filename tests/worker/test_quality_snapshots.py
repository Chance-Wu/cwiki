"""MQ-003 评分与关系分类输入输出快照测试。

锁定当前算法行为，任何评分/关系判定逻辑变更必须显式更新快照。
"""

import json
from pathlib import Path

import pytest

from apps.worker.dedup import _classify_high_similarity, classify_relation
from apps.worker.scoring import calculate_value_score, classify_priority, score_candidate

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _load_snapshot(name: str) -> dict:
    path = SNAPSHOT_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_snapshot(name: str, data: dict) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))


class TestScoringSnapshots:
    """评分函数快照：锁定 calculate_value_score 和 classify_priority 的行为。"""

    def test_high_quality_snapshot(self):
        candidate = {
            "title": "SQLite WAL 同步前必须 checkpoint",
            "content": "cwiki 使用 SQLite WAL 模式，同步前需执行 PRAGMA wal_checkpoint(TRUNCATE)，确保数据库提交完整。",
            "reusability": 0.9,
            "stability": 0.85,
            "confidence": 0.9,
            "importance": 0.85,
            "evidence_strength": 0.8,
        }
        result = {
            "value_score": calculate_value_score(candidate),
            "priority": classify_priority(calculate_value_score(candidate)),
        }
        snapshot = _load_snapshot("scoring_high_quality")
        if snapshot:
            assert result["value_score"] == pytest.approx(snapshot["value_score"], abs=1e-6)
            assert result["priority"] == snapshot["priority"]
        else:
            _save_snapshot("scoring_high_quality", result)

    def test_low_quality_snapshot(self):
        candidate = {
            "title": "随便写的",
            "content": "一些想法",
            "reusability": 0.1,
            "stability": 0.1,
            "confidence": 0.1,
            "importance": 0.1,
            "evidence_strength": 0.1,
        }
        result = {
            "value_score": calculate_value_score(candidate),
            "priority": classify_priority(calculate_value_score(candidate)),
        }
        snapshot = _load_snapshot("scoring_low_quality")
        if snapshot:
            assert result["value_score"] == pytest.approx(snapshot["value_score"], abs=1e-6)
            assert result["priority"] == snapshot["priority"]
        else:
            _save_snapshot("scoring_low_quality", result)

    def test_none_dimensions_return_none(self):
        candidate = {
            "title": "test",
            "content": "content",
            "reusability": None,
            "stability": 0.6,
            "confidence": None,
            "importance": 0.7,
            "evidence_strength": None,
        }
        score = calculate_value_score(candidate)
        snapshot = _load_snapshot("scoring_none_dimensions")
        if snapshot:
            assert score is None
        else:
            _save_snapshot("scoring_none_dimensions", {"value_score": score})
        assert score is None

    def test_full_pipeline_snapshot(self):
        candidate = {
            "title": "FastAPI 异步会话工厂",
            "content": "使用 SQLAlchemy async sessionmaker，每次请求创建独立会话，避免跨请求状态泄漏。",
            "reusability": 0.8,
            "stability": 0.75,
            "confidence": 0.85,
            "importance": 0.7,
            "evidence_strength": 0.6,
            "novelty": 0.7,
        }
        result = score_candidate(candidate)
        snapshot = _load_snapshot("scoring_full_pipeline")
        if snapshot:
            assert result["value_score"] == pytest.approx(snapshot["value_score"], abs=1e-6)
            assert result["priority"] == snapshot["priority"]
            assert result["novelty"] == pytest.approx(snapshot["novelty"], abs=1e-6)
        else:
            _save_snapshot("scoring_full_pipeline", {
                "value_score": result["value_score"],
                "priority": result["priority"],
                "novelty": result["novelty"],
            })


class TestRelationSnapshots:
    """关系分类快照：锁定 classify_relation 和 _classify_high_similarity 的行为。"""

    @staticmethod
    def _make_vecs(sim: float) -> tuple[list[float], list[float]]:
        a = [1.0, 0.0, 0.0]
        b = [sim, (1 - sim**2) ** 0.5, 0.0]
        return a, b

    def test_version_update_candidate(self):
        a, b = self._make_vecs(0.98)
        result = classify_relation(
            a, b,
            "部署使用 v2.1.0，蓝绿发布",
            "部署使用 v2.0.0，滚动发布",
        )
        assert result == "update_candidate"

    def test_date_update_candidate(self):
        a, b = self._make_vecs(0.98)
        result = classify_relation(
            a, b,
            "2026-10-15 决定采用方案 B",
            "2026-09-01 讨论了方案 A/B",
        )
        assert result == "update_candidate"

    def test_similar_content_returns_similar(self):
        a, b = self._make_vecs(0.98)
        result = classify_relation(
            a, b,
            "使用 SQLAlchemy async 会话工厂",
            "使用 SQLAlchemy async 会话工厂。",
        )
        assert result == "similar"

    def test_complementary_returns_similar(self):
        a, b = self._make_vecs(0.98)
        result = classify_relation(
            a, b,
            "前端 Vite 构建配置要点",
            "后端 FastAPI 部署配置要点",
            "前端构建",
            "后端部署",
        )
        assert result == "similar"

    def test_medium_similarity_returns_new(self):
        a, b = self._make_vecs(0.50)
        result = classify_relation(
            a, b,
            "使用 Redis 缓存用户会话",
            "PostgreSQL 连接池配置",
        )
        assert result == "new"

    def test_classify_high_sim_snapshot(self):
        result = _classify_high_similarity(
            "连接池大小 20，超时 30 秒，新增只读副本路由",
            "连接池大小 20，超时 30 秒",
            "数据库连接池",
            "数据库连接池",
        )
        snapshot = _load_snapshot("classify_high_sim_superset")
        if snapshot:
            assert result == snapshot["relation"]
        else:
            _save_snapshot("classify_high_sim_superset", {"relation": result})
