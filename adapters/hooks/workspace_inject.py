"""PreToolUse：工具执行前为 cwiki MCP 调用注入 workspace_name（确定性归属）。

注册表机制在"同宿主多窗口并发"下有 last-write-wins 竞态：A 项目会话提问后、
save 执行前，B 项目会话的提问会把注册表盖掉。PreToolUse 与每次工具调用一一
对应，hook 的 stdin payload 自带**本次调用所属会话的 cwd**——据此注入
workspace_name，把归属从"尽力而为"变成确定性。

规则：
- 只处理 cwiki 的 workspace 作用域工具；Agent 显式传了 workspace_name/workspace_id
  时绝不覆盖（跨区操作保留）。
- memory_search 不在其列：省略 workspace_name 的"跨全部工作区检索"是设计语义。
- 推导不出合法项目名（default）时不注入，等价于原回落链。

输出（Claude/Qoder PreToolUse 协议，缺 hookEventName 会导致整个 stdout 被拒）：
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput": {...}}}
"""

from __future__ import annotations

from typing import Any

from .profiles import derive_workspace_from_dir

# 省略 workspace_name 时回落会话/注册表工作区的工具——注入本次调用的 cwd 更准。
# memory_search 不在其中：省略 = 跨全部工作区搜索（设计语义）。
INJECT_TOOLS = frozenset(
    {
        "memory_save",
        "memory_checkpoint",
        "memory_status",
        "memory_export",
        "memory_import",
        "memory_feedback",
        "memory_forget",
        "memory_review_due",
        "memory_review_submit",
        "memory_review_stats",
    }
)


def _tool_suffix(name: str) -> str:
    """MCP 全名 mcp__server__tool → tool；普通工具名原样返回。"""
    return name.rsplit("__", 1)[-1] if "__" in name else name


def _unwrap(payload: dict[str, Any]) -> tuple[str, dict[str, Any] | None, bool]:
    """识别两种宿主形态，返回 (cwiki 工具名, arguments, 是否嵌套包装)。

    - Qoder app：tool_name="mcp_call"，tool_input={"toolName": "mcp__…__memory_save",
      "arguments": {...}}——必须整体回写包装结构。
    - CLI 直连（Claude Code 等）：tool_name="mcp__cwiki__memory_save"，tool_input 即参数。
    """
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return "", None, False
    outer = str(payload.get("tool_name") or "")
    if outer == "mcp_call":
        inner = tool_input.get("toolName") or tool_input.get("tool_name") or ""
        args = tool_input.get("arguments")
        return str(inner), args if isinstance(args, dict) else None, True
    return outer, tool_input, False


def updated_input(payload: dict[str, Any]) -> dict[str, Any] | None:
    """返回应替换的 tool_input；None 表示无需改写。任何异常路径都必须安全返回 None。"""
    inner, args, wrapped = _unwrap(payload)
    if _tool_suffix(inner) not in INJECT_TOOLS or not isinstance(args, dict):
        return None
    if args.get("workspace_name") or args.get("workspace_id"):
        return None
    # 只信任本次调用 payload 的 cwd（协议字段，必含且属于该会话的项目）
    workspace = derive_workspace_from_dir(str(payload.get("cwd") or ""))
    if workspace == "default":
        return None
    new_args = {**args, "workspace_name": workspace}
    return {**payload["tool_input"], "arguments": new_args} if wrapped else new_args
