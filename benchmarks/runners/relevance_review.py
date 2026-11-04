"""Blind presentation and strict external-label validation; never certifies independence."""

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path

PROTOCOL = "cwiki-pair-review-v1"


def load_review_json(path: Path) -> dict:
    """Reject ambiguous duplicate keys instead of silently taking the last label."""

    def unique_object(items: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise TypeError("review JSON root must be an object")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def export_packet(pairs: list[dict], corpus: dict[str, dict]) -> dict:
    """Strip model labels, reasons, descriptive IDs, keys and policy results."""
    if not pairs:
        raise ValueError("empty review packet")
    items = []
    seen = set()
    for pair in pairs:
        entry = corpus[pair["key"]]
        item = {"query": pair["query"], "title": entry["title"], "content": entry["content"]}
        if any(not isinstance(value, str) or not value.strip() for value in item.values()):
            raise ValueError("query/title/content must be nonempty strings")
        pair_id = _digest(item)
        if pair_id in seen:
            raise ValueError("duplicate query-document pair")
        seen.add(pair_id)
        items.append({"pair_id": pair_id, **item})
    items.sort(key=lambda item: item["pair_id"])
    payload = {"protocol": PROTOCOL, "split": "development", "items": items}
    return {**payload, "packet_id": _digest(payload)}


def validate_annotations(packet: dict, annotations: dict) -> dict:
    """Require complete, explicit judgments bound to the exact rendered snapshot."""
    if not isinstance(packet, dict) or not isinstance(annotations, dict):
        raise TypeError("packet and annotations must be objects")
    if set(packet) != {"protocol", "split", "items", "packet_id"}:
        raise ValueError("invalid packet fields")
    payload = {key: packet[key] for key in ("protocol", "split", "items")}
    if packet["protocol"] != PROTOCOL or packet["split"] != "development":
        raise ValueError("unsupported protocol/split; exposed pairs are development only")
    if packet["packet_id"] != _digest(payload):
        raise ValueError("packet snapshot mismatch")
    if not packet["items"]:
        raise ValueError("empty review packet")
    if not isinstance(packet["items"], list):
        raise TypeError("items must be a list")
    expected = set()
    for item in packet["items"]:
        if not isinstance(item, dict):
            raise TypeError("item must be an object")
        if set(item) != {"pair_id", "query", "title", "content"}:
            raise ValueError("invalid item fields")
        snapshot = {key: item[key] for key in ("query", "title", "content")}
        if any(not isinstance(value, str) or not value.strip() for value in snapshot.values()):
            raise ValueError("invalid item snapshot")
        if item["pair_id"] != _digest(snapshot) or item["pair_id"] in expected:
            raise ValueError("invalid or duplicate pair_id")
        expected.add(item["pair_id"])
    if set(annotations) != {"packet_id", "reviewer", "judgments"}:
        raise ValueError("invalid annotation fields")
    if annotations["packet_id"] != packet["packet_id"]:
        raise ValueError("annotation packet mismatch")
    if not isinstance(annotations["reviewer"], str) or not annotations["reviewer"].strip():
        raise ValueError("reviewer must be nonempty")
    if not isinstance(annotations["judgments"], list):
        raise TypeError("judgments must be a list")
    seen = set()
    for row in annotations["judgments"]:
        if not isinstance(row, dict):
            raise TypeError("judgment must be an object")
        if set(row) != {"pair_id", "relevant", "rationale"}:
            raise ValueError("invalid judgment fields")
        pair_id = row["pair_id"]
        if not isinstance(pair_id, str) or pair_id not in expected or pair_id in seen:
            raise ValueError("unknown or duplicate judgment")
        if type(row["relevant"]) is not bool:
            raise ValueError("relevant must be boolean; unresolved labels are not scored")
        if not isinstance(row["rationale"], str) or not row["rationale"].strip():
            raise ValueError("rationale must be nonempty")
        seen.add(pair_id)
    if seen != expected:
        raise ValueError("incomplete annotations")
    return {
        "packet_id": packet["packet_id"],
        "split": "development",
        "reviewer": annotations["reviewer"],
        "independence_verified": False,
        "judgments": deepcopy(annotations["judgments"]),
    }


def compare_annotations(packet: dict, annotations: dict) -> dict:
    """Score exactly the reviewed snapshots; never reload fixture labels or text."""
    from benchmarks.runners.domain_gate_runner import evaluate

    validated = validate_annotations(packet, annotations)
    judgments = {row["pair_id"]: row for row in validated["judgments"]}
    pairs = []
    corpus = {}
    for item in packet["items"]:
        pair_id = item["pair_id"]
        judgment = judgments[pair_id]
        pairs.append(
            {
                "id": pair_id,
                "key": pair_id,
                "query": item["query"],
                "relevant": judgment["relevant"],
                "reason": judgment["rationale"],
            }
        )
        corpus[pair_id] = {"title": item["title"], "content": item["content"]}
    return {
        "packet_id": validated["packet_id"],
        "split": validated["split"],
        "reviewer": validated["reviewer"],
        "independence_verified": False,
        "label_source": "external_annotation_file_not_identity_verified",
        "boundary": "Development paired ablation only; not held-out, retrieval/API or answer success. Null rates mean a class has no labels.",
        "results": [
            evaluate(pairs, corpus, policy)
            for policy in ("baseline", "first_domain", "any_explicit_domain")
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("dataset", type=Path)
    for command in ("check", "compare"):
        subparser = commands.add_parser(command)
        subparser.add_argument("packet", type=Path)
        subparser.add_argument("annotations", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        from benchmarks.fixtures.generate_fixture import CORPUS

        dataset = load_review_json(args.dataset)
        result = export_packet(dataset["pairs"], {entry["key"]: entry for entry in CORPUS})
    else:
        operation = compare_annotations if args.command == "compare" else validate_annotations
        result = operation(
            load_review_json(args.packet),
            load_review_json(args.annotations),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
