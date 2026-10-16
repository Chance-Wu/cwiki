#!/usr/bin/env python3
"""cwiki 后端常驻服务（无 --reload）— 供计划任务开机自启调用。

用法: pythonw serve_backend.py  （python.exe 也可，但会一直挂着控制台窗口）

行为:
- 幂等: 端口已有健康服务时直接退出 0（重复触发不会起第二个实例）
- 自愈: 子进程异常退出且端口空闲时，指数退避重启（5s → 60s 封顶）
- 让位: 重启时发现端口被外部接管（如 tasks.py restart-serve / 手动 dev 起服），退出 0 让位
- 日志: 仅写 cwiki-data/serve_backend.log（pythonw 下无控制台，绝不 print 到 stdout）

不传 --reload、不读 settings.debug——代码更新后用 `python tasks.py restart-mcp` 之外的
方式重启服务：`schtasks /end /tn cwiki-backend && schtasks /run /tn cwiki-backend`。
"""

import atexit
import os
import signal as _signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# pythonw 下 sys.stdout/stderr 为 None，端口工具里的 print/logging 不至于崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = sys.stdout

from scripts.common import ensure_venv_interpreter, load_app_config

ensure_venv_interpreter(PROJECT_ROOT)

from scripts.port_utils import port_has_healthy_service, port_is_free
from scripts.process_utils import WindowsJob, stop_process_tree

try:
    API_PORT = int(load_app_config(PROJECT_ROOT).get("app", {}).get("api_port", 5172))
except Exception:
    API_PORT = 5172

LOG_PATH = PROJECT_ROOT / "cwiki-data" / "serve_backend.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
IS_WINDOWS = os.name == "nt"

# 当前子进程引用，供信号处理器和 atexit 安全网访问
_current_proc: subprocess.Popen | None = None
_shutting_down = False


def _cleanup_child(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    """优雅终止子进程。幂等；异常仅记录日志，不中断退出流程。"""
    if proc is None:
        return
    try:
        stop_process_tree(proc, timeout=timeout)
    except Exception as exc:
        log(f"清理子进程异常（不影响退出）: {exc}")


def _request_shutdown(signum: int, _frame: object) -> None:
    """信号处理器：终止子进程并退出。"""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    try:
        name = _signal.Signals(signum).name
    except (ValueError, AttributeError):
        name = str(signum)
    log(f"收到 {name}，正在优雅关闭…")
    _cleanup_child(_current_proc)
    log("后端服务已关闭")
    sys.exit(0)


def _atexit_cleanup() -> None:
    """atexit 安全网：父进程退出时确保子进程被回收。"""
    proc = _current_proc
    if proc is not None and proc.poll() is None:
        _cleanup_child(proc, timeout=3.0)


def log(msg: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 超过上限时轮转为 .1，避免常驻进程日志无限增长
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            LOG_PATH.replace(LOG_PATH.with_name(LOG_PATH.name + ".1"))
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().astimezone():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def spawn() -> subprocess.Popen:
    """启动后端 API（与 start.py 同参，但不含 --reload、不启前端）。"""
    cmd = [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--port", str(API_PORT)]
    logf = LOG_PATH.open("a", encoding="utf-8")
    try:
        spawn_kwargs: dict = {}
        if IS_WINDOWS:
            # 新进程组隔离 Ctrl+C：信号由本守护进程统一转发/回收
            spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # 新会话脱离控制终端，便于 killpg 整树回收
            spawn_kwargs["start_new_session"] = True
        return subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=logf,
            stderr=subprocess.STDOUT,
            **spawn_kwargs,
        )
    finally:
        logf.close()


def main() -> int:
    global _current_proc
    os.chdir(PROJECT_ROOT)

    # 注册信号处理器与 atexit 安全网
    _signal.signal(_signal.SIGTERM, _request_shutdown)
    _signal.signal(_signal.SIGINT, _request_shutdown)
    atexit.register(_atexit_cleanup)

    if not port_is_free(API_PORT):
        if port_has_healthy_service(API_PORT):
            log(f"端口 {API_PORT} 已有健康服务，无需启动，退出")
            return 0
        log(f"端口 {API_PORT} 被占用但无响应，退出（请手动清理或重启机器）")
        return 1

    log(f"cwiki 后端常驻服务启动 port={API_PORT} python={sys.executable}")
    backoff = 5.0
    while True:
        job = WindowsJob() if IS_WINDOWS else None
        started = time.monotonic()
        try:
            proc = spawn()
            _current_proc = proc
            if job is not None:
                job.assign(proc)
            code = proc.wait()
        except OSError as exc:
            log(f"启动失败: {exc}")
            code = 1
        finally:
            _current_proc = None
            if job is not None:
                job.close()
        if code == 0:
            log("后端正常退出，服务结束")
            return 0
        if not port_is_free(API_PORT):
            log(f"后端退出(code={code})但端口仍被占用，视为外部接管，退出")
            return 0
        if time.monotonic() - started >= 60:
            backoff = 5.0  # 稳定运行过一段时间，重置退避，避免长期稳定后被罚 60s
        log(f"后端异常退出(code={code})，{backoff:.0f}s 后重启")
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    sys.exit(main())
