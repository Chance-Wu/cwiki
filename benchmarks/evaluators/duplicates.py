"""重复检测评测器。

把 duplicate_detection 的分类结果（exact/possible/distinct）与黄金标签对比：

- duplicate：exact_duplicate 或 possible_duplicate 都算命中
- distinct：只有 distinct 算正确

指标：precision / recall / f1 / accuracy（正类 = duplicate）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DUPLICATE_CLASSES = frozenset(("exact_duplicate", "possible_duplicate"))


@dataclass(frozen=True)
class DuplicateGold:
    id: str
    label: str  # duplicate | distinct
    a: dict[str, Any]
    b: dict[str, Any]


def load_gold(path: Path) -> list[DuplicateGold]:
    pairs: list[DuplicateGold] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        record = json.loads(line)
        pairs.append(
            DuplicateGold(id=record["id"], label=record["label"], a=record["a"], b=record["b"])
        )
    return pairs


def evaluate(labels: list[str], classifications: list[str]) -> dict[str, float]:
    """按二分类计算指标；classifications 与 labels 一一对应。"""
    if len(labels) != len(classifications):
        raise ValueError("labels 与 classifications 长度不一致")
    tp = fp = fn = tn = 0
    for label, classification in zip(labels, classifications):
        predicted = classification in DUPLICATE_CLASSES
        actual = label == "duplicate"
        if actual and predicted:
            tp += 1
        elif actual and not predicted:
            fn += 1
        elif not actual and predicted:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = len(labels) or 1
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / total, 4),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
    }
