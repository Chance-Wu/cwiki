"""config.yaml 定点写回：只改目标标量键所在行，保留注释、缩进与换行风格。

整份 `yaml.dump` 回写会把 config.yaml 里当作文档使用的中文注释（含注释掉的
规则示例）全部洗掉，因此这里按行定位 `section.key` 做替换。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import yaml

_TOP_LEVEL_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?=\s|#|$)")
_DEFAULT_INDENT = 2


def _format_scalar(value: Any) -> str:
    # bool 必须先于 int 判：Python 里 True 是 int 的实例
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
    raise TypeError(f"定点写回只支持标量，收到 {type(value).__name__}")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _is_content(line: str) -> bool:
    return bool(line.strip()) and not line.strip().startswith("#")


def _split_inline_comment(line: str) -> str:
    """返回行尾注释（引号外的 # 且前导为空白才算注释起始），无注释返回空串。"""
    quote: str | None = None
    for index, char in enumerate(line):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "#" and index > 0 and line[index - 1] in " \t":
            return line[index:]
    return ""


def _find_section(lines: list[str], section: str) -> int:
    for index, line in enumerate(lines):
        match = _TOP_LEVEL_KEY.match(line)
        if match and match.group(1) == section:
            return index
    return -1


def _section_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if _TOP_LEVEL_KEY.match(lines[index]):
            return index
    return len(lines)


def _apply_one(lines: list[str], section: str, key: str, value: str) -> list[str]:
    start = _find_section(lines, section)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{section}:")
        lines.append(f"{' ' * _DEFAULT_INDENT}{key}: {value}")
        return lines

    end = _section_end(lines, start)
    child_indent: int | None = None
    target = re.compile(rf"^{re.escape(key)}:(?=\s|$)")
    for index in range(start + 1, end):
        line = lines[index]
        if _is_blank_or_comment(line):
            continue
        if child_indent is None:
            child_indent = _indent_of(line)
        if _indent_of(line) != child_indent:
            continue
        if not target.match(line.strip()):
            continue
        prefix = line[: len(line) - len(line.lstrip(" \t"))]
        comment = _split_inline_comment(line)
        suffix = f"  {comment}" if comment else ""
        lines[index] = f"{prefix}{key}: {value}{suffix}"
        return lines

    insert_at = start + 1
    for index in range(start + 1, end):
        if _is_content(lines[index]):
            insert_at = index + 1
    pad = child_indent if child_indent is not None else _DEFAULT_INDENT
    lines.insert(insert_at, f"{' ' * pad}{key}: {value}")
    return lines


def apply_scalar_updates(raw: str, updates: Sequence[tuple[str, str, Any]]) -> str:
    """把 ``section.key = value`` 逐个写回 *raw* 文本，其余行原样保留。"""
    if not updates:
        return raw

    eol = "\r\n" if "\r\n" in raw else "\n"
    ends_with_eol = raw.endswith(eol)
    lines = raw.split(eol)
    if ends_with_eol and lines and lines[-1] == "":
        lines.pop()

    for section, key, value in updates:
        lines = _apply_one(lines, section, key, _format_scalar(value))

    text = eol.join(lines)
    return text + eol if ends_with_eol else text
