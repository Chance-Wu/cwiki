"""写入策略：在候选创建阶段决定自动生效、强制人工审核或拒绝。

配置位于 ``config.yaml`` 的 ``memory.write_policy``。规则按声明顺序匹配，
命中第一条即停止；所有匹配字段之间是 AND 关系，同一个字段内的多个值：

- ``type`` / ``workspace``：任一命中即可（OR）
- ``tags``：必须全部存在（AND）
- ``keyword`` / ``regex``：正文或标题命中任意一个即可（OR，二者合并为文本维度）
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

PolicyAction = Literal["auto", "review", "reject"]
_VALID_ACTIONS: frozenset[str] = frozenset({"auto", "review", "reject"})
_MATCH_KEYS: frozenset[str] = frozenset({"workspace", "type", "tags", "keyword", "regex"})


@dataclass(frozen=True)
class PolicyDecision:
    """命中规则后的决策，随候选持久化用于审计。"""

    rule_id: str
    action: PolicyAction
    reason: str | None = None


@dataclass(frozen=True)
class WriteRule:
    """一条写入规则；空匹配字段表示不限制该维度。"""

    id: str
    action: PolicyAction
    reason: str | None = None
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
class WritePolicy:
    """写入策略集合；未启用或未命中时返回 None，沿用全局审核配置。"""

    enabled: bool = False
    rules: tuple[WriteRule, ...] = ()

    def decide(
        self,
        *,
        workspace_name: str,
        workspace_id: str,
        memory_type: str,
        tags: list[str],
        title: str,
        content: str,
    ) -> PolicyDecision | None:
        if not self.enabled:
            return None
        for rule in self.rules:
            if rule.matches(
                workspace_name=workspace_name,
                workspace_id=workspace_id,
                memory_type=memory_type,
                tags=tags,
                title=title,
                content=content,
            ):
                return PolicyDecision(rule_id=rule.id, action=rule.action, reason=rule.reason)
        return None


def parse_write_policy(raw: Any) -> WritePolicy:
    """解析配置；非法规则跳过并告警，不影响其他规则与服务启动。"""
    if raw is None:
        return WritePolicy()
    if not isinstance(raw, dict):
        logger.warning("memory.write_policy 必须是映射，已忽略")
        return WritePolicy()

    enabled = raw.get("enabled", False) is True
    raw_rules = raw.get("rules", [])
    if not isinstance(raw_rules, list):
        logger.warning("memory.write_policy.rules 必须是列表，已忽略")
        return WritePolicy(enabled=enabled)

    rules: list[WriteRule] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_rules):
        rule = _parse_rule(item, index)
        if rule is None:
            continue
        if rule.id.casefold() in seen:
            logger.warning("write_policy 规则 id 重复：%s（忽略后出现的规则）", rule.id)
            continue
        seen.add(rule.id.casefold())
        rules.append(rule)

    return WritePolicy(enabled=enabled, rules=tuple(rules))


def _parse_rule(item: Any, index: int) -> WriteRule | None:
    if not isinstance(item, dict):
        logger.warning("write_policy.rules[%d] 必须是映射，已跳过", index)
        return None

    rule_id = item.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        logger.warning("write_policy.rules[%d] 缺少非空 id，已跳过", index)
        return None

    action_raw = item.get("action")
    if not isinstance(action_raw, str) or action_raw not in _VALID_ACTIONS:
        logger.warning("write_policy 规则 %s 的 action 必须是 auto/review/reject，已跳过", rule_id)
        return None

    match_raw = item.get("match", {})
    if match_raw is None:
        match_raw = {}
    if not isinstance(match_raw, dict):
        logger.warning("write_policy 规则 %s 的 match 必须是映射，已跳过", rule_id)
        return None
    unknown = set(match_raw) - _MATCH_KEYS
    if unknown:
        logger.warning(
            "write_policy 规则 %s 含未知匹配字段 %s，已跳过",
            rule_id,
            sorted(unknown),
        )
        return None

    reason = item.get("reason")
    reason_value = reason.strip() if isinstance(reason, str) and reason.strip() else None

    workspaces = _as_strings(match_raw.get("workspace"), field="workspace", rule_id=rule_id)
    types = _as_strings(match_raw.get("type"), field="type", rule_id=rule_id)
    tags = _as_strings(match_raw.get("tags"), field="tags", rule_id=rule_id)
    keywords = _as_strings(match_raw.get("keyword"), field="keyword", rule_id=rule_id)
    regexes = _as_strings(match_raw.get("regex"), field="regex", rule_id=rule_id)
    if workspaces is None or types is None or tags is None or keywords is None or regexes is None:
        return None

    if (
        len(workspaces) > MAX_MATCH_VALUES
        or len(types) > MAX_MATCH_VALUES
        or len(tags) > MAX_MATCH_VALUES
        or len(keywords) > MAX_KEYWORD_VALUES
        or len(regexes) > MAX_REGEX_VALUES
    ):
        logger.warning("write_policy 规则 %s 的匹配值数量超过上限，已跳过", rule_id)
        return None

    for pattern in regexes:
        try:
            re.compile(pattern)
        except re.error as exc:
            logger.warning(
                "write_policy 规则 %s 的正则 %r 无效（%s），已跳过整条规则",
                rule_id,
                pattern,
                exc,
            )
            return None

    if not (workspaces or types or tags or keywords or regexes):
        logger.warning("write_policy 规则 %s 没有匹配条件，将匹配所有候选", rule_id)

    return WriteRule(
        id=rule_id.strip(),
        action=cast(PolicyAction, action_raw),
        reason=reason_value,
        workspaces=workspaces,
        types=types,
        tags=tags,
        keywords=keywords,
        regexes=regexes,
    )


def _as_strings(value: Any, *, field: str, rule_id: str) -> tuple[str, ...] | None:
    """把字符串或字符串列表规范化为去空白、去重后的元组（保留原始大小写）。

    非法类型返回 None 并告警——宁可跳过整条规则，也不能让字段类型错误
    退化成"该维度不限制"从而匹配全部内容。
    """
    if value is None:
        return ()
    values: Any = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)):
        logger.warning(
            "write_policy 规则 %s 的 match.%s 必须是字符串或字符串列表，已跳过",
            rule_id,
            field,
        )
        return None
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str) or not item.strip():
            logger.warning(
                "write_policy 规则 %s 的 match.%s 含非字符串或空值，已跳过",
                rule_id,
                field,
            )
            return None
        text = item.strip()
        if len(text) > MAX_MATCH_VALUE_CHARS:
            logger.warning(
                "write_policy 规则 %s 的 match.%s 含超过 %d 字符的值，已跳过",
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
