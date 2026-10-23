"""SessionStart 写入决策注入测试。"""

from __future__ import annotations

from adapters.hooks import decisions as decisions_hint
from packages.domain.config import agent_policy_config
from packages.domain.write_decisions import WriteDecisionPolicy, WriteDecisionRule


def _policy(*rules: WriteDecisionRule, **kwargs) -> WriteDecisionPolicy:
    return WriteDecisionPolicy(
        enabled=kwargs.pop("enabled", True),
        default_action=kwargs.pop("default_action", "write"),
        rules=tuple(rules),
    )


def test_enabled_policy_injects_rules(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_policy_config,
        "write_decisions",
        _policy(
            WriteDecisionRule(
                id="r1",
                action="write",
                description="用户纠正必须记录",
                examples=("不要这样做",),
                workspaces=("cwiki",),
            ),
            WriteDecisionRule(
                id="r2",
                action="skip",
                description="其他工作区的规则",
                workspaces=("other",),
            ),
        ),
    )

    hint = decisions_hint.build_hint("cwiki")

    assert "cwiki 写入决策" in hint
    assert "用户纠正必须记录" in hint
    assert "其他工作区的规则" not in hint


def test_disabled_policy_falls_back_to_legacy_must_save(monkeypatch) -> None:
    monkeypatch.setattr(agent_policy_config, "write_decisions", WriteDecisionPolicy(enabled=False))
    monkeypatch.setattr(agent_policy_config, "must_save_types", ("feedback", "rule"))
    monkeypatch.setattr(agent_policy_config, "must_save_keywords", ("以后",))

    hint = decisions_hint.build_hint("cwiki")

    assert "cwiki 写入策略" in hint
    assert "feedback" in hint
    assert "以后" in hint


def test_no_policy_and_no_legacy_hint_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(agent_policy_config, "write_decisions", WriteDecisionPolicy(enabled=False))
    monkeypatch.setattr(agent_policy_config, "must_save_types", ())
    monkeypatch.setattr(agent_policy_config, "must_save_keywords", ())

    assert decisions_hint.build_hint("cwiki") == ""


def test_build_hint_fails_open(monkeypatch) -> None:
    monkeypatch.setattr(
        agent_policy_config,
        "write_decisions",
        _policy(WriteDecisionRule(id="r1", action="write")),
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("packages.domain.write_decisions.build_agent_hint", _boom)

    assert decisions_hint.build_hint("cwiki") == ""
