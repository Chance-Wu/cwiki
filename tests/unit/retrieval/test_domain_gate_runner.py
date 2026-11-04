"""A domain gate must expose both reduced leakage and lost cross-domain support."""

import json
from pathlib import Path

import pytest

from benchmarks.fixtures.generate_fixture import CORPUS
from benchmarks.runners.domain_gate_runner import evaluate, keep_pair


def test_paired_gate_tradeoff():
    path = Path(__file__).resolve().parents[3] / "benchmarks/datasets/retrieval/domain-pairs.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    corpus = {entry["key"]: entry for entry in CORPUS}
    baseline = evaluate(dataset["pairs"], corpus, "baseline")
    strict = evaluate(dataset["pairs"], corpus, "first_domain")
    permissive = evaluate(dataset["pairs"], corpus, "any_explicit_domain")
    assert baseline["positive_keep_rate"] == 1
    assert baseline["negative_reject_rate"] == 0
    assert "positive-cross-compare" in strict["false_exclusions"]
    assert "positive-cross-compare" not in permissive["false_exclusions"]
    assert "positive-cross-implicit" in permissive["false_exclusions"]
    assert "negative-same-domain" in permissive["negative_leaks"]
    assert "negative-lock-cache" in permissive["negative_leaks"]
    assert permissive["negative_reject_rate"] > baseline["negative_reject_rate"]
    assert permissive["positive_keep_rate"] < baseline["positive_keep_rate"]


def test_fail_open_and_input_boundaries():
    assert keep_pair("quorum 怎么设置", "Redis Sentinel", "any_explicit_domain")
    assert keep_pair("MYSQL", "mysql", "first_domain")
    with pytest.raises(ValueError, match="unknown policy"):
        keep_pair("MySQL", "Redis", "invalid")
    with pytest.raises(ValueError, match="empty"):
        evaluate([], {}, "baseline")
    with pytest.raises(ValueError, match="boolean"):
        evaluate([{"relevant": 1}], {}, "baseline")
