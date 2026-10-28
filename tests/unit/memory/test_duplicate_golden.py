"""重复检测黄金集回归门禁（词面通道，确定性）。"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.runners.duplicate_runner import run

BASELINE = (
    Path(__file__).parent.parent.parent.parent
    / "benchmarks"
    / "reports"
    / "duplicate_baseline.json"
)
TOLERANCE = 0.03


def test_duplicate_golden_meets_baseline() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    metrics = run()

    assert metrics["total"] == baseline["total"]
    for key in ("precision", "recall", "f1", "accuracy"):
        assert metrics[key] >= baseline[key] - TOLERANCE, (
            f"{key} 回退：当前 {metrics[key]} < 基线 {baseline[key]} - {TOLERANCE}；"
            f"完整指标 {metrics}"
        )
