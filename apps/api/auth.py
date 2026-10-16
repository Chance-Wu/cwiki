"""cwiki API 认证模块。

单用户本地部署模式：不做 token 校验，所有请求默认可信。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentIdentity:
    """本地默认 Agent 身份。

    scopes 集合保留了按资源划分的权限声明，供未来多身份扩展时复用；
    本地模式下不做实际校验。
    """

    agent_id: str = "local"
    workspace_id: str = "default"
    scopes: set[str] = field(
        default_factory=lambda: {
            "events:write",
            "candidates:write",
            "memories:read",
            "context:read",
            "sessions:read",
            "sessions:write",
            "episodes:read",
            "reviews:write",
            "search:read",
            "file-memories:read",
            "file-memories:write",
            "workspaces:write",
            "projects:write",
            "feedback:write",
            "conflicts:write",
            "agents:write",
            "usage:write",
            "types:write",
            "skills:read",
            "skills:write",
        }
    )
