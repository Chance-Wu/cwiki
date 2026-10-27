"""守卫 cwiki-save skill 文档与实际工具契约一致，防止文档再次漂移。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from adapters.mcp.tool_definitions import build_tool_definitions
from packages.domain.types import TYPE_DEFINITIONS

SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "cwiki-save"
SKILL_MD = SKILL_DIR / "SKILL.md"
TOOL_CONTRACT = SKILL_DIR / "references" / "tool-contract.md"
CONTENT_TEMPLATES = SKILL_DIR / "references" / "content-templates.md"

# 与 apps/web/src/components/MarkdownContent.tsx 的 callout 正则保持同步；
# 不在列表内的类型会渲染成普通引用块
SUPPORTED_CALLOUTS = {
    "note",
    "tip",
    "important",
    "warning",
    "caution",
    "abstract",
    "summary",
    "info",
    "example",
    "question",
    "danger",
}
# memory_search.filters 的子键不是顶层参数
FILTER_KEYS = {"type", "min_confidence", "tags"}


def _tools() -> dict[str, dict[str, Any]]:
    return {tool["name"]: tool for tool in build_tool_definitions()}


def _tool_table_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    text = TOOL_CONTRACT.read_text(encoding="utf-8")
    for line in text.splitlines():
        match = re.match(r"\| `(memory_[a-z_]+)` \|", line)
        if match:
            rows[match.group(1)] = line
    return rows


def test_documented_tools_match_schema() -> None:
    assert set(_tool_table_rows()) == set(_tools())


def test_workspace_column_matches_schema() -> None:
    tools = _tools()
    for name, row in _tool_table_rows().items():
        props = tools[name]["inputSchema"].get("properties", {})
        assert row.rstrip().endswith("| ✓ |") is ("workspace_name" in props), name


def test_documented_params_exist_in_schema() -> None:
    tools = _tools()
    for name, row in _tool_table_rows().items():
        props = set(tools[name]["inputSchema"].get("properties", {}))
        cells = row.split("|")
        documented = set(re.findall(r"`([a-z_]+)`", "|".join(cells[2:4])))
        documented -= FILTER_KEYS
        assert documented <= props, f"{name}: 文档多出参数 {documented - props}"


def test_skill_md_tool_count_matches() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.search(r"工具概览\*\*（(\d+) 个", text)
    assert match, "SKILL.md 缺少工具概览计数"
    assert int(match.group(1)) == len(_tools())


def test_checkpoint_reasons_match_schema() -> None:
    schema = _tools()["memory_checkpoint"]["inputSchema"]
    enum = set(schema["properties"]["trigger_reason"]["enum"])
    text = TOOL_CONTRACT.read_text(encoding="utf-8")
    line = text.split("memory_checkpoint.trigger_reason", 1)[1].split("\n", 1)[0]
    documented = set(re.findall(r"`([a-z_]+)`", line))
    assert documented == enum


def test_template_types_match_definitions() -> None:
    text = CONTENT_TEMPLATES.read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| \*\*[^*]+\*\* \(([a-z]+)\)", text, re.M))
    assert documented == set(TYPE_DEFINITIONS)


def test_template_callouts_are_supported_by_web_renderer() -> None:
    text = CONTENT_TEMPLATES.read_text(encoding="utf-8")
    callouts = set(re.findall(r"> \[!(\w+)\]", text))
    assert callouts, "模板未给出任何 callout"
    assert callouts <= SUPPORTED_CALLOUTS, callouts - SUPPORTED_CALLOUTS


def test_skill_referenced_files_exist() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for rel in re.findall(r"\]\(([^)]+\.md)\)", text):
        assert (SKILL_DIR / rel).is_file(), rel
