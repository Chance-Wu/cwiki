"""write-ahead outbox 崩溃安全与并发隔离测试。"""

from __future__ import annotations

import builtins
import multiprocessing
import os
import threading
import time
from importlib.util import module_from_spec, spec_from_file_location
from multiprocessing.synchronize import Barrier, Event
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from adapters.mcp import outbox as outbox_module
from adapters.mcp.outbox import (
    WriteAheadOutbox,
    _atomic_write_json,
    _load_json,
    _with_lock,
)

# 子进程会重新导入本模块并争抢 CPU；30 秒的紧凑预算在并行负载
# （mypy/ruff 与 pytest 同时运行）下容易闪断。
_SPAWN_TIMEOUT = 120.0


def _spawn_write_entries(state_dir: Path, start: int, count: int, barrier: Barrier) -> None:
    outbox = WriteAheadOutbox(state_dir=state_dir)
    barrier.wait(timeout=_SPAWN_TIMEOUT)
    for i in range(start, start + count):
        outbox.log_pending("ws-1", "memory_save", {"content": f"msg-{i}"}, f"ms:{i}")


def _spawn_waiting_writer(state_dir: Path, ready: Event, done: Event) -> None:
    outbox = WriteAheadOutbox(state_dir=state_dir)
    ready.set()
    outbox.log_pending("ws-1", "memory_save", {"content": "after release"}, "ms:waiting")
    done.set()


@pytest.fixture
def windows_lock_api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    api = SimpleNamespace(LK_LOCK=1, LK_UNLCK=0, locking=Mock())
    # 只替换 outbox 分支，绝不改 os.name（它还会影响 pathlib）。
    monkeypatch.setattr(outbox_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(outbox_module, "msvcrt", api, raising=False)
    return api


class TestAtomicWriteJson:
    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "outbox.json"
        _atomic_write_json(path, [{"id": "1"}])
        assert path.exists()
        assert _load_json(path) == [{"id": "1"}]

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "outbox.json"
        _atomic_write_json(path, [{"id": "1"}])
        _atomic_write_json(path, [{"id": "2"}])
        assert _load_json(path) == [{"id": "2"}]

    def test_no_leftover_temp_on_success(self, tmp_path: Path) -> None:
        path = tmp_path / "outbox.json"
        _atomic_write_json(path, [{"id": "1"}])
        temp_files = list(tmp_path.glob(".outbox.*.tmp"))
        assert temp_files == []

    def test_replace_retries_transient_permission_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "outbox.json"
        real_replace = os.replace
        attempts: list[tuple[str, Path]] = []
        sleeps: list[float] = []

        def flaky_replace(src: str, dst: Path) -> None:
            attempts.append((src, dst))
            if len(attempts) < 3:
                raise PermissionError("held by filter driver")
            real_replace(src, dst)

        monkeypatch.setattr(os, "replace", flaky_replace)
        monkeypatch.setattr(time, "sleep", sleeps.append)
        _atomic_write_json(path, [{"id": "1"}])

        assert len(attempts) == 3
        assert sleeps == [outbox_module._REPLACE_RETRY_DELAY] * 2
        assert _load_json(path) == [{"id": "1"}]
        assert list(tmp_path.glob(".outbox.*.tmp")) == []

    def test_replace_exhausts_retries_and_cleans_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "outbox.json"
        attempts: list[tuple[str, Path]] = []

        def denied(src: str, dst: Path) -> None:
            attempts.append((src, dst))
            raise PermissionError("held by filter driver")

        monkeypatch.setattr(os, "replace", denied)
        monkeypatch.setattr(time, "sleep", lambda _s: None)
        with pytest.raises(PermissionError, match="filter driver"):
            _atomic_write_json(path, [{"id": "1"}])

        assert len(attempts) == outbox_module._REPLACE_RETRIES + 1
        assert not path.exists()
        assert list(tmp_path.glob(".outbox.*.tmp")) == []


class TestWriteAheadOutbox:
    def test_log_and_load_pending(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox.log_pending("ws-1", "memory_save", {"content": "test"}, "ms:abc123")
        assert entry["state"] == "pending"
        assert entry["client_write_id"] == "ms:abc123"

        pending = outbox.load_pending("ws-1")
        assert len(pending) == 1
        assert pending[0]["id"] == entry["id"]

    def test_mark_success_removes_entry(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox.log_pending("ws-1", "memory_save", {"content": "test"}, "ms:abc")
        outbox.mark_success("ws-1", entry["id"])

        assert outbox.load_pending("ws-1") == []
        assert outbox.load_all("ws-1") == []

    def test_mark_failed_keeps_entry(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox.log_pending("ws-1", "memory_save", {"content": "test"}, "ms:abc")
        outbox.mark_failed("ws-1", entry["id"])

        assert outbox.load_pending("ws-1") == []
        failed = [e for e in outbox.load_all("ws-1") if e["state"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["attempts"] == 1

    def test_concurrent_workspace_isolation(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        outbox.log_pending("ws-2", "memory_save", {"content": "b"}, "ms:b")

        assert (tmp_path / "ws-1.json").exists()
        assert (tmp_path / "ws-2.json").exists()

        outbox.mark_success("ws-1", e1["id"])
        assert outbox.load_all("ws-1") == []
        assert len(outbox.load_all("ws-2")) == 1

    def test_load_all_workspaces(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        outbox.log_pending("ws-2", "memory_save", {"content": "b"}, "ms:b")

        all_entries = outbox.load_all_workspaces()
        assert "ws-1" in all_entries
        assert "ws-2" in all_entries
        assert len(all_entries["ws-1"]) == 1
        assert len(all_entries["ws-2"]) == 1

    def test_crash_recovery_survives_restart(self, tmp_path: Path) -> None:
        outbox1 = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox1.log_pending("ws-1", "memory_save", {"content": "crash"}, "ms:crash")

        outbox2 = WriteAheadOutbox(state_dir=tmp_path)
        pending = outbox2.load_pending("ws-1")
        assert len(pending) == 1
        assert pending[0]["id"] == entry["id"]
        assert pending[0]["client_write_id"] == "ms:crash"

    def test_empty_workspace_returns_empty(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        assert outbox.load_pending("nonexistent") == []
        assert outbox.load_all("nonexistent") == []


class TestUpdateEntry:
    def test_freezes_processed_args(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox.log_pending("ws-1", "memory_save", {"content": "raw"}, "ms:abc")

        outbox.update_entry(
            "ws-1",
            entry["id"],
            {
                "arguments": {
                    "content": "raw",
                    "inferred_type": "fact",
                    "wrapped_content": "## 场景\nraw\n## 知识\nraw\n## 原因\nraw",
                }
            },
        )

        loaded = outbox.load_all("ws-1")
        assert len(loaded) == 1
        args = loaded[0]["arguments"]
        assert args["inferred_type"] == "fact"
        assert "## 场景" in args["wrapped_content"]

    def test_update_nonexistent_entry_is_noop(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "test"}, "ms:abc")
        outbox.update_entry("ws-1", "nonexistent-id", {"arguments": {"x": 1}})
        loaded = outbox.load_all("ws-1")
        assert len(loaded) == 1
        assert loaded[0]["arguments"] == {"content": "test"}


class TestLoadRetryable:
    def test_returns_pending_and_failed(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "pending"}, "ms:p")
        e2 = outbox.log_pending("ws-1", "memory_save", {"content": "will-fail"}, "ms:f")
        outbox.mark_failed("ws-1", e2["id"])

        retryable = outbox.load_retryable()
        assert "ws-1" in retryable
        ids = {e["id"] for e in retryable["ws-1"]}
        assert e1["id"] in ids
        assert e2["id"] in ids

    def test_excludes_exhausted_entries(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "pending"}, "ms:p")
        e2 = outbox.log_pending("ws-1", "memory_save", {"content": "exhausted"}, "ms:e")
        outbox.mark_failed("ws-1", e2["id"])
        outbox.mark_exhausted("ws-1", e2["id"])

        retryable = outbox.load_retryable()
        ids = {e["id"] for e in retryable.get("ws-1", [])}
        assert e1["id"] in ids
        assert e2["id"] not in ids

    def test_empty_when_no_retryable(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "done"}, "ms:d")
        outbox.mark_success("ws-1", e1["id"])
        assert outbox.load_retryable() == {}


class TestWindowsFileLocking:
    def test_import_without_fcntl(self) -> None:
        windows_os = SimpleNamespace(name="nt")
        windows_api = SimpleNamespace()

        def windows_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "os":
                return windows_os
            if name == "msvcrt":
                return windows_api
            if name == "fcntl":
                raise ModuleNotFoundError("No module named 'fcntl'")
            return builtins.__import__(name, *args, **kwargs)

        # 只对本模块提供 importer，保持真实的 os/pathlib 不受影响。
        spec = spec_from_file_location("_outbox_windows_test", outbox_module.__file__)
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        module.__dict__["__builtins__"] = dict(vars(builtins), __import__=windows_import)
        spec.loader.exec_module(module)
        assert module._IS_WINDOWS is True
        assert module.msvcrt is windows_api
        assert hasattr(module, "WriteAheadOutbox")

    @pytest.mark.parametrize("initial_bytes", [None, b"", b"keep-existing-lock"])
    def test_locks_first_byte_without_truncating(
        self, tmp_path: Path, windows_lock_api: SimpleNamespace, initial_bytes: bytes | None
    ) -> None:
        path = tmp_path / "outbox.json"
        lock_path = path.with_suffix(".lock")
        if initial_bytes is not None:
            lock_path.write_bytes(initial_bytes)
        calls = []
        descriptors = []

        def locking(fd: int, mode: int, count: int) -> None:
            descriptors.append(fd)
            calls.append((mode, os.lseek(fd, 0, os.SEEK_CUR), count))

        windows_lock_api.locking.side_effect = locking

        def callback(locked_path: Path) -> str:
            assert locked_path == path
            assert calls == [(windows_lock_api.LK_LOCK, 0, 1)]
            assert lock_path.read_bytes() == (initial_bytes or b"\0")
            # 即使当前偏移已移动，解锁时也必须 seek 回文件头。
            os.lseek(descriptors[0], 7, os.SEEK_SET)
            return "result"

        assert _with_lock(path, callback) == "result"
        assert calls == [(windows_lock_api.LK_LOCK, 0, 1), (windows_lock_api.LK_UNLCK, 0, 1)]
        assert descriptors[0] == descriptors[1]
        assert lock_path.read_bytes() == (initial_bytes or b"\0")
        with pytest.raises(OSError):
            os.fstat(descriptors[0])

    @pytest.mark.parametrize("error", [RuntimeError("callback failed"), KeyboardInterrupt()])
    def test_callback_exception_releases_lock(
        self, tmp_path: Path, windows_lock_api: SimpleNamespace, error: BaseException
    ) -> None:
        with pytest.raises(type(error)) as caught:
            _with_lock(tmp_path / "outbox.json", Mock(side_effect=error))
        assert caught.value is error
        acquire, release = windows_lock_api.locking.call_args_list
        fd = acquire.args[0]
        assert acquire.args == (fd, windows_lock_api.LK_LOCK, 1)
        assert release.args == (fd, windows_lock_api.LK_UNLCK, 1)
        with pytest.raises(OSError):
            os.fstat(fd)

    def test_acquire_failure_does_not_run_callback_or_unlock(
        self, tmp_path: Path, windows_lock_api: SimpleNamespace
    ) -> None:
        error = OSError("lock acquisition failed")
        windows_lock_api.locking.side_effect = error
        callback = Mock()
        with pytest.raises(OSError) as caught:
            _with_lock(tmp_path / "outbox.json", callback)
        assert caught.value is error
        callback.assert_not_called()
        windows_lock_api.locking.assert_called_once()
        fd, mode, count = windows_lock_api.locking.call_args.args
        assert (mode, count) == (windows_lock_api.LK_LOCK, 1)
        with pytest.raises(OSError):
            os.fstat(fd)

    def test_unlock_failure_is_not_silenced(
        self, tmp_path: Path, windows_lock_api: SimpleNamespace
    ) -> None:
        error = OSError("unlock failed")
        windows_lock_api.locking.side_effect = [None, error]
        callback = Mock()
        with pytest.raises(OSError) as caught:
            _with_lock(tmp_path / "outbox.json", callback)
        assert caught.value is error
        callback.assert_called_once()
        fd, mode, count = windows_lock_api.locking.call_args.args
        assert (mode, count) == (windows_lock_api.LK_UNLCK, 1)
        with pytest.raises(OSError):
            os.fstat(fd)


class TestFileLocking:
    def test_spawn_concurrent_writes_no_data_loss(self, tmp_path: Path) -> None:
        context = multiprocessing.get_context("spawn")
        process_count, entries_per_process = 4, 20
        barrier = context.Barrier(process_count + 1)
        processes = [
            context.Process(
                target=_spawn_write_entries,
                args=(tmp_path, i * entries_per_process, entries_per_process, barrier),
            )
            for i in range(process_count)
        ]
        try:
            for process in processes:
                process.start()
            barrier.wait(timeout=_SPAWN_TIMEOUT)
            for process in processes:
                process.join(timeout=_SPAWN_TIMEOUT)
            assert [process.exitcode for process in processes] == [0] * process_count
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                if process.pid is not None:
                    process.join(timeout=10)

        entries = WriteAheadOutbox(state_dir=tmp_path).load_all("ws-1")
        total = process_count * entries_per_process
        assert len(entries) == total
        assert len({entry["id"] for entry in entries}) == total
        assert {entry["client_write_id"] for entry in entries} == {f"ms:{i}" for i in range(total)}
        assert list(tmp_path.glob(".ws-1.*.tmp")) == []

    def test_spawn_writer_waits_and_proceeds_after_exception(self, tmp_path: Path) -> None:
        context = multiprocessing.get_context("spawn")
        ready, done = context.Event(), context.Event()
        process = context.Process(target=_spawn_waiting_writer, args=(tmp_path, ready, done))

        def fail_while_locked(path: Path) -> None:
            process.start()
            assert ready.wait(timeout=_SPAWN_TIMEOUT), "Child writer did not start"
            assert not done.wait(timeout=0.25), "Child wrote while the parent held the lock"
            raise ValueError("mutation failed")

        try:
            with pytest.raises(ValueError, match="mutation failed"):
                _with_lock(tmp_path / "ws-1.json", fail_while_locked)
            process.join(timeout=_SPAWN_TIMEOUT)
            assert process.exitcode == 0
            assert done.is_set()
        finally:
            if process.is_alive():
                process.terminate()
            if process.pid is not None:
                process.join(timeout=10)

        entries = WriteAheadOutbox(state_dir=tmp_path).load_all("ws-1")
        assert [entry["client_write_id"] for entry in entries] == ["ms:waiting"]

    def test_write_failure_preserves_data_and_releases_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "original"}, "ms:original")
        outbox.log_pending("ws-1", "memory_save", {"content": "keep"}, "ms:keep")
        with monkeypatch.context() as patch:
            patch.setattr(
                outbox_module, "_atomic_write_json", Mock(side_effect=OSError("disk full"))
            )
            with pytest.raises(OSError, match="disk full"):
                outbox.mark_success("ws-1", e1["id"])
        # 条目 e1 仍在：因为写入失败了。
        all_entries = outbox.load_all("ws-1")
        assert len(all_entries) == 2
        outbox.mark_success("ws-1", e1["id"])
        remaining = outbox.load_all("ws-1")
        assert len(remaining) == 1
        assert remaining[0]["client_write_id"] == "ms:keep"

    def test_concurrent_writes_no_data_loss(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        errors: list[Exception] = []

        def write_entries(start: int, count: int) -> None:
            try:
                for i in range(count):
                    outbox.log_pending(
                        "ws-1",
                        "memory_save",
                        {"content": f"msg-{start + i}"},
                        f"ms:{start + i}",
                    )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=write_entries, args=(0, 10)),
            threading.Thread(target=write_entries, args=(10, 10)),
            threading.Thread(target=write_entries, args=(20, 10)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        all_entries = outbox.load_all("ws-1")
        assert len(all_entries) == 30

    def test_concurrent_mark_operations(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entries = []
        for i in range(20):
            entries.append(
                outbox.log_pending("ws-1", "memory_save", {"content": f"m{i}"}, f"ms:{i}")
            )

        errors: list[Exception] = []

        def mark_success_batch(entry_ids: list[str]) -> None:
            try:
                for eid in entry_ids:
                    outbox.mark_success("ws-1", eid)
            except Exception as e:
                errors.append(e)

        first_half = [e["id"] for e in entries[:10]]
        second_half = [e["id"] for e in entries[10:]]

        t1 = threading.Thread(target=mark_success_batch, args=(first_half,))
        t2 = threading.Thread(target=mark_success_batch, args=(second_half,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == []
        assert outbox.load_all("ws-1") == []


class TestPurgeExhausted:
    def test_purges_old_exhausted_entries(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime, timedelta

        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "old"}, "ms:old")
        outbox.mark_failed("ws-1", e1["id"])
        outbox.mark_exhausted("ws-1", e1["id"])

        # 手动把 exhausted_at 时间戳改旧
        all_entries = outbox.load_all("ws-1")
        all_entries[0]["exhausted_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        from adapters.mcp.outbox import _atomic_write_json

        _atomic_write_json(tmp_path / "ws-1.json", all_entries)

        purged = outbox.purge_exhausted(ttl_seconds=7 * 24 * 3600)

        assert purged == 1
        assert outbox.load_all("ws-1") == []

    def test_keeps_recent_exhausted_entries(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "recent"}, "ms:recent")
        outbox.mark_failed("ws-1", e1["id"])
        outbox.mark_exhausted("ws-1", e1["id"])

        purged = outbox.purge_exhausted(ttl_seconds=7 * 24 * 3600)

        assert purged == 0
        assert len(outbox.load_all("ws-1")) == 1

    def test_keeps_non_exhausted_entries(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "pending"}, "ms:p")
        e2 = outbox.log_pending("ws-1", "memory_save", {"content": "failed"}, "ms:f")
        outbox.mark_failed("ws-1", e2["id"])

        purged = outbox.purge_exhausted(ttl_seconds=0)

        assert purged == 0
        assert len(outbox.load_all("ws-1")) == 2

    def test_purge_across_workspaces(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime, timedelta

        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "old1"}, "ms:o1")
        outbox.mark_failed("ws-1", e1["id"])
        outbox.mark_exhausted("ws-1", e1["id"])

        e2 = outbox.log_pending("ws-2", "memory_save", {"content": "old2"}, "ms:o2")
        outbox.mark_failed("ws-2", e2["id"])
        outbox.mark_exhausted("ws-2", e2["id"])

        # 两个都改旧
        for ws in ["ws-1", "ws-2"]:
            entries = outbox.load_all(ws)
            entries[0]["exhausted_at"] = (datetime.now(UTC) - timedelta(days=10)).isoformat()
            from adapters.mcp.outbox import _atomic_write_json

            _atomic_write_json(tmp_path / f"{ws}.json", entries)

        purged = outbox.purge_exhausted(ttl_seconds=7 * 24 * 3600)

        assert purged == 2
        assert outbox.load_all("ws-1") == []
        assert outbox.load_all("ws-2") == []


class TestCheckpoint:
    def test_record_and_get_checkpoint(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)

        assert outbox.get_last_checkpoint("session-1") is None

        outbox.record_checkpoint("session-1")
        result = outbox.get_last_checkpoint("session-1")

        assert result is not None
        assert isinstance(result, str)

    def test_checkpoint_update_overwrites(self, tmp_path: Path) -> None:
        import time

        outbox = WriteAheadOutbox(state_dir=tmp_path)

        outbox.record_checkpoint("session-1")
        first = outbox.get_last_checkpoint("session-1")

        time.sleep(0.01)
        outbox.record_checkpoint("session-1")
        second = outbox.get_last_checkpoint("session-1")

        assert second is not None
        assert first is not None
        assert second >= first

    def test_multiple_sessions_isolated(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)

        outbox.record_checkpoint("session-1")
        outbox.record_checkpoint("session-2")

        assert outbox.get_last_checkpoint("session-1") is not None
        assert outbox.get_last_checkpoint("session-2") is not None
        assert outbox.get_last_checkpoint("session-3") is None

    def test_workspace_watermarks_are_isolated_and_not_counted_as_writes(
        self, tmp_path: Path
    ) -> None:
        outbox = WriteAheadOutbox(tmp_path)
        outbox.record_checkpoint("session", "ws-a", "2026-01-01T00:00:00+00:00")
        outbox.record_checkpoint("session", "ws-b", "2026-01-02T00:00:00+00:00")
        outbox.record_checkpoint("legacy-session")
        assert outbox.get_last_checkpoint("session", "ws-a") == "2026-01-01T00:00:00+00:00"
        assert outbox.get_last_checkpoint("session", "ws-b") == "2026-01-02T00:00:00+00:00"
        assert outbox.get_last_checkpoint("legacy-session", "ws-a") is None
        assert outbox.load_all_workspaces() == {}
        assert outbox.load_retryable() == {}
        assert outbox.count_all_by_state() == {
            "pending": 0,
            "failed": 0,
            "exhausted": 0,
            "rejected": 0,
        }


def test_rejected_entry_survives_restart_and_only_manual_reset_makes_it_retryable(
    tmp_path: Path,
) -> None:
    outbox = WriteAheadOutbox(tmp_path)
    entry = outbox.log_pending("ws", "memory_save", {"content": "原始正文"}, "ms:body")
    outbox.mark_rejected("ws", entry["id"], "API error 422")
    restarted = WriteAheadOutbox(tmp_path)
    assert restarted.load_all("ws")[0]["arguments"] == entry["arguments"]
    assert restarted.load_all("ws")[0]["last_error"] == "API error 422"
    assert restarted.count_by_state("ws")["rejected"] == 1
    assert restarted.load_retryable() == {}
    restarted.reset_entry("ws", entry["id"])
    assert restarted.load_retryable()["ws"][0]["attempts"] == 0


def test_reset_all_exhausted_resets_for_startup_retry(tmp_path: Path) -> None:
    """启动时将 exhausted 条目重置为 failed 且 attempts=0。"""
    outbox = WriteAheadOutbox(tmp_path)
    e1 = outbox.log_pending("ws-a", "memory_save", {"content": "one"}, "ms:1")
    e2 = outbox.log_pending("ws-a", "memory_save", {"content": "two"}, "ms:2")
    e3 = outbox.log_pending("ws-b", "memory_save", {"content": "three"}, "ms:3")

    # 模拟 3 次失败尝试 → 进入 exhausted
    for _ in range(3):
        outbox.mark_failed("ws-a", e1["id"], "Connection failed")
        outbox.mark_failed("ws-a", e2["id"], "Connection failed")
        outbox.mark_failed("ws-b", e3["id"], "Connection failed")
    outbox.mark_exhausted("ws-a", e1["id"])
    outbox.mark_exhausted("ws-a", e2["id"])
    outbox.mark_exhausted("ws-b", e3["id"])

    assert outbox.count_by_state("ws-a")["exhausted"] == 2
    assert outbox.count_by_state("ws-b")["exhausted"] == 1
    assert outbox.load_retryable() == {}  # exhausted 不可重试

    # 启动重置
    reset_count = outbox.reset_all_exhausted()
    assert reset_count == 3

    # 全部重置为 failed 且 attempts=0
    retryable = outbox.load_retryable()
    assert len(retryable["ws-a"]) == 2
    assert len(retryable["ws-b"]) == 1
    for entries in retryable.values():
        for e in entries:
            assert e["state"] == "failed"
            assert e["attempts"] == 0
            assert "exhausted_at" not in e

    # 非 exhausted 条目不受影响
    outbox.mark_failed("ws-a", e1["id"], "timeout")
    outbox.reset_all_exhausted()  # e1 是 failed 而非 exhausted → 无变化
    assert outbox.count_by_state("ws-a")["failed"] >= 1


class TestLogPendingDedup:
    def test_duplicate_client_write_id_returns_existing(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "first"}, "ms:dup")
        e2 = outbox.log_pending("ws-1", "memory_save", {"content": "second"}, "ms:dup")
        assert e1["id"] == e2["id"]
        assert e2["arguments"] == {"content": "first"}
        assert len(outbox.load_all("ws-1")) == 1

    def test_different_client_write_ids_create_separate_entries(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        outbox.log_pending("ws-1", "memory_save", {"content": "b"}, "ms:b")
        assert len(outbox.load_all("ws-1")) == 2

    def test_dedup_across_workspaces_is_independent(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:same")
        e2 = outbox.log_pending("ws-2", "memory_save", {"content": "b"}, "ms:same")
        assert e1["id"] != e2["id"]
        assert len(outbox.load_all("ws-1")) == 1
        assert len(outbox.load_all("ws-2")) == 1


class TestMarkSuccessBatch:
    def test_removes_multiple_entries(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        e2 = outbox.log_pending("ws-1", "memory_save", {"content": "b"}, "ms:b")
        outbox.log_pending("ws-1", "memory_save", {"content": "c"}, "ms:c")

        removed = outbox.mark_success_batch("ws-1", [e1["id"], e2["id"]])
        assert removed == 2
        remaining = outbox.load_all("ws-1")
        assert len(remaining) == 1
        assert remaining[0]["client_write_id"] == "ms:c"

    def test_empty_id_list_is_noop(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        assert outbox.mark_success_batch("ws-1", []) == 0
        assert len(outbox.load_all("ws-1")) == 1

    def test_ignores_nonexistent_ids(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        removed = outbox.mark_success_batch("ws-1", ["nonexistent-id"])
        assert removed == 0
        assert len(outbox.load_all("ws-1")) == 1


class TestEmptyFileCleanup:
    def test_mark_success_deletes_empty_file(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        entry = outbox.log_pending("ws-1", "memory_save", {"content": "only"}, "ms:only")
        assert (tmp_path / "ws-1.json").exists()
        outbox.mark_success("ws-1", entry["id"])
        assert not (tmp_path / "ws-1.json").exists()

    def test_mark_success_batch_deletes_empty_file(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        outbox.mark_success_batch("ws-1", [e1["id"]])
        assert not (tmp_path / "ws-1.json").exists()

    def test_purge_exhausted_deletes_empty_file(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime, timedelta

        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "old"}, "ms:old")
        outbox.mark_failed("ws-1", e1["id"])
        outbox.mark_exhausted("ws-1", e1["id"])
        entries = outbox.load_all("ws-1")
        entries[0]["exhausted_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        _atomic_write_json(tmp_path / "ws-1.json", entries)

        purged = outbox.purge_exhausted(ttl_seconds=7 * 24 * 3600)
        assert purged == 1
        assert not (tmp_path / "ws-1.json").exists()

    def test_mark_success_keeps_file_when_entries_remain(self, tmp_path: Path) -> None:
        outbox = WriteAheadOutbox(state_dir=tmp_path)
        e1 = outbox.log_pending("ws-1", "memory_save", {"content": "a"}, "ms:a")
        outbox.log_pending("ws-1", "memory_save", {"content": "b"}, "ms:b")
        outbox.mark_success("ws-1", e1["id"])
        assert (tmp_path / "ws-1.json").exists()
        assert len(outbox.load_all("ws-1")) == 1


def test_corrupt_shard_is_quarantined_and_others_load(tmp_path: Path) -> None:
    """单个坏分片不应让 retry/drain 整体失败：隔离坏文件后继续读其它分片。"""
    outbox = WriteAheadOutbox(state_dir=tmp_path)
    outbox.log_pending("ws-good", "memory_save", {"content": "ok"}, "ms:good")
    bad_path = outbox._path("ws-bad")  # type: ignore[attr-defined]
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not valid json", encoding="utf-8")

    retryable = outbox.load_retryable()

    assert "ws-good" in retryable and len(retryable["ws-good"]) == 1
    assert not bad_path.exists()
    quarantined = list(tmp_path.rglob("*.corrupt-*"))
    assert quarantined and quarantined[0].read_text(encoding="utf-8") == "{not valid json"
