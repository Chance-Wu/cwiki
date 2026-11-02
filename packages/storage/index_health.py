"""派生索引健康检查：向量 npz/json 配对、维度/模型、index.db 覆盖。

只读纯函数，供 doctor 与 rebuild-db 的轻量跳过判断共用，避免两处
各自复制"索引是否仍然有效"的口径。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class VectorIndexHealth:
    """向量索引健康状态。"""

    present: bool
    ids_count: int = 0
    rows: int = 0
    dimensions: int | None = None
    model: str | None = None
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.present and not self.issues


def inspect_vector_index(
    npz_path: Path,
    meta_path: Path,
    *,
    expected_dimensions: int,
    expected_model: str,
) -> VectorIndexHealth:
    """检查 vectors.npz + vectors.json 的配对、数量、维度与模型。

    维度/模型缺失视为 legacy 索引：加载仍兼容，但无法证明与当前配置
    可比，健康检查会要求重建。
    """
    if not npz_path.is_file() or not meta_path.is_file():
        return VectorIndexHealth(present=False, issues=["vector files missing"])

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return VectorIndexHealth(present=True, issues=[f"vectors.json unreadable: {exc}"])
    if not isinstance(meta, dict):
        return VectorIndexHealth(present=True, issues=["vectors.json is not an object"])

    ids = meta.get("ids")
    ids_count = len(ids) if isinstance(ids, list) else 0
    dimensions = meta.get("dimensions") if isinstance(meta.get("dimensions"), int) else None
    model = meta.get("model") if isinstance(meta.get("model"), str) else None

    try:
        with np.load(npz_path) as data:
            rows = len(data["vectors"])
            embedded_ids = data["ids"].tolist() if "ids" in data.files else None

    except (OSError, ValueError, KeyError) as exc:
        return VectorIndexHealth(
            present=True,
            ids_count=ids_count,
            dimensions=dimensions,
            model=model,
            issues=[f"vectors.npz unreadable: {exc}"],
        )

    issues: list[str] = []
    if embedded_ids is not None and [str(i) for i in embedded_ids] != [str(i) for i in ids]:
        issues.append("embedded ids do not match metadata ids")
    if meta.get("vector_hash"):
        digest = hashlib.sha256(npz_path.read_bytes()).hexdigest()
        if digest != meta["vector_hash"]:
            issues.append("vector hash mismatch")
    if ids_count != rows:
        issues.append(f"id/vector count mismatch: {ids_count} ids vs {rows} rows")
    if dimensions is None:
        issues.append("dimensions missing (legacy index)")
    elif dimensions != expected_dimensions:
        issues.append(f"dimension mismatch: index={dimensions}, configured={expected_dimensions}")
    if not model:
        issues.append("model missing (legacy index)")
    elif model != expected_model:
        issues.append(f"model mismatch: index={model}, configured={expected_model}")

    return VectorIndexHealth(
        present=True,
        ids_count=ids_count,
        rows=rows,
        dimensions=dimensions,
        model=model,
        issues=issues,
    )


def index_active_count(index_db_path: Path) -> int | None:
    """统计 index.db 中 active 行；不可读返回 None。"""
    if not index_db_path.is_file():
        return None
    try:
        conn = sqlite3.connect(str(index_db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM memory_index WHERE status = 'active'"
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else None
    except sqlite3.Error:
        return None
