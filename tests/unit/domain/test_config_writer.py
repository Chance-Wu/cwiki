"""config.yaml 定点写回测试：UI 拨一次开关不能把配置文件的中文注释洗掉。"""

from __future__ import annotations

import pytest

from packages.domain.config_writer import apply_scalar_updates

RAW = """app:
  # 是否输出调试日志
  debug: true
  port: 5172  # 监听端口
retrieval:
  bm25_weight: 0.6
  # 旧写法示例，保持注释状态：
  # explain_enabled: false
  explain_enabled: true
memory:
  write_policy:
    enabled: false
  auto_approve_enabled: false
"""


def test_replaces_only_the_target_line() -> None:
    assert apply_scalar_updates(RAW, [("app", "debug", False)]) == RAW.replace(
        "  debug: true", "  debug: false"
    )


def test_keeps_trailing_inline_comment() -> None:
    out = apply_scalar_updates(RAW, [("app", "port", 8080)])
    assert "  port: 8080  # 监听端口" in out


def test_does_not_rewrite_commented_out_line() -> None:
    out = apply_scalar_updates(RAW, [("retrieval", "explain_enabled", False)])
    assert "  # explain_enabled: false" in out
    assert "  explain_enabled: false" in out


def test_ignores_key_nested_deeper_than_section() -> None:
    """memory.enabled 不是 write_policy.enabled，深层同名键不得被改。"""
    out = apply_scalar_updates(RAW, [("memory", "enabled", True)])
    assert "    enabled: false" in out


def test_inserts_missing_key_after_last_content_line() -> None:
    out = apply_scalar_updates(RAW, [("app", "verbose", True)])
    lines = out.splitlines()
    assert lines[lines.index("  port: 5172  # 监听端口") + 1] == "  verbose: true"


def test_appends_missing_section() -> None:
    out = apply_scalar_updates(RAW, [("scheduler", "tick_minutes", 5)])
    assert "scheduler:\n  tick_minutes: 5" in out


def test_applies_multiple_updates_in_one_pass() -> None:
    out = apply_scalar_updates(
        RAW,
        [
            ("retrieval", "bm25_weight", 0.25),
            ("memory", "auto_approve_enabled", True),
        ],
    )
    assert "  bm25_weight: 0.25" in out
    assert "  auto_approve_enabled: true" in out


def test_preserves_crlf_line_endings() -> None:
    crlf = RAW.replace("\n", "\r\n")
    out = apply_scalar_updates(crlf, [("app", "debug", False)])
    assert "  debug: false\r\n" in out
    assert "\r\n" in out


def test_rejects_non_scalar_value() -> None:
    """列表/字典写回需要整块替换语义，定点编辑器不支持，必须显式失败。"""
    with pytest.raises(TypeError):
        apply_scalar_updates(RAW, [("memory", "rules", [{"id": "x"}])])
