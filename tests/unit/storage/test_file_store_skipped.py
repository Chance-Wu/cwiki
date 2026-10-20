"""FileStore ``list_with_skipped`` 对损坏/空 MD 文件的显式告警测试。

W7 P0-1：MD 是重建的权威源，解析失败必须可见——此前 0 字节或无
frontmatter id 的文件被静默跳过（skipped=0、无日志），重建时记忆
无声消失。
"""

import uuid

from packages.storage.file_store import FileStore, MemoryFile


def _save_ok(store: FileStore, workspace: str) -> str:
    mid = str(uuid.uuid4())
    store.save(MemoryFile(id=mid, title="t", content="c"), workspace_name=workspace)
    return mid


def test_list_with_skipped_returns_valid_memories(tmp_path):
    store = FileStore(str(tmp_path))
    mid = _save_ok(store, "ws")

    memories, skipped = store.list_with_skipped()

    assert [m.id for m in memories] == [mid]
    assert skipped == []


def test_empty_md_recorded_as_skipped(tmp_path):
    store = FileStore(str(tmp_path))
    _save_ok(store, "ws")
    empty_file = tmp_path / "ws" / "fact" / "empty.md"
    empty_file.write_text("", encoding="utf-8")

    memories, skipped = store.list_with_skipped()

    assert len(memories) == 1
    assert len(skipped) == 1
    path, reason = skipped[0]
    assert path.endswith("empty.md")
    # 0 字节文件读不出 frontmatter，归入 no_frontmatter_id 一类
    assert reason == "no_frontmatter_id"


def test_no_frontmatter_id_recorded_as_skipped(tmp_path):
    store = FileStore(str(tmp_path))
    _save_ok(store, "ws")
    bad_file = tmp_path / "ws" / "fact" / "bad.md"
    bad_file.write_text("# 无 frontmatter 的正文\n", encoding="utf-8")

    _, skipped = store.list_with_skipped()

    assert len(skipped) == 1
    path, reason = skipped[0]
    assert path.endswith("bad.md")
    assert reason == "no_frontmatter_id"


def test_unreadable_file_recorded_as_read_error(tmp_path):
    store = FileStore(str(tmp_path))
    _save_ok(store, "ws")
    binary_file = tmp_path / "ws" / "fact" / "broken.md"
    binary_file.write_bytes(b"\xff\xfe\x00\xfa")

    _, skipped = store.list_with_skipped()

    assert len(skipped) == 1
    path, reason = skipped[0]
    assert path.endswith("broken.md")
    assert reason.startswith("read_error:")


def test_list_delegates_to_list_with_skipped(tmp_path):
    store = FileStore(str(tmp_path))
    mid = _save_ok(store, "ws")
    (tmp_path / "ws" / "fact" / "empty.md").write_text("", encoding="utf-8")

    memories = store.list()

    # list() 行为不变：只返回可解析记忆，损坏文件不混入
    assert [m.id for m in memories] == [mid]
