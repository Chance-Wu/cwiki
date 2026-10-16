#!/usr/bin/env python3
"""cwiki 一键启动脚本 — 同时启动后端 API 和前端开发服务器（跨平台）。"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from scripts.common import (
    ensure_venv_interpreter,
    load_app_config,
    patch_metadata,
    print_message,
)

ensure_venv_interpreter(Path(__file__).resolve().parent)

patch_metadata()

from scripts.port_utils import ensure_port_free, force_restart_port
from scripts.process_utils import WindowsJob, stop_process_tree

try:
    from packages.domain.config import settings
except ImportError:
    # 配置模块不可用时兜底，保证脚本本身仍可运行（按非 debug 模式处理）
    class _FakeSettings:
        debug = False

    settings = _FakeSettings()  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"


def check_npm() -> str | None:
    """返回 npm 可执行路径；未找到时返回 None。"""
    return shutil.which("npm.cmd" if IS_WINDOWS else "npm")


def check_python_deps() -> list[str]:
    """返回缺失的关键 Python 依赖包列表。"""
    missing = []
    for package in ["uvicorn", "fastapi", "sqlalchemy", "alembic"]:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    return missing


def ensure_node_modules(npm: str) -> bool:
    """node_modules 缺失时执行安装；成功返回 True。"""
    node_modules = PROJECT_ROOT / "apps" / "web" / "node_modules"
    if node_modules.is_dir():
        return True
    print_message("  未找到 node_modules，正在安装前端依赖...")
    try:
        subprocess.run(
            [npm, "install"],
            cwd=str(PROJECT_ROOT / "apps" / "web"),
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> int:
    restart_mode = "--restart" in sys.argv
    action = "重启" if restart_mode else "启动"

    print_message(f"\n  {action} cwiki")
    print_message("  " + "─" * 30)

    npm = check_npm()
    if npm is None:
        print_message("  ✗ 未找到 npm，请安装 Node.js LTS 并加入 PATH")
        print_message("    https://nodejs.org/")
        return 1

    missing = check_python_deps()
    if missing:
        print_message(f"  ✗ 缺少 Python 依赖: {', '.join(missing)}")
        print_message("    请先运行: python tasks.py install")
        return 1

    cfg = load_app_config(PROJECT_ROOT)
    api_port = cfg.get("app", {}).get("api_port", 5172)
    memory_dir = cfg.get("storage", {}).get("memory_dir", "./cwiki-data")
    memory_path = PROJECT_ROOT / memory_dir
    memory_path.mkdir(parents=True, exist_ok=True)

    if restart_mode:
        try:
            force_restart_port(api_port, "后端 API")
            force_restart_port(5173, "前端界面")
        except RuntimeError as exc:
            print_message(f"  ✗ {exc}")
            return 1
        api_port_free = True
        web_port_free = True
    else:
        try:
            api_port_free = ensure_port_free(api_port, "后端 API")
            web_port_free = ensure_port_free(5173, "前端界面")
        except RuntimeError as exc:
            print_message(f"  ✗ {exc}")
            return 1
        if not api_port_free and not web_port_free:
            print_message(f"\n  所有服务已在运行，无需{action}")
            print_message(f"  后端 API  → http://localhost:{api_port}")
            print_message("  前端界面  → http://localhost:5173")
            print_message("\n  如需重启: python tasks.py restart")
            return 0

    if web_port_free:
        print_message("  [准备] 前端依赖")
        if not ensure_node_modules(npm):
            print_message("  ✗ npm install 失败，请在 apps/web 目录手动执行: npm install")
            return 1

    # 为子进程标记开发运行环境；setdefault 不覆盖外部已设的值
    os.environ.setdefault("CWIKI_DEV_MODE", "true")

    print_message()
    print_message(f"  后端 API  → http://localhost:{api_port}")
    print_message("  前端界面  → http://localhost:5173")
    print_message("  Ctrl+C 停止所有服务")
    print_message()

    processes: list[subprocess.Popen] = []
    process_labels: list[str] = []
    old_handlers: dict[int, object] = {}
    job = None

    def shutdown(_signum: int, _frame: object) -> None:
        # 信号处理里只触发退出，子进程回收统一交给 finally，避免重入清理
        sys.exit(0)

    try:
        job = WindowsJob() if IS_WINDOWS else None
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.signal(sig, shutdown)
        # Windows 用新进程组隔离 Ctrl+C；POSIX 用新会话，便于 killpg 整树回收
        process_options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if IS_WINDOWS
            else {"start_new_session": True}
        )
        if api_port_free:
            uvicorn_cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.api.main:app",
                "--host",
                settings.api_host,
                "--port",
                str(api_port),
            ]
            if settings.debug:
                uvicorn_cmd.append("--reload")
            processes.append(
                subprocess.Popen(uvicorn_cmd, cwd=str(PROJECT_ROOT), **process_options)
            )
            process_labels.append("后端 API")
            if job is not None:
                job.assign(processes[-1])
        if web_port_free:
            processes.append(
                subprocess.Popen(
                    [npm, "run", "dev"],
                    cwd=str(PROJECT_ROOT / "apps" / "web"),
                    **process_options,
                )
            )
            process_labels.append("前端界面")
            if job is not None:
                job.assign(processes[-1])

        if not processes:
            # 两个端口都已被占用（服务非本进程启动），仅保持前台等待 Ctrl+C
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return 0

        while True:
            for i, process in enumerate(processes):
                returncode = process.poll()
                if returncode is not None:
                    label = process_labels[i] if i < len(process_labels) else f"进程 {process.pid}"
                    if returncode:
                        print_message(f"\n  {label} 异常退出 (code={returncode})，正在清理...")
                        return returncode
                    print_message(f"\n  {label} 已退出，正在清理其他服务...")
                    return 0
            # 带超时阻塞等待，兼顾及时感知退出与避免忙轮询空耗 CPU
            try:
                processes[0].wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print_message(f"\n  ✗ 服务启动失败: {exc}")
        return 1
    finally:
        try:
            # 回收期间屏蔽信号，避免清理流程被再次 Ctrl+C 打断
            for sig in old_handlers:
                signal.signal(sig, signal.SIG_IGN)
            # 逆序回收：先停前端再停后端
            for process in reversed(processes):
                try:
                    stop_process_tree(process)
                except (OSError, subprocess.SubprocessError) as exc:
                    print_message(f"  清理进程 {process.pid} 失败，请检查其子进程: {exc}")
        finally:
            try:
                if job is not None:
                    job.close()
            finally:
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
