"""Epic 4 生命周期状态转换校验测试。"""

import pytest

from packages.memory.lifecycle import (
    InvalidStatusTransition,
    get_allowed_candidate_transitions,
    get_allowed_memory_transitions,
    validate_candidate_status_transition,
    validate_memory_status_transition,
)


class TestMemoryStatusTransitions:
    """正式记忆状态转换校验。"""

    @pytest.mark.parametrize(
        "current,target",
        [
            ("active", "superseded"),
            ("active", "conflicted"),
            ("active", "archived"),
            ("active", "deprecated"),
            ("superseded", "active"),
            ("superseded", "archived"),
            ("conflicted", "active"),
            ("conflicted", "superseded"),
            ("conflicted", "archived"),
            ("archived", "active"),
            ("deprecated", "archived"),
        ],
    )
    def test_valid_transitions(self, current, target):
        validate_memory_status_transition(current, target)

    @pytest.mark.parametrize(
        "current,target",
        [
            ("active", "active"),
            ("archived", "superseded"),
            ("deprecated", "active"),
            ("superseded", "conflicted"),
        ],
    )
    def test_invalid_transitions(self, current, target):
        with pytest.raises(InvalidStatusTransition):
            validate_memory_status_transition(current, target)

    def test_error_contains_details(self):
        with pytest.raises(InvalidStatusTransition) as exc_info:
            validate_memory_status_transition("archived", "superseded")
        assert exc_info.value.current == "archived"
        assert exc_info.value.target == "superseded"
        assert "active" in exc_info.value.allowed


class TestCandidateStatusTransitions:
    """候选记忆状态转换校验。"""

    @pytest.mark.parametrize(
        "current,target",
        [
            ("pending_review", "approved"),
            ("pending_review", "rejected"),
            ("pending_review", "merged"),
            ("pending_review", "deferred"),
            ("pending_review", "needs_enrichment"),
            ("needs_enrichment", "pending_review"),
            ("needs_enrichment", "rejected"),
            ("deferred", "pending_review"),
            ("rejected", "pending_review"),
        ],
    )
    def test_valid_transitions(self, current, target):
        validate_candidate_status_transition(current, target)

    @pytest.mark.parametrize(
        "current,target",
        [
            ("approved", "pending_review"),
            ("merged", "pending_review"),
            ("pending_review", "active"),
        ],
    )
    def test_invalid_transitions(self, current, target):
        with pytest.raises(InvalidStatusTransition):
            validate_candidate_status_transition(current, target)


class TestAllowedTransitions:
    def test_memory_active_allows_four(self):
        allowed = get_allowed_memory_transitions("active")
        assert set(allowed) == {"superseded", "conflicted", "archived", "deprecated"}

    def test_candidate_pending_review_allows_five(self):
        allowed = get_allowed_candidate_transitions("pending_review")
        assert "approved" in allowed
        assert "needs_enrichment" in allowed

    def test_unknown_status_returns_empty(self):
        assert get_allowed_memory_transitions("unknown") == []
        assert get_allowed_candidate_transitions("unknown") == []
