#!/usr/bin/env python3
"""三层存储一致性巡检（DB / Markdown / _meta + 派生索引），只读为主。

用法：
    python scripts/check_integrity.py            # 人读报告，有异常退出 1
    python scripts/check_integrity.py --json     # JSON 输出
    python scripts/check_integrity.py --fix      # 仅做安全修复：补齐 _workspaces.json 缺失工作区

不删除任何用户数据；不一致项只报告并给出建议命令。
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_ID_RE = re.compile(r"^id:\s*([0-9a-fA-F-]{36})\s*$")


def _sqlite_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2)


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
    finally:
        con.close()
    return {
        "ids": ids,
        "active_ids": active_ids,
        "workspaces": workspaces,
        "embedded_active": embedded_active,
    }


def _md_ids(memory_dir: Path) -> dict[str, str]:
    """Markdown frontmatter id → 文件路径（相对 memory_dir）。"""
    found: dict[str, str] = {}
    for path in memory_dir.rglob("*.md"):
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            continue
        for line in head.splitlines():
            match = _ID_RE.match(line.strip())
            if match:
                found[match.group(1)] = path.relative_to(memory_dir).as_posix()
                break
    return found


def _meta_ids(meta_dir: Path) -> set[str]:
    if not meta_dir.is_dir():
        return set()
    return {path.stem for path in meta_dir.glob("*.json") if not path.name.startswith("_")}


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
    md = _md_ids(memory_dir)
    meta = _meta_ids(meta_dir)
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
        "数据库 active 记忆缺少 Markdown 镜像；可执行 rebuild-db 或从 _meta 重建",
    )
    _flag(
        "orphan_meta",
        meta - db_ids,
        " _meta 快照存在但数据库无对应行；确认后可手工归档（脚本不自动删除）",
    )
    _flag(
        "missing_meta",
        db["active_ids"] - meta,
        "数据库 active 记忆缺少 _meta 快照；可执行 rebuild-db 重新导出",
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
        },
        "issues": issues,
        "ok": not issues,
    }
    if check_port:
        report["api_port"] = _port_diagnosis(api_port)
        if report["api_port"].get("healthy") is False:
            report["ok"] = False
    return report


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
