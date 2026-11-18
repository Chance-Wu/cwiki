"""config.yaml 定点写回：只改目标标量键所在行，保留注释、缩进与换行风格。

整份 `yaml.dump` 回写会把 config.yaml 里当作文档使用的中文注释（含注释掉的
规则示例）全部洗掉，因此这里按行定位 `section.key` 做替换。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
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
        # 包一层映射再取值：PyYAML 对根级标量会追加文档结束符 "..."，
        # 直接 dump 字符串会把那行垃圾一起写进 config.yaml。
        dumped = yaml.safe_dump(
            {"v": value}, default_flow_style=False, allow_unicode=True, width=4096
        )
        return dumped[len("v: ") :].rstrip("\n")
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


def _is_root_flow_document(lines: list[str]) -> bool:
    """首个内容行是根级 ``{`` ⇒ 整份文档是流式映射，无法按行编辑。

    在流式文档后插入 ``section:`` 块会产出非法 YAML（根上既有流映射
    又有块映射），这种文档只能解析后整份重写。
    """
    for line in lines:
        if _is_content(line):
            return line.lstrip().startswith("{")
    return False


def _rewrite_flow_document(raw: str, assign: Callable[[dict[str, Any]], None]) -> str:
    """解析流式文档、应用 *assign* 后整份重写（此类文档本无注释可保）。"""
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        data = {}
    assign(data)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=4096)


def apply_scalar_updates(raw: str, updates: Sequence[tuple[str, str, Any]]) -> str:
    """把 ``section.key = value`` 逐个写回 *raw* 文本，其余行原样保留。"""
    if not updates:
        return raw

    lines = raw.splitlines()
    if _is_root_flow_document(lines):

        def _assign(data: dict[str, Any]) -> None:
            for section_name, key, value in updates:
                data.setdefault(section_name, {})[key] = value

        return _rewrite_flow_document(raw, _assign)

    eol = "\r\n" if "\r\n" in raw else "\n"
    ends_with_eol = raw.endswith(eol)
    if ends_with_eol and lines and lines[-1] == "":
        lines.pop()

    for section, key, value in updates:
        lines = _apply_one(lines, section, key, _format_scalar(value))

    text = eol.join(lines)
    return text + eol if ends_with_eol else text


def _content_indent(lines: list[str], start: int, end: int, parent_indent: int) -> int:
    """子级缩进取块内第一个非注释行；空块按父级 + 默认缩进推断。"""
    for index in range(start, end):
        if _is_content(lines[index]):
            return _indent_of(lines[index])
    return parent_indent + _DEFAULT_INDENT


def _find_key(lines: list[str], start: int, end: int, indent: int, key: str) -> int:
    """在 [start, end) 内找缩进为 *indent* 的 ``key:`` 行；注释掉的同名键不算命中。"""
    target = re.compile(rf"^{re.escape(key)}:(?=\s|$)")
    for index in range(start, end):
        line = lines[index]
        if _is_blank_or_comment(line) or _indent_of(line) != indent:
            continue
        if target.match(line.strip()):
            return index
    return -1


def _subtree_end(lines: list[str], key_index: int) -> int:
    """键行所属子树的结束行（不含）：下一个缩进不大于它的非注释行。"""
    indent = _indent_of(lines[key_index])
    for index in range(key_index + 1, len(lines)):
        if _is_content(lines[index]) and _indent_of(lines[index]) <= indent:
            return index
    return len(lines)


def _last_content(lines: list[str], start: int, end: int) -> int:
    for index in range(end - 1, start - 1, -1):
        if _is_content(lines[index]):
            return index
    return start - 1


def _value_block_end(lines: list[str], key_index: int) -> int:
    """值块的结束行（不含）。

    尾部纯注释行不算值块：config.yaml 把可直接抄用的规则示例注释在 ``rules: []``
    之后，它们是文档而不是值的一部分。
    """
    indent = _indent_of(lines[key_index])
    last = -1
    for index in range(key_index + 1, len(lines)):
        line = lines[index]
        if not _is_content(line):
            continue
        if _indent_of(line) <= indent:
            break
        last = index
    return last + 1 if last >= 0 else key_index + 1


def _render_value(key: str, value: Any, suffix: str, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, (list, tuple, dict)):
        if not value:
            empty = "[]" if isinstance(value, (list, tuple)) else "{}"
            return [f"{prefix}{key}: {empty}{suffix}"]
        dumped = yaml.dump(
            value,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            indent=_DEFAULT_INDENT,
            width=4096,
        ).rstrip("\n")
        body = [f"{prefix}{' ' * _DEFAULT_INDENT}{line}" for line in dumped.split("\n")]
        return [f"{prefix}{key}:{suffix}", *body]
    return [f"{prefix}{key}: {_format_scalar(value)}{suffix}"]


def _apply_block_one(lines: list[str], path: tuple[str, ...], value: Any) -> list[str]:
    parent_start, parent_end, parent_indent = 0, len(lines), -_DEFAULT_INDENT
    key_index = -1
    for key in path:
        indent = _content_indent(lines, parent_start, parent_end, parent_indent)
        found = _find_key(lines, parent_start, parent_end, indent, key)
        if found < 0:
            # 缺失层级就地补在父块末尾，不能追加到文件底部（会跑出错位的兄弟段）
            found = _last_content(lines, parent_start, parent_end) + 1
            lines.insert(found, f"{' ' * indent}{key}:")
        key_index = found
        parent_start, parent_end, parent_indent = found + 1, _subtree_end(lines, found), indent

    target_line = lines[key_index]
    comment = _split_inline_comment(target_line)
    suffix = f"  {comment}" if comment else ""
    lines[key_index : _value_block_end(lines, key_index)] = _render_value(
        path[-1], value, suffix, _indent_of(target_line)
    )
    return lines


def apply_block_updates(raw: str, updates: Sequence[tuple[Sequence[str], Any]]) -> str:
    """把 ``路径 -> 值`` 逐个写回 *raw*：只替换目标键的值块，块外内容逐字保留。

    路径支持任意层级（如 ``("agent_policy", "write_decisions", "rules")``），值可以是
    标量、列表或字典；规则这类嵌套结构无法按单行编辑，只能整块替换。
    """
    if not updates:
        return raw

    lines = raw.splitlines()
    if _is_root_flow_document(lines):

        def _assign(data: dict[str, Any]) -> None:
            for path, value in updates:
                keys = tuple(path)
                if not keys:
                    raise ValueError("块级写回至少需要一层键名")
                node = data
                for key in keys[:-1]:
                    child = node.get(key)
                    if not isinstance(child, dict):
                        child = {}
                        node[key] = child
                    node = child
                node[keys[-1]] = value

        return _rewrite_flow_document(raw, _assign)

    eol = "\r\n" if "\r\n" in raw else "\n"
    ends_with_eol = raw.endswith(eol)
    lines = raw.split(eol)
    if ends_with_eol and lines and lines[-1] == "":
        lines.pop()

    for path, value in updates:
        keys = tuple(path)
        if not keys:
            raise ValueError("块级写回至少需要一层键名")
        lines = _apply_block_one(lines, keys, value)

    text = eol.join(lines)
    return text + eol if ends_with_eol else text
