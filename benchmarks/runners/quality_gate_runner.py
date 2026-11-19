"""质量门校准 runner：对候选标注基线做分布/阈值/相关性分析。

读取 `benchmarks/datasets/quality_annotation_baseline.json`（真实候选快照，
含 gate/value/novelty 分数与人工标注位），产出三部分报告：

1. 分布：quality_gate_score / value_score / novelty 分位数
2. 阈值敏感度：needs_enrichment(<0.35)、UI 徽章(0.7)、auto-approve(0.75)
   三档在基线中的命中数量——评估阈值在真实候选流上的区分度
3. 校准闭环：
   - 互补性验证：gate vs value_score / novelty 的 Pearson 相关（预期低，
     证实质量门与价值分度量不同维度、互为补充）
   - 人工标注闭环：`overall_quality`(1-5) 有标注时，计算 gate 与人工分的
     相关性 + 「gate≥0.75 vs 人工≥4」混淆矩阵；标注全空时输出标注指引

用法（手动，不接 CI）：
    python -m benchmarks.runners.quality_gate_runner [--baseline <path>]

报告输出 benchmarks/reports/quality-gate/report.{json,md}。
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).parent.parent / "datasets" / "quality_annotation_baseline.json"
REPORTS_DIR = Path(__file__).parent.parent / "reports" / "quality-gate"

# 与生产阈值对齐（packages/domain/config.py + 前端徽章）
THRESHOLDS = {
    "needs_enrichment": 0.35,
    "ui_badge_high": 0.7,
    "auto_approve_gate": 0.75,
}


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)

    def pct(p: float) -> float:
        idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
        return round(ordered[idx], 4)

    return {
        "min": round(ordered[0], 4),
        "p25": pct(25),
        "median": pct(50),
        "p75": pct(75),
        "max": round(ordered[-1], 4),
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson 相关；样本不足或零方差时返回 None。"""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return round(cov / ((var_x * var_y) ** 0.5), 4)


def _threshold_sensitivity(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    gates = [c["quality_gate_score"] for c in candidates if c.get("quality_gate_score") is not None]
    values = [c["value_score"] for c in candidates if c.get("value_score") is not None]
    return {
        "total_candidates": len(candidates),
        "scored_candidates": len(gates),
        "bands": {
            name: {
                "threshold": threshold,
                "below": sum(1 for g in gates if g < threshold),
                "at_or_above": sum(1 for g in gates if g >= threshold),
            }
            for name, threshold in THRESHOLDS.items()
        },
        "value_bands": {
            name: {
                "threshold": threshold,
                "below": sum(1 for v in values if v < threshold),
                "at_or_above": sum(1 for v in values if v >= threshold),
            }
            for name, threshold in THRESHOLDS.items()
            if name in ("needs_enrichment", "auto_approve_gate")
        },
    }


def _calibration(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """互补性验证 + 人工标注闭环。"""
    pairs_gate_value = [
        (c["quality_gate_score"], c["value_score"])
        for c in candidates
        if c.get("quality_gate_score") is not None and c.get("value_score") is not None
    ]
    pairs_gate_novelty = [
        (c["quality_gate_score"], c["novelty"])
        for c in candidates
        if c.get("quality_gate_score") is not None and c.get("novelty") is not None
    ]

    annotated = [
        (c["quality_gate_score"], float(c["annotations"]["overall_quality"]))
        for c in candidates
        if c.get("quality_gate_score") is not None
        and (c.get("annotations") or {}).get("overall_quality") is not None
    ]

    calibration: dict[str, Any] = {
        "corr_gate_vs_value": _pearson(
            [p[0] for p in pairs_gate_value], [p[1] for p in pairs_gate_value]
        ),
        "corr_gate_vs_novelty": _pearson(
            [p[0] for p in pairs_gate_novelty], [p[1] for p in pairs_gate_novelty]
        ),
    }
    if annotated:
        gates = [p[0] for p in annotated]
        humans = [p[1] for p in annotated]
        calibration["human_annotation"] = {
            "annotated_count": len(annotated),
            "corr_gate_vs_human": _pearson(gates, humans),
            "confusion": {
                "gate_ge_threshold": sum(1 for g in gates if g >= THRESHOLDS["auto_approve_gate"]),
                "human_ge_4": sum(1 for h in humans if h >= 4),
                "both": sum(
                    1 for g, h in annotated if g >= THRESHOLDS["auto_approve_gate"] and h >= 4
                ),
            },
        }
    else:
        calibration["human_annotation"] = {
            "annotated_count": 0,
            "status": "awaiting_annotation",
            "guide": (
                "在 quality_annotation_baseline.json 的 annotations.overall_quality "
                "填入 1-5 分（4 维标注法：标题准确性/正文完整性/事实忠实度/可复用性），"
                "重跑本 runner 即可计算 gate 与人工判断的相关性与混淆矩阵。"
            ),
        }
    return calibration


def run(baseline_path: Path = BASELINE_PATH, output_dir: Path = REPORTS_DIR) -> Path:
    candidates = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        raise TypeError(f"基线文件应为候选数组，收到 {type(candidates).__name__}")

    gates = [c["quality_gate_score"] for c in candidates if c.get("quality_gate_score") is not None]
    values = [c["value_score"] for c in candidates if c.get("value_score") is not None]
    novelties = [c["novelty"] for c in candidates if c.get("novelty") is not None]

    report: dict[str, Any] = {
        "benchmark": "quality_gate_calibration",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline": str(baseline_path),
        "candidates": len(candidates),
        "distribution": {
            "quality_gate_score": _percentiles(gates),
            "value_score": _percentiles(values),
            "novelty": _percentiles(novelties),
        },
        "threshold_sensitivity": _threshold_sensitivity(candidates),
        "calibration": _calibration(candidates),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_dir / "report.md").write_text(_format_md(report), encoding="utf-8")
    print(f"Report saved to {json_path}")
    return json_path


def _format_md(report: dict[str, Any]) -> str:
    lines = [
        "# Quality Gate Calibration Report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- candidates: {report['candidates']}",
        "",
        "## Distribution",
        "",
        "| Metric | Min | P25 | Median | P75 | Max |",
        "|--------|-----|-----|--------|-----|-----|",
    ]
    for name, dist in report["distribution"].items():
        if dist:
            lines.append(
                f"| {name} | {dist['min']} | {dist['p25']} | {dist['median']} | {dist['p75']} | {dist['max']} |"
            )

    lines += ["", "## Threshold Sensitivity (quality_gate_score)", ""]
    sens = report["threshold_sensitivity"]
    for name, band in sens["bands"].items():
        lines.append(
            f"- **{name}** (≥{band['threshold']}): {band['at_or_above']} 条达标 / {band['below']} 条低于阈值"
        )

    lines += ["", "## Calibration", ""]
    cal = report["calibration"]
    for key in ("corr_gate_vs_value", "corr_gate_vs_novelty"):
        v = cal.get(key)
        lines.append(f"- `{key}`: {'null（样本不足）' if v is None else v}")
    human = cal.get("human_annotation", {})
    if human.get("annotated_count"):
        lines.append(
            f"- 人工标注：{human['annotated_count']} 条，gate↔人工相关 {human.get('corr_gate_vs_human')}"
        )
        confusion = human.get("confusion", {})
        lines.append(
            f"- 混淆矩阵（gate≥{THRESHOLDS['auto_approve_gate']} vs 人工≥4）："
            f"both={confusion.get('both')}, gate_only={confusion.get('gate_ge_threshold', 0) - confusion.get('both', 0)}, "
            f"human_only={confusion.get('human_ge_4', 0) - confusion.get('both', 0)}"
        )
    else:
        lines.append(f"- 人工标注：{human.get('status')} — {human.get('guide')}")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quality gate calibration runner")
    parser.add_argument("--baseline", default=None, help="标注基线路径（默认内置基线）")
    parser.add_argument("--output-dir", default=None, help="报告输出目录")
    args = parser.parse_args()
    run(
        Path(args.baseline) if args.baseline else BASELINE_PATH,
        Path(args.output_dir) if args.output_dir else REPORTS_DIR,
    )
