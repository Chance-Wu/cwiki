"""写入决策：决定 Agent 提交的内容是否写入、拒绝或更新已有记忆。

配置位于 ``config.yaml`` 的 ``agent_policy.write_decisions``。规则按固定
优先级匹配：不写入（skip）> 更新（update）> 写入（write）；同组内按声明
顺序，命中第一条即停止；未命中使用 ``default_action``。匹配字段语义与
``memory.write_policy`` 共用 ``packages.domain.rule_match``。

“写入但需要人工审核”不在这里表达，统一由 ``memory.write_policy`` 管理。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from packages.domain.rule_match import (
    MAX_KEYWORD_VALUES,
    MAX_MATCH_VALUE_CHARS,
    MAX_MATCH_VALUES,
    MAX_REGEX_VALUES,
    matches_fields,
)

logger = logging.getLogger(__name__)


def _log_issue(quiet: bool, message: str, *args: Any) -> None:
    """草稿预览时降级为 debug，避免编辑过程中反复刷 warning。"""
    (logger.debug if quiet else logger.warning)(message, *args)


DecisionAction = Literal["write", "skip", "update"]
DefaultAction = Literal["write", "skip"]
_VALID_ACTIONS: frozenset[str] = frozenset({"write", "skip", "update"})
_VALID_DEFAULTS: frozenset[str] = frozenset({"write", "skip"})
_MATCH_KEYS: frozenset[str] = frozenset({"workspace", "type", "tags", "keyword", "regex"})
_ACTION_PRIORITY: dict[str, int] = {"skip": 0, "update": 1, "write": 2}

_ACTION_LABELS: dict[str, str] = {
    "write": "写入",
    "skip": "不写入",
    "update": "更新已有",
}
# 写入决策的硬限制；API 校验、注入摘要与前端计数器共用同一组数值
DEFAULT_MAX_HINT_CHARS = 800
MAX_DESCRIPTION_CHARS = 300
MAX_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 120
MAX_RULES = 30


@dataclass(frozen=True)
class Decision:
    """一次准入决策；rule_id 为空表示使用 default_action。"""

    action: DecisionAction
    rule_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class HintDetails:
    """会话注入摘要及其预算信息；截断时 shown_rules < total_rules。"""

    text: str
    max_chars: int
    shown_rules: int
    total_rules: int

    @property
    def length(self) -> int:
        return len(self.text)

    @property
    def truncated(self) -> bool:
        return self.shown_rules < self.total_rules


@dataclass(frozen=True)
class WriteDecisionRule:
    """一条写入决策规则；空匹配字段表示不限制该维度。"""

    id: str
    action: DecisionAction
    description: str = ""
    examples: tuple[str, ...] = ()
    workspaces: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    regexes: tuple[str, ...] = ()

    def matches(
        self,
        *,
        workspace_name: str,
        workspace_id: str,
        memory_type: str,
        tags: list[str],
        title: str,
        content: str,
    ) -> bool:
        return matches_fields(
            workspaces=self.workspaces,
            types=self.types,
            tags=self.tags,
            keywords=self.keywords,
            regexes=self.regexes,
            workspace_name=workspace_name,
            workspace_id=workspace_id,
            memory_type=memory_type,
            memory_tags=tags,
            title=title,
            content=content,
        )


@dataclass(frozen=True)
class WriteDecisionPolicy:
    """写入决策规则集合；未启用时始终返回 default_action。"""

    enabled: bool = False
    default_action: DefaultAction = "write"
    rules: tuple[WriteDecisionRule, ...] = ()

    def decide(
        self,
        *,
        workspace_name: str,
        workspace_id: str,
        memory_type: str,
        tags: list[str],
        title: str,
        content: str,
    ) -> Decision:
        if not self.enabled:
            return Decision(action=self.default_action)
        # 固定优先级：拒绝优先于更新，更新优先于写入；同组内按声明顺序
        for action in ("skip", "update", "write"):
            for rule in self.rules:
                if rule.action != action:
                    continue
                if rule.matches(
                    workspace_name=workspace_name,
                    workspace_id=workspace_id,
                    memory_type=memory_type,
                    tags=tags,
                    title=title,
                    content=content,
                ):
                    return Decision(
                        action=rule.action,
                        rule_id=rule.id,
                        reason=rule.description or None,
                    )
        return Decision(action=self.default_action)


def parse_write_decisions(raw: Any, *, quiet: bool = False) -> WriteDecisionPolicy:
    """解析配置；非法规则告警跳过，不影响其他规则与服务启动。"""
    if raw is None:
        return WriteDecisionPolicy()
    if not isinstance(raw, dict):
        _log_issue(quiet, "agent_policy.write_decisions 必须是映射，已忽略")
        return WriteDecisionPolicy()

    enabled = raw.get("enabled", False) is True
    default_raw = raw.get("default_action", "write")
    if isinstance(default_raw, str) and default_raw in _VALID_DEFAULTS:
        default_action = cast(DefaultAction, default_raw)
    else:
        _log_issue(quiet, "write_decisions.default_action 必须是 write/skip，已回退 write")
        default_action = "write"

    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        _log_issue(quiet, "write_decisions.rules 必须是列表，已忽略")
        return WriteDecisionPolicy(enabled=enabled, default_action=default_action)

    rules: list[WriteDecisionRule] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_rules):
        rule = _parse_rule(item, index, quiet=quiet)
        if rule is None:
            continue
        if rule.id.casefold() in seen:
            _log_issue(quiet, "write_decisions 规则 id 重复：%s（忽略后出现的规则）", rule.id)
            continue
        seen.add(rule.id.casefold())
        rules.append(rule)

    return WriteDecisionPolicy(
        enabled=enabled,
        default_action=default_action,
        rules=tuple(rules),
    )


def build_agent_hint_details(
    policy: WriteDecisionPolicy,
    workspace_name: str = "",
    *,
    max_chars: int = DEFAULT_MAX_HINT_CHARS,
) -> HintDetails:
    """生成注入摘要与预算细节；纯函数，API 预览与 hook 共用。"""
    if not policy.enabled:
        return HintDetails(text="", max_chars=max_chars, shown_rules=0, total_rules=0)

    applicable = [
        rule
        for rule in policy.rules
        if not workspace_name
        or not rule.workspaces
        or any(item.casefold() == workspace_name.strip().casefold() for item in rule.workspaces)
    ]
    applicable.sort(key=lambda rule: _ACTION_PRIORITY.get(rule.action, 9))

    default_label = _ACTION_LABELS.get(policy.default_action, policy.default_action)
    header = f"cwiki 写入决策（优先级：不写入 > 更新 > 写入；未命中：{default_label}）："
    footer = "\n规则只决定是否写入/更新；写入后的审核在 write_policy 中配置，查重与格式仍遵循 cwiki-save skill。"

    lines: list[str] = []
    for rule in applicable:
        description = (rule.description.strip() or rule.id)[:120]
        examples = [item[:80] for item in rule.examples[:2]]
        line = f"- [{_ACTION_LABELS.get(rule.action, rule.action)}] {description}"
        if examples:
            line += "｜例：" + "；".join(examples)
        lines.append(line)

    if not lines:
        lines.append("（未配置规则，按 cwiki-save skill 判断）")

    # 预留“另有 N 条”与 footer 的空间，避免摘要超预算后截断关键说明
    reserve = 32
    budget = max(120, max_chars - len(header) - len(footer) - reserve)
    shown: list[str] = []
    used = 0
    for line in lines:
        if shown and used + len(line) + 1 > budget:
            break
        shown.append(line)
        used += len(line) + 1

    remaining = len(applicable) - len(shown)
    text = header + "\n" + "\n".join(shown)
    if remaining > 0:
        text += f"\n（另有 {remaining} 条规则未展示）"
    text += footer
    return HintDetails(
        text=text[:max_chars],
        max_chars=max_chars,
        shown_rules=len(shown),
        total_rules=len(applicable),
    )


def build_agent_hint(
    policy: WriteDecisionPolicy,
    workspace_name: str = "",
    *,
    max_chars: int = DEFAULT_MAX_HINT_CHARS,
) -> str:
    """生成 SessionStart 注入摘要；纯函数，API 预览与 hook 共用。"""
    return build_agent_hint_details(policy, workspace_name, max_chars=max_chars).text


def _parse_rule(item: Any, index: int, *, quiet: bool = False) -> WriteDecisionRule | None:
    if not isinstance(item, dict):
        _log_issue(quiet, "write_decisions.rules[%d] 必须是映射，已跳过", index)
        return None

    rule_id = item.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        _log_issue(quiet, "write_decisions.rules[%d] 缺少非空 id，已跳过", index)
        return None

    action_raw = item.get("action")
    if not isinstance(action_raw, str) or action_raw not in _VALID_ACTIONS:
        _log_issue(
            quiet,
            "write_decisions 规则 %s 的 action 必须是 write/skip/update，已跳过",
            rule_id,
        )
        return None

    match_raw = item.get("match", {})
    if match_raw is None:
        match_raw = {}
    if not isinstance(match_raw, dict):
        _log_issue(quiet, "write_decisions 规则 %s 的 match 必须是映射，已跳过", rule_id)
        return None
    unknown = set(match_raw) - _MATCH_KEYS
    if unknown:
        _log_issue(
            quiet,
            "write_decisions 规则 %s 含未知匹配字段 %s，已跳过",
            rule_id,
            sorted(unknown),
        )
        return None

    workspaces = _as_strings(
        match_raw.get("workspace"), field="workspace", rule_id=rule_id, quiet=quiet
    )
    types = _as_strings(match_raw.get("type"), field="type", rule_id=rule_id, quiet=quiet)
    tags = _as_strings(match_raw.get("tags"), field="tags", rule_id=rule_id, quiet=quiet)
    keywords = _as_strings(match_raw.get("keyword"), field="keyword", rule_id=rule_id, quiet=quiet)
    regexes = _as_strings(match_raw.get("regex"), field="regex", rule_id=rule_id, quiet=quiet)
    if workspaces is None or types is None or tags is None or keywords is None or regexes is None:
        return None

    if (
        len(workspaces) > MAX_MATCH_VALUES
        or len(types) > MAX_MATCH_VALUES
        or len(tags) > MAX_MATCH_VALUES
        or len(keywords) > MAX_KEYWORD_VALUES
        or len(regexes) > MAX_REGEX_VALUES
    ):
        _log_issue(quiet, "write_decisions 规则 %s 的匹配值数量超过上限，已跳过", rule_id)
        return None

    if not _valid_regexes(regexes, rule_id=rule_id, quiet=quiet):
        return None

    if not (workspaces or types or tags or keywords or regexes):
        _log_issue(quiet, "write_decisions 规则 %s 没有匹配条件，将匹配所有候选", rule_id)

    description_raw = item.get("description")
    description = (
        description_raw.strip()[:MAX_DESCRIPTION_CHARS]
        if isinstance(description_raw, str) and description_raw.strip()
        else ""
    )
    examples_raw = item.get("examples")
    examples = _as_examples(examples_raw, rule_id=rule_id, quiet=quiet)

    return WriteDecisionRule(
        id=rule_id.strip(),
        action=cast(DecisionAction, action_raw),
        description=description,
        examples=examples,
        workspaces=workspaces,
        types=types,
        tags=tags,
        keywords=keywords,
        regexes=regexes,
    )


def _valid_regexes(regexes: tuple[str, ...], *, rule_id: str, quiet: bool = False) -> bool:
    """解析期编译校验：一条非法正则就跳过整条规则，避免维度退化成不限制。"""
    for pattern in regexes:
        try:
            re.compile(pattern)
        except re.error as exc:
            _log_issue(
                quiet,
                "write_decisions 规则 %s 的正则 %r 无效（%s），已跳过整条规则",
                rule_id,
                pattern,
                exc,
            )
            return False
    return True


def _as_strings(
    value: Any, *, field: str, rule_id: str, quiet: bool = False
) -> tuple[str, ...] | None:
    """规范化为去空白、去重后的元组（保留原始大小写）。"""
    if value is None:
        return ()
    values: Any = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        _log_issue(
            quiet,
            "write_decisions 规则 %s 的 match.%s 必须是字符串或字符串列表，已跳过",
            rule_id,
            field,
        )
        return None
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            _log_issue(
                quiet,
                "write_decisions 规则 %s 的 match.%s 含非字符串或空值，已跳过",
                rule_id,
                field,
            )
            return None
        text = item.strip()
        if len(text) > MAX_MATCH_VALUE_CHARS:
            _log_issue(
                quiet,
                "write_decisions 规则 %s 的 match.%s 含超过 %d 字符的值，已跳过",
                rule_id,
                field,
                MAX_MATCH_VALUE_CHARS,
            )
            return None
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def _as_examples(value: Any, *, rule_id: str, quiet: bool = False) -> tuple[str, ...]:
    if value is None:
        return ()
    values: Any = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        _log_issue(quiet, "write_decisions 规则 %s 的 examples 必须是列表，已忽略", rule_id)
        return ()
    result: list[str] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            result.append(item.strip()[:MAX_EXAMPLE_CHARS])
        if len(result) >= MAX_EXAMPLES:
            break
    return tuple(result)
