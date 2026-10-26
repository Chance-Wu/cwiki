"""写入决策规则解析、匹配与注入摘要测试。"""

from __future__ import annotations

import logging

from packages.domain.rule_match import matches_fields
from packages.domain.write_decisions import (
    WriteDecisionPolicy,
    WriteDecisionRule,
    build_agent_hint,
    build_agent_hint_details,
    parse_write_decisions,
)
from packages.domain.write_policy import WriteRule


def _decide(policy: WriteDecisionPolicy, **overrides):
    values = {
        "workspace_name": "cwiki",
        "workspace_id": "11111111-1111-1111-1111-111111111111",
        "memory_type": "lesson",
        "tags": ["pinned", "cwiki"],
        "title": "部署约定",
        "content": "这个口径必须保留。",
    }
    values.update(overrides)
    return policy.decide(**values)


def test_disabled_policy_returns_default_without_matching() -> None:
    policy = WriteDecisionPolicy(
        enabled=False,
        default_action="skip",
        rules=(WriteDecisionRule(id="never", action="write"),),
    )
    assert _decide(policy).action == "skip"


def test_skip_priority_beats_write_even_when_declared_first() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=(
            WriteDecisionRule(id="allow", action="write"),
            WriteDecisionRule(id="deny", action="skip", keywords=("必须保留",)),
        ),
    )
    decision = _decide(policy)
    assert decision.action == "skip"
    assert decision.rule_id == "deny"


def test_priority_order_skip_then_update_then_write() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=(
            WriteDecisionRule(id="allow", action="write"),
            WriteDecisionRule(id="update", action="update", keywords=("补充",)),
            WriteDecisionRule(id="deny", action="skip", keywords=("禁止",)),
        ),
    )
    assert _decide(policy, content="禁止 补充").action == "skip"
    assert _decide(policy, content="补充").action == "update"
    assert _decide(policy, content="普通内容").action == "write"


def test_match_combines_fields_with_and() -> None:
    rule = WriteDecisionRule(
        id="pinned",
        action="write",
        workspaces=("cwiki",),
        types=("decision", "lesson"),
        tags=("pinned",),
        keywords=("必须保留",),
    )
    policy = WriteDecisionPolicy(enabled=True, default_action="skip", rules=(rule,))

    assert _decide(policy).action == "write"
    assert _decide(policy, workspace_name="other").action == "skip"
    assert _decide(policy, memory_type="fact").action == "skip"
    assert _decide(policy, tags=["cwiki"]).action == "skip"
    assert _decide(policy, content="无关内容").action == "skip"


def test_default_actions() -> None:
    for action in ("write", "skip"):
        policy = WriteDecisionPolicy(enabled=True, default_action=action)
        decision = _decide(policy)
        assert decision.action == action
        assert decision.rule_id is None


def test_update_action_and_reason() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=(WriteDecisionRule(id="upd", action="update", description="补充已有记忆"),),
    )
    decision = _decide(policy)
    assert decision.action == "update"
    assert decision.reason == "补充已有记忆"


def test_parse_accepts_description_examples_and_scalar_match() -> None:
    policy = parse_write_decisions(
        {
            "enabled": True,
            "default_action": "skip",
            "rules": [
                {
                    "id": " r1 ",
                    "action": "skip",
                    "description": " 一次性状态 ",
                    "examples": [" 现在几点 ", "确认一下"],
                    "match": {"type": "issue", "keyword": "ECONNRESET"},
                }
            ],
        }
    )
    assert policy.enabled is True
    assert policy.default_action == "skip"
    (rule,) = policy.rules
    assert rule.id == "r1"
    assert rule.description == "一次性状态"
    assert rule.examples == ("现在几点", "确认一下")
    assert rule.types == ("issue",)
    assert rule.keywords == ("ECONNRESET",)


def test_parse_skips_invalid_rules(caplog) -> None:
    caplog.set_level(logging.WARNING)
    policy = parse_write_decisions(
        {
            "enabled": True,
            "default_action": "unknown",
            "rules": [
                {"action": "write"},
                {"id": "bad-action", "action": "delete"},
                {"id": "review-action", "action": "review"},
                {"id": "bad-match", "action": "write", "match": {"typo": "x"}},
                {"id": "bad-type", "action": "write", "match": {"tags": {"x": "y"}}},
                {"id": "ok", "action": "write"},
            ],
        }
    )
    assert policy.default_action == "write"
    assert [rule.id for rule in policy.rules] == ["ok"]
    assert "缺少非空 id" in caplog.text
    assert "action 必须是" in caplog.text
    assert "未知匹配字段" in caplog.text
    assert "必须是字符串或字符串列表" in caplog.text


def test_parse_skips_duplicate_ids_and_warns_catch_all(caplog) -> None:
    caplog.set_level(logging.WARNING)
    policy = parse_write_decisions(
        {
            "enabled": True,
            "rules": [
                {"id": "dup", "action": "write"},
                {"id": "DUP", "action": "skip"},
            ],
        }
    )
    assert [rule.action for rule in policy.rules] == ["write"]
    assert "规则 id 重复" in caplog.text
    assert "没有匹配条件" in caplog.text


def test_build_hint_filters_workspace_and_truncates() -> None:
    long_description = "长说明" * 80
    policy = WriteDecisionPolicy(
        enabled=True,
        default_action="skip",
        rules=(
            WriteDecisionRule(
                id="r1",
                action="write",
                description=long_description,
                examples=("示例一" * 60, "示例二", "示例三"),
                workspaces=("cwiki",),
            ),
            WriteDecisionRule(
                id="r2",
                action="skip",
                description="只在其他工作区",
                workspaces=("other",),
            ),
        ),
    )
    hint = build_agent_hint(policy, "cwiki")
    assert "cwiki 写入决策" in hint
    assert "优先级：不写入 > 更新 > 写入" in hint
    assert "[写入]" in hint
    assert "未命中：不写入" in hint
    assert "只在其他工作区" not in hint
    assert len(hint) <= 800
    # 描述截到 120 字，示例最多 2 条
    assert hint.count("例：") == 1
    assert "示例三" not in hint


def test_build_hint_respects_small_budget() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=tuple(
            WriteDecisionRule(id=f"r{i}", action="write", description="说明" * 40)
            for i in range(10)
        ),
    )
    hint = build_agent_hint(policy, "", max_chars=200)
    assert len(hint) <= 200


def test_parse_quiet_suppresses_draft_warnings(caplog) -> None:
    raw = {
        "enabled": True,
        "default_action": "write",
        "rules": [
            {"id": "", "action": "write", "match": {}},
            {"id": "ok", "action": "write", "match": {}},
        ],
    }

    with caplog.at_level(logging.WARNING):
        policy = parse_write_decisions(raw, quiet=True)
    assert [rule.id for rule in policy.rules] == ["ok"]
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        parse_write_decisions(raw)
    assert any(record.levelno >= logging.WARNING for record in caplog.records)


def test_build_hint_disabled_returns_empty() -> None:
    assert build_agent_hint(WriteDecisionPolicy(enabled=False), "cwiki") == ""


def test_build_hint_details_reports_budget_and_truncation() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=tuple(
            WriteDecisionRule(id=f"r{i}", action="write", description="说明" * 40)
            for i in range(10)
        ),
    )
    details = build_agent_hint_details(policy, "", max_chars=200)

    assert details.length == len(details.text) <= 200
    assert details.total_rules == 10
    assert details.shown_rules < details.total_rules
    assert details.truncated is True
    assert "另有" in details.text and "条规则未展示" in details.text


def test_build_hint_details_marks_untruncated_when_budget_fits() -> None:
    policy = WriteDecisionPolicy(
        enabled=True,
        rules=(WriteDecisionRule(id="r1", action="write", description="短说明"),),
    )
    details = build_agent_hint_details(policy, "cwiki")

    assert details.shown_rules == details.total_rules == 1
    assert details.truncated is False
    assert details.max_chars == 800


def test_build_hint_details_disabled_has_no_rules() -> None:
    details = build_agent_hint_details(WriteDecisionPolicy(enabled=False), "cwiki")

    assert details.text == ""
    assert details.length == 0
    assert details.shown_rules == details.total_rules == 0
    assert details.truncated is False


def test_decision_and_write_policy_share_match_semantics() -> None:
    fields = {
        "workspaces": ("cwiki",),
        "types": ("lesson", "decision"),
        "tags": ("pinned",),
        "keywords": ("必须保留",),
    }
    cases = [
        {
            "workspace_name": "cwiki",
            "memory_type": "lesson",
            "tags": ["pinned"],
            "title": "t",
            "content": "必须保留",
        },
        {
            "workspace_name": "other",
            "memory_type": "lesson",
            "tags": ["pinned"],
            "title": "t",
            "content": "必须保留",
        },
        {
            "workspace_name": "cwiki",
            "memory_type": "fact",
            "tags": ["pinned"],
            "title": "t",
            "content": "必须保留",
        },
        {
            "workspace_name": "cwiki",
            "memory_type": "lesson",
            "tags": [],
            "title": "t",
            "content": "必须保留",
        },
        {
            "workspace_name": "cwiki",
            "memory_type": "lesson",
            "tags": ["pinned"],
            "title": "t",
            "content": "无关",
        },
    ]
    decision_rule = WriteDecisionRule(id="d", action="write", **fields)
    policy_rule = WriteRule(id="p", action="review", **fields)
    for case in cases:
        kwargs = {
            "workspace_name": case["workspace_name"],
            "workspace_id": "11111111-1111-1111-1111-111111111111",
            "memory_type": case["memory_type"],
            "memory_tags": case["tags"],
            "title": case["title"],
            "content": case["content"],
        }
        expected = matches_fields(**fields, **kwargs)
        assert (
            decision_rule.matches(
                workspace_name=case["workspace_name"],
                workspace_id="11111111-1111-1111-1111-111111111111",
                memory_type=case["memory_type"],
                tags=case["tags"],
                title=case["title"],
                content=case["content"],
            )
            == expected
        )
        assert (
            policy_rule.matches(
                workspace_name=case["workspace_name"],
                workspace_id="11111111-1111-1111-1111-111111111111",
                memory_type=case["memory_type"],
                tags=case["tags"],
                title=case["title"],
                content=case["content"],
            )
            == expected
        )
