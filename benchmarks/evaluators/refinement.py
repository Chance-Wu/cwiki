"""提炼质量评估器：自动评分候选的标题/正文/类型/结构质量。

评估维度：
- title_length: 标题长度（10-80 字符合理）
- title_has_object: 标题是否含关键对象（名词/技术词）
- content_length: 正文长度（≥200 字符完整）
- content_structured: 正文是否有 Markdown 分段（## 标题）
- type_valid: 类型是否在合法枚举中
- quality_gate_pass: 质量门分数 ≥ 0.6

输出：每条候选的各维度得分 + 总分（0-1）
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

# 合法类型枚举（与 packages/domain/models/memory.py 的 TYPE_DEFINITIONS 同步）
VALID_TYPES = {
    "fact", "lesson", "issue", "decision", "convention", "pattern",
    "procedure", "feedback", "reference", "constraint", "rule",
}

# 技术词/名词模式（标题应包含至少一个）
OBJECT_PATTERN = re.compile(
    r"[A-Z][a-zA-Z0-9_]+|"  # CamelCase/PascalCase
    r"[a-z]+_[a-z_]+|"       # snake_case
    r"[\u4e00-\u9fa5]{2,}"   # 中文词（2+ 字）
)


def evaluate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """评估单条候选，返回各维度得分 + 总分。"""
    title = candidate.get("title", "")
    content = candidate.get("content", "")
    ctype = candidate.get("type", "")
    qg_score = candidate.get("quality_gate_score", 0.0)

    # 1. 标题长度（10-80 字符满分，线性插值）
    title_len = len(title)
    if 10 <= title_len <= 80:
        title_length_score = 1.0
    elif title_len < 10:
        title_length_score = title_len / 10.0
    else:
        title_length_score = max(0.0, 1.0 - (title_len - 80) / 40.0)

    # 2. 标题含关键对象
    title_has_object = 1.0 if OBJECT_PATTERN.search(title) else 0.0

    # 3. 正文长度（≥200 字符满分）
    content_len = len(content)
    content_length_score = min(1.0, content_len / 200.0)

    # 4. 正文结构化（有##分段）
    content_structured = 1.0 if "## " in content else 0.0

    # 5. 类型合法
    type_valid = 1.0 if ctype in VALID_TYPES else 0.0

    # 6. 质量门通过（≥0.6）
    quality_gate_pass = 1.0 if qg_score >= 0.6 else 0.0

    # 总分（加权平均）
    weights = {
        "title_length": 0.15,
        "title_has_object": 0.20,
        "content_length": 0.20,
        "content_structured": 0.20,
        "type_valid": 0.10,
        "quality_gate_pass": 0.15,
    }
    total = (
        title_length_score * weights["title_length"]
        + title_has_object * weights["title_has_object"]
        + content_length_score * weights["content_length"]
        + content_structured * weights["content_structured"]
        + type_valid * weights["type_valid"]
        + quality_gate_pass * weights["quality_gate_pass"]
    )

    return {
        "candidate_id": candidate.get("id"),
        "title": title,
        "type": ctype,
        "quality_gate_score": qg_score,
        "scores": {
            "title_length": title_length_score,
            "title_has_object": title_has_object,
            "content_length": content_length_score,
            "content_structured": content_structured,
            "type_valid": type_valid,
            "quality_gate_pass": quality_gate_pass,
        },
        "total_score": total,
    }


def run_evaluation(db_path: Path = Path("cwiki-data/cwiki.db")) -> list[dict[str, Any]]:
    """从数据库读取候选并评估，返回结果列表。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        "SELECT id, title, content, type, quality_gate_score "
        "FROM candidate_memory ORDER BY created_at DESC"
    )
    candidates = [dict(row) for row in c.fetchall()]
    conn.close()

    results = [evaluate_candidate(c) for c in candidates]
    return results


def generate_report(results: list[dict[str, Any]]) -> str:
    """生成可读报告。"""
    if not results:
        return "无候选数据"

    # 统计
    total = len(results)
    avg_score = sum(r["total_score"] for r in results) / total
    pass_count = sum(1 for r in results if r["total_score"] >= 0.7)
    pass_rate = pass_count / total

    # 各维度平均分
    dim_avg = {}
    for dim in results[0]["scores"]:
        dim_avg[dim] = sum(r["scores"][dim] for r in results) / total

    report = []
    report.append(f"# 提炼质量评估报告\n")
    report.append(f"**候选总数**: {total}")
    report.append(f"**平均分**: {avg_score:.3f}")
    report.append(f"**通过率** (≥0.7): {pass_count}/{total} = {pass_rate:.1%}\n")

    report.append("## 各维度平均分\n")
    report.append("| 维度 | 平均分 |")
    report.append("|------|--------|")
    for dim, avg in dim_avg.items():
        report.append(f"| {dim} | {avg:.3f} |")

    report.append("\n## 各候选得分\n")
    report.append("| 标题 | 类型 | 质量门 | 总分 |")
    report.append("|------|------|--------|------|")
    for r in sorted(results, key=lambda x: x["total_score"], reverse=True):
        title_short = r["title"][:40] + "..." if len(r["title"]) > 40 else r["title"]
        report.append(
            f"| {title_short} | {r['type']} | {r['quality_gate_score']:.2f} | {r['total_score']:.3f} |"
        )

    return "\n".join(report)


if __name__ == "__main__":
    results = run_evaluation()
    report = generate_report(results)
    print(report)

    # 保存结果
    out_dir = Path("benchmarks/reports/refinement")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    (out_dir / "report.md").write_text(report)
    print(f"\n结果已保存到 {out_dir}/baseline.json 和 {out_dir}/report.md")
