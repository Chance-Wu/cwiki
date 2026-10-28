"""重复检测黄金集运行器。

用法：
    python -m benchmarks.runners.duplicate_runner             # 词面通道（确定性，CI 门槛）
    python -m benchmarks.runners.duplicate_runner --semantic  # embedding 语义通道（改写句）

词面集只使用 detect_duplicate（无 embedding），保证 CI 可复现；
语义集用 detect_duplicate_with_embedding 评估改写/同义表达，需要本地模型可用。
语义通道的 exact 判定由 tests/unit/memory/test_duplicate_detection.py 覆盖。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from benchmarks.evaluators.duplicates import DuplicateGold, evaluate, load_gold
from packages.memory.duplicate_detection import (
    detect_duplicate,
    detect_duplicate_with_embedding,
)

DEFAULT_GOLD = Path(__file__).parent.parent / "datasets" / "duplicates" / "gold.jsonl"
SEMANTIC_GOLD = Path(__file__).parent.parent / "datasets" / "duplicates" / "gold_semantic.jsonl"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "reports" / "duplicate-report.json"
SEMANTIC_OUTPUT = Path(__file__).parent.parent / "reports" / "duplicate-semantic-report.json"


def run(gold_path: Path = DEFAULT_GOLD) -> dict[str, Any]:
    pairs: list[DuplicateGold] = load_gold(gold_path)
    verdicts = [detect_duplicate(pair.a, pair.b) for pair in pairs]
    metrics = evaluate([pair.label for pair in pairs], [v.classification for v in verdicts])
    return {"dataset": gold_path.name, "channel": "lexical", "total": len(pairs), **metrics}


async def run_semantic(gold_path: Path = SEMANTIC_GOLD) -> dict[str, Any]:
    pairs: list[DuplicateGold] = load_gold(gold_path)
    verdicts = [await detect_duplicate_with_embedding(pair.a, pair.b) for pair in pairs]
    metrics = evaluate([pair.label for pair in pairs], [v.classification for v in verdicts])
    return {"dataset": gold_path.name, "channel": "semantic", "total": len(pairs), **metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description="重复检测黄金集评测")
    parser.add_argument("--semantic", action="store_true", help="使用 embedding 语义通道")
    parser.add_argument("--gold", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if args.semantic:
        report = asyncio.run(run_semantic(args.gold or SEMANTIC_GOLD))
        output = args.output or SEMANTIC_OUTPUT
    else:
        report = run(args.gold or DEFAULT_GOLD)
        output = args.output or DEFAULT_OUTPUT

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
