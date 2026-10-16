"""内容安全过滤：提示注入（prompt injection）检测。"""

import re

from packages.domain.errors import AppError


class UnsafeMemoryContent(AppError, ValueError):
    """检测到已知注入模式即拒绝；绝不清洗（sanitize）已存储文本。"""

    def __init__(self) -> None:
        super().__init__(
            "unsafe_memory_content",
            "内容包含已知提示注入指令，拒绝写入；请移除相关指令后重试。",
            status_code=422,
        )


# 已知注入模式清单（中英文各一组）。策略是整体拒绝而非改写：
# 对注入文本做局部清洗很容易留下绕过空间。
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?prior\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(
        r"you\s+are\s+now\s+(?:a|an|the|acting|playing|pretending|role|system|assistant)\b",
        re.IGNORECASE,
    ),
    re.compile(r"new\s+(system|role)\s+(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"override\s+(previous|prior|system)", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all|previous)", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|所有)(的)?指令"),
    re.compile(r"无视(之前|以上|所有)(的)?"),
    re.compile(r"你现在是"),
    re.compile(r"新的(系统|角色)(指令|提示)"),
    re.compile(r"覆盖(之前|以上|原有)(的)?"),
    re.compile(r"忘记(所有|之前|一切)"),
]


def check_injection(content: str) -> bool:
    """内容命中已知提示注入模式时返回 True。"""
    return any(p.search(content) for p in _INJECTION_PATTERNS)


def validate_safe_content(content: str) -> str:
    """拒绝已知注入指令，其余文本原样保留。"""
    if check_injection(content):
        raise UnsafeMemoryContent()
    return content
