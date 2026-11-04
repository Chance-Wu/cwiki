"""No synthetic annotation in this test constitutes human review."""

import json
from copy import deepcopy

import pytest

from benchmarks.runners.relevance_review import (
    compare_annotations,
    export_packet,
    load_review_json,
    validate_annotations,
)


def example():
    packet = export_packet(
        [
            {
                "id": "negative-secret",
                "key": "secret",
                "query": "question",
                "relevant": False,
                "reason": "leak",
            }
        ],
        {"secret": {"title": "title", "content": "document"}},
    )
    labels = {
        "packet_id": packet["packet_id"],
        "reviewer": "test-only-not-human",
        "judgments": [
            {"pair_id": packet["items"][0]["pair_id"], "relevant": True, "rationale": "test"}
        ],
    }
    return packet, labels


def test_no_label_leak_or_heldout_claim():
    packet, labels = example()
    assert set(packet["items"][0]) == {"pair_id", "query", "title", "content"}
    assert "secret" not in str(packet)
    assert "leak" not in str(packet)
    result = validate_annotations(packet, labels)
    assert result["split"] == "development"
    assert result["independence_verified"] is False
    assert result["judgments"][0]["relevant"] is True


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "unknown", "integer", "null", "blank", "reviewer", "packet", "extra"],
)
def test_reject_ambiguous_or_incomplete_labels(change):
    packet, labels = example()
    row = labels["judgments"][0]
    if change == "missing":
        labels["judgments"] = []
    elif change == "duplicate":
        labels["judgments"].append(deepcopy(row))
    elif change == "unknown":
        row["pair_id"] = "unknown"
    elif change == "integer":
        row["relevant"] = 1
    elif change == "null":
        row["relevant"] = None
    elif change == "blank":
        row["rationale"] = " "
    elif change == "reviewer":
        labels["reviewer"] = ""
    elif change == "packet":
        labels["packet_id"] = "different"
    else:
        row["score"] = 0.5
    with pytest.raises(ValueError):
        validate_annotations(packet, labels)


def test_snapshot_binding_and_development_only():
    packet, labels = example()
    changed = deepcopy(packet)
    changed["items"][0]["content"] = "changed"
    with pytest.raises(ValueError, match="snapshot mismatch"):
        validate_annotations(changed, labels)
    changed = deepcopy(packet)
    changed["split"] = "heldout"
    with pytest.raises(ValueError, match="development only"):
        validate_annotations(changed, labels)
    with pytest.raises(ValueError, match="duplicate"):
        export_packet([{"query": "q", "key": "k"}] * 2, {"k": {"title": "t", "content": "c"}})
    with pytest.raises(ValueError, match="empty"):
        export_packet([], {})


def test_comparison_uses_external_label_and_snapshot_only():
    packet, labels = example()
    before_packet, before_labels = deepcopy(packet), deepcopy(labels)
    report = compare_annotations(packet, labels)
    assert packet == before_packet and labels == before_labels
    assert report["split"] == "development"
    assert report["independence_verified"] is False
    for result in report["results"]:
        assert result["positive_count"] == 1  # original export source was False
        assert result["negative_count"] == 0
        assert result["negative_reject_rate"] is None
        assert result["pairs"][0]["reason"] == "test"
    report["results"][0]["pairs"][0]["reason"] = "mutated"
    validated = validate_annotations(packet, labels)
    validated["judgments"][0]["rationale"] = "mutated"
    assert labels == before_labels


def test_comparison_joins_by_id_not_annotation_order():
    packet = export_packet(
        [{"query": "MySQL", "key": "redis"}, {"query": "Redis", "key": "redis"}],
        {"redis": {"title": "Redis", "content": "Sentinel"}},
    )
    labels = {
        "packet_id": packet["packet_id"],
        "reviewer": "test-only-not-human",
        "judgments": [
            {
                "pair_id": item["pair_id"],
                "relevant": item["query"] == "Redis",
                "rationale": item["query"],
            }
            for item in reversed(packet["items"])
        ],
    }
    result = compare_annotations(packet, labels)["results"][2]
    assert result["positive_keep_rate"] == 1
    assert result["negative_reject_rate"] == 1
    labels["judgments"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        compare_annotations(packet, labels)


@pytest.mark.parametrize(
    "content",
    [
        '{"relevant": false, "relevant": true}',
        '{"judgments": [{"relevant": false, "relevant": true}]}',
    ],
)
def test_duplicate_json_fields_rejected(tmp_path, content):
    path = tmp_path / "ambiguous.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_review_json(path)


@pytest.mark.parametrize("command", ["check", "compare"])
def test_cli_reads_external_annotations(tmp_path, monkeypatch, capsys, command):
    from benchmarks.runners.relevance_review import main

    packet, labels = example()
    packet_path, labels_path = tmp_path / "packet.json", tmp_path / "labels.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    labels_path.write_text(json.dumps(labels), encoding="utf-8-sig")
    monkeypatch.setattr("sys.argv", ["review", command, str(packet_path), str(labels_path)])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["packet_id"] == packet["packet_id"]
    assert result["independence_verified"] is False
    assert result["split"] == "development"


def test_json_root_and_bom(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"reviewer": "人工"}', encoding="utf-8-sig")
    assert load_review_json(path) == {"reviewer": "人工"}
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="root must be an object"):
        load_review_json(path)
    with pytest.raises(TypeError, match="must be objects"):
        validate_annotations([], {})
