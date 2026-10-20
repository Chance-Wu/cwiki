"""记忆提取的信号检测规则与事件分析。

纯函数集合——不依赖 MCPServer、CwikiClient 或传输层，便于单测与复用。
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from packages.domain.config import settings
from packages.domain.types import MIN_CONTENT_LENGTH

try:
    from packages.memory.type_classifier import infer_memory_type
except ImportError:
    infer_memory_type = None  # type: ignore[assignment]

try:
    from adapters.mcp.content_processing import (
        auto_title,
        extract_keywords,
        is_test_content,
    )
except ImportError:

    def auto_title(content: str, max_len: int = 60) -> str:
        first_line = content.strip().splitlines()[0] if content.strip() else "记忆"
        return first_line[:max_len]

    def extract_keywords(texts: list[str], top_n: int = 5) -> list[str]:
        return []

    def is_test_content(content: str) -> bool:
        return False


MAX_FAILURE_CANDIDATES = 2
CONTENT_PREVIEW_LENGTH = 200
AUTO_GROUP_SIGNAL_TYPE = "auto_group"

_NOTE_TYPE_MAP: dict[str, str] = {
    "convention": "convention",
    "feedback": "feedback",
    "decision": "decision",
    "issue": "issue",
    "pattern": "pattern",
    "procedure": "procedure",
    "reference": "reference",
    "fact": "fact",
    "constraint": "constraint",
    "lesson": "lesson",
    "rule": "rule",
}

# (trigger_reasons, keywords, memory_type, min_len)
# None = 不限触发来源，关键词匹配即可；具体 trigger_reason 仅在对应检查点触发
_SIGNAL_RULES: list[tuple[str | None, list[str], str, int]] = [
    # --- 特定触发来源（优先匹配，避免被通用规则抢占）---
    (
        "user_correction",
        [
            "不要",
            "不应该",
            "必须",
            "应该",
            "错了",
            "纠正",
            "不对",
            "别这样",
            "以后",
            "记住",
            "别忘了",
        ],
        "feedback",
        20,
    ),
    (
        "technical_decision",
        ["选择", "决定", "方案", "架构", "设计", "改用", "选型", "取舍", "权衡", "不如"],
        "decision",
        30,
    ),
    (
        "problem_solved",
        ["修复", "解决", "根因", "搞定", "通了", "原因找到", "修好了"],
        "issue",
        30,
    ),
    (
        "convention_discovered",
        ["规范", "约定", "命名", "统一", "必须遵守", "项目特有", "写法", "模式"],
        "convention",
        25,
    ),
    # --- 通用信号（任何检查点触发时均可匹配）---
    (
        None,
        ["踩坑", "workaround", "变通", "经验", "教训", "下次", "不要再", "原来"],
        "lesson",
        25,
    ),
    (
        None,
        ["报错", "异常", "失败", "排查", "根因", "堆栈", "traceback", "错误信息"],
        "issue",
        30,
    ),
    (
        None,
        ["必须", "禁止", "不能", "不允许", "严禁", "红线", "安全", "合规"],
        "rule",
        20,
    ),
    (
        None,
        ["版本", "兼容", "环境", "依赖", "平台", "升级", "不兼容", "适配"],
        "constraint",
        25,
    ),
    (
        None,
        ["文档", "链接", "参考", "入口", "官网", "API 地址", "工具地址"],
        "reference",
        20,
    ),
    (
        None,
        ["部署", "迁移", "安装", "配置步骤", "操作步骤", "测试策略", "发布流程"],
        "procedure",
        25,
    ),
]

_ANALYSIS_HINT = (
    "这是有限的已采集事件报告，不等于完整对话的语义检查。\n"
    "报告中的摘要和预览可能截短，不能替代来源正文。\n"
    "检索、提取质量、查重更新和提交时机统一遵循 cwiki-save skill；"
    "工具参数和投递状态以当前工具契约为准。"
)


def classify_memory_type(content: str) -> str:
    """用配置的类型分类器推断记忆类型，无法推断时回落 'fact'。"""
    if infer_memory_type is not None:
        return infer_memory_type(content)
    return "fact"


def summarize_notes_by_type(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in notes:
        if n.get("signal_type") == AUTO_GROUP_SIGNAL_TYPE:
            continue
        if not n.get("formalized", False):
            grouped[n.get("signal_type", "other")].append(n)

    summaries = []
    for signal_type, group in sorted(grouped.items(), key=lambda x: -len(x[1])):
        contents = [n.get("content", "") for n in group]
        keywords = extract_keywords(contents)
        summaries.append(
            {
                "signal_type": signal_type,
                "count": len(group),
                "keywords": keywords,
                "sample": contents[0][:CONTENT_PREVIEW_LENGTH] if contents else "",
                "suggestion": (
                    f"{len(group)} 条 {signal_type} 信号"
                    + (f"，关键词：{', '.join(keywords[:3])}" if keywords else "")
                ),
            }
        )
    return summaries


def extract_context_around_keyword(text: str, keywords: list[str], max_chars: int = 400) -> str:
    """提取关键词周围的上下文，而非简单截断。"""
    for kw in keywords:
        idx = text.find(kw)
        if idx == -1:
            continue
        start = max(0, idx - 100)
        end = min(len(text), idx + max_chars - 100)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        return snippet
    return text[:max_chars]


def extract_memories_from_events(
    events: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    trigger_reason: str,
) -> list[dict[str, Any]]:
    """从事件流和会话笔记中提取记忆候选。纯规则匹配，不调用 LLM。"""
    candidates: list[dict[str, Any]] = []

    # 1. 未整理的会话笔记 → 直接转为候选记忆
    unformalized = [
        n
        for n in notes
        if not n.get("formalized", False) and n.get("signal_type") != AUTO_GROUP_SIGNAL_TYPE
    ]
    for note in unformalized:
        content = note.get("content", "")
        if len(content.strip()) < MIN_CONTENT_LENGTH:
            continue
        signal = note.get("signal_type", "other")
        mem_type = _NOTE_TYPE_MAP.get(signal, "fact")
        title = auto_title(content, max_len=settings.memory_title_max_length)
        if is_test_content(content):
            title = f"[临时] {title}"[: settings.memory_title_max_length]
        candidate: dict[str, Any] = {
            "title": title,
            "content": content,
            "type": mem_type,
            "source": f"note:{signal}",
        }
        if note.get("id") is not None:
            candidate["note_ids"] = [str(note["id"])]
        candidates.append(candidate)

    # 2. 工具失败事件 → issue 候选；仅在解题/手动/会话结束检查点提取，限流防爆量
    if trigger_reason in ("problem_solved", "manual", "session_ending"):
        failures = [e for e in events if e.get("event_type") == "tool.failed"]
        for failure in failures:
            if len(candidates) >= MAX_FAILURE_CANDIDATES:
                break
            error_msg = failure.get("error", "")
            tool_name = " ".join(failure.get("tool_name", "").splitlines())
            if len(error_msg.strip()) >= MIN_CONTENT_LENGTH:
                title = f"{tool_name} 调用失败" if tool_name else "工具调用失败"
                content = f"使用 {tool_name or '未知工具'} 时遇到错误：{error_msg}"
                candidates.append(
                    {
                        "title": title[: settings.memory_title_max_length],
                        "content": content,
                        "type": "issue",
                        "source": "event:tool.failed",
                    }
                )

    # 3. prompt 事件中的信号检测
    for reason_filter, keywords, mem_type, min_len in _SIGNAL_RULES:
        if reason_filter is not None and trigger_reason not in (
            reason_filter,
            "manual",
            "session_ending",
        ):
            continue
        for event in events:
            if event.get("event_type") != "prompt.submitted":
                continue
            content = event.get("content", "")
            if not any(kw in content for kw in keywords) or len(content.strip()) < max(
                min_len, MIN_CONTENT_LENGTH
            ):
                continue
            title = auto_title(
                extract_context_around_keyword(content, keywords),
                max_len=settings.memory_title_max_length,
            )
            candidates.append(
                {
                    "title": title,
                    "content": content,
                    "type": mem_type,
                    "source": f"event:prompt.submitted:{reason_filter}",
                }
            )
            break

    # 标题只是预览：只有来源正文完全相同才算重复，故按内容摘要去重。
    seen: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for c in candidates:
        digest = hashlib.sha256(c["content"].encode()).hexdigest()
        first = seen.get(digest)
        if first is None:
            seen[digest] = c
            deduped.append(c)
            continue
        # 合并重复候选的来源笔记，保证提交后所有同内容笔记都能 formalize
        for note_id in c.get("note_ids", []):
            merged = first.setdefault("note_ids", [])
            if note_id not in merged:
                merged.append(note_id)

    return deduped


def build_event_analysis_report(
    events: list[dict[str, Any]],
    workers_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """按 session 分组事件，构建供 Agent 分析的报告。"""
    sessions: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        sid = event.get("session_id", "unknown")
        sessions.setdefault(sid, []).append(event)

    session_summaries = []
    for sid, session_events in sessions.items():
        event_types = [e.get("event_type", "") for e in session_events]
        tool_names = [
            e.get("tool_name", "")
            for e in session_events
            if e.get("event_type") == "tool.completed" and e.get("tool_name")
        ]
        prompts = [
            e.get("content", "")[:CONTENT_PREVIEW_LENGTH]
            for e in session_events
            if e.get("event_type") == "prompt.submitted"
        ]

        summary: dict[str, Any] = {
            "session_id": sid,
            "event_count": len(session_events),
            "event_types": list(dict.fromkeys(event_types)),
        }
        if tool_names:
            unique_tools = list(dict.fromkeys(tool_names))
            summary["tools_used"] = unique_tools
        if prompts:
            summary["user_prompts"] = prompts

        summary["events"] = session_events
        session_summaries.append(summary)

    report: dict[str, Any] = {
        "sessions": session_summaries,
        "total_events": len(events),
        "total_sessions": len(sessions),
        "hint": _ANALYSIS_HINT,
    }

    if workers_candidates:
        report["already_extracted"] = [
            {"title": c.get("title"), "type": c.get("type")} for c in workers_candidates
        ]
        report["dedup_hint"] = (
            "以上条目已由 Hook 流程自动提取为候选记忆，请勿重复提交相同或相似内容。"
        )

    return report
