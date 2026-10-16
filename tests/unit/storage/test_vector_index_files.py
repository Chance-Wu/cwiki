"""VectorIndex 文件配对与临时文件清理的回归测试。

索引以*配对*形式存储：``vectors.npz``（行序 = ids 顺序）和
``vectors.json``（``{ids, metadata, version}``）。任一半边被删都会
静默禁用语义检索，因此两者必须一起写入、一起清理。
"""

from __future__ import annotations

import glob

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
