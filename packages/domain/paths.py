"""跨平台文件名/路径组件校验与清洗。"""

from __future__ import annotations

import re

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\ud800-\udfff]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
}


def _is_reserved(name: str) -> bool:
    """检查主文件名（去扩展名、去尾部空格）是否为 Windows 保留名。"""
    return name.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_NAMES


def validate_path_component(name: str) -> str:
    """校验名称可作为跨平台路径组件，不合法时抛出 ValueError。

    记忆以 Markdown 文件落盘，workspace 名等会直接用作文件名，
    因此必须满足最严格平台（Windows）的约束：结尾点/空格、保留名。
    """
    if not name or name.endswith((".", " ")) or _INVALID_CHARS.search(name):
        raise ValueError("Name must be a valid path component without trailing dots or spaces")
    if _is_reserved(name):
        raise ValueError("Name is reserved on Windows")
    if len(name.encode("utf-8")) > 255:
        raise ValueError("Name exceeds the portable filename length limit")
    return name


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """把任意标题清洗为安全文件名：替换非法字符、避开保留名、限制字节长度。"""
    name = _INVALID_CHARS.sub("-", name).strip(". ")
    if _is_reserved(name):
        name = f"_{name}"
    # 按 UTF-8 字节截断即可同时满足 UTF-16 长度限制，且不会切出半个字符。
    name = name.encode("utf-8")[:max_length].decode("utf-8", errors="ignore").rstrip(". ")
    if _is_reserved(name):
        name = f"_{name}"[:max_length]
    return name or "untitled"
