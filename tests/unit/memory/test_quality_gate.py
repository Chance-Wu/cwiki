"""packages.memory.quality_gate 测试（spec 8.1-8.2 节）。"""

import pytest

from packages.memory.quality_gate import compute_quality_gate


class TestComputeQualityGate:
    def test_high_quality_candidate(self):
        candidate = {
            "type": "constraint",
            "content": (
                "必须使用连接池，禁止直接查询数据库。"
                "This is a long enough content to pass the length check. "
                "It contains project context and reusable patterns for the team."
            ),
            "evidences": [
                {"type": "observation"},
                {"type": "observation"},
                {"type": "observation"},
            ],
        }
        result = compute_quality_gate(candidate)
        assert result.score >= 0.7
        assert result.review_priority <= 0.5

    def test_low_quality_candidate(self):
        candidate = {
            "type": "fact",
            "content": "short",
            "evidences": [],
        }
        result = compute_quality_gate(candidate)
        assert result.score < 0.6
        assert result.review_priority >= 0.7

    def test_stable_type_scores_high(self):
        constraint = {"type": "constraint", "content": "x" * 150, "evidences": []}
        history = {"type": "history", "content": "x" * 150, "evidences": []}
        r1 = compute_quality_gate(constraint)
        r2 = compute_quality_gate(history)
        assert r1.criteria["stable"] > r2.criteria["stable"]

    def test_all_types_have_stable_base(self):
        for t in [
            "constraint",
            "rule",
            "decision",
            "convention",
            "lesson",
            "pattern",
            "procedure",
            "issue",
            "feedback",
            "reference",
            "fact",
        ]:
            result = compute_quality_gate({"type": t, "content": "x" * 50, "evidences": []})
            assert 0.0 <= result.criteria["stable"] <= 1.0

    def test_reusable_content_length(self):
        short = {"type": "rule", "content": "x" * 25, "evidences": []}
        long = {"type": "rule", "content": "x project team session " * 20, "evidences": []}
        r1 = compute_quality_gate(short)
        r2 = compute_quality_gate(long)
        assert r2.criteria["reusable"] > r1.criteria["reusable"]

    def test_reusable_code_and_examples(self):
        plain = {"type": "pattern", "content": "x" * 100, "evidences": []}
        rich = {
            "type": "pattern",
            "content": "x" * 100 + " 例如 `code` example",
            "evidences": [],
        }
        r1 = compute_quality_gate(plain)
        r2 = compute_quality_gate(rich)
        assert r2.criteria["reusable"] > r1.criteria["reusable"]

    def test_scoped_long_content_is_not_penalized(self):
        content = "离线部署机器保存完整依赖清单与采集记录，便于后续核对环境。"
        short = compute_quality_gate({"type": "fact", "content": content, "evidences": []})
        long = compute_quality_gate({"type": "fact", "content": content * 500, "evidences": []})
        assert long.criteria["scoped"] >= short.criteria["scoped"]

    @pytest.mark.parametrize(
        "length,expected",
        [(5, 0.1), (15, 0.3), (30, 0.6), (50, 0.85), (500, 0.85), (10001, 0.85)],
    )
    def test_scoped_length_boundaries(self, length, expected):
        result = compute_quality_gate({"type": "fact", "content": "字" * length, "evidences": []})
        assert result.criteria["scoped"] == expected

    def test_scoped_many_headings_penalized(self):
        content = "\n".join(f"## Topic {i}\nSome text here." for i in range(8))
        result = compute_quality_gate({"type": "fact", "content": content, "evidences": []})
        assert result.criteria["scoped"] == 0.5

    def test_actionable_content(self):
        actionable = {"type": "rule", "content": "使用 pytest 运行测试", "evidences": []}
        vague = {"type": "fact", "content": "some random info here", "evidences": []}
        r1 = compute_quality_gate(actionable)
        r2 = compute_quality_gate(vague)
        assert r1.criteria["actionable"] > r2.criteria["actionable"]

    def test_actionable_structure_bonus(self):
        prose = {"type": "pattern", "content": "use retry with backoff " * 10, "evidences": []}
        structured = {
            "type": "pattern",
            "content": "- use retry with backoff\n- check error codes\n- set timeout",
            "evidences": [],
        }
        r1 = compute_quality_gate(prose)
        r2 = compute_quality_gate(structured)
        assert r2.criteria["actionable"] > r1.criteria["actionable"]

    def test_evidence_backed(self):
        no_evidence = {"type": "rule", "content": "x" * 100, "evidences": []}
        with_evidence = {
            "type": "rule",
            "content": "x" * 100,
            "evidences": [{"type": "obs"}, {"type": "obs"}, {"type": "obs"}],
        }
        r1 = compute_quality_gate(no_evidence)
        r2 = compute_quality_gate(with_evidence)
        assert r2.criteria["evidence_backed"] > r1.criteria["evidence_backed"]

    def test_evidence_internal_data_points(self):
        plain = {"type": "issue", "content": "something happened", "evidences": []}
        with_data = {
            "type": "issue",
            "content": "error rate increased by 15% after commit abc1234, traceback shows NPE",
            "evidences": [],
        }
        r1 = compute_quality_gate(plain)
        r2 = compute_quality_gate(with_data)
        assert r2.criteria["evidence_backed"] > r1.criteria["evidence_backed"]

    def test_quality_gate_does_not_auto_approve(self):
        """Quality Gate 只决定复审优先级，不自动批准。"""
        candidate = {
            "type": "constraint",
            "content": "必须使用连接池。" + "x" * 200,
            "evidences": [{"type": "obs"}, {"type": "obs"}, {"type": "obs"}],
        }
        result = compute_quality_gate(candidate)
        assert result.review_priority > 0.0

    def test_to_dict(self):
        candidate = {"type": "rule", "content": "use pytest", "evidences": []}
        result = compute_quality_gate(candidate)
        d = result.to_dict()
        assert "quality_gate_score" in d
        assert "quality_gate_reason" in d
        assert "review_priority" in d
        assert "criteria" in d

    def test_reason_includes_strengths(self):
        candidate = {
            "type": "constraint",
            "content": "必须使用连接池。" + "x" * 200,
            "evidences": [{"type": "obs"}, {"type": "obs"}, {"type": "obs"}],
        }
        result = compute_quality_gate(candidate)
        assert "Strengths" in result.reason

    def test_empty_candidate(self):
        candidate = {"type": "", "content": "", "evidences": []}
        result = compute_quality_gate(candidate)
        assert 0.0 <= result.score <= 1.0

    def test_variance_increases_review_priority(self):
        balanced = {
            "type": "constraint",
            "content": "必须做X。" * 30 + " project team ensure check",
            "evidences": [{"type": "obs"}, {"type": "obs"}],
        }
        unbalanced = {
            "type": "fact",
            "content": "short",
            "evidences": [],
        }
        r_bal = compute_quality_gate(balanced)
        r_unbal = compute_quality_gate(unbalanced)
        assert r_bal.criteria["stable"] > r_unbal.criteria["stable"]
