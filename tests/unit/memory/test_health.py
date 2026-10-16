"""packages.memory.health.compute_health 单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.memory.health import compute_health


def _now() -> datetime:
    return datetime.now(UTC)


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


# ---- 基线：全新且口碑良好的记忆应为 healthy ------------------------------


def test_fresh_memory_with_no_signals_is_healthy():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.8,
        importance=0.7,
    )
    assert h.status == "healthy"
    assert h.score >= 0.85
    assert h.reasons == []


# ---- 冲突是硬性阻断 -----------------------------------------------------


def test_conflict_overrides_everything():
    h = compute_health(
        memory_status="active",
        utility_score=1.0,
        conflict_count=2,
        feedback_useful=10,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=100,
        confidence=0.9,
    )
    assert h.status == "conflicted"
    assert h.score <= 0.2  # 2 次冲突 → 0.2 - 0.05*(2-1) = 0.15


def test_conflicted_status_also_hard_blocks():
    h = compute_health(
        memory_status="conflicted",
        utility_score=1.0,
        conflict_count=0,
        feedback_useful=10,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=100,
    )
    assert h.status == "conflicted"


# ---- 反馈信号 ------------------------------------------------------------


def test_single_not_useful_vote_has_small_impact():
    """单张反对票不应重创分数（样本置信度低）。"""
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=1,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.7,
    )
    assert h.status == "healthy"
    assert h.score >= 0.75


def test_many_not_useful_votes_drag_score_down():
    h_few = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.7,
    )
    h_many = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=2,
        feedback_not_useful=20,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.7,
    )
    assert h_many.score < h_few.score
    # 显著的负反馈应明显拉低分数
    assert h_few.score - h_many.score > 0.05


def test_no_feedback_is_neutral():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.7,
    )
    assert not any("feedback" in r.lower() for r in h.reasons)


# ---- 陈旧度 --------------------------------------------------------------


def test_recently_used_memory_has_no_staleness_penalty():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_days_ago(7),
        created_at=_days_ago(30),
        usage_count=5,
        confidence=0.7,
    )
    assert not any("not used" in r.lower() for r in h.reasons)


def test_long_unused_memory_penalised():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_days_ago(365),
        created_at=_days_ago(400),
        usage_count=5,
        confidence=0.7,
    )
    # 长期未使用应触发陈旧度惩罚
    assert any("not used" in r.lower() for r in h.reasons)
    # 陈旧度惩罚被加权平均稀释，所以分数仍相对较高
    assert h.score < 0.95


def test_never_used_new_memory_has_grace_period():
    """创建 60 天但从未使用的记忆不应被重罚。"""
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=None,
        created_at=_days_ago(60),
        usage_count=0,
        confidence=0.7,
    )
    # 宽限期内分数应保持较高
    assert h.score >= 0.85


def test_never_used_old_memory_penalised():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=None,
        created_at=_days_ago(365),
        usage_count=0,
        confidence=0.7,
    )
    # 一年未使用应拉低分数
    assert h.score < 0.9
    assert any("never used" in r.lower() for r in h.reasons)


# ---- 置信度 --------------------------------------------------------------


def test_low_confidence_memory_penalised():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.1,
    )
    # 低置信度应把分数拉到健康基线以下
    assert h.score < 0.95
    assert any("confidence" in r.lower() for r in h.reasons)


def test_high_confidence_memory_no_penalty():
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
        confidence=0.9,
    )
    # 高置信度应得到健康分数
    assert h.score > 0.85
    # 高置信度可能作为提示信息出现在 reasons 中
    assert h.status == "healthy"


# ---- 永久记忆下限 --------------------------------------------------------


def test_permanent_memory_has_score_floor():
    h = compute_health(
        memory_status="active",
        utility_score=0.1,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=30,
        last_used_at=_days_ago(400),
        created_at=_days_ago(500),
        usage_count=0,
        confidence=0.1,
        importance=0.1,
        is_permanent=True,
    )
    assert h.score >= 0.6
    assert any("permanent" in r.lower() or "pinned" in r.lower() for r in h.reasons)


def test_non_permanent_memory_can_drop_below_floor():
    h = compute_health(
        memory_status="active",
        utility_score=0.1,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=30,
        last_used_at=_days_ago(400),
        created_at=_days_ago(500),
        usage_count=0,
        confidence=0.1,
        importance=0.1,
        is_permanent=False,
    )
    assert h.score < 0.6


# ---- 状态分桶 -------------------------------------------------------------


def test_status_buckets():
    def h(score_kwargs):
        return compute_health(
            memory_status="active",
            conflict_count=0,
            feedback_useful=0,
            feedback_not_useful=0,
            usage_count=5,
            **score_kwargs,
        )

    # healthy：高效用、近期、高置信度
    assert (
        h(
            {
                "utility_score": 0.9,
                "last_used_at": _now(),
                "created_at": _days_ago(5),
                "confidence": 0.9,
            }
        ).status
        == "healthy"
    )
    # needs_review：高效用低、陈旧、低置信度
    assert (
        h(
            {
                "utility_score": 0.2,
                "last_used_at": _days_ago(300),
                "created_at": _days_ago(400),
                "confidence": 0.2,
            }
        ).status
        == "needs_review"
    )
    # suspicious：所有信号都很差
    assert (
        h(
            {
                "utility_score": 0.0,
                "last_used_at": _days_ago(800),
                "created_at": _days_ago(1000),
                "confidence": 0.05,
            }
        ).status
        == "suspicious"
    )


# ---- 向后兼容：不传新 kwargs 的旧调用点 ----------------------------------


def test_works_without_new_kwargs():
    """不传 confidence/importance/is_permanent 的旧调用点仍可用。"""
    h = compute_health(
        memory_status="active",
        utility_score=0.7,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(10),
        usage_count=5,
    )
    assert h.status == "healthy"
    assert h.score >= 0.7


# ---- 分数限定在 [0, 1] --------------------------------------------------


def test_score_never_exceeds_bounds():
    worst = compute_health(
        memory_status="active",
        utility_score=0.0,
        conflict_count=0,
        feedback_useful=0,
        feedback_not_useful=100,
        last_used_at=_days_ago(1000),
        created_at=_days_ago(2000),
        usage_count=0,
        confidence=0.0,
        importance=0.0,
    )
    assert 0.0 <= worst.score <= 1.0

    best = compute_health(
        memory_status="active",
        utility_score=1.0,
        conflict_count=0,
        feedback_useful=100,
        feedback_not_useful=0,
        last_used_at=_now(),
        created_at=_days_ago(1),
        usage_count=1000,
        confidence=1.0,
        importance=1.0,
    )
    assert 0.0 <= best.score <= 1.0
