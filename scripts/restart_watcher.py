"""脱离 API 进程的守护脚本：终止旧 API 进程并在需要时重新拉起。

由 POST /v1/system/restart 以子进程方式调用。API 进程无法重启自身，
只能由这个外部监督者代为完成。

注意 watcher 自身是旧 API 的子进程，所以只能用 ``taskkill /PID`` 精确结束
服务进程，**不能加 /T**——否则会连正在执行重启的 watcher 一起杀掉。
多数部署由计划任务（serve_backend.py）监督，杀掉子进程后监督者会自动拉起
新实例；这里先等服务恢复健康，超时才自己兜底启动。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_API_PORT = 5172
HEALTH_TIMEOUT_SECONDS = 25.0


def _api_port(project_root: str) -> int:
    try:
        import yaml

        with open(Path(project_root) / "config.yaml", encoding="utf-8") as f:
            port = (yaml.safe_load(f) or {}).get("app", {}).get("api_port")
        return int(port) if port else DEFAULT_API_PORT
    except (OSError, ValueError, TypeError, ImportError):
        return DEFAULT_API_PORT


def _wait_healthy(port: int, timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    """轮询 /v1/health；监督者拉起的新实例通常数秒内恢复。"""
    url = f"http://127.0.0.1:{port}/v1/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if b"healthy" in response.read(200):
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.5)
    return False


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
        return
    try:
        os.kill(pid, 9)
    except ProcessLookupError:
        pass


def _spawn_fallback(project_root: str) -> None:
    """没有监督者时的兜底：交给 tasks.py restart-serve 重新拉起 API。

    必须显式重定向 stdio：调用方（旧 API）的 stdout 句柄会随旧进程失效，
    新进程继承后一写日志就阻塞，表现为端口可连但无任何响应。
    """
    tasks_py = os.path.join(project_root, "tasks.py")
    log_path = Path(project_root) / "cwiki-data" / "restart.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        # 以新进程组/新会话启动，避免新服务随本守护脚本退出而被终止
        subprocess.Popen(
            [sys.executable, tasks_py, "restart-serve"],
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: restart_watcher.py <old_pid> <project_root>")
        sys.exit(1)

    old_pid = int(sys.argv[1])
    project_root = sys.argv[2]
    port = _api_port(project_root)

    # 先等 1.5s，让重启响应返回给调用方，再动手杀旧进程
    time.sleep(1.5)
    _kill(old_pid)

    # 监督者（计划任务）会重新拉起子进程；等健康即视为重启完成
    if _wait_healthy(port):
        return

    _spawn_fallback(project_root)


if __name__ == "__main__":
    main()
