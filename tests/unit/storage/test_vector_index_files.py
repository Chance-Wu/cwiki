"""VectorIndex 文件配对与临时文件清理的回归测试。

索引以*配对*形式存储：``vectors.npz``（行序 = ids 顺序）和
``vectors.json``（``{ids, metadata, version}``）。任一半边被删都会
静默禁用语义检索，因此两者必须一起写入、一起清理。
"""

from __future__ import annotations

import glob
import json

import numpy as np
import pytest

from packages.storage.vector_index import VectorIndex


def test_save_writes_json_companion_and_leaves_no_tmp_files(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0], {"type": "note", "tags": []})
    vi.add("b", [0.0, 1.0, 0.0], {"type": "note", "tags": []})
    vi.save()

    assert index_path.exists()
    meta_path = index_path.with_suffix(".json")
    assert meta_path.exists()
    # mkstemp 桩文件与暂存文件必须被改名收尾，不得残留。
    assert glob.glob(str(tmp_path / "*.tmp*")) == []

    reloaded = VectorIndex(dimensions=3, index_path=str(index_path))
    assert set(reloaded.vectors) == {"a", "b"}
    assert reloaded.metadata["a"] == {"type": "note", "tags": []}


def test_load_without_json_companion_stays_empty_without_crashing(tmp_path):
    """缺少 json 半边时必须降级为空索引，而不是抛异常。"""
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()
    index_path.with_suffix(".json").unlink()

    reloaded = VectorIndex(dimensions=3, index_path=str(index_path))
    assert reloaded.vectors == {}
    assert reloaded.search([1.0, 0.0, 0.0], top_k=1) == []


def test_save_empty_index_removes_both_files(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()
    vi.remove("a")
    vi.save()

    assert not index_path.exists()
    assert not index_path.with_suffix(".json").exists()


def test_meta_records_dimensions_and_model(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path), model="model-a")
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()

    meta = json.loads(index_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["dimensions"] == 3
    assert meta["model"] == "model-a"


def test_model_mismatch_discards_vectors(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path), model="model-a")
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()

    reloaded = VectorIndex(dimensions=3, index_path=str(index_path), model="model-b")
    assert reloaded.vectors == {}


def test_embedded_ids_reject_same_count_reordered_metadata(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.add("b", [0.0, 1.0, 0.0])
    vi.save()
    meta_path = index_path.with_suffix(".json")
    meta = json.loads(meta_path.read_text())
    meta["ids"] = ["b", "a"]
    meta_path.write_text(json.dumps(meta))
    reloaded = VectorIndex(dimensions=3, index_path=str(index_path))
    assert reloaded.vectors == {}


def test_hash_rejects_same_ids_changed_vectors(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()
    with np.load(index_path) as data:
        np.savez(index_path, vectors=data["vectors"] * 2, ids=data["ids"])
    reloaded = VectorIndex(dimensions=3, index_path=str(index_path))
    assert reloaded.vectors == {}


def test_second_replace_failure_never_binds_new_vectors_to_old_ids(tmp_path, monkeypatch):
    from packages.storage import vector_index as module
    from packages.storage.index_health import inspect_vector_index

    path = tmp_path / "vectors.npz"
    index = VectorIndex(dimensions=3, index_path=str(path), model="audit")
    index.add("a", [1, 0, 0])
    index.add("b", [0, 1, 0])
    index.save()
    index.remove("a")
    index.add("c", [-1, 0, 0])
    replace = module._atomic_replace

    def fail_meta(src, dst):
        if dst.suffix == ".json":
            raise OSError("injected metadata replacement failure")
        replace(src, dst)

    monkeypatch.setattr(module, "_atomic_replace", fail_meta)
    with pytest.raises(OSError):
        index.save()
    reloaded = VectorIndex(dimensions=3, index_path=str(path), model="audit")
    assert reloaded.vectors == {}
    health = inspect_vector_index(
        path, path.with_suffix(".json"), expected_dimensions=3, expected_model="audit"
    )
    assert not health.ok
    assert list(tmp_path.glob("*.tmp*")) == []


def test_dimension_mismatch_discards_vectors(tmp_path):
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()

    reloaded = VectorIndex(dimensions=4, index_path=str(index_path))
    assert reloaded.vectors == {}
