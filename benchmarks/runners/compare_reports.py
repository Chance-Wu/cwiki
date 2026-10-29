"""检索评测报告对比：baseline.json 门槛 vs 当前报告目录。

供 W3 回归验证与 W4 CI 评测回归（3% 容差）共用：
逐管线对比 recall_at_10 / mrr / ndcg_at_10 / useful_at_10，
超出容差的指标下降标记 FAIL，否则 PASS。

用法：
    python -m benchmarks.runners.compare_reports \
        [--baseline benchmarks/reports/baseline.json] \
        [--current benchmarks/reports/eval-fixture] \
        [--dataset eval-fixture] [--tolerance 0.03]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICS = ["recall_at_10", "mrr", "ndcg_at_10", "useful_at_10", "useful_at_10_ratio"]
DEFAULT_BASELINE = Path(__file__).parent.parent / "reports" / "baseline.json"


def load_baseline(path: Path) -> dict[str, dict[str, float]]:
    return json.loads(path.read_text())["pipelines"]


def load_current(dir_path: Path, dataset: str) -> dict[str, dict[str, float]]:
    """从报告目录读取各管线 JSON（命名 {dataset}-retrieval-report-{pipeline}.json）。"""
    reports: dict[str, dict[str, float]] = {}
    for path in sorted(dir_path.glob(f"{dataset}-retrieval-report-*.json")):
        data = json.loads(path.read_text())
        pipeline = data["pipeline"]
        reports[pipeline] = {m: data[m] for m in METRICS}
    return reports


def compare(
    baseline: dict[str, dict[str, float]],
    current: dict[str, dict[str, float]],
    tolerance: float,
) -> tuple[list[str], list[str]]:
    """返回 (markdown 行, 失败原因列表)。指标下降超出容差记失败。"""
    lines = [
        "| Pipeline | Metric | Baseline | Current | Delta | Verdict |",
        "|----------|--------|----------|---------|-------|---------|",
    ]
    failures: list[str] = []

    for pipeline in sorted(set(baseline) | set(current)):
        base = baseline.get(pipeline)
        cur = current.get(pipeline)
        if base is None:
            failures.append(f"{pipeline}: 当前报告存在但基线缺失")
            continue
        if cur is None:
            failures.append(f"{pipeline}: 基线存在但当前报告缺失")
            continue
        for metric in METRICS:
            b, c = base[metric], cur[metric]
            delta = c - b
            # 容差按绝对降幅衡量（指标本身是 0-1 的比率，3% 即 0.03）
            fail = delta < -tolerance
            verdict = "FAIL" if fail else "PASS"
            if fail:
                failures.append(f"{pipeline}.{metric}: {b:.4f} -> {c:.4f} ({delta:+.4f})")
            lines.append(
                f"| {pipeline} | {metric} | {b:.4f} | {c:.4f} | {delta:+.4f} | {verdict} |"
            )
    return lines, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare retrieval reports against baseline")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--current", type=Path, required=True, help="报告目录")
    parser.add_argument("--dataset", type=str, default="eval-fixture")
    parser.add_argument("--tolerance", type=float, default=0.03)
    parser.add_argument("--output", type=Path, default=None, help="MD 输出路径（缺省打印 stdout）")
    args = parser.parse_args()

    baseline = load_baseline(args.baseline)
    current = load_current(args.current, args.dataset)
    lines, failures = compare(baseline, current, args.tolerance)

    header = [
        "# Retrieval Regression Comparison",
        "",
        f"Baseline: `{args.baseline}`  Current: `{args.current}`  Tolerance: {args.tolerance}",
        "",
        *lines,
        "",
    ]
    if failures:
        header.append(f"**{len(failures)} regression(s) detected:**")
        header.extend(f"- {f}" for f in failures)
        header.append("")
    else:
        header.append("All metrics within tolerance.")
        header.append("")

    text = "\n".join(header)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
