"""写入策略规则解析与匹配测试。"""

from __future__ import annotations

import logging

from packages.domain.write_policy import PolicyDecision, WritePolicy, WriteRule, parse_write_policy


def _decide(policy: WritePolicy, **overrides) -> PolicyDecision | None:
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


def test_disabled_policy_never_matches() -> None:
    policy = parse_write_policy({"enabled": False, "rules": [{"id": "r1", "action": "auto"}]})
    assert policy.enabled is False
    assert [rule.id for rule in policy.rules] == ["r1"]
    assert _decide(policy) is None


def test_empty_match_matches_everything() -> None:
    policy = WritePolicy(enabled=True, rules=(WriteRule(id="all", action="reject"),))
    decision = _decide(policy)
    assert decision is not None
    assert decision.rule_id == "all"
    assert decision.action == "reject"


def test_first_matching_rule_wins() -> None:
    policy = WritePolicy(
        enabled=True,
        rules=(
            WriteRule(id="reject-errors", action="reject", types=("issue",)),
            WriteRule(id="catch-all", action="review"),
        ),
    )
    decision = _decide(policy, memory_type="issue")
    assert decision is not None
    assert decision.rule_id == "reject-errors"


def test_match_combines_fields_with_and() -> None:
    rule = WriteRule(
        id="pinned",
        action="auto",
        workspaces=("cwiki",),
        types=("decision", "lesson"),
        tags=("pinned",),
        keywords=("必须保留",),
    )
    policy = WritePolicy(enabled=True, rules=(rule,))

    assert _decide(policy) is not None
    assert _decide(policy, workspace_name="other") is None
    assert _decide(policy, memory_type="fact") is None
    assert _decide(policy, tags=["cwiki"]) is None
    assert _decide(policy, content="无关内容") is None


def test_workspace_matches_uuid() -> None:
    policy = WritePolicy(
        enabled=True,
        rules=(
            WriteRule(
                id="uuid", action="review", workspaces=("22222222-2222-2222-2222-222222222222",)
            ),
        ),
    )
    decision = _decide(policy, workspace_id="22222222-2222-2222-2222-222222222222")
    assert decision is not None
    assert decision.rule_id == "uuid"


def test_keyword_is_case_insensitive_and_any_value() -> None:
    rule = WriteRule(id="kw", action="review", keywords=("econnreset", "口径"))
    policy = WritePolicy(enabled=True, rules=(rule,))

    assert _decide(policy, content="Error: ECONNRESET") is not None
    assert _decide(policy, title="口径说明", content="正文") is not None
    assert _decide(policy, title="其他", content="无关") is None


def test_tags_require_all_values() -> None:
    rule = WriteRule(id="tags", action="auto", tags=("pinned", "cwiki"))
    policy = WritePolicy(enabled=True, rules=(rule,))

    assert _decide(policy, tags=["cwiki", "pinned", "extra"]) is not None
    assert _decide(policy, tags=["pinned"]) is None


def test_parse_normalizes_scalar_values() -> None:
    policy = parse_write_policy(
        {
            "enabled": True,
            "rules": [
                {
                    "id": " r1 ",
                    "action": "auto",
                    "reason": " 用户指定 ",
                    "match": {"workspace": " CWiki ", "type": "Decision", "tags": "Pinned"},
                }
            ],
        }
    )
    assert policy.enabled is True
    (rule,) = policy.rules
    assert rule.id == "r1"
    assert rule.reason == "用户指定"
    # 保留原始大小写便于展示，匹配时再统一 casefold
    assert rule.workspaces == ("CWiki",)
    assert rule.types == ("Decision",)
    assert rule.tags == ("Pinned",)


def test_parse_skips_invalid_rules(caplog) -> None:
    caplog.set_level(logging.WARNING)
    policy = parse_write_policy(
        {
            "enabled": True,
            "rules": [
                {"action": "auto"},
                {"id": "bad-action", "action": "delete"},
                {"id": "bad-match", "action": "auto", "match": {"tags": ["x"], "typo": "y"}},
                {"id": "bad-tags-type", "action": "auto", "match": {"tags": {"x": "y"}}},
                {"id": "ok", "action": "review"},
            ],
        }
    )
    assert [rule.id for rule in policy.rules] == ["ok"]
    assert "缺少非空 id" in caplog.text
    assert "action 必须是" in caplog.text
    assert "未知匹配字段" in caplog.text
    assert "必须是字符串或字符串列表" in caplog.text


def test_parse_keeps_first_duplicate_id(caplog) -> None:
    caplog.set_level(logging.WARNING)
    policy = parse_write_policy(
        {
            "enabled": True,
            "rules": [
                {"id": "dup", "action": "auto"},
                {"id": "dup", "action": "reject"},
            ],
        }
    )
    assert [rule.action for rule in policy.rules] == ["auto"]
    assert "规则 id 重复" in caplog.text
