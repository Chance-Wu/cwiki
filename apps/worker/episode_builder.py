"""Episode 构建器——把事件流加工成 episode。"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EpisodeData:
    """从事件流中提取的结构化 episode 数据。"""

    goal: str = ""
    summary: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    solutions: list[dict[str, Any]] = field(default_factory=list)
    verification: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)
    # MQ-203: 上下文完整性检查
    is_partial: bool = False
    missing_context: list[str] = field(default_factory=list)
    # MQ-203: 区分已验证/推断/待确认
    verified_results: list[str] = field(default_factory=list)
    agent_inferences: list[str] = field(default_factory=list)
    pending_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化的 dict。"""
        return {
            "goal": self.goal,
            "summary": self.summary,
            "actions": self.actions,
            "problems": self.problems,
            "solutions": self.solutions,
            "verification": self.verification,
            "lessons": self.lessons,
            "is_partial": self.is_partial,
            "missing_context": self.missing_context,
            "verified_results": self.verified_results,
            "agent_inferences": self.agent_inferences,
            "pending_items": self.pending_items,
        }


def _extract_goal(events: list[dict[str, Any]]) -> str:
    """从 prompt.submitted 事件提取用户目标。"""
    for event in events:
        if event.get("event_type") == "prompt.submitted":
            payload = event.get("payload", {})
            content = payload.get("content", "")
            if content:
                return str(content)
    return ""


def _extract_actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取执行过的动作：工具调用与文件变更。"""
    actions: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        if event_type == "tool.completed":
            actions.append(
                {
                    "type": "tool_call",
                    "tool_name": payload.get("tool_name", "unknown"),
                    "tool_use_id": payload.get("tool_use_id"),
                    "input_summary": _summarize_tool_input(payload.get("input", {})),
                    "duration_ms": payload.get("duration_ms"),
                    "success": True,
                }
            )
        elif event_type == "file.changed":
            actions.append(
                {
                    "type": "file_change",
                    "path": payload.get("path", ""),
                    "operation": payload.get("operation", "modified"),
                    "success": True,
                }
            )

    return actions


def _extract_problems(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取遇到的问题：工具失败与测试失败。"""
    problems: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        if event_type == "tool.failed":
            problems.append(
                {
                    "type": "tool_failure",
                    "tool_name": payload.get("tool_name", "unknown"),
                    "error": payload.get("error", ""),
                    "input_summary": _summarize_tool_input(payload.get("input", {})),
                }
            )
        elif event_type == "test.failed":
            problems.append(
                {
                    "type": "test_failure",
                    "test_name": payload.get("test_name", ""),
                    "error": payload.get("error", payload.get("message", "")),
                    "details": payload.get("details", ""),
                }
            )

    return problems


def _extract_solutions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取解决方案：失败之后成功的修复操作。"""
    solutions: list[dict[str, Any]] = []

    had_failure = False
    # 只把"失败后紧随的编辑/写盘/命令"记为修复，避免把常规操作误判为解决方案
    for event in events:
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        if event_type in ("tool.failed", "test.failed"):
            had_failure = True
        elif event_type == "tool.completed" and had_failure:
            tool_name = payload.get("tool_name", "")
            if tool_name in ("Edit", "Write", "Bash"):
                solutions.append(
                    {
                        "type": "fix_applied",
                        "tool_name": tool_name,
                        "input_summary": _summarize_tool_input(payload.get("input", {})),
                        "resolved_after_failure": True,
                    }
                )
                had_failure = False
        elif event_type == "test.passed" and had_failure:
            solutions.append(
                {
                    "type": "test_fixed",
                    "test_name": payload.get("test_name", ""),
                    "resolved_after_failure": True,
                }
            )
            had_failure = False

    return solutions


def _extract_verification(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """提取测试结果与验证结论。"""
    verification: list[dict[str, Any]] = []

    for event in events:
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        if event_type == "test.passed":
            verification.append(
                {
                    "type": "test_passed",
                    "test_name": payload.get("test_name", ""),
                    "success": True,
                }
            )
        elif event_type == "test.failed":
            verification.append(
                {
                    "type": "test_failed",
                    "test_name": payload.get("test_name", ""),
                    "error": payload.get("error", payload.get("message", "")),
                    "success": False,
                }
            )

    return verification


def _summarize_tool_input(input_data: dict[str, Any]) -> str:
    """为提升可读性摘要工具输入。"""
    if not input_data:
        return ""

    if "command" in input_data:
        cmd = str(input_data["command"])
        return cmd[:200] if len(cmd) > 200 else cmd
    if "file_path" in input_data:
        return str(input_data["file_path"])
    if "path" in input_data:
        return str(input_data["path"])

    keys = list(input_data.keys())[:3]
    return f"({', '.join(keys)})"


def _calculate_importance(
    events: list[dict[str, Any]], problems: list[dict[str, Any]], solutions: list[dict[str, Any]]
) -> float:
    """根据事件类型与结果计算 episode 重要性。

    返回 0.0 到 1.0 之间的分值。
    """
    if not events:
        return 0.0

    score = 0.0

    event_type_weights = {
        "prompt.submitted": 0.1,
        "tool.completed": 0.05,
        "tool.failed": 0.15,
        "file.changed": 0.1,
        "test.passed": 0.1,
        "test.failed": 0.2,
        "subagent.started": 0.1,
        "subagent.completed": 0.1,
        "context.compacted": 0.05,
    }

    for event in events:
        event_type = event.get("event_type", "")
        weight = event_type_weights.get(event_type, 0.02)
        score += weight

    problem_bonus = len(problems) * 0.1
    solution_bonus = len(solutions) * 0.15
    score += problem_bonus + solution_bonus

    return min(score, 1.0)


def _generate_summary(episode: EpisodeData) -> str:
    """生成 episode 的人类可读摘要。"""
    parts = []

    if episode.goal:
        parts.append(f"Goal: {episode.goal}")

    if episode.actions:
        tool_names = set()
        file_paths = set()
        for action in episode.actions:
            if action.get("type") == "tool_call":
                tool_names.add(action.get("tool_name", ""))
            elif action.get("type") == "file_change":
                file_paths.add(action.get("path", ""))

        summary_parts = []
        if tool_names:
            summary_parts.append(f"Used tools: {', '.join(sorted(tool_names))}")
        if file_paths:
            summary_parts.append(f"Modified {len(file_paths)} file(s)")
        if summary_parts:
            parts.append("Actions: " + "; ".join(summary_parts))

    if episode.problems:
        parts.append(f"Encountered {len(episode.problems)} problem(s)")

    if episode.solutions:
        parts.append(f"Applied {len(episode.solutions)} solution(s)")

    if episode.verification:
        passed = sum(1 for v in episode.verification if v.get("success"))
        failed = len(episode.verification) - passed
        parts.append(f"Verification: {passed} passed, {failed} failed")

    return "\n".join(parts) if parts else "Episode with no notable activity"


def _derive_lessons(problems: list[dict[str, Any]], solutions: list[dict[str, Any]]) -> list[str]:
    """从问题与解决方案归纳初步经验教训。"""
    lessons: list[str] = []

    tool_failures = [p for p in problems if p.get("type") == "tool_failure"]
    test_failures = [p for p in problems if p.get("type") == "test_failure"]

    if tool_failures and solutions:
        lessons.append(f"Encountered {len(tool_failures)} tool failure(s) and resolved them")

    if test_failures:
        lessons.append(f"Tests failed {len(test_failures)} time(s) during development")

    return lessons


def _check_context_completeness(
    events: list[dict[str, Any]],
    problems: list[dict[str, Any]],
    solutions: list[dict[str, Any]],
    verification: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """MQ-203: 检查上下文完整性，标记缺失项。

    不凭空补齐——缺失就标记 partial，让下游决定是否补全或暂缓提炼。
    """
    missing: list[str] = []

    has_goal = any(e.get("event_type") == "prompt.submitted" for e in events)
    if not has_goal:
        missing.append("no_user_goal")

    if problems and not solutions:
        missing.append("problems_without_solutions")

    failed_tests = [v for v in verification if not v.get("success")]
    if failed_tests and not solutions:
        missing.append("failing_tests_without_fix")

    is_partial = len(missing) > 0
    return is_partial, missing


def _classify_results(
    verification: list[dict[str, Any]],
    solutions: list[dict[str, Any]],
    lessons: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """MQ-203: 区分已验证结果、Agent 推断与待确认事项。"""
    verified = [v.get("test_name", "unknown") for v in verification if v.get("success")]

    inferences = list(lessons)

    failed_tests = [v.get("test_name", "unknown") for v in verification if not v.get("success")]
    pending = list(failed_tests)

    return verified, inferences, pending


def build_episode(
    session_id: str,
    events: list[dict[str, Any]],
) -> EpisodeData:
    """从事件流构建 episode。

    按用户 prompt 边界组织事件，提取目标、汇总动作、
    跟踪问题与解决方案，并计算重要性。

    Args:
        session_id: episode 所属会话。
        events: 事件 dict 列表，按 sequence 排序。

    Returns:
        包含全部提取信息的 EpisodeData。
    """
    if not events:
        return EpisodeData()

    # 先按 sequence 排序，保证"失败→修复"等时序推断正确
    events_sorted = sorted(events, key=lambda e: e.get("sequence", 0))

    goal = _extract_goal(events_sorted)
    actions = _extract_actions(events_sorted)
    problems = _extract_problems(events_sorted)
    solutions = _extract_solutions(events_sorted)
    verification = _extract_verification(events_sorted)
    lessons = _derive_lessons(problems, solutions)

    # MQ-203: 上下文完整性检查与结果分类
    is_partial, missing_context = _check_context_completeness(
        events_sorted, problems, solutions, verification
    )
    verified_results, agent_inferences, pending_items = _classify_results(
        verification, solutions, lessons
    )

    episode = EpisodeData(
        goal=goal,
        summary="",
        actions=actions,
        problems=problems,
        solutions=solutions,
        verification=verification,
        lessons=lessons,
        is_partial=is_partial,
        missing_context=missing_context,
        verified_results=verified_results,
        agent_inferences=agent_inferences,
        pending_items=pending_items,
    )

    episode.summary = _generate_summary(episode)

    importance = _calculate_importance(events_sorted, problems, solutions)

    logger.info(
        f"Built episode for session {session_id}: "
        f"goal='{goal[:80]}', "
        f"{len(actions)} actions, "
        f"{len(problems)} problems, "
        f"{len(solutions)} solutions, "
        f"importance={importance:.2f}"
    )

    return episode
