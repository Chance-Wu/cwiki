#!/usr/bin/env python3
"""三层存储一致性巡检（DB / Markdown / _meta + 派生索引），只读为主。

用法：
    python scripts/check_integrity.py            # 人读报告，有异常退出 1
    python scripts/check_integrity.py --json     # JSON 输出
    python scripts/check_integrity.py --fix      # 仅做安全修复：补齐 _workspaces.json 缺失工作区
    python scripts/check_integrity.py --fix-meta # 从 DB 正向补导出缺失的 _meta 快照
    python scripts/check_integrity.py --prune-meta # 删除 DB 已无对应行的孤儿 _meta 快照

除 --prune-meta 外不删除任何用户数据；不一致项只报告并给出建议命令。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2)


def _parse_tags(raw: Any) -> list[str]:
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


def _db_state(db_path: Path) -> dict[str, Any]:
    con = _sqlite_ro(db_path)
    try:
        ids = {
            str(row[0]): str(row[1])
            for row in con.execute("select id, status from memory").fetchall()
        }
        active_ids = {mid for mid, status in ids.items() if status == "active"}
        workspaces = [
            {"id": str(row[0]), "name": str(row[1])}
            for row in con.execute("select id, name from workspace").fetchall()
        ]
        embedded_active = {
            str(row[0])
            for row in con.execute(
                "select id from memory where status='active' and embedding is not null"
            ).fetchall()
        }
        # 内容漂移需要完整行；老库/最小测试库缺列时退化为仅 id/status
        try:
            rows = {
                str(row[0]): {
                    "status": str(row[1]),
                    "title": str(row[2] or ""),
                    "content": str(row[3] or ""),
                    "type": str(row[4] or "fact"),
                    "tags": _parse_tags(row[5]),
                    "updated_at": None if row[6] is None else str(row[6]),
                }
                for row in con.execute(
                    "select id, status, title, content, type, tags, updated_at from memory"
                ).fetchall()
            }
        except sqlite3.Error:
            rows = {}
    finally:
        con.close()
    return {
        "ids": ids,
        "active_ids": active_ids,
        "workspaces": workspaces,
        "embedded_active": embedded_active,
        "rows": rows,
    }


def _md_entries(
    memory_dir: Path,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, str], list[str]]:
    """解析 Markdown 的 frontmatter 与正文。

    返回 (id→相对路径, id→字段, id→绝对路径, 无法解析的相对路径)。
    """
    ids: dict[str, str] = {}
    entries: dict[str, dict[str, Any]] = {}
    paths: dict[str, str] = {}
    bad: list[str] = []
    for path in memory_dir.rglob("*.md"):
        rel = path.relative_to(memory_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            bad.append(rel)
            continue
        if not text.startswith("---"):
            bad.append(rel)
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            bad.append(rel)
            continue
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            bad.append(rel)
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            bad.append(rel)
            continue
        memory_id = str(meta["id"])
        ids[memory_id] = rel
        paths[memory_id] = str(path)
        entries[memory_id] = {
            "title": str(meta.get("title") or ""),
            "content": parts[2].strip(),
            "type": str(meta.get("type") or "fact"),
            "tags": meta.get("tags") if isinstance(meta.get("tags"), list) else [],
            "status": str(meta.get("status") or "active"),
        }
    return ids, entries, paths, bad


def _meta_health(meta_dir: Path) -> tuple[set[str], list[str]]:
    """返回 (可解析的 _meta id 集, 损坏文件名)。"""
    if not meta_dir.is_dir():
        return set(), []
    ids: set[str] = set()
    bad: list[str] = []
    for path in sorted(meta_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            bad.append(path.stem)
            continue
        if not isinstance(data, dict):
            bad.append(path.stem)
            continue
        ids.add(path.stem)
    return ids, bad


def _index_ids(index_db: Path) -> set[str]:
    if not index_db.is_file():
        return set()
    con = _sqlite_ro(index_db)
    try:
        return {str(row[0]) for row in con.execute("select id from memory_index").fetchall()}
    except sqlite3.Error:
        return set()
    finally:
        con.close()


def _vector_ids(vectors_json: Path) -> set[str]:
    if not vectors_json.is_file():
        return set()
    try:
        data = json.loads(vectors_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    ids = data.get("ids") if isinstance(data, dict) else None
    return {str(item) for item in ids} if isinstance(ids, list) else set()


def _workspaces_meta(meta_dir: Path) -> list[dict[str, Any]]:
    path = meta_dir / "_workspaces.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _port_diagnosis(port: int) -> dict[str, Any]:
    """端口监听但健康检查失败时给出清理指引（不自动杀进程）。"""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    listening = sock.connect_ex(("127.0.0.1", port)) == 0
    sock.close()
    if not listening:
        return {"listening": False, "healthy": None}

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/v1/health", timeout=2) as resp:
            healthy = resp.status == 200
    except (urllib.error.URLError, OSError):
        healthy = False
    result: dict[str, Any] = {"listening": True, "healthy": healthy}
    if not healthy:
        result["hint"] = (
            f"端口 {port} 在监听但 /v1/health 不通（常见为计划任务残留的孤儿 uvicorn）。"
            f"查找 PID：netstat -ano | findstr :{port}，再 taskkill /PID <pid> /T /F，"
            "随后 schtasks /run /tn cwiki-backend 重新拉起。"
        )
    return result


def collect(
    db_path: Path,
    memory_dir: Path,
    *,
    check_port: bool = True,
    api_port: int = 5172,
) -> dict[str, Any]:
    meta_dir = memory_dir / "_meta"
    db = _db_state(db_path)
    md, md_entries, _md_paths, bad_md = _md_entries(memory_dir)
    meta, bad_meta = _meta_health(meta_dir)
    index = _index_ids(memory_dir / "index.db")
    vectors = _vector_ids(memory_dir / "vectors.json")
    ws_meta = _workspaces_meta(meta_dir)

    db_ids = set(db["ids"])
    db_ws_ids = {ws["id"] for ws in db["workspaces"]}
    ws_meta_ids = {str(ws.get("id")) for ws in ws_meta if ws.get("id")}

    issues: list[dict[str, Any]] = []

    def _flag(kind: str, items: set[str], hint: str) -> None:
        if items:
            issues.append(
                {"kind": kind, "count": len(items), "sample": sorted(items)[:20], "hint": hint}
            )

    _flag(
        "orphan_markdown",
        set(md) - db_ids,
        "Markdown 存在但数据库无对应行；确认后可手工移出 memory_dir（脚本不自动删除）",
    )
    _flag(
        "missing_markdown",
        db["active_ids"] - set(md),
        "数据库 active 记忆缺少 Markdown 镜像；执行 python tasks.py migrate-to-git 重新导出",
    )
    _flag(
        "orphan_meta",
        meta - db_ids,
        " _meta 快照存在但数据库无对应行；重建时会跳过它们，可用 check_integrity.py --prune-meta 清理",
    )
    _flag(
        "missing_meta",
        db["active_ids"] - meta,
        "数据库 active 记忆缺少 _meta 快照；执行 python scripts/check_integrity.py --fix-meta 补齐",
    )
    _flag(
        "stale_index",
        index - db_ids,
        "索引含数据库不存在的记忆 id；执行 rebuild-db --index-only 重建索引",
    )
    _flag(
        "missing_index",
        db["embedded_active"] - index,
        "active 且已有 embedding 的记忆未进入索引；执行 rebuild-db --index-only",
    )
    _flag(
        "stale_vectors",
        vectors - db_ids,
        "向量索引含数据库不存在的 id；执行 rebuild-db --index-only",
    )
    _flag(
        "missing_vectors",
        db["embedded_active"] - vectors,
        "active 且已有 embedding 的记忆缺少向量；执行 rebuild-db --index-only",
    )
    _flag(
        "workspace_meta_missing",
        db_ws_ids - ws_meta_ids,
        "数据库工作区未写入 _workspaces.json；执行 check_integrity.py --fix 补齐",
    )
    _flag(
        "workspace_meta_orphan",
        ws_meta_ids - db_ws_ids,
        "_workspaces.json 含数据库不存在的工作区；重建时会被复活，需人工确认",
    )
    _flag(
        "bad_markdown",
        set(bad_md),
        "Markdown frontmatter 缺失/无法解析；确认文件内容后修复或移出 memory_dir",
    )
    _flag(
        "bad_meta",
        set(bad_meta),
        "_meta JSON 无法解析；执行 check_integrity.py --fix-meta 从 DB 重新导出",
    )

    # 内容漂移：MD 与 DB 的 title/content/type/tags/status 不一致
    drift: list[str] = []
    for memory_id in set(db["rows"]) & set(md_entries):
        db_row = db["rows"][memory_id]
        md_row = md_entries[memory_id]
        if (
            db_row["title"].strip() != md_row["title"].strip()
            or db_row["content"].strip() != md_row["content"].strip()
            or db_row["type"] != md_row["type"]
            or sorted(db_row["tags"]) != sorted(md_row["tags"])
            or db_row["status"] != md_row["status"]
        ):
            drift.append(memory_id)
    _flag(
        "content_drift",
        set(drift),
        "Markdown 与数据库内容不一致（手改 MD 未同步）；执行 "
        "python tasks.py doctor --fix-drift（以 MD 为准）或 python tasks.py rebuild-db",
    )

    # 向量索引健康：配对、行数、维度、模型
    from packages.domain.config import settings
    from packages.storage.index_health import index_active_count, inspect_vector_index

    npz_path = memory_dir / "vectors.npz"
    vector_meta_path = memory_dir / "vectors.json"
    vector_health = inspect_vector_index(
        npz_path,
        vector_meta_path,
        expected_dimensions=settings.embedding_dimensions,
        expected_model=settings.embedding_model,
    )
    if vector_health.present and not vector_health.ok:
        issues.append(
            {
                "kind": "vector_index_unhealthy",
                "count": len(vector_health.issues),
                "sample": vector_health.issues[:10],
                "hint": "执行 python tasks.py rebuild-db --index-only（必要时 --force-index）",
            }
        )
    elif npz_path.exists() != vector_meta_path.exists():
        issues.append(
            {
                "kind": "vector_index_broken",
                "count": 1,
                "sample": ["vectors.npz 与 vectors.json 必须成对存在"],
                "hint": "执行 python tasks.py rebuild-db --index-only",
            }
        )
    index_active = index_active_count(memory_dir / "index.db")
    if vector_health.present and index_active is not None and index_active != vector_health.rows:
        issues.append(
            {
                "kind": "index_vector_mismatch",
                "count": 1,
                "sample": [f"index active={index_active}, vectors={vector_health.rows}"],
                "hint": "执行 python tasks.py rebuild-db --index-only",
            }
        )

    report: dict[str, Any] = {
        "counts": {
            "db_total": len(db_ids),
            "db_active": len(db["active_ids"]),
            "workspaces_db": len(db_ws_ids),
            "markdown": len(md),
            "meta": len(meta),
            "index": len(index),
            "vectors": len(vectors),
            "workspaces_meta": len(ws_meta_ids),
            "vector_dimensions": vector_health.dimensions,
            "vector_model": vector_health.model,
        },
        "issues": issues,
        "ok": not issues,
    }
    if check_port:
        report["api_port"] = _port_diagnosis(api_port)
        if report["api_port"].get("healthy") is False:
            report["ok"] = False
    return report


def _delete_orphan_meta(db_path: Path, memory_dir: Path, *, dry_run: bool) -> list[str]:
    """删除 DB 中已无对应记忆行的 _meta 快照。

    正常删除路径会同步清掉快照；残留只可能来自 DB 行被外部删除或历史泄漏。
    这类文件在重建时会被跳过（不导入关联行），留着只会被 git 同步传播，
    并在每次巡检里报成 orphan_meta。
    """
    meta_dir = memory_dir / "_meta"
    if not meta_dir.is_dir():
        return []
    known = set(_db_state(db_path)["ids"])
    orphans = sorted(
        p for p in meta_dir.glob("*.json") if not p.name.startswith("_") and p.stem not in known
    )
    if not dry_run:
        for p in orphans:
            p.unlink(missing_ok=True)
    return [p.stem for p in orphans]


def _fix_workspaces_meta(db_path: Path, memory_dir: Path) -> list[str]:
    """把数据库中的工作区补齐进 _workspaces.json（只增不删）。"""
    db = _db_state(db_path)
    meta_dir = memory_dir / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = meta_dir / "_workspaces.json"
    existing = _workspaces_meta(meta_dir)
    existing_ids = {str(ws.get("id")) for ws in existing if ws.get("id")}
    added: list[str] = []
    for ws in db["workspaces"]:
        if ws["id"] not in existing_ids:
            existing.append(
                {
                    "name": ws["name"],
                    "id": ws["id"],
                    "created_at": None,
                    "updated_at": None,
                }
            )
            added.append(ws["name"])
    if added:
        path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return added


def _fix_missing_meta(db_url: str, memory_dir: Path) -> list[str]:
    """把 DB 中存在但 ``_meta`` 缺失的 active 记忆正向补导出（只增不删）。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from packages.domain.models import Memory
    from packages.storage.meta_export import export_memory_meta

    async def _run() -> list[str]:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        engine = create_async_engine(db_url, connect_args=connect_args)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        meta_dir = memory_dir / "_meta"
        try:
            async with session_factory() as session:
                active_ids = (
                    (await session.execute(select(Memory.id).where(Memory.status == "active")))
                    .scalars()
                    .all()
                )
                missing = [mid for mid in active_ids if not (meta_dir / f"{mid}.json").is_file()]
                for mid in missing:
                    await export_memory_meta(session, mid, meta_dir)
                return [str(mid) for mid in missing]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _drift_ids(db_path: Path, memory_dir: Path) -> list[str]:
    """返回 MD 与 DB 内容不一致的 memory id。"""
    db = _db_state(db_path)
    _, md_entries, _, _ = _md_entries(memory_dir)
    drift: list[str] = []
    for memory_id in set(db["rows"]) & set(md_entries):
        db_row = db["rows"][memory_id]
        md_row = md_entries[memory_id]
        if (
            db_row["title"].strip() != md_row["title"].strip()
            or db_row["content"].strip() != md_row["content"].strip()
            or db_row["type"] != md_row["type"]
            or sorted(db_row["tags"]) != sorted(md_row["tags"])
            or db_row["status"] != md_row["status"]
        ):
            drift.append(memory_id)
    return sorted(drift)


async def _fix_drift(db_url: str, memory_dir: Path) -> list[str]:
    """以 Markdown 为准，把内容漂移的单条记忆同步回数据库。"""
    db_path = Path(db_url.partition(":///")[2])
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    drift = _drift_ids(db_path, memory_dir)
    if not drift:
        return []

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from packages.storage.file_store import FileStore
    from packages.storage.md_sync import sync_memory_from_markdown

    _, _, md_paths, _ = _md_entries(memory_dir)
    store = FileStore(memory_dir)
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    engine = create_async_engine(db_url, connect_args=connect_args)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    fixed: list[str] = []
    try:
        for memory_id in drift:
            path = md_paths.get(memory_id)
            if not path:
                continue
            memory_file = store.load_from_path(path)
            if memory_file is None:
                continue
            async with session_factory() as session:
                try:
                    # 必须显式传 meta_dir：不传时 sync_memory_from_markdown 会落到
                    # 配置里的真实数据目录，把巡检记忆写进用户库（污染 _meta）。
                    result = await sync_memory_from_markdown(
                        session, memory_file, meta_dir=memory_dir / "_meta"
                    )
                    if result.status == "updated":
                        await session.commit()
                        fixed.append(memory_id)
                    else:
                        await session.rollback()
                except Exception as exc:
                    await session.rollback()
                    print(f"  修复 {memory_id} 失败：{exc}", file=sys.stderr)
        return fixed
    finally:
        await engine.dispose()


def _format_human(report: dict[str, Any]) -> str:
    counts = report["counts"]
    lines = [
        "cwiki 一致性巡检",
        "=================",
        (
            f"DB 记忆 {counts['db_total']}（active {counts['db_active']}） | "
            f"Markdown {counts['markdown']} | _meta {counts['meta']} | "
            f"索引 {counts['index']} | 向量 {counts['vectors']} | "
            f"工作区 DB {counts['workspaces_db']} / meta {counts['workspaces_meta']}"
        ),
    ]
    port = report.get("api_port") or {}
    if port.get("listening"):
        lines.append(f"API 端口：监听中，健康检查{'通过' if port.get('healthy') else '失败'}")
        if port.get("hint"):
            lines.append(f"  提示：{port['hint']}")
    if report["ok"]:
        lines.append("结论：一致（无异常）")
        return "\n".join(lines)

    lines.append(f"发现 {len(report['issues'])} 类异常：")
    for issue in report["issues"]:
        lines.append(f"- {issue['kind']}（{issue['count']}）：{', '.join(issue['sample'])}")
        lines.append(f"  处理：{issue['hint']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="cwiki 三层存储一致性巡检")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--fix", action="store_true", help="仅补齐 _workspaces.json 缺失工作区")
    parser.add_argument("--fix-meta", action="store_true", help="从数据库补导出缺失的 _meta 快照")
    parser.add_argument(
        "--fix-drift",
        action="store_true",
        help="以 Markdown 为准，把内容漂移的单条记忆同步回数据库",
    )
    parser.add_argument(
        "--prune-meta",
        action="store_true",
        help="删除 DB 中已无对应记忆行的孤儿 _meta 快照",
    )
    parser.add_argument("--skip-port", action="store_true", help="跳过 API 端口诊断")
    args = parser.parse_args()

    from packages.domain.config import settings
    from packages.storage import config as storage_config

    url = settings.database_url
    if not url.startswith("sqlite"):
        print("仅支持 SQLite 数据库", file=sys.stderr)
        return 2
    db_path = Path(url.partition(":///")[2])
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    memory_dir = Path(storage_config.memory_dir)
    if not memory_dir.is_absolute():
        memory_dir = PROJECT_ROOT / memory_dir

    if not db_path.is_file():
        print(f"数据库不存在：{db_path}", file=sys.stderr)
        return 2

    if args.fix:
        added = _fix_workspaces_meta(db_path, memory_dir)
        if added:
            print(f"已补齐 _workspaces.json：{', '.join(added)}")

    if args.fix_meta:
        fixed = _fix_missing_meta(settings.database_url, memory_dir)
        print(f"已补导出 _meta：{len(fixed)} 条" + (f"（{', '.join(fixed)}）" if fixed else ""))

    if args.fix_drift:
        fixed = asyncio.run(_fix_drift(settings.database_url, memory_dir))
        print(
            f"已按 MD 修复内容漂移：{len(fixed)} 条" + (f"（{', '.join(fixed)}）" if fixed else "")
        )

    if args.prune_meta:
        removed = _delete_orphan_meta(db_path, memory_dir, dry_run=False)
        print(
            f"已删除孤儿 _meta 快照：{len(removed)} 个"
            + (f"（{', '.join(removed)}）" if removed else "")
        )

    report = collect(
        db_path,
        memory_dir,
        check_port=not args.skip_port,
        api_port=settings.api_port,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _format_human(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
