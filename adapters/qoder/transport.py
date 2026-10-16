"""MCP 服务器的 stdio 传输层与 git 信息辅助函数。

负责 stdin/stdout 上的原始二进制读写：stdio 是阻塞 fd，
由独立守护线程读写并桥接回 asyncio，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from typing import Any

logger = logging.getLogger("cwiki-mcp")

MAX_MESSAGE_BYTES = 8 * 1024 * 1024
STDIN_READ_BUFFER = 65536
SESSION_INIT_TIMEOUT = 3.0

_JSONRPC_TRANSPORT_ERROR = -32000
_JSONRPC_PARSE_ERROR = -32700
_JSONRPC_INVALID_REQUEST = -32600


def _jsonrpc_error(code: int, message: str, *, id: Any = None) -> dict[str, Any]:
    """构造 JSON-RPC 2.0 错误响应对象。"""
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


OVERSIZE_ERROR: dict[str, Any] = _jsonrpc_error(
    _JSONRPC_TRANSPORT_ERROR,
    f"Message exceeds {MAX_MESSAGE_BYTES} bytes; transport closed",
)

PARSE_ERROR: dict[str, Any] = _jsonrpc_error(_JSONRPC_PARSE_ERROR, "Invalid JSON or UTF-8")

INVALID_REQUEST_ERROR: dict[str, Any] = _jsonrpc_error(_JSONRPC_INVALID_REQUEST, "Invalid request")

# 以公开名再导出，供 mcp_server.py 导入（测试可经 mcp_server 模块 monkeypatch）
JSONRPC_PARSE_ERROR = _JSONRPC_PARSE_ERROR
JSONRPC_INVALID_REQUEST = _JSONRPC_INVALID_REQUEST
JSONRPC_METHOD_NOT_FOUND = -32601


def stdin_reader() -> asyncio.StreamReader:
    """启动守护线程，把 stdin 数据喂入 asyncio StreamReader。"""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
    stdin_fd = sys.stdin.fileno()
    if sys.platform == "win32":
        import msvcrt

        # Windows 下 stdio 默认文本模式，须切回二进制，保证 JSON 字节流不被改写
        msvcrt.setmode(stdin_fd, os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    def read_input() -> None:
        try:
            while data := os.read(stdin_fd, STDIN_READ_BUFFER):
                loop.call_soon_threadsafe(reader.feed_data, data)
            loop.call_soon_threadsafe(reader.feed_eof)
        except OSError as exc:
            if not loop.is_closed():
                loop.call_soon_threadsafe(reader.set_exception, exc)
        except RuntimeError:
            pass

    threading.Thread(target=read_input, name="cwiki-stdin", daemon=True).start()
    return reader


async def write_stdout(data: bytes) -> None:
    """在后台线程写 stdout，异步等待写完。"""
    loop = asyncio.get_running_loop()
    completed = loop.create_future()
    stdout_fd = sys.stdout.fileno()

    def finish(error: OSError | None) -> None:
        if not completed.done():
            if error is None:
                completed.set_result(None)
            else:
                completed.set_exception(error)

    def write_output() -> None:
        error = None
        try:
            remaining = memoryview(data)
            while remaining:
                remaining = remaining[os.write(stdout_fd, remaining) :]
        except OSError as exc:
            error = exc
        try:
            loop.call_soon_threadsafe(finish, error)
        except RuntimeError:
            pass

    threading.Thread(target=write_output, name="cwiki-stdout", daemon=True).start()
    await completed


def git_output(args: list[str]) -> str | None:
    """执行 git 命令并返回去空白后的 stdout；任何失败都返回 None。"""
    try:
        return subprocess.check_output(
            ["git"] + args,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            timeout=SESSION_INIT_TIMEOUT,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_git_info() -> tuple[str | None, str | None]:
    """通过 git 命令获取仓库 remote URL 与当前分支，供 agent session 上报。"""
    repository = git_output(["config", "--get", "remote.origin.url"])
    branch = git_output(["rev-parse", "--abbrev-ref", "HEAD"])
    return repository, branch
