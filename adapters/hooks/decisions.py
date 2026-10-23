"""SessionStart 写入决策注入。

从 config.yaml + config.local.yaml 读取 agent_policy.write_decisions，
生成紧凑摘要交给宿主；任何异常都 fail-open，不阻塞会话启动。
"""

from __future__ import annotations

from . import recall


def build_hint(workspace: str) -> str:
    """返回写入决策摘要；未启用时回退旧的 must_save 提示。"""
    try:
        from packages.domain.config import agent_policy_config
        from packages.domain.write_decisions import build_agent_hint

        policy = agent_policy_config.write_decisions
        if policy.enabled:
            return build_agent_hint(policy, workspace)
        return recall.must_save_hint()
    except Exception:
        return ""
