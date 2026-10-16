"""敏感信息脱敏模块：清洗文本中的密钥并识别敏感文件。"""

from __future__ import annotations

import re

# 密钥模式列表 —— 每项为 (已编译正则, 替换模板)
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API 密钥（通用 key=value 或 key: value 形式）
    (
        re.compile(r"(?i)(api[_-]?key|apikey)\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{20,})[\"']?"),
        r"\1=[REDACTED]",
    ),
    # Bearer 令牌
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9_\-.]+"), r"\1[REDACTED]"),
    # Authorization 请求头
    (re.compile(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+"), r"\1[REDACTED]"),
    # 通用 token（access_token / refresh_token 等）
    (
        re.compile(
            r"(?i)(token|access_token|refresh_token)\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{16,})[\"']?"
        ),
        r"\1=[REDACTED]",
    ),
    # 密码
    (re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*[\"']?[^\s\"']+[\"']?"), r"\1=[REDACTED]"),
    # 私钥（PEM 块整体替换）
    (
        re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"),
        "[REDACTED]",
    ),
    # OpenAI 风格 sk- 前缀密钥
    (re.compile(r"\bsk-[A-Za-z0-9]{10,}"), "[REDACTED]"),
    # AWS 访问密钥
    (re.compile(r"(?i)(AKIA[0-9A-Z]{16})"), "[REDACTED]"),
    # 通用 secret / secret_key
    (
        re.compile(r"(?i)(secret|secret_key)\s*[=:]\s*[\"']?([A-Za-z0-9_\-]{16,})[\"']?"),
        r"\1=[REDACTED]",
    ),
    # Cookie（整行值脱敏）
    (re.compile(r"(?i)(cookie|set-cookie)\s*[:=]\s*[^\r\n]+"), r"\1=[REDACTED]"),
    # 带密码的数据库连接串
    (
        re.compile(r"(?i)(postgresql|mysql|mongodb|redis)://[^\s\"']:[^\s\"']@[^\s\"']+"),
        "[REDACTED]",
    ),
]

# 敏感文件名模式
_SENSITIVE_FILE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\.env(\..+)?$"),
    re.compile(r"(?i)\.pem$"),
    re.compile(r"(?i)\.key$"),
    re.compile(r"(?i)credentials\..+$"),
    re.compile(r"(?i)secrets\..+$"),
    re.compile(r"(?i)id_rsa$"),
    re.compile(r"(?i)\.ssh[\\/]"),
    re.compile(r"(?i)\.pgpass$"),
    re.compile(r"(?i)\.netrc$"),
]


def redact_secrets(text: str) -> str:
    """将文本中命中的密钥模式替换为 [REDACTED]。"""
    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def is_sensitive_file(path: str) -> bool:
    """判断文件路径是否命中敏感文件模式。"""
    return any(p.search(path) for p in _SENSITIVE_FILE_PATTERNS)
