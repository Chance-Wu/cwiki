"""Offline ablation of deliberately simple domain gates, not a production filter."""

import json
import re
from pathlib import Path

DOMAINS = {"redis": r"redis", "mysql": r"mysql", "sqlite": r"sqlite"}


def domains(text: str) -> set[str]:
    return {name for name, pattern in DOMAINS.items() if re.search(pattern, text, re.IGNORECASE)}


def keep_pair(query: str, document: str, policy: str) -> bool:
    """Unknown domains fail open; only explicit product names are recognized."""
    if policy == "baseline":
        return True
    if policy not in {"first_domain", "any_explicit_domain"}:
        raise ValueError(f"unknown policy: {policy}")
    query_domains = domains(query)
    document_domains = domains(document)
    if not query_domains or not document_domains:
        return True
    if policy == "first_domain":
        first = min(query_domains, key=lambda name: query.lower().index(name))
        return first in document_domains
    return bool(query_domains & document_domains)


def evaluate(pairs: list[dict], corpus: dict[str, dict], policy: str) -> dict:
    if not pairs:
        raise ValueError("empty paired evaluation")
    rows = []
    for pair in pairs:
        if type(pair["relevant"]) is not bool:
            raise ValueError("relevant must be boolean")
        entry = corpus[pair["key"]]
        document = entry["title"] + "\n" + entry["content"]
        kept = keep_pair(pair["query"], document, policy)
        rows.append({**pair, "kept": kept, "title": entry["title"]})
    positives = [row for row in rows if row["relevant"]]
    negatives = [row for row in rows if not row["relevant"]]
    return {
        "policy": policy,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "positive_keep_rate": sum(row["kept"] for row in positives) / len(positives)
        if positives
        else None,
        "negative_reject_rate": sum(not row["kept"] for row in negatives) / len(negatives)
        if negatives
        else None,
        "false_exclusions": [row["id"] for row in positives if not row["kept"]],
        "negative_leaks": [row["id"] for row in negatives if row["kept"]],
        "pairs": rows,
    }


def main() -> None:
    from benchmarks.fixtures.generate_fixture import CORPUS

    root = Path(__file__).resolve().parents[2]
    dataset = json.loads(
        (root / "benchmarks/datasets/retrieval/domain-pairs.json").read_text(encoding="utf-8")
    )
    corpus = {entry["key"]: entry for entry in CORPUS}
    report = {
        "provenance": dataset["provenance"],
        "boundary": "Candidate-pair ablation only; no recall, ranking, API, or answer evaluation. No calibrated scores or production changes.",
        "results": [
            evaluate(dataset["pairs"], corpus, policy)
            for policy in ("baseline", "first_domain", "any_explicit_domain")
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
