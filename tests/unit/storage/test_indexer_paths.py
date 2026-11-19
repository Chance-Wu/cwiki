"""平台原生索引路径与 watchdog 事件的回归测试。"""

from __future__ import annotations

import asyncio
import ntpath
import os
import posixpath
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from packages.storage import indexer as indexer_module
from packages.storage.file_store import FileStore, MemoryFile
from packages.storage.indexer import MemoryIndexer
from packages.storage.vector_index import VectorIndex


@pytest.fixture
async def indexer(tmp_path, monkeypatch):
    embedding_service = SimpleNamespace(generate_embedding=AsyncMock(return_value=[1.0, 0.0, 0.0]))
    monkeypatch.setattr(indexer_module, "get_embedding_service", lambda: embedding_service)
    instance = MemoryIndexer(
        db_path=str(tmp_path / "index.sqlite3"),
        file_store=FileStore(tmp_path / "memories"),
        vector_index_path=str(tmp_path / "vectors.npz"),
        embedding_dimensions=3,
    )
    # 孤儿清理会交叉校验主库 active 集合；单测不连真实主库，
    # 默认「主库为空」保持既有清理语义，需要时由用例覆盖返回值。
    instance._main_db_active_ids = AsyncMock(return_value=set())  # type: ignore[method-assign]
    try:
        await instance.init_db()
        yield instance
    finally:
        # 不关闭的话 aiosqlite 工作线程会在事件循环关闭后报 "Event loop is closed"
        await instance.close()


@pytest.fixture
async def watcher(indexer, monkeypatch):
    observer = Mock()
    submitted = []

    def capture(coroutine, loop):
        assert loop is asyncio.get_running_loop()
        submitted.append(coroutine)

    monkeypatch.setattr(indexer_module, "WATCHDOG_AVAILABLE", True)
    monkeypatch.setattr(indexer_module, "Observer", Mock(return_value=observer))
    # 替换模块引用，而不是 asyncio 的共享函数。
    monkeypatch.setattr(
        indexer_module,
        "asyncio",
        SimpleNamespace(
            get_event_loop=asyncio.get_running_loop,
            run_coroutine_threadsafe=capture,
            to_thread=asyncio.to_thread,
        ),
    )
    indexer.start_watching()
    handler = observer.schedule.call_args.args[0]
    observer.schedule.assert_called_once_with(
        handler, str(indexer.file_store.base_path), recursive=True
    )
    try:
        yield SimpleNamespace(handler=handler, submitted=submitted)
    finally:
        for coroutine in submitted:
            coroutine.close()
        indexer.stop_watching()


@pytest.fixture
def memory():
    return MemoryFile(
        id="memory-one",
        title="Metadata title",
        content="Memory content for path regression tests.",
        workspace="workspace",
    )


def save_as(indexer, memory, filename):
    path = indexer.file_store.save(memory, workspace_name=memory.workspace)
    return path.rename(path.with_name(filename))


async def dispatch(watcher, method, src_path, dest_path="", is_directory=False):
    event = SimpleNamespace(
        src_path=str(src_path), dest_path=str(dest_path), is_directory=is_directory
    )
    getattr(watcher.handler, method)(event)
    # 移动操作必须只调度一个协程，而非独立的 delete/index 任务。
    assert len(watcher.submitted) == 1
    await watcher.submitted.pop()


@pytest.mark.parametrize("suffix", [".md", ".MD", ".mD"])
async def test_index_memory_discovers_actual_filename(indexer, memory, suffix, monkeypatch):
    path = save_as(indexer, memory, f"Manually renamed{suffix}")
    fallback = Mock(side_effect=AssertionError("Existing files must not use metadata paths"))
    monkeypatch.setattr(indexer.file_store, "_get_file_path", fallback)

    await indexer.index_memory(memory)

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == os.path.normcase(os.path.abspath(path))
    assert memory.id in indexer.vector_index.vectors
    fallback.assert_not_called()


@pytest.mark.parametrize("relative", [False, True])
async def test_explicit_path_skips_discovery(indexer, memory, tmp_path, monkeypatch, relative):
    path = save_as(indexer, memory, "Different filename.MD")
    monkeypatch.chdir(tmp_path)
    find_file = Mock(side_effect=AssertionError("The event path is authoritative"))
    fallback = Mock(side_effect=AssertionError("The event path is authoritative"))
    monkeypatch.setattr(indexer.file_store, "_find_file_by_id", find_file)
    monkeypatch.setattr(indexer.file_store, "_get_file_path", fallback)
    file_path = os.path.relpath(path) if relative else path

    # 既有位置参数 embedding/update_vector 的含义保持不变。
    await indexer.index_memory(memory, [0.0, 1.0, 0.0], True, file_path=file_path)

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == os.path.normcase(os.path.abspath(path))
    assert indexer.vector_index.get_vector(memory.id).tolist() == [0.0, 1.0, 0.0]
    indexer._embedding_service.generate_embedding.assert_not_awaited()
    find_file.assert_not_called()
    fallback.assert_not_called()


async def test_missing_file_falls_back_to_metadata(indexer, memory):
    memory.workspace = None
    filename = indexer.file_store._make_filename(memory.id, memory.title) + ".md"
    expected = indexer.file_store.base_path / "chat" / memory.type / filename

    await indexer.index_memory(memory, None, False)

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == os.path.normcase(os.path.abspath(expected))
    indexer._embedding_service.generate_embedding.assert_not_awaited()
    assert not indexer.vector_index.vectors


@pytest.mark.parametrize("method", ["on_created", "on_modified"])
@pytest.mark.parametrize("suffix", [".md", ".MD", ".mD"])
async def test_change_events_use_actual_path(indexer, watcher, memory, method, suffix):
    path = save_as(indexer, memory, f"Actual name{suffix}")
    if method == "on_modified":
        await indexer.index_memory(memory, file_path=path)
        memory.content = "Content updated without changing the actual filename."
        path.write_text(indexer.file_store._serialize(memory), encoding="utf-8")

    await dispatch(watcher, method, path)

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == os.path.normcase(os.path.abspath(path))
    assert row["content"] == memory.content
    assert memory.id in indexer.vector_index.vectors


@pytest.mark.parametrize("relative_index", [False, True])
@pytest.mark.parametrize("relative_delete", [False, True])
async def test_delete_normalizes_paths(
    indexer, watcher, memory, tmp_path, monkeypatch, relative_index, relative_delete
):
    path = save_as(indexer, memory, "Actual filename.MD")
    monkeypatch.chdir(tmp_path)
    indexed_path = os.path.relpath(path) if relative_index else path
    # 加入冗余成分，验证归一化不止是大小写处理。
    deleted_path = path.parent / ".." / path.parent.name / path.name
    if relative_delete:
        deleted_path = os.path.relpath(deleted_path)
    await indexer.index_memory(memory, file_path=indexed_path)
    path.unlink()

    await dispatch(watcher, "on_deleted", deleted_path)

    assert await indexer.get_memory(memory.id) is None
    assert memory.id not in indexer.vector_index.vectors


async def test_delete_uses_persistent_connection(indexer, watcher, memory, monkeypatch):
    """持久连接模式下 _handle_delete 复用已有连接。"""
    path = save_as(indexer, memory, "Removed.MD")
    await indexer.index_memory(memory, file_path=path)

    # 确保持久连接在 delete 前已建立。
    db = await indexer._get_db()
    assert db is not None

    original_remove = indexer.remove_from_index
    remove = AsyncMock(side_effect=original_remove)
    monkeypatch.setattr(indexer, "remove_from_index", remove)
    await watcher.handler._handle_delete(str(path))

    remove.assert_awaited_once_with(memory.id)
    assert await indexer.get_memory(memory.id) is None
    assert memory.id not in indexer.vector_index.vectors


@pytest.mark.parametrize("method", ["on_created", "on_modified", "on_deleted", "on_moved"])
@pytest.mark.parametrize(
    ("src_path", "dest_path", "is_directory"),
    [
        ("Directory.MD", "Moved.md", True),
        ("Directory.txt", "Moved.MD", True),
        ("notes.txt", "renamed.txt", False),
        ("notes.MD.bak", "renamed.md.bak", False),
    ],
)
async def test_unrelated_and_directory_events_are_ignored(
    watcher, method, src_path, dest_path, is_directory
):
    event = SimpleNamespace(src_path=src_path, dest_path=dest_path, is_directory=is_directory)

    getattr(watcher.handler, method)(event)

    assert not watcher.submitted


@pytest.mark.parametrize("windows_paths", [False, True])
@pytest.mark.parametrize(
    ("src_name", "dest_name"),
    [
        ("Before.md", "After.MD"),
        ("Case.MD", "case.md"),
        ("Before.MD", "Superseded.txt"),
        ("Untracked.txt", "Restored.MD"),
    ],
)
async def test_moves_delete_before_indexing(
    indexer, watcher, memory, monkeypatch, windows_paths, src_name, dest_name
):
    if windows_paths:
        # 隔离 Windows 路径语义，且不改全局 os.path/os.name。
        monkeypatch.setattr(indexer_module, "os", SimpleNamespace(path=ntpath))
    src_path = save_as(indexer, memory, src_name)
    if src_path.suffix.lower() == ".md":
        await indexer.index_memory(memory, file_path=src_path)
    dest_path = src_path.rename(src_path.with_name(dest_name))
    original_change = watcher.handler._handle_change

    async def change_after_deletion(file_path):
        assert await indexer.get_memory(memory.id) is None
        assert memory.id not in indexer.vector_index.vectors
        await original_change(file_path)

    change = AsyncMock(side_effect=change_after_deletion)
    delete = AsyncMock(wraps=watcher.handler._handle_delete)
    monkeypatch.setattr(watcher.handler, "_handle_change", change)
    monkeypatch.setattr(watcher.handler, "_handle_delete", delete)

    await dispatch(watcher, "on_moved", src_path, dest_path)

    if src_path.suffix.lower() == ".md":
        delete.assert_awaited_once_with(str(src_path))
    else:
        delete.assert_not_awaited()
    row = await indexer.get_memory(memory.id)
    if dest_path.suffix.lower() == ".md":
        change.assert_awaited_once_with(str(dest_path))
        path_module = ntpath if windows_paths else os.path
        assert row["file_path"] == path_module.normcase(path_module.abspath(dest_path))
        assert memory.id in indexer.vector_index.vectors
    else:
        change.assert_not_awaited()
        assert row is None
        assert memory.id not in indexer.vector_index.vectors


@pytest.mark.parametrize(
    ("indexed_path", "deleted_path", "expected"),
    [
        (r"C:\Wiki\Folder\Note.MD", "c:/wiki/folder/./NOTE.md", r"c:\wiki\folder\note.md"),
        (
            r"\\Server\Share\Wiki\Note.MD",
            "//SERVER/share/WIKI/NOTE.md",
            r"\\server\share\wiki\note.md",
        ),
    ],
)
async def test_windows_paths_are_case_normalized(
    indexer, watcher, memory, monkeypatch, indexed_path, deleted_path, expected
):
    monkeypatch.setattr(indexer_module, "os", SimpleNamespace(path=ntpath))

    await indexer.index_memory(memory, file_path=indexed_path)

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == expected
    await watcher.handler._handle_delete(deleted_path)
    assert await indexer.get_memory(memory.id) is None
    assert memory.id not in indexer.vector_index.vectors


async def test_posix_paths_preserve_case(indexer, watcher, memory, monkeypatch):
    monkeypatch.setattr(indexer_module, "os", SimpleNamespace(path=posixpath))
    other = MemoryFile(id="memory-two", title="Other memory", content="Separate case variant.")
    # 仅 SQLite 的路径也在大小写不敏感主机上演练 POSIX 语义。
    await indexer.index_memory(memory, file_path="/Wiki/Note.MD")
    await indexer.index_memory(other, file_path="/Wiki/note.md")

    assert (await indexer.get_memory(memory.id))["file_path"] == "/Wiki/Note.MD"
    assert (await indexer.get_memory(other.id))["file_path"] == "/Wiki/note.md"
    await watcher.handler._handle_delete("/Wiki/./Note.MD")

    assert await indexer.get_memory(memory.id) is None
    assert await indexer.get_memory(other.id) is not None
    assert set(indexer.vector_index.vectors) == {other.id}


@pytest.mark.parametrize("keep_memory", [False, True])
async def test_sync_repairs_legacy_paths_and_commits_orphan_cleanup(
    indexer, watcher, memory, keep_memory, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    original = indexer.file_store.save(memory, workspace_name=memory.workspace)
    await indexer.index_memory(memory)
    db = await indexer._get_db()
    await db.execute(
        "UPDATE memory_index SET file_path = ? WHERE id = ?",
        (os.path.relpath(original), memory.id),
    )
    await db.commit()
    renamed = original.rename(original.with_name("Renamed.MD"))
    # 重命名会保留 mtime；显式回拨以复现"仅靠 mtime 会跳过路径修复"的场景
    os.utime(renamed, (1, 1))
    if not keep_memory:
        renamed.unlink()
    orphan = MemoryFile(id="sqlite-orphan", title="Deleted memory", content="Missing file.")
    await indexer.index_memory(orphan, update_vector=False)
    indexer.vector_index.add("vector-orphan", [0.0, 1.0, 0.0])
    await indexer.save_vector_index()

    await indexer.sync_all()

    expected_ids = {memory.id} if keep_memory else set()
    assert {row["id"] for row in await indexer.list_memories()} == expected_ids
    assert set(indexer.vector_index.vectors) == expected_ids
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert set(reloaded.vectors) == expected_ids
    if keep_memory:
        row = await indexer.get_memory(memory.id)
        assert row["file_path"] == os.path.normcase(os.path.abspath(renamed))
        renamed.unlink()
        await watcher.handler._handle_delete(os.path.relpath(renamed))
        assert await indexer.get_memory(memory.id) is None
        assert memory.id not in indexer.vector_index.vectors


@pytest.mark.parametrize("rewrite", [False, True])
async def test_sync_never_keeps_vectors_for_superseded_files(indexer, memory, rewrite):
    """已取代文件保留 SQLite 行，但其向量会被剪除且不再回加。"""
    superseded = MemoryFile(
        id="superseded-one",
        title="Superseded memory",
        content="Superseded body.",
        status="superseded",
    )
    active_path = save_as(indexer, memory, "Active.MD")
    superseded_path = save_as(indexer, superseded, "Superseded.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=active_path)
    await indexer.index_memory(superseded, update_vector=False, file_path=superseded_path)
    # 模拟历史残留：一条仍持有向量的已取代记忆。
    indexer.vector_index.add(superseded.id, [0.0, 1.0, 0.0])
    await indexer.save_vector_index()

    if rewrite:
        # 强制走重索引分支：待重索引的文件已已取代。
        db = await indexer._get_db()
        await db.execute(
            "UPDATE memory_index SET updated = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", superseded.id),
        )
        await db.commit()

    await indexer.sync_all()

    assert set(indexer.vector_index.vectors) == {memory.id}
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert set(reloaded.vectors) == {memory.id}
    assert (await indexer.get_memory(superseded.id))["status"] == "superseded"
    assert (await indexer.get_memory(memory.id))["status"] == "active"


async def test_change_event_archives_and_persists_vector_removal(indexer, watcher, memory):
    path = save_as(indexer, memory, "Flips to superseded.MD")
    await indexer.index_memory(memory, [0.5, 0.5, 0.0], file_path=path)
    await indexer.save_vector_index()
    assert memory.id in indexer.vector_index.vectors

    memory.status = "superseded"
    path.write_text(indexer.file_store._serialize(memory), encoding="utf-8")

    await dispatch(watcher, "on_modified", path)

    assert (await indexer.get_memory(memory.id))["status"] == "superseded"
    assert memory.id not in indexer.vector_index.vectors
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert reloaded.vectors == {}


async def test_sync_uses_loaded_paths_without_repeated_directory_scans(
    indexer, memory, monkeypatch
):
    path = save_as(indexer, memory, "Manually renamed.MD")
    find_file = Mock(side_effect=AssertionError("Sync must reuse the already discovered file path"))
    monkeypatch.setattr(indexer.file_store, "_find_file_by_id", find_file)

    await indexer.sync_all()

    row = await indexer.get_memory(memory.id)
    assert row["file_path"] == os.path.normcase(os.path.abspath(path))
    find_file.assert_not_called()


@pytest.mark.parametrize("loader", ["load", "load_from_path", "list"])
async def test_loaded_paths_are_not_serialized(indexer, memory, loader):
    path = save_as(indexer, memory, "Actual.MD")
    if loader == "load":
        loaded = indexer.file_store.load(memory.workspace, memory.type, memory.title, memory.id)
    elif loader == "load_from_path":
        loaded = indexer.file_store.load_from_path(path)
    else:
        loaded = indexer.file_store.list()[0]
    assert loaded.file_path == path
    assert "file_path" not in loaded.to_dict()
    assert "file_path" not in indexer.file_store._serialize(loaded)


async def test_sync_never_prunes_index_when_markdown_listing_is_empty(indexer, memory):
    """清单为空但主库仍有 active 记忆时，必须保留索引行与向量。

    这正是「重启后索引整批消失」的复现路径：sync_all 若以单边 MD 清单
    判定孤儿，任何暂时的空清单都会把索引删光。
    """
    path = save_as(indexer, memory, "Keep.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=path)
    await indexer.save_vector_index()
    # 模拟清单读取异常：文件还在盘上，但 list_with_skipped 返回空
    indexer.file_store.list_with_skipped = lambda *a, **k: ([], [])  # type: ignore[method-assign]
    indexer._main_db_active_ids = AsyncMock(return_value={memory.id})  # type: ignore[method-assign]

    await indexer.sync_all()

    assert await indexer.get_memory(memory.id) is not None
    assert memory.id in indexer.vector_index.vectors
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert memory.id in reloaded.vectors


async def test_sync_skips_pruning_when_files_unreadable(indexer, memory):
    """存在无法解析的 MD 文件时清单不可信，跳过孤儿清理。"""
    path = save_as(indexer, memory, "Keep.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=path)
    indexer.file_store.list_with_skipped = lambda *a, **k: (
        [],
        [(str(path), "read_error: PermissionError")],
    )  # type: ignore[method-assign]
    indexer._main_db_active_ids = AsyncMock(return_value=set())  # type: ignore[method-assign]

    await indexer.sync_all()

    assert await indexer.get_memory(memory.id) is not None


async def test_sync_skips_pruning_when_main_db_unreadable(indexer, memory):
    """主库不可读时宁可保留陈旧行，也不做破坏性清理。"""
    path = save_as(indexer, memory, "Keep.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=path)
    indexer.file_store.list_with_skipped = lambda *a, **k: ([], [])  # type: ignore[method-assign]
    indexer._main_db_active_ids = AsyncMock(return_value=None)  # type: ignore[method-assign]

    await indexer.sync_all()

    assert await indexer.get_memory(memory.id) is not None


async def test_sync_still_prunes_rows_absent_from_both_carriers(indexer, memory):
    """MD 与主库都缺席的行仍会被正常清理（安全闸门不阻断真实孤儿）。"""
    orphan = MemoryFile(id="gone-everywhere", title="Gone", content="Gone body.")
    await indexer.index_memory(orphan, update_vector=False)

    # 清单为空但主库仍 active：单边清单不构成删除依据，保留
    indexer.file_store.list_with_skipped = lambda *a, **k: ([], [])  # type: ignore[method-assign]
    indexer._main_db_active_ids = AsyncMock(return_value={orphan.id})  # type: ignore[method-assign]
    await indexer.sync_all()
    assert await indexer.get_memory(orphan.id) is not None

    # 双载体都缺席：正常清理
    indexer._main_db_active_ids = AsyncMock(return_value=set())  # type: ignore[method-assign]
    await indexer.sync_all()
    assert await indexer.get_memory(orphan.id) is None


async def test_watcher_delete_keeps_row_when_main_db_still_active(indexer, watcher, memory):
    """git 式文件替换（删除+重建）不得误删仍 active 记忆的索引行。"""
    path = save_as(indexer, memory, "Replaced.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=path)
    indexer._main_db_active_ids = AsyncMock(return_value={memory.id})  # type: ignore[method-assign]

    await watcher.handler._handle_delete(path)

    assert await indexer.get_memory(memory.id) is not None
    assert memory.id in indexer.vector_index.vectors


def test_vector_save_skips_when_disk_changed_externally(tmp_path):
    """另一进程重建过 vectors.npz 后，本实例不得用旧内存状态覆盖。"""
    index_path = tmp_path / "vectors.npz"
    vi = VectorIndex(dimensions=3, index_path=str(index_path))
    vi.add("a", [1.0, 0.0, 0.0])
    vi.save()

    # 模拟外部进程（rebuild-db）改写文件
    other = VectorIndex(dimensions=3, index_path=str(index_path))
    other.add("b", [0.0, 1.0, 0.0])
    other.save()
    assert vi.disk_changed_externally()

    vi.add("c", [0.0, 0.0, 1.0])
    vi.save()  # 检测到外部改写 -> 跳过

    reloaded = VectorIndex(dimensions=3, index_path=str(index_path))
    assert set(reloaded.vectors) == {"a", "b"}  # 保留外部权威版本，未被覆盖

    # 显式 force 才允许覆盖（重建语义）：以本实例内存状态整体替换磁盘内容
    vi.save(force=True)
    assert set(VectorIndex(dimensions=3, index_path=str(index_path)).vectors) == {"a", "c"}


async def test_indexer_save_vector_index_only_if_unchanged(indexer):
    indexer.vector_index.add("x", [1.0, 0.0, 0.0])
    await indexer.save_vector_index()
    # 外部改写
    external = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    external.add("y", [0.0, 1.0, 0.0])
    external.save()

    saved = await indexer.save_vector_index(only_if_unchanged=True)
    assert saved is False
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert set(reloaded.vectors) == {"x", "y"}


async def test_sync_restores_missing_vectors_from_main_db(indexer, tmp_path, monkeypatch):
    """mtime 跳过路径也要补齐缺失向量：否则启动同步永远修不好 missing_vectors。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from packages.domain import database as database_module
    from packages.domain.models import Memory as DbMemory
    from packages.domain.models import Workspace
    from packages.domain.models.base import Base as ModelsBase

    memory = MemoryFile(
        id=str(uuid.uuid4()),
        title="Restore memory",
        content="Restore this vector body.",
        workspace="chat",
    )
    path = save_as(indexer, memory, "Keep.MD")
    await indexer.index_memory(memory, [1.0, 0.0, 0.0], file_path=path)
    # 模拟 vectors.npz 曾丢失该条目（索引行仍是最新，mtime 会走跳过路径）
    indexer.vector_index.remove(memory.id)
    await indexer.save_vector_index()

    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'main.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(ModelsBase.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        db.add(Workspace(id=uuid.uuid4(), name=memory.workspace or "chat"))
        ws_id = (await db.execute(select(Workspace.id))).scalar_one()
        db.add(
            DbMemory(
                id=uuid.UUID(memory.id),
                workspace_id=ws_id,
                title=memory.title,
                content=memory.content,
                type=memory.type,
                status="active",
                source="mcp",
                embedding=[1.0, 0.0, 0.0],
            )
        )
        await db.commit()
    monkeypatch.setattr(database_module, "async_session_maker", sessions)
    indexer._main_db_active_ids = AsyncMock(return_value={memory.id})  # type: ignore[method-assign]

    await indexer.sync_all()
    await engine.dispose()

    assert memory.id in indexer.vector_index.vectors
    reloaded = VectorIndex(dimensions=3, index_path=str(indexer.vector_index.index_path))
    assert memory.id in reloaded.vectors
