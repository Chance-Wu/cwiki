"""候选记忆质量门（规范 8.1-8.2 节）。

按五项准则计算 quality_gate_score 与 quality_gate_reason：
stable（稳定）、reusable（可复用）、actionable（可执行）、
scoped（聚焦）、evidence-backed（有依据）。

质量门决定复核优先级，而非自动通过。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 各类型的「稳定性」基础分：约束/规则类长期有效得分高，fact/reference 易过时得分低
_STABLE_TYPE_BASE: dict[str, float] = {
    "constraint": 0.9,
    "rule": 0.85,
    "decision": 0.85,
    "convention": 0.8,
    "lesson": 0.75,
    "pattern": 0.7,
    "procedure": 0.7,
    "issue": 0.6,
    "feedback": 0.55,
    "reference": 0.5,
    "fact": 0.5,
}

# 绝对化措辞意味着规律性强、不易失效，稳定性加分
_STABILITY_KEYWORDS = [
    "always",
    "never",
    "must",
    "must not",
    "必须",
    "禁止",
    "不得",
    "不能",
    "始终",
]

# 出现跨上下文关键词说明知识可跨会话/项目复用
_REUSE_CONTEXT_KEYWORDS = [
    "session",
    "project",
    "team",
    "workspace",
    "deploy",
    "migrate",
    "会话",
    "项目",
    "团队",
    "部署",
    "迁移",
    "环境",
]

# 可执行内容通常含动作动词（中英文）
_ACTION_VERBS = [
    "use",
    "do",
    "avoid",
    "ensure",
    "check",
    "run",
    "set",
    "create",
    "delete",
    "update",
    "verify",
    "test",
    "configure",
    "使用",
    "避免",
    "确保",
    "检查",
    "运行",
    "设置",
    "创建",
    "删除",
    "验证",
    "测试",
    "配置",
]

# 信号类型 → 证据可信度：纠正/调试结论有真实失败背书，得分最高
_EVIDENCE_SIGNAL_MAP: dict[str, float] = {
    "correction": 0.8,
    "debug_resolution": 0.75,
    "decision": 0.65,
    "pattern": 0.6,
    "fact": 0.5,
    "other": 0.3,
}


@dataclass
class ExclusionResult:
    excluded: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"excluded": self.excluded, "reason": self.reason}


def _looks_like_code(line: str) -> bool:
    """判断一行文本是否形似代码（用于识别可从代码推导的内容）。"""
    line = line.strip()
    if not line:
        return False
    code_prefixes = (
        "import ",
        "from ",
        "class ",
        "def ",
        "function ",
        "const ",
        "let ",
        "var ",
        "public ",
        "private ",
        "return ",
        "if ",
        "for ",
        "while ",
        "package ",
        "module ",
        "require(",
        "#include",
    )
    if any(line.startswith(p) for p in code_prefixes):
        return True
    if re.match(r"^[a-z_]+:\s*\S+$", line):
        return True
    if re.match(r"^[/A-Z]:\\?[\w./\\-]+$", line):
        return True
    return line.startswith(("//", "/*", "*"))


def check_exclusion_list(title: str, content: str) -> ExclusionResult:
    """排除规则：过短或大段代码的内容不入库。

    质量门之前的硬性过滤——可从代码/git 直接推导的信息没有记忆价值。
    """
    stripped = content.strip()
    if len(stripped) < 30:
        return ExclusionResult(True, "too_short_for_memory")

    lines = stripped.splitlines()
    non_empty = [l for l in lines if l.strip()]
    if non_empty:
        # 代码形行占比超过 80% 视为代码片段
        code_like = sum(1 for l in non_empty if _looks_like_code(l))
        if code_like / len(non_empty) > 0.8:
            return ExclusionResult(True, "code_derivable")

    return ExclusionResult(False, "")


@dataclass
class QualityGateResult:
    score: float
    reason: str
    review_priority: float
    criteria: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality_gate_score": round(self.score, 4),
            "quality_gate_reason": self.reason,
            "review_priority": round(self.review_priority, 4),
            "criteria": {k: round(v, 4) for k, v in self.criteria.items()},
        }


def compute_quality_gate(candidate: dict[str, Any]) -> QualityGateResult:
    """计算五项准则得分并汇总为质量门结果（取平均，不设否决）。"""
    criteria = {
        "stable": _score_stable(candidate),
        "reusable": _score_reusable(candidate),
        "actionable": _score_actionable(candidate),
        "scoped": _score_scoped(candidate),
        "evidence_backed": _score_evidence_backed(candidate),
    }

    score = sum(criteria.values()) / len(criteria)
    reason = _build_reason(criteria)
    review_priority = _compute_review_priority(score, criteria)

    return QualityGateResult(
        score=score,
        reason=reason,
        review_priority=review_priority,
        criteria=criteria,
    )


def _score_stable(candidate: dict[str, Any]) -> float:
    """稳定性：内容是否会很快失效。含版本号的语句容易随版本过时。"""
    memory_type = candidate.get("type", "")
    content = candidate.get("content", "")
    content_lower = content.lower()

    base = _STABLE_TYPE_BASE.get(memory_type, 0.5)

    if len(content) > 100:
        base += 0.05
    if len(content) > 300:
        base += 0.05

    if any(kw in content_lower for kw in _STABILITY_KEYWORDS):
        base += 0.05

    has_version = bool(re.search(r"v?\d+\.\d+|version|版本", content_lower))
    if has_version:
        base -= 0.05

    return min(max(base, 0.0), 1.0)


def _score_reusable(candidate: dict[str, Any]) -> float:
    """可复用性：是否跨上下文有效、结构是否便于引用。"""
    content = candidate.get("content", "")
    content_lower = content.lower()
    length = len(content)

    # 过短内容几乎不具复用价值，直接给低分
    if length < 20:
        return 0.2

    base = 0.4

    if any(kw in content_lower for kw in _REUSE_CONTEXT_KEYWORDS):
        base += 0.15

    if length > 80:
        base += 0.1
    if length > 200:
        base += 0.1
    if length > 500:
        base += 0.05

    has_code = bool(re.search(r"`[^`]+`|```", content))
    if has_code:
        base += 0.1

    has_example = bool(re.search(r"例如|比如|example|e\.g\.|for example", content_lower))
    if has_example:
        base += 0.1

    return min(max(base, 0.0), 1.0)


def _score_actionable(candidate: dict[str, Any]) -> float:
    """可执行性：按动词密度、结构化程度、条件从句与 why/how 标记评估。"""
    content = candidate.get("content", "")
    content_lower = content.lower()

    verb_count = sum(1 for w in _ACTION_VERBS if w in content_lower)
    verb_score = min(0.3 + verb_count * 0.1, 0.7)

    structure_score = 0.0
    if re.search(r"^[-*]\s|^\d+[.)]\s", content, re.MULTILINE):
        structure_score += 0.15
    if re.search(r"`[^`]+`|```", content):
        structure_score += 0.1
    if re.search(r"^#{1,4}\s", content, re.MULTILINE):
        structure_score += 0.05

    conditional = bool(
        re.search(
            r"if |when |unless |在.*时|如果|当.*时",
            content_lower,
        )
    )
    conditional_bonus = 0.1 if conditional else 0.0

    has_why = bool(re.search(r"\*\*why\*\*|原因|因为|why:|\*\*Why:\*\*", content_lower))
    has_how = bool(re.search(r"\*\*how|应用|何时|when|how to|\*\*How", content_lower))
    if has_why and has_how:
        structure_bonus = 0.15
    elif has_why or has_how:
        structure_bonus = 0.05
    else:
        structure_bonus = 0.0

    return min(verb_score + structure_score + conditional_bonus + structure_bonus, 1.0)


def _score_scoped(candidate: dict[str, Any]) -> float:
    """聚焦度：单条记忆应聚焦单一主题，篇幅大且多主题的扣分。"""
    content = candidate.get("content", "").strip()
    length = len(content)

    if length < 10:
        return 0.1
    if length < 20:
        return 0.3
    if length < 50:
        return 0.6

    # 标题超过 5 个说明内容大而杂，聚焦度低
    topic_count = len(re.findall(r"^#{1,4}\s", content, re.MULTILINE))
    if topic_count > 5:
        return 0.5

    return 0.85


def _score_evidence_backed(candidate: dict[str, Any]) -> float:
    """有依据性：外部证据给高分；无证据时按正文内证与信号类型递减。"""
    evidences = candidate.get("evidences", [])
    evidence_count = len(evidences) if isinstance(evidences, list) else 0

    if evidence_count >= 3:
        return 1.0
    if evidence_count == 2:
        return 0.8
    if evidence_count == 1:
        return 0.55

    content = candidate.get("content", "")
    internal_evidence = 0
    if re.search(r"\d+%|\d+\.\d+x|\d+\s*ms|\d+\s*秒", content):
        internal_evidence += 1
    if re.search(r"error|exception|traceback|报错|异常|堆栈", content.lower()):
        internal_evidence += 1
    if re.search(r"git\s+commit|commit\s+[a-f0-9]|PR\s*#?\d+|issue\s*#?\d+", content.lower()):
        internal_evidence += 1

    if internal_evidence >= 2:
        return 0.6
    if internal_evidence == 1:
        return 0.4

    signal_type = candidate.get("signal_type", "")
    if signal_type:
        return _EVIDENCE_SIGNAL_MAP.get(signal_type, 0.3)

    return 0.2


def _build_reason(criteria: dict[str, float]) -> str:
    """把强项/弱项汇总成可读的 reason 字符串。"""
    strengths: list[str] = []
    weaknesses: list[str] = []

    for name, value in criteria.items():
        if value >= 0.7:
            strengths.append(name)
        elif value < 0.4:
            weaknesses.append(name)

    parts: list[str] = []
    if strengths:
        parts.append(f"Strengths: {', '.join(strengths)}")
    if weaknesses:
        parts.append(f"Weaknesses: {', '.join(weaknesses)}")

    return "; ".join(parts) if parts else "Balanced candidate"


def _compute_review_priority(score: float, criteria: dict[str, float]) -> float:
    """得分越低越需要人工把关，复核优先级越高。"""
    values = list(criteria.values())
    variance = sum((v - score) ** 2 for v in values) / len(values)

    base: float
    if score >= 0.8:
        base = 0.2
    elif score >= 0.6:
        base = 0.5
    elif score >= 0.4:
        base = 0.7
    else:
        base = 0.9

    # 准则间方差大说明评分不稳定（各维度表现悬殊），优先级上调
    if variance > 0.04:
        base = min(base + 0.1, 1.0)

    return base
