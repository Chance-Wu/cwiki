"""cwiki 统一错误层级。

所有领域错误继承自 AppError，携带错误码、人类可读消息和
用于 API 响应的 HTTP 状态码。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """携带错误码、HTTP 状态码与可选结构化附加信息的领域错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra
        super().__init__(message)


class WriteDecisionRejected(AppError):
    """写入决策规则拒绝保存（skip/update）；携带规则与目标信息供 Agent 处理。"""

    def __init__(
        self,
        *,
        action: str,
        rule_id: str | None,
        message: str,
        reason: str | None = None,
        target_memory_id: str | None = None,
        target_title: str | None = None,
        similarity: float | None = None,
    ) -> None:
        payload: dict[str, Any] = {"action": action, "rule_id": rule_id}
        if reason:
            payload["reason"] = reason
        if target_memory_id:
            payload["target_memory_id"] = target_memory_id
        if target_title:
            payload["target_title"] = target_title
        if similarity is not None:
            payload["similarity"] = round(similarity, 4)
        code = "write_decision_update" if action == "update" else "write_decision_skip"
        super().__init__(
            code,
            message,
            status_code=409 if action == "update" else 400,
            extra={"write_decision": payload},
        )
