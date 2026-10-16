"""脱离 API 进程的守护脚本：终止旧 API 进程并重启服务。

由 POST /v1/system/restart 以子进程方式调用。API 进程无法重启自身，
只能由这个外部监督者代为完成。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: restart_watcher.py <old_pid> <project_root>")
        sys.exit(1)

    old_pid = int(sys.argv[1])
    project_root = sys.argv[2]

    # 先等 1.5s，让重启响应返回给调用方，再动手杀旧进程
    time.sleep(1.5)

    # 终止旧进程树：Windows 用 taskkill /T 连子进程一起杀；POSIX 直接 SIGKILL
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(old_pid), "/T", "/F"], capture_output=True, check=False
        )
    else:
        try:
            os.kill(old_pid, 9)
        except ProcessLookupError:
            pass

    # 再等 1s，确保端口释放后新进程才能绑定
    time.sleep(1)

    # 经由 tasks.py start 全新启动
    tasks_py = os.path.join(project_root, "tasks.py")
    # 以新进程组/新会话启动，避免新服务随本守护脚本退出而被终止
    subprocess.Popen(
        [sys.executable, tasks_py, "start"],
        cwd=project_root,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )


if __name__ == "__main__":
    main()
