#!/usr/bin/env python3
"""把 Qoder 原生 Auto-Memory 导入 cwiki「待整理」。

默认 dry-run，只打印将导入的条目；确认后加 ``--apply`` 才会 POST 到
``/v1/integrations/agent/capture``。导入内容保持 Markdown 全文，不摘要化。

Qoder 的 Auto-Memory 位于 ``~/.qoder/memories/<id>/projects/<project>/
task_summary_experience/*.md``；每条带 YAML frontmatter 与 ``Related files``。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ROOT = Path.home() / ".qoder" / "memories"
API_URL = os.environ.get("CWIKI_API_URL", "http://127.0.0.1:5172").rstrip("/")
WORKSPACE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_PATH_RE = re.compile(r"(?:/Users/[\w./-]+|[A-Za-z]:\\[\w\\. /-]+)")


def parse_memory(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(text.strip()) < 80:
        return None

    meta: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            try:
                parsed = yaml.safe_load(text[3:end])
                if isinstance(parsed, dict):
                    meta = parsed
            except yaml.YAMLError:
                pass
            body = text[end + 3 :].strip()

    title = str(meta.get("title") or "").strip()
    if not title:
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    if not title:
        title = path.stem

    related = _related_paths(body)
    workspace = _workspace_for(related)
    content = f"# {title}\n\n{body}".strip()
    record_id = hashlib.sha256(f"{path}:{content}".encode()).hexdigest()[:32]
    return {
        "record_id": record_id,
        "kind": "compact_summary",
        "session_id": f"qoder-auto-memory:{record_id}",
        "workspace": workspace,
        "cwd": str(related[0].parent) if related else None,
        "content": content,
        "signal_type": "session_snapshot",
        "occurred_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
        "path": str(path),
    }


def _related_paths(body: str) -> list[Path]:
    paths: list[Path] = []
    for match in _PATH_RE.findall(body):
        raw = match.strip()
        try:
            path = Path(raw)
        except (OSError, ValueError):
            continue
        # Windows 上 Path("/Users/...") 因缺盘符不被视为绝对路径，
        # 但记忆可能从 macOS/Linux 同步而来，仍需保留。
        if (path.is_absolute() or raw.startswith("/")) and path not in paths:
            paths.append(path)
    return paths[:20]


def _common_parent(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    try:
        return Path(os.path.commonpath([str(p) for p in paths]))
    except (ValueError, OSError):
        return None


def _workspace_for(paths: list[Path]) -> str:
    common = _common_parent(paths)
    candidate: str | None = None
    if common is not None:
        candidate = common.name
        # common 常常是 code-space / projects 这类容器；取第一个路径相对它的首段
        if candidate in {"code-space", "projects", "Users", "home", "src"} and paths:
            try:
                rel = paths[0].relative_to(common)
                if rel.parts:
                    candidate = rel.parts[0]
            except ValueError:
                pass
    if not candidate and paths:
        candidate = paths[0].parent.name
    if not candidate:
        candidate = "qoder-auto"
    candidate = WORKSPACE_RE.sub("-", candidate).strip("-")[:64]
    if not candidate or re.match(r"^[A-Za-z]--", candidate):
        return "qoder-auto"
    return candidate


def discover(root: Path, limit: int, since_days: int | None) -> list[dict[str, Any]]:
    cutoff = None
    if since_days is not None:
        cutoff = datetime.now(UTC).timestamp() - since_days * 86400
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.md")):
        if len(records) >= limit:
            break
        if "task_summary_experience" not in path.parts:
            continue
        if cutoff is not None and path.stat().st_mtime < cutoff:
            continue
        record = parse_memory(path)
        if record is not None:
            records.append(record)
    return records


def post(records: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "host": "qoder",
        "records": [{k: v for k, v in record.items() if k != "path"} for record in records],
    }
    request = urllib.request.Request(
        f"{API_URL}/v1/integrations/agent/capture",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--apply", action="store_true", help="实际 POST 到 cwiki")
    args = parser.parse_args()

    records = discover(args.root.expanduser(), args.limit, args.since_days)
    print(f"found {len(records)} Qoder Auto-Memory notes under {args.root}")
    for record in records:
        print(f"  [{record['workspace']}] {record['path']} ({len(record['content'])} chars)")
    if not args.apply:
        print("dry-run: add --apply to import into cwiki inbox")
        return 0
    if not records:
        return 0
    try:
        result = post(records)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"import failed: {exc}")
        return 1
    print(
        f"imported: accepted={result.get('accepted')} "
        f"duplicates={result.get('duplicates')} rejected={len(result.get('rejected') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
