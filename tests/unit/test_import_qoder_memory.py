"""Qoder Auto-Memory 导入器的解析与 workspace 映射测试。"""

from __future__ import annotations

from pathlib import Path

from scripts.import_qoder_memory import discover, parse_memory


def _write(root: Path, name: str, body: str, title: str = "任务摘要") -> Path:
    path = (
        root
        / "mem-1"
        / "projects"
        / "Users-alice-code-space-demo"
        / "task_summary_experience"
        / name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\nkeywords:\n  - demo\nsource: auto\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def test_parse_memory_maps_workspace_from_related_files(tmp_path):
    path = _write(
        tmp_path,
        "demo.md",
        "## Task description\n- Core requirement: demo\n\n"
        "## Related files\n- /Users/alice/code-space/demo/src/app.py\n"
        "- /Users/alice/code-space/demo/README.md\n",
    )
    record = parse_memory(path)
    assert record is not None
    assert record["workspace"] == "demo"
    assert record["content"].startswith("# 任务摘要")
    assert "Core requirement: demo" in record["content"]
    assert record["kind"] == "compact_summary"
    assert record["record_id"]


def test_parse_memory_without_related_files_uses_bucket(tmp_path):
    path = _write(tmp_path, "plain.md", "## Task description\n- Core requirement: plain")
    record = parse_memory(path)
    assert record is not None
    assert record["workspace"] == "qoder-auto"


def test_discover_only_reads_task_summary_experience(tmp_path):
    _write(tmp_path, "ok.md", "## Task description\n- Core requirement: ok")
    other = tmp_path / "mem-1" / "projects" / "x" / "other" / "skip.md"
    other.parent.mkdir(parents=True)
    other.write_text("not a task summary" * 20, encoding="utf-8")
    records = discover(tmp_path, limit=10, since_days=None)
    assert len(records) == 1
    assert records[0]["content"].startswith("# 任务摘要")
