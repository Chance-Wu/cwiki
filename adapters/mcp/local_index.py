"""本地优先的只读检索（SQLite + 进程内 BM25）。

MCP 进程与 hook 进程直接以 ``mode=ro`` 打开 ``cwiki-data/cwiki.db``，
不依赖 HTTP API。索引按 DB/WAL 的 mtime 与行数指纹做进程内缓存，
写入提交后下一次查询自动重建；只读连接不会阻塞 API 的 WAL 写入。

MCP 先用本模块：覆盖率 ≥ ``STRONG_COVERAGE`` 直接返回，弱命中再请求
API 做语义补充；API 不可用时回落本模块。只有关键词检索，没有向量语义、
RRF 融合与重排。
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from packages.domain.config import CONFIG_PATH, settings
from packages.retrieval.bm25 import BM25Index

logger = logging.getLogger("cwiki.mcp.local_index")

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
# 只读查询最多等待 1s，与 hook 的 3s 超时预算留出余量
BUSY_TIMEOUT_MS = 1000
# 查询词命中覆盖率下限：长 prompt 用 BM25 时，无关记忆也可能拿到最高原始分。
# 实测相关命中覆盖率 ≥0.77、无关命中 ≤0.53，取 0.5 偏精度（降级路径宁可少召回）。
MIN_COVERAGE = 0.5
# 本地结果达到该覆盖率即视为「强命中」，MCP 可直接返回、不再请求 API
STRONG_COVERAGE = 0.6

_ASCII_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")


class _FastBM25(BM25Index):
    """hook 场景的轻量分词：不加载 jieba（首次加载 0.8–1.6s，会超 hook 超时）。

    ASCII 按整词、CJK 按单字 + 二元组切分；召回略低于 jieba，但延迟稳定。
    """

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        lowered = text.lower()
        tokens = _ASCII_RE.findall(lowered)
        for span in _CJK_RE.findall(lowered):
            if len(span) == 1:
                tokens.append(span)
            else:
                # 只用二元组：单字会把「今天天气不错」这类无关文本匹配到大部分记忆
                tokens.extend(span[i : i + 2] for i in range(len(span) - 1))
        return tokens


@dataclass(frozen=True)
class _Snapshot:
    """一次 DB 指纹对应的内存索引快照。"""

    fingerprint: tuple[int, int, int, str | None]
    rows: dict[str, dict[str, Any]]
    index: BM25Index
    tokens: dict[str, set[str]]
    df: dict[str, int]


_cache: dict[str, _Snapshot] = {}
_lock = threading.Lock()


def _resolve_db_path(db_path: str | Path | None = None) -> Path | None:
    """解析只读 DB 路径：显式参数 > CWIKI_DB_PATH > config.yaml database.url。"""
    raw: str | Path | None = db_path or os.environ.get("CWIKI_DB_PATH")
    if raw:
        path = Path(raw)
    else:
        url = settings.database_url
        if not url.startswith("sqlite"):
            return None
        _, _, tail = url.partition(":///")
        if not tail:
            return None
        path = Path(tail)
        if not path.is_absolute():
            # 相对路径以 config.yaml 所在的项目根为基准，避免受进程 cwd 影响
            path = CONFIG_PATH.parent / path
    path = path.expanduser()
    return path if path.is_file() else None


def _connect(path: Path) -> sqlite3.Connection | None:
    """打开只读连接；任何失败都返回 None（调用方回落）。"""
    uri = f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error:
        return None


def _fingerprint(path: Path, conn: sqlite3.Connection) -> tuple[int, int, int, str | None] | None:
    try:
        db_mtime = path.stat().st_mtime_ns
        wal = path.with_name(path.name + "-wal")
        wal_mtime = wal.stat().st_mtime_ns if wal.exists() else 0
    except OSError:
        return None
    try:
        row = conn.execute("SELECT COUNT(*), MAX(updated_at) FROM memory").fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    updated = None if row[1] is None else str(row[1])
    return (db_mtime, wal_mtime, int(row[0] or 0), updated)


def _parse_tags(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(tag) for tag in raw]
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return []
        if isinstance(parsed, list):
            return [str(tag) for tag in parsed]
    return []


def _load_rows(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT m.id, m.workspace_id, w.name AS workspace, m.title, m.content,
               m.type, m.tags, m.version, m.confidence, m.importance,
               m.valid_to, m.usage_count, m.is_permanent
        FROM memory m
        JOIN workspace w ON w.id = m.workspace_id
        WHERE m.status = 'active'
        """
    )
    rows: dict[str, dict[str, Any]] = {}
    for row in cursor.fetchall():
        rows[str(row[0])] = {
            "id": str(row[0]),
            "workspace_id": str(row[1]),
            "workspace": str(row[2]),
            "title": str(row[3] or ""),
            "content": str(row[4] or ""),
            "type": str(row[5] or "fact"),
            "tags": _parse_tags(row[6]),
            "version": int(row[7] or 1),
            "confidence": float(row[8] or 0.0),
            "importance": float(row[9] or 0.0),
            "valid_to": None if row[10] is None else str(row[10]),
            "usage_count": int(row[11] or 0),
            "is_permanent": bool(row[12]),
        }
    return rows


def _build_snapshot(
    path: Path, conn: sqlite3.Connection, fingerprint: tuple[Any, ...]
) -> _Snapshot:
    rows = _load_rows(conn)
    index = _FastBM25()
    tokens: dict[str, set[str]] = {}
    df: dict[str, int] = {}
    for memory_id, row in rows.items():
        # 分词只做一次：同一份 token 既喂给 BM25，也用于覆盖率集合
        title_tokens = _FastBM25._tokenize(row["title"])
        content_tokens = _FastBM25._tokenize(row["content"])
        index.add(
            memory_id,
            row["content"],
            row["title"],
            tokens=content_tokens,
            title_tokens=title_tokens,
        )
        doc_tokens = set(title_tokens) | set(content_tokens)
        tokens[memory_id] = doc_tokens
        for token in doc_tokens:
            df[token] = df.get(token, 0) + 1
    return _Snapshot(
        fingerprint=fingerprint,
        rows=rows,
        index=index,
        tokens=tokens,
        df=df,
    )


def _snapshot(path: Path) -> _Snapshot | None:
    """取索引快照；DB/WAL 变化时重建。"""
    conn = _connect(path)
    if conn is None:
        return None
    try:
        fingerprint = _fingerprint(path, conn)
        if fingerprint is None:
            return None
        with _lock:
            cached = _cache.get(str(path))
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
        snapshot = _build_snapshot(path, conn, fingerprint)
        with _lock:
            _cache[str(path)] = snapshot
        return snapshot
    except sqlite3.Error:
        # 读不到（被锁/正在迁移）时静默回落，不向 hook stderr 输出
        return None
    finally:
        conn.close()


def reset_cache() -> None:
    """测试或维护用：清空进程内索引缓存。"""
    with _lock:
        _cache.clear()


def _is_stale(valid_to: str | None) -> bool:
    if not valid_to:
        return False
    try:
        parsed = datetime.fromisoformat(valid_to)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return datetime.now(UTC) > parsed


def _resolve_workspace(snapshot: _Snapshot, workspace: str) -> str | None:
    """workspace 名称或 UUID → workspace_id；未知返回 None。"""
    if any(row["workspace_id"] == workspace for row in snapshot.rows.values()):
        return workspace
    for row in snapshot.rows.values():
        if row["workspace"] == workspace:
            return str(row["workspace_id"])
    return None


def _query_coverage(
    query_tokens: set[str],
    row_tokens: set[str],
    df: dict[str, int],
    total_docs: int,
) -> float:
    """IDF 加权覆盖率：只命中常见字的条目得分低，避免长 prompt 误召回。"""
    total_weight = 0.0
    matched_weight = 0.0
    for token in query_tokens:
        doc_freq = df.get(token, 0)
        if doc_freq == 0:
            continue
        weight = math.log(1.0 + total_docs / doc_freq)
        total_weight += weight
        if token in row_tokens:
            matched_weight += weight
    if total_weight == 0:
        return 0.0
    return matched_weight / total_weight


def search_local(
    keyword: str,
    *,
    workspace: str | None = None,
    limit: int = DEFAULT_LIMIT,
    memory_type: str | None = None,
    min_confidence: float | None = None,
    tags: list[str] | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """只读关键词检索，返回结构与 ``/v1/search`` 对齐。

    ``score`` 按本次结果集的最高原始 BM25 分归一化到 0–1，
    使 hook 的 MIN_SCORE 阈值在降级模式下仍可用；覆盖率低于
    ``MIN_COVERAGE`` 的条目视为不相关并丢弃。
    """
    keyword = (keyword or "").strip()
    base: dict[str, Any] = {
        "keyword": keyword,
        "results": [],
        "total": 0,
        "insufficient": True,
        "source": "local",
    }
    if not keyword:
        return {**base, "available": True, "reason": "empty_keyword"}

    path = _resolve_db_path(db_path)
    if path is None:
        return {**base, "available": False, "reason": "database_not_found"}
    snapshot = _snapshot(path)
    if snapshot is None:
        return {**base, "available": False, "reason": "database_unavailable"}

    workspace_id: str | None = None
    if workspace:
        workspace_id = _resolve_workspace(snapshot, workspace)
        if workspace_id is None:
            return {**base, "available": True, "reason": "unknown_workspace"}

    raw_matches = snapshot.index.search(keyword, top_k=max(len(snapshot.rows), 1))
    if not raw_matches:
        return {**base, "available": True, "reason": "no_match"}

    query_tokens = set(_FastBM25._tokenize(keyword))
    total_docs = len(snapshot.rows)
    # 「罕见词」门槛：至少命中一个低文档频率词，避免只靠常用词进入结果
    distinctive_df = max(2, int(total_docs * 0.1))
    wanted_tags = set(tags or ())
    filtered: list[tuple[dict[str, Any], float, float]] = []
    for memory_id, raw_score in raw_matches:
        row = snapshot.rows.get(memory_id)
        if row is None:
            continue
        if workspace_id is not None and row["workspace_id"] != workspace_id:
            continue
        if memory_type is not None and row["type"] != memory_type:
            continue
        if min_confidence is not None and row["confidence"] < min_confidence:
            continue
        if wanted_tags and not wanted_tags.issubset(set(row["tags"])):
            continue
        row_tokens = snapshot.tokens.get(memory_id, set())
        matched = query_tokens & row_tokens
        if not any(snapshot.df.get(token, total_docs + 1) <= distinctive_df for token in matched):
            continue
        coverage = _query_coverage(query_tokens, row_tokens, snapshot.df, total_docs)
        if coverage < MIN_COVERAGE:
            continue
        filtered.append((row, raw_score, coverage))

    if not filtered:
        return {**base, "available": True, "reason": "no_relevant_match"}

    max_score = max(score for _, score, _coverage in filtered) or 1.0
    capped_limit = min(max(limit, 1), MAX_LIMIT)
    results = []
    for row, raw_score, coverage in filtered[:capped_limit]:
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "type": row["type"],
                "tags": row["tags"],
                "version": row["version"],
                "score": round(raw_score / max_score, 4),
                "coverage": round(coverage, 4),
                "confidence": row["confidence"],
                "valid_to": row["valid_to"],
                "is_stale": _is_stale(row["valid_to"]),
            }
        )
    return {
        **base,
        "available": True,
        "results": results,
        "total": len(filtered),
        "insufficient": False,
    }


def head(
    workspace: str | None = None,
    *,
    types: tuple[str, ...] | list[str] = ("feedback", "rule"),
    tags: tuple[str, ...] | list[str] = (),
    include_permanent: bool = True,
    max_items: int = 8,
    max_chars: int = 1200,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """常驻知识头：永久记忆 + 指定类型/标签，按预算压缩后供 SessionStart 注入。

    与检索不同，这里不需要查询词：稳定、跨会话有效的偏好和规则优先。
    """
    base: dict[str, Any] = {"available": False, "items": [], "text": "", "total": 0}
    path = _resolve_db_path(db_path)
    if path is None:
        return {**base, "reason": "database_not_found"}
    snapshot = _snapshot(path)
    if snapshot is None:
        return {**base, "reason": "database_unavailable"}

    workspace_id: str | None = None
    if workspace:
        workspace_id = _resolve_workspace(snapshot, workspace)
        if workspace_id is None:
            return {**base, "available": True, "reason": "unknown_workspace"}

    wanted_types = {item.casefold() for item in types}
    wanted_tags = {item.casefold() for item in tags}
    selected: list[dict[str, Any]] = []
    for row in snapshot.rows.values():
        if workspace_id is not None and row["workspace_id"] != workspace_id:
            continue
        pinned = include_permanent and row["is_permanent"]
        type_match = row["type"].casefold() in wanted_types
        tag_match = bool(wanted_tags.intersection({tag.casefold() for tag in row["tags"]}))
        if pinned or type_match or tag_match:
            selected.append(row)

    selected.sort(
        key=lambda row: (row["is_permanent"], row["importance"], row["usage_count"]),
        reverse=True,
    )

    budget = max(200, max_chars)
    blocks: list[str] = []
    items: list[dict[str, Any]] = []
    used = 0
    for row in selected[: max(1, max_items)]:
        block = f"## {row['title']}\n{row['content']}\n"
        truncated = False
        if used + len(block) > budget:
            remaining = budget - used
            if remaining <= 80:
                break
            block = block[:remaining]
            truncated = True
        blocks.append(block)
        used += len(block)
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "type": row["type"],
                "is_permanent": row["is_permanent"],
                "truncated": truncated,
            }
        )
        if truncated:
            break

    return {
        "available": True,
        "items": items,
        "text": "\n".join(blocks).strip(),
        "total": len(selected),
    }


def build_local_context(
    *,
    workspace: str,
    query: str,
    max_items: int = DEFAULT_LIMIT,
    max_tokens: int = 5000,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """``curated=true`` 的降级组装：关键词命中的标题 + 正文，按字符预算截断。"""
    data = search_local(
        query,
        workspace=workspace,
        limit=max_items,
        db_path=db_path,
    )
    if not data.get("available"):
        return {
            "available": False,
            "context": "",
            "items": [],
            "total": 0,
            "source": "local",
            "error": "local database unavailable",
        }

    # 粗略换算：中文约 1 token/字符，英文约 1 token/4 字符；取中间值 2
    budget = max(200, max_tokens * 2)
    parts: list[str] = []
    items: list[dict[str, Any]] = []
    used = 0
    for row in data["results"]:
        block = f"## {row['title']}\n\n{row['content']}\n"
        truncated = False
        if used + len(block) > budget:
            remaining = budget - used
            if remaining <= 80:
                break
            block = block[:remaining]
            truncated = True
        parts.append(block)
        used += len(block)
        items.append(
            {
                "memory_id": row["id"],
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "type": row["type"],
                "version": row["version"],
                "score": row["score"],
                "source": "memory",
                "metadata": {
                    "local": True,
                    "truncated": truncated,
                    "coverage": row.get("coverage"),
                },
            }
        )
        if truncated:
            break
    return {
        "available": True,
        "context": "\n".join(parts),
        "items": items,
        "total": len(items),
        "source": "local",
    }


def local_available(db_path: str | Path | None = None) -> bool:
    """DB 可只读打开且能读到 memory 表。"""
    path = _resolve_db_path(db_path)
    if path is None:
        return False
    conn = _connect(path)
    if conn is None:
        return False
    try:
        conn.execute("SELECT 1 FROM memory LIMIT 1")
        return True
    except sqlite3.Error:
        return False
    finally:
        conn.close()
