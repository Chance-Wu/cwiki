"""一致性巡检：正常布局无异常；构造的孤儿/缺失能被识别；--fix 只补工作区。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts import check_integrity

WS_ID = "11111111-1111-1111-1111-111111111111"
MEM_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MEM_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _make_db(path: Path, memory_rows: list[tuple[str, str]], workspaces: list[tuple[str, str]]):
    con = sqlite3.connect(path)
    con.execute("create table memory (id text, status text, embedding blob)")
    con.execute("create table workspace (id text, name text)")
    for mid, status in memory_rows:
        con.execute("insert into memory values (?, ?, ?)", (mid, status, b"vec"))
    for wid, name in workspaces:
        con.execute("insert into workspace values (?, ?)", (wid, name))
    con.commit()
    con.close()


def _write_md(memory_dir: Path, workspace: str, memory_id: str) -> None:
    folder = memory_dir / workspace / "fact"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{memory_id}_title.md").write_text(
        f"---\nid: {memory_id}\nconfidence: 0.5\n---\n\n正文\n", encoding="utf-8"
    )


def _make_index(memory_dir: Path, ids: list[str]) -> None:
    con = sqlite3.connect(memory_dir / "index.db")
    con.execute("create table memory_index (id text)")
    for mid in ids:
        con.execute("insert into memory_index values (?)", (mid,))
    con.commit()
    con.close()
    (memory_dir / "vectors.json").write_text(json.dumps({"ids": ids}), encoding="utf-8")


def _make_layout(tmp_path: Path) -> tuple[Path, Path]:
    memory_dir = tmp_path / "cwiki-data"
    meta_dir = memory_dir / "_meta"
    meta_dir.mkdir(parents=True)
    db_path = memory_dir / "cwiki.db"
    _make_db(
        db_path,
        [(MEM_A, "active"), (MEM_B, "archived")],
        [(WS_ID, "ws-one")],
    )
    for mid in (MEM_A, MEM_B):
        _write_md(memory_dir, "ws-one", mid)
        (meta_dir / f"{mid}.json").write_text("{}", encoding="utf-8")
    _make_index(memory_dir, [MEM_A])
    (meta_dir / "_workspaces.json").write_text(
        json.dumps([{"name": "ws-one", "id": WS_ID}]), encoding="utf-8"
    )
    return db_path, memory_dir


def test_consistent_layout_is_ok(tmp_path: Path) -> None:
    db_path, memory_dir = _make_layout(tmp_path)

    report = check_integrity.collect(db_path, memory_dir, check_port=False)

    assert report["ok"] is True, report["issues"]


def test_detects_orphans_and_missing_workspace_meta(tmp_path: Path) -> None:
    db_path, memory_dir = _make_layout(tmp_path)
    # 孤儿 Markdown + 孤儿 _meta + 索引残留
    _write_md(memory_dir, "ws-one", "cccccccc-cccc-cccc-cccc-cccccccccccc")
    (memory_dir / "_meta" / "dddddddd-dddd-dddd-dddd-dddddddddddd.json").write_text(
        "{}", encoding="utf-8"
    )
    con = sqlite3.connect(memory_dir / "index.db")
    con.execute("insert into memory_index values (?)", ("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",))
    con.commit()
    con.close()
    # 工作区 meta 缺失
    (memory_dir / "_meta" / "_workspaces.json").write_text("[]", encoding="utf-8")

    report = check_integrity.collect(db_path, memory_dir, check_port=False)

    kinds = {issue["kind"] for issue in report["issues"]}
    assert "orphan_markdown" in kinds
    assert "orphan_meta" in kinds
    assert "stale_index" in kinds
    assert "workspace_meta_missing" in kinds
    assert report["ok"] is False


def test_fix_adds_missing_workspace_without_deleting(tmp_path: Path) -> None:
    db_path, memory_dir = _make_layout(tmp_path)
    meta_path = memory_dir / "_meta" / "_workspaces.json"
    meta_path.write_text(json.dumps([{"name": "old", "id": "9999"}]), encoding="utf-8")

    added = check_integrity._fix_workspaces_meta(db_path, memory_dir)

    assert added == ["ws-one"]
    stored = json.loads(meta_path.read_text(encoding="utf-8"))
    ids = {item["id"] for item in stored}
    assert WS_ID in ids
    assert "9999" in ids  # 只增不删
