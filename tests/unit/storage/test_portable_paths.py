import io
import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.domain.export_import import export_to_zip
from packages.domain.paths import sanitize_filename, validate_path_component
from packages.domain.schemas.workspace import WorkspaceCreate
from packages.storage.file_store import FileStore, MemoryFile


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "CON",
        "con.txt",
        "CON .txt",
        "NUL",
        "prn",
        "Aux",
        "COM1",
        "com9.log",
        "LPT1",
        "lpt9",
        "COM¹",
        "LPT²",
        "CONIN$",
        "CONOUT$",
        "bad/name",
        "bad\\name",
        "C:drive",
        "a?b",
        "a*b",
        "a<b",
        "a>b",
        'a"b',
        "a|b",
        "a\x00b",
        "a\x1fb",
        "a\nb",
        "trailing.",
        "trailing ",
        "a" * 256,
        "中" * 86,
        "\U00020000" * 64,
        "bad\ud800",
    ],
)
def test_path_component_rejects_nonportable_names(name: str) -> None:
    with pytest.raises(ValueError):
        validate_path_component(name)
    with pytest.raises(ValidationError):
        WorkspaceCreate(name=name)


@pytest.mark.parametrize(
    "name", ["default", "我的 工作区", "team-a.v2", "con-safe", "com10", "LPT0", "a" * 128]
)
def test_workspace_keeps_valid_name(name: str) -> None:
    assert WorkspaceCreate(name=name).name == name
    assert validate_path_component(name) == name


@pytest.mark.parametrize(
    "title,expected",
    [
        ('a<>:"/\\|?*b', "a---------b"),
        ("a\x00\x1f\nb", "a---b"),
        (".. 中文 . ", "中文"),
        ("CON", "_CON"),
        ("con.txt", "_con.txt"),
        ("LPT²", "_LPT²"),
        ("... ", "untitled"),
        ("", "untitled"),
        ("bad\ud800", "bad-"),
    ],
)
def test_filename_sanitizing(title: str, expected: str) -> None:
    assert sanitize_filename(title) == expected
    assert validate_path_component(expected) == expected


@pytest.mark.parametrize(
    "title", ["a" * 400, "中" * 200, "\U00020000" * 200, "中a\U00020000" * 100]
)
def test_file_store_limits_full_filename_without_splitting_unicode(
    tmp_path: Path, title: str
) -> None:
    store = FileStore(tmp_path / "data")
    memory = MemoryFile(id=str(uuid4()), title=title, content="中文正文", workspace="个人知识")
    path = store.save(memory, "个人知识")
    assert len(path.name.encode("utf-8")) <= 255
    assert len(path.name.encode("utf-16-le")) // 2 <= 255
    assert path.name.startswith(memory.id[:8] + "_")
    assert path.name.endswith(".md")
    loaded = store.load("个人知识", "fact", title, memory_id=memory.id)
    assert loaded is not None and loaded.title == title
    assert loaded.content == "中文正文"
    assert store.delete("个人知识", "fact", title, memory_id=memory.id)


@pytest.mark.parametrize("workspace", ["CON", "../outside", "trailing.", "bad\x00dir"])
def test_file_store_rejects_unsafe_workspace_before_creating_directories(
    tmp_path: Path, workspace: str
) -> None:
    store = FileStore(tmp_path / "data")
    with pytest.raises(ValueError):
        store.save(MemoryFile(id=str(uuid4()), title="normal", content="test"), workspace)
    assert list(store.base_path.iterdir()) == []
    assert not (tmp_path / "outside").exists()


def test_file_store_sanitizes_title_and_id_without_leaving_root(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    path = store.save(MemoryFile(id="../../id", title="../bad\x00:name", content="test"))
    assert path.parent == tmp_path / "chat" / "fact"
    validate_path_component(path.name)


def test_file_store_reads_uppercase_extension_and_ignores_directories(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    memory = MemoryFile(id=str(uuid4()), title="中文", content="test", workspace="default")
    path = store.save(memory, "default")
    renamed = path.with_name("manually-renamed.MD")
    path.rename(renamed)
    (renamed.parent / "not-a-file.md").mkdir()
    assert store._find_file_by_id("default", "fact", memory.id) == renamed
    assert [m.id for m in store.list()] == [memory.id]
    assert store.delete("default", "fact", memory.title, memory_id=memory.id)


def test_zip_entries_are_portable_and_keep_original_data(tmp_path: Path) -> None:
    titles = ['中文:标题?*<>|/\\\x00\n"', "CON", "\U00020000" * 200, "a/b", "a\\b"]
    memories = [
        {
            "id": str(uuid4()),
            "title": title,
            "content": "记忆正文",
            "type": "fact",
            "source": "mcp",
            "status": "active",
            "confidence": 0.9,
            "importance": 0.5,
            "version": 1,
            "is_permanent": False,
            "created_at": "2026-09-18T00:00:00Z",
            "updated_at": "2026-09-18T00:00:00Z",
        }
        for title in titles
    ]
    data = {"memories": memories}
    with zipfile.ZipFile(io.BytesIO(export_to_zip(data))) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)) == 2 + len(titles)
        assert json.loads(archive.read("data.json")) == data
        for folder, items in (("memories", memories),):
            for item in items:
                entry = f"{folder}/{item['id'][:8]}_{sanitize_filename(item['title'][:50])}.md"
                assert entry in names
                filename = entry.split("/")[1]
                assert not re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)
                assert validate_path_component(filename) == filename
                assert len(filename.encode("utf-16-le")) // 2 <= 255
                assert item["content"] in archive.read(entry).decode("utf-8")
        archive.extractall(tmp_path)
    assert len(list((tmp_path / "memories").iterdir())) == len(titles)
