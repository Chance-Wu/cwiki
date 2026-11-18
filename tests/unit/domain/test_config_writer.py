"""config.yaml 定点写回测试：UI 拨一次开关不能把配置文件的中文注释洗掉。"""

from __future__ import annotations

import pytest

from packages.domain.config_writer import apply_block_updates, apply_scalar_updates

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
    """列表/字典写回需要整块替换语义，定点标量编辑器不支持，必须显式失败。"""
    with pytest.raises(TypeError):
        apply_scalar_updates(RAW, [("memory", "rules", [{"id": "x"}])])


RULES_RAW = """agent_policy:
  # 写入决策：结构化规则决定是否写入
  write_decisions:
    enabled: true
    default_action: write
    rules:  # 按顺序命中，先跳过再写入
      - id: skip-credentials
        action: skip
        match:
          keyword: ["api_key"]
      - id: save-decisions
        action: write
memory:
  # 被注释掉的旧键，不得被改写
  # write_policy:
  #   enabled: true
  write_policy:
    enabled: false
    rules: []
    # - id: pinned-auto
    #   action: auto
"""

OLD_RULES_BLOCK = """      - id: skip-credentials
        action: skip
        match:
          keyword: ["api_key"]
      - id: save-decisions
        action: write"""


def test_block_update_replaces_only_the_target_block() -> None:
    out = apply_block_updates(
        RULES_RAW,
        [(("agent_policy", "write_decisions", "rules"), [{"id": "only-rule", "action": "write"}])],
    )
    assert out == RULES_RAW.replace(OLD_RULES_BLOCK, "      - id: only-rule\n        action: write")


def test_block_update_keeps_comment_lines_after_the_value_block() -> None:
    """`rules: []` 之后注释掉的示例规则属于文档，替换值块不能把它们吞掉。"""
    out = apply_block_updates(
        RULES_RAW, [(("memory", "write_policy", "rules"), [{"id": "pinned", "action": "auto"}])]
    )
    lines = out.splitlines()
    assert lines[lines.index("    rules:") + 1 : lines.index("    rules:") + 3] == [
        "      - id: pinned",
        "        action: auto",
    ]
    assert lines.index("    # - id: pinned-auto") > lines.index("        action: auto")
    assert lines.index("    #   action: auto") == lines.index("    # - id: pinned-auto") + 1


def test_block_update_renders_empty_list_inline_and_keeps_key_comment() -> None:
    out = apply_block_updates(RULES_RAW, [(("agent_policy", "write_decisions", "rules"), [])])
    assert "    rules: []  # 按顺序命中，先跳过再写入" in out
    assert "skip-credentials" not in out


def test_block_update_skips_commented_out_keys() -> None:
    out = apply_block_updates(RULES_RAW, [(("memory", "write_policy", "enabled"), True)])
    assert "  #   enabled: true" in out
    assert "    enabled: false" not in out
    assert "  # write_policy:" in out


def test_block_update_creates_missing_nested_parent_inside_section() -> None:
    raw = (
        "agent_policy:\n  always_inject:\n    enabled: true\nstorage:\n  memory_dir: ./cwiki-data\n"
    )
    out = apply_block_updates(
        raw, [(("agent_policy", "write_decisions", "rules"), [{"id": "x", "action": "write"}])]
    )
    assert out == (
        "agent_policy:\n"
        "  always_inject:\n"
        "    enabled: true\n"
        "  write_decisions:\n"
        "    rules:\n"
        "      - id: x\n"
        "        action: write\n"
        "storage:\n"
        "  memory_dir: ./cwiki-data\n"
    )


def test_block_update_preserves_crlf_and_trailing_newline() -> None:
    updates = [(("agent_policy", "write_decisions", "rules"), [{"id": "x"}])]
    out = apply_block_updates(RULES_RAW.replace("\n", "\r\n"), updates)
    assert out.count("\n") == out.count("\r\n")
    assert out.endswith("\r\n")
    assert (
        out.replace("\r\n", "\n").splitlines()
        == apply_block_updates(RULES_RAW, updates).splitlines()
    )


def test_scalar_update_writes_string_without_document_end_marker() -> None:
    """PyYAML 给根级标量补 `...`，取值必须走映射上下文，否则写回多出一行垃圾。"""
    out = apply_scalar_updates(RAW, [("app", "name", "cwiki")])
    lines = out.splitlines()
    assert lines[lines.index("  port: 5172  # 监听端口") + 1] == "  name: cwiki"
    assert "..." not in lines


def test_block_update_writes_string_scalar_without_document_end_marker() -> None:
    out = apply_block_updates(
        RULES_RAW, [(("agent_policy", "write_decisions", "default_action"), "skip")]
    )
    lines = out.splitlines()
    assert lines.count("    default_action: skip") == 1
    assert "..." not in lines


class TestRootFlowDocument:
    """根级流式映射文档（如测试用的 `{}`）无法按行编辑，必须整份重写。

    在 `{}` 后插入 `section:` 块会产出既有流映射又有块映射的非法 YAML。
    """

    def test_block_update_rewrites_flow_document(self) -> None:
        import yaml

        out = apply_block_updates(
            "{}\n",
            [
                (("memory", "write_policy", "enabled"), True),
                (("memory", "write_policy", "rules"), [{"id": "pinned-auto"}]),
            ],
        )
        data = yaml.safe_load(out)
        assert data["memory"]["write_policy"]["enabled"] is True
        assert data["memory"]["write_policy"]["rules"] == [{"id": "pinned-auto"}]

    def test_scalar_update_rewrites_flow_document(self) -> None:
        import yaml

        out = apply_scalar_updates("{}\n", [("memory", "title_max_length", 80)])
        assert yaml.safe_load(out) == {"memory": {"title_max_length": 80}}

    def test_flow_rewrite_preserves_existing_keys(self) -> None:
        import yaml

        raw = "{app: {api_port: 5172}}\n"
        out = apply_block_updates(raw, [(("memory", "similarity_strategy"), "hybrid")])
        data = yaml.safe_load(out)
        assert data["app"]["api_port"] == 5172
        assert data["memory"]["similarity_strategy"] == "hybrid"
