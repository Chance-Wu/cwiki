"""cwiki 统一错误层级。

所有领域错误继承自 AppError，携带错误码、人类可读消息和
用于 API 响应的 HTTP 状态码。
"""

from __future__ import annotations


class AppError(Exception):
    """携带错误码与 HTTP 状态码的基础错误。"""

    def __init__(self, code: str, message: str, status_code: int = 500) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)
