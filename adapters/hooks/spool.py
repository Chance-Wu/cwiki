"""Hook 捕获的本地 spool。

API 不可用时先落盘，SessionStart/SessionEnd/drain 再补投。按 host 分目录，
每个宿主会话一个 JSONL 文件；文件超过上限时轮转，避免无限增长。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 10 * 1024 * 1024
_SAFE_SESSION = re.compile(r"[^A-Za-z0-9._-]+")


def state_root() -> Path:
    root = Path(os.environ.get("CWIKI_HOOK_STATE_DIR", "~/.cwiki/state/hooks")).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def host_dir(host: str) -> Path:
    path = state_root() / host
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_session(session_id: str) -> str:
    cleaned = _SAFE_SESSION.sub("-", session_id).strip("-")
    return cleaned[:120] or "unknown"


def _lock(fh: Any) -> None:
    """尽力加排他锁（POSIX fcntl / Windows msvcrt），失败不阻塞写入。"""
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            # win32 下 fcntl 桩模块无这些属性；该分支只在 POSIX 运行
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
    except (ImportError, OSError):
        pass


def _unlock(fh: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
    except (ImportError, OSError):
        pass


def append(host: str, session_id: str, record: dict[str, Any]) -> Path:
    path = host_dir(host) / f"{_safe_session(session_id)}.jsonl"
    if path.exists() and path.stat().st_size >= MAX_FILE_BYTES:
        rotated = path.with_suffix(".1.jsonl")
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        _lock(fh)
        try:
            fh.write(line)
            fh.flush()
        finally:
            _unlock(fh)
    return path


def iter_files(host: str) -> list[Path]:
    directory = host_dir(host)
    return sorted(p for p in directory.iterdir() if p.suffix == ".jsonl" and p.is_file())


def load(host: str, limit: int = 200) -> list[tuple[Path, dict[str, Any]]]:
    """读取待投递记录；坏行跳过，不阻塞后续行。"""
    items: list[tuple[Path, dict[str, Any]]] = []
    for path in iter_files(host):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue
        for line in lines:
            if len(items) >= limit:
                return items
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                items.append((path, record))
    return items


def remove_delivered(host: str, delivered_ids: set[str]) -> None:
    """从 spool 中删除已成功投递的 record_id；保留未投递/坏行。

    加锁后原地重写，避免与并发 append（SessionEnd 的 session-end 与 drain
    同时触发）交错导致丢记录。
    """
    if not delivered_ids:
        return
    for path in iter_files(host):
        kept: list[str] | None = None
        try:
            with open(path, "r+", encoding="utf-8") as fh:
                _lock(fh)
                try:
                    lines = fh.read().splitlines()
                    kept = []
                    for line in lines:
                        try:
                            record = json.loads(line)
                        except ValueError:
                            kept.append(line)
                            continue
                        if isinstance(record, dict) and record.get("record_id") in delivered_ids:
                            continue
                        kept.append(line)
                    fh.seek(0)
                    fh.truncate()
                    if kept:
                        fh.write("\n".join(kept) + "\n")
                        fh.flush()
                finally:
                    _unlock(fh)
        except (OSError, ValueError):
            continue
        if kept is not None and not kept:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
