"""MQ-002 候选记忆质量标注数据集。

从数据库抽取真实候选，匿名化后供人工标注。
标注维度：标题准确性、关键上下文完整性、无依据陈述、未来可复用性。
"""

import json
import sqlite3
import uuid
from pathlib import Path

DATASET_DIR = Path(__file__).parent


def extract_candidates_for_annotation(
    db_path: str = "cwiki-data/cwiki.db",
    output_path: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """从数据库抽取候选记忆，生成标注数据集。

    每条记录包含：
    - candidate_id: 匿名化 ID
    - title: 候选标题
    - content: 候选正文
    - type: 记忆类型
    - source: 来源
    - value_score: 系统评分
    - quality_gate_score: 质量门分
    - quality_gate_criteria: 各维度分项

    标注字段（待人工填写）：
    - title_accuracy: 标题是否准确概括内容 (1-5)
    - context_completeness: 关键上下文是否完整 (1-5)
    - evidence_sufficiency: 陈述是否有依据 (1-5)
    - future_reusability: 未来是否值得检索 (1-5)
    - overall_quality: 综合质量 (1-5)
    - annotation_notes: 备注
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, title, content, type, source,
               value_score, quality_gate_score, quality_gate_reason,
               novelty, status, created_at
        FROM candidate_memory
        ORDER BY created_at DESC
        LIMIT ?
    """,
        (limit,),
    )

    dataset = []
    for row in cur.fetchall():
        anon_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(row["id"])))
        entry = {
            "candidate_id": anon_id[:8],
            "title": row["title"],
            "content": row["content"],
            "type": row["type"],
            "source": row["source"],
            "value_score": round(row["value_score"], 4) if row["value_score"] else None,
            "quality_gate_score": round(row["quality_gate_score"], 4)
            if row["quality_gate_score"]
            else None,
            "quality_gate_reason": row["quality_gate_reason"],
            "novelty": round(row["novelty"], 4) if row["novelty"] else None,
            "status": row["status"],
            "annotations": {
                "title_accuracy": None,
                "context_completeness": None,
                "evidence_sufficiency": None,
                "future_reusability": None,
                "overall_quality": None,
                "annotation_notes": "",
            },
        }
        dataset.append(entry)

    conn.close()

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False))

    return dataset


def generate_annotation_template() -> dict:
    """生成标注说明模板。"""
    return {
        "schema_version": "1.0",
        "annotation_guide": {
            "title_accuracy": "标题是否准确概括了正文的核心内容？1=完全不准确，5=非常准确",
            "context_completeness": "正文是否包含理解结论所需的关键上下文（环境、条件、版本）？1=严重缺失，5=完整",
            "evidence_sufficiency": "正文中的陈述是否有依据支持？1=全部无依据，5=全部有充分依据",
            "future_reusability": "这条记忆未来是否值得被检索到？1=毫无价值，5=非常有价值",
            "overall_quality": "综合质量评分。1=不可用，5=优秀",
        },
        "scale": "1-5 整数分",
        "target_count": 100,
    }
