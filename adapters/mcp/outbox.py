"""崩溃安全的记忆提交 WAL outbox。

条目在 HTTP 调用前先落盘，成功后才删除；进程若在提交中途崩溃，
条目仍保留供重试，并借助 client_write_id 幂等去重。

文件按 workspace_id 分片以隔离并发会话；所有写入都是原子的
（临时文件 + os.replace），并受文件锁保护。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TypeVar

_IS_WINDOWS = os.name == "nt"
if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl

_CHECKPOINT_FILE = "checkpoints.json"
_DEFAULT_PURGE_TTL = 7 * 24 * 3600
# msvcrt 的 LK_LOCK 内部只重试约 10s；高 CPU 负载下可能持锁者仍存活而预算耗尽，
# 因此在应用层再套一层重试。
_LOCK_ACQUIRE_TIMEOUT = 60.0
_LOCK_RETRY_DELAY = 0.25
# Windows 上的过滤驱动（杀软/加密）可能瞬时占用文件，os.replace 需短暂重试。
_REPLACE_RETRIES = 4
_REPLACE_RETRY_DELAY = 0.1

_T = TypeVar("_T")


def _default_state_dir() -> Path:
    return Path.home() / ".cwiki" / "state" / "outbox"


def _outbox_path(state_dir: Path, workspace_id: str) -> Path:
    # workspace_id 可能含路径分隔符，替换为下划线以防目录穿越
    safe_name = workspace_id.replace("/", "_").replace("\\", "_")
    return state_dir / f"{safe_name}.json"


def _replace_with_retry(src: str, dst: Path) -> None:
    """os.replace 替换临时文件；对瞬时 PermissionError 短暂重试。"""
    for attempt in range(_REPLACE_RETRIES + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt >= _REPLACE_RETRIES:
                raise
            time.sleep(_REPLACE_RETRY_DELAY)


def _atomic_write_json(path: Path, data: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.stem}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        _replace_with_retry(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return []


def _acquire_windows_lock(lf: BinaryIO) -> None:
    """获取单字节锁，突破 msvcrt 约 10s 的 LK_LOCK 内部预算。

    高 CPU 负载下 LK_LOCK 可能在持锁者仍存活时耗尽内部重试并抛
    PermissionError (EACCES)；在应用层按总期限持续重试。
    """
    deadline = time.monotonic() + _LOCK_ACQUIRE_TIMEOUT
    while True:
        lf.seek(0)
        try:
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_LOCK_RETRY_DELAY)


def _with_lock(path: Path, fn: Callable[[Path], _T]) -> _T:
    """持有排他文件锁执行 fn。

    按需创建父目录与锁文件，保证首次写入也能拿到锁。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+b") as lf:
        if _IS_WINDOWS:
            _acquire_windows_lock(lf)
        else:
            # POSIX 分支；win32 下 mypy 将 fcntl 解析为无属性的桩模块，需忽略类型
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            # Windows 允许锁定 EOF 之后的区域；拿到锁后再初始化锁字节，避免竞态
            if _IS_WINDOWS and os.fstat(lf.fileno()).st_size == 0:
                lf.write(b"\0")
                lf.flush()
            return fn(path)
        finally:
            if _IS_WINDOWS:
                lf.seek(0)
                msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


class WriteAheadOutbox:
    """按工作区分片的 WAL outbox：原子文件 I/O + 文件锁。"""

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state_dir = state_dir or _default_state_dir()

    def _path(self, workspace_id: str) -> Path:
        return _outbox_path(self._state_dir, workspace_id)

    def _iter_workspace_files(self) -> list[Path]:
        """返回全部工作区 JSON 文件，排除 checkpoint 文件。"""
        if not self._state_dir.exists():
            return []
        return [p for p in self._state_dir.glob("*.json") if p.name != _CHECKPOINT_FILE]

    def _checkpoint_path(self) -> Path:
        return self._state_dir / _CHECKPOINT_FILE

    def _locked_rmw(self, path: Path, mutate: Callable[[list[dict[str, Any]]], Any]) -> Any:
        """加锁的读-改-写：加载条目、执行 mutate(entries)、保存。

        mutate 收到条目列表（可原位修改），其返回值透传给调用方。
        """

        def _do(p: Path) -> Any:
            entries = _load_json(p)
            result = mutate(entries)
            _atomic_write_json(p, entries)
            return result

        return _with_lock(path, _do)

    def _write_or_remove(self, path: Path, entries: list[dict[str, Any]]) -> None:
        """原子写入条目；列表为空时删除文件，避免残留空分片。"""
        if entries:
            _atomic_write_json(path, entries)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def log_pending(
        self,
        workspace_id: str,
        tool: str,
        arguments: dict[str, Any],
        client_write_id: str,
    ) -> dict[str, Any]:
        entry = {
            "id": str(uuid.uuid4()),
            "workspace_id": workspace_id,
            "client_write_id": client_write_id,
            "tool": tool,
            "arguments": arguments,
            "state": "pending",
            "attempts": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }

        existing: dict[str, Any] | None = None

        def _mutate(entries: list[dict[str, Any]]) -> None:
            nonlocal existing
            # 幂等：相同 client_write_id 的条目已存在则跳过写入，返回既有条目
            for e in entries:
                if e.get("client_write_id") == client_write_id:
                    existing = dict(e)
                    return
            entries.append(entry)

        self._locked_rmw(self._path(workspace_id), _mutate)
        return existing if existing is not None else entry

    def update_entry(
        self,
        workspace_id: str,
        entry_id: str,
        updates: dict[str, Any],
    ) -> None:
        """合并更新到既有条目字段（如冻结补全后的参数）。"""

        def _mutate(entries: list[dict[str, Any]]) -> None:
            for e in entries:
                if e.get("id") == entry_id:
                    e.update(updates)
                    break

        self._locked_rmw(self._path(workspace_id), _mutate)

    def mark_success(self, workspace_id: str, entry_id: str) -> None:
        path = self._path(workspace_id)

        def _do(p: Path) -> None:
            entries = _load_json(p)
            kept = [e for e in entries if e.get("id") != entry_id]
            self._write_or_remove(p, kept)

        _with_lock(path, _do)

    def mark_success_batch(self, workspace_id: str, entry_ids: list[str]) -> int:
        """单次加锁批量删除多条目，返回实际删除数。"""
        if not entry_ids:
            return 0
        path = self._path(workspace_id)
        id_set = set(entry_ids)
        removed = 0

        def _do(p: Path) -> None:
            nonlocal removed
            entries = _load_json(p)
            kept = []
            for e in entries:
                if e.get("id") in id_set:
                    removed += 1
                else:
                    kept.append(e)
            self._write_or_remove(p, kept)

        _with_lock(path, _do)
        return removed

    def mark_failed(self, workspace_id: str, entry_id: str, reason: str | None = None) -> None:
        self._mark_entry_error(workspace_id, entry_id, "failed", reason)

    def mark_rejected(self, workspace_id: str, entry_id: str, reason: str) -> None:
        """保留原始载荷供人工恢复；reason 必须由调用方脱敏。"""
        self._mark_entry_error(workspace_id, entry_id, "rejected", reason)

    def _mark_entry_error(
        self, workspace_id: str, entry_id: str, state: str, reason: str | None
    ) -> None:
        """把条目置为错误状态并累计尝试次数。"""

        def _mutate(entries: list[dict[str, Any]]) -> None:
            for e in entries:
                if e.get("id") == entry_id:
                    e["state"] = state
                    e["attempts"] = e.get("attempts", 0) + 1
                    e["last_error_at"] = datetime.now(UTC).isoformat()
                    if reason is not None:
                        e["last_error"] = reason
                    break

        self._locked_rmw(self._path(workspace_id), _mutate)

    def mark_exhausted(self, workspace_id: str, entry_id: str) -> None:
        """标记条目为 exhausted（重试耗尽），保留以便人工排查。"""

        def _mutate(entries: list[dict[str, Any]]) -> None:
            for e in entries:
                if e.get("id") == entry_id:
                    e["state"] = "exhausted"
                    e["exhausted_at"] = datetime.now(UTC).isoformat()
                    break

        self._locked_rmw(self._path(workspace_id), _mutate)

    def reset_entry(self, workspace_id: str, entry_id: str) -> None:
        """把 exhausted 条目重置回 failed 状态以便重试。"""

        def _mutate(entries: list[dict[str, Any]]) -> None:
            for e in entries:
                if e.get("id") == entry_id:
                    e["state"] = "failed"
                    e["attempts"] = 0
                    break

        self._locked_rmw(self._path(workspace_id), _mutate)

    def load_pending(self, workspace_id: str) -> list[dict[str, Any]]:
        def _do(p: Path) -> list[dict[str, Any]]:
            return [e for e in _load_json(p) if e.get("state") == "pending"]

        return _with_lock(self._path(workspace_id), _do)

    def load_all(self, workspace_id: str) -> list[dict[str, Any]]:
        def _do(p: Path) -> list[dict[str, Any]]:
            return _load_json(p)

        return _with_lock(self._path(workspace_id), _do)

    def load_all_workspaces(self) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for path in self._iter_workspace_files():

            def _do(p: Path) -> list[dict[str, Any]]:
                return _load_json(p)

            entries = _with_lock(path, _do)
            for entry in entries:
                ws_id = entry.get("workspace_id", "")
                if ws_id:
                    result.setdefault(ws_id, []).append(entry)
        return result

    def reset_all_exhausted(self) -> int:
        """把全部 exhausted 条目重置回 failed 且 attempts=0。

        启动时调用：上一会话重试耗尽的条目，在服务恢复可达后获得新一轮
        重试机会。每个工作区文件只加一次锁。
        """
        count = 0
        for path in self._iter_workspace_files():

            def _mutate(entries: list[dict[str, Any]]) -> None:
                nonlocal count
                for e in entries:
                    if e.get("state") == "exhausted":
                        e["state"] = "failed"
                        e["attempts"] = 0
                        e.pop("exhausted_at", None)
                        count += 1

            self._locked_rmw(path, _mutate)
        return count

    def load_retryable(self) -> dict[str, list[dict[str, Any]]]:
        """跨工作区加载全部 pending/failed 条目（供启动清账）。"""
        result: dict[str, list[dict[str, Any]]] = {}
        for path in self._iter_workspace_files():

            def _do(p: Path) -> list[dict[str, Any]]:
                return [e for e in _load_json(p) if e.get("state") in ("pending", "failed")]

            entries = _with_lock(path, _do)
            for entry in entries:
                ws_id = entry.get("workspace_id", "")
                if ws_id:
                    result.setdefault(ws_id, []).append(entry)
        return result

    def count_by_state(self, workspace_id: str) -> dict[str, int]:
        """返回工作区各状态条目的计数。"""

        def _do(p: Path) -> dict[str, int]:
            counts: dict[str, int] = {"pending": 0, "failed": 0, "exhausted": 0, "rejected": 0}
            for e in _load_json(p):
                state = e.get("state", "pending")
                if state in counts:
                    counts[state] += 1
            return counts

        return _with_lock(self._path(workspace_id), _do)

    def count_all_by_state(self) -> dict[str, int]:
        """返回全部工作区按状态聚合的计数。"""
        totals: dict[str, int] = {"pending": 0, "failed": 0, "exhausted": 0, "rejected": 0}
        for path in self._iter_workspace_files():

            def _do(p: Path) -> list[dict[str, Any]]:
                return _load_json(p)

            entries = _with_lock(path, _do)
            for e in entries:
                state = e.get("state", "pending")
                if state in totals:
                    totals[state] += 1
        return totals

    def remove_entry(self, workspace_id: str, entry_id: str) -> None:
        self.mark_success(workspace_id, entry_id)

    def purge_exhausted(self, ttl_seconds: float = _DEFAULT_PURGE_TTL) -> int:
        """删除超过 TTL 的 exhausted 条目，返回清理数量。"""
        cutoff = datetime.now(UTC).timestamp() - ttl_seconds
        total_purged = 0

        for path in self._iter_workspace_files():

            def _do(p: Path) -> int:
                entries = _load_json(p)
                original_count = len(entries)
                kept = []
                for e in entries:
                    if e.get("state") != "exhausted":
                        kept.append(e)
                        continue
                    exhausted_at = e.get("exhausted_at")
                    if not exhausted_at:
                        kept.append(e)
                        continue
                    try:
                        ts = datetime.fromisoformat(exhausted_at).timestamp()
                        if ts >= cutoff:
                            kept.append(e)
                    except ValueError:
                        kept.append(e)
                if len(kept) < original_count:
                    self._write_or_remove(p, kept)
                return original_count - len(kept)

            purged = _with_lock(path, _do)
            total_purged += purged

        return total_purged

    def record_checkpoint(
        self,
        session_id: str,
        workspace_id: str = "",
        checkpoint_at: str | None = None,
        event_session_id: str | None = None,
    ) -> None:
        """记录采集起始水位，按 session 与 workspace 隔离。"""
        checkpoint_path = self._checkpoint_path()

        def _do(p: Path) -> None:
            checkpoints = _load_json(p)
            checkpoint_map = {(c["session_id"], c.get("workspace_id", "")): c for c in checkpoints}
            entry = {
                "session_id": session_id,
                "workspace_id": workspace_id,
                "checkpoint_at": checkpoint_at or datetime.now(UTC).isoformat(),
            }
            if event_session_id is not None:
                entry["event_session_id"] = event_session_id
            checkpoint_map[(session_id, workspace_id)] = entry
            _atomic_write_json(p, list(checkpoint_map.values()))

        _with_lock(checkpoint_path, _do)

    def get_last_checkpoint(
        self, session_id: str, workspace_id: str = "", event_session_id: str | None = None
    ) -> str | None:
        """读取最近检查点水位；旧的无作用域水位不得跨工作区跳过事件。"""
        checkpoint_path = self._checkpoint_path()

        def _do(p: Path) -> str | None:
            for c in _load_json(p):
                if c.get("session_id") == session_id and c.get("workspace_id", "") == workspace_id:
                    if event_session_id is not None:
                        stored = c.get("event_session_id")
                        # 仅匹配相同 event_session_id，或无该字段的旧条目
                        if stored is not None and stored != event_session_id:
                            continue
                    return c.get("checkpoint_at")
            return None

        return _with_lock(checkpoint_path, _do)
