"""跨平台端口管理工具 — 供 start.py 和 tasks.py 共享使用。"""

import logging
import os
import signal
import socket
import subprocess
import time

logger = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"


def port_is_free(port: int) -> bool:
    """端口在 localhost 上空闲时返回 True。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        # connect_ex 返回 0 表示连接成功，即端口已被占用
        return sock.connect_ex(("127.0.0.1", port)) != 0


def port_has_healthy_service(port: int) -> bool:
    """端口上有进程响应 HTTP 即视为健康（4xx/5xx 也算存活）。"""
    try:
        import urllib.error
        import urllib.request

        urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        logger.debug("Port %d health check failed", port, exc_info=True)
        return False


def force_kill_port(port: int) -> None:
    """终止占用 *port* 的进程。失败时抛出 RuntimeError。"""
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            pids: set[str] = set()
            # netstat 行格式：协议 本地地址 外部地址 状态 PID，只取监听/已建立且命中端口的行
            for line in result.stdout.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    # 只比较端口号本身，避免 :5172 误匹配 15172 / 51720
                    and parts[1].rsplit(":", 1)[-1] == str(port)
                    and parts[3] in ("LISTENING", "ESTABLISHED")
                ):
                    pid = parts[4].strip()
                    if pid and pid != "0":
                        pids.add(pid)
            for pid in pids:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                print(f"    已终止 PID {pid} 及其子进程")
            if pids:
                # 二次清理兜底：部分机器上 PowerShell 启动可能超过 10s，
                # 此处超时不能视为致命——taskkill 已先行执行，下方等待
                # 循环仍会确认端口是否真正释放。
                try:
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            f"Get-Process -Id {','.join(pids)} -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=20,
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    print(f"    二次清理未完成（不阻塞）: {exc}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"释放端口 {port} 失败: {exc}") from exc
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            pids_list = [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]
            if not pids_list:
                # lsof 缺失或无输出时退回 fuser
                subprocess.run(
                    ["fuser", "-k", f"{port}/tcp"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                for pid in pids_list:
                    os.kill(int(pid), signal.SIGKILL)
                    print(f"    已终止 PID {pid}")
        except FileNotFoundError:
            subprocess.run(
                ["fuser", "-k", f"{port}/tcp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"释放端口 {port} 失败: {exc}") from exc

    # 最多等待 10s（40 × 0.25s）确认端口真正释放，超时交由人工处理
    for _ in range(40):
        if port_is_free(port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"端口 {port} 释放超时，请手动检查")


def ensure_port_free(port: int, service_name: str | None = None) -> bool:
    """确保端口可用，返回端口是否空闲。

    已有健康服务在运行时打印提示并返回 False；端口被占用但无响应时
    强制释放，释放失败抛出 RuntimeError。
    """
    label = service_name or "服务"
    if port_is_free(port):
        return True
    if port_has_healthy_service(port):
        print(f"  端口 {port} 已有服务运行（{label}），请先停止或使用 restart 命令")
        return False
    print(f"  端口 {port} 被占用但无响应，正在释放...")
    force_kill_port(port)
    return True


def kill_mcp_adapter() -> int:
    """终止运行中的 MCP 适配器进程，使 CLI 下次拉起时加载新代码。

    返回终止的进程数。
    """
    killed = 0
    if IS_WINDOWS:
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
                        "| Where-Object { $_.CommandLine -like '*adapters.qoder.mcp_server*' } "
                        "| Select-Object -ExpandProperty ProcessId"
                    ),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=30,
            )
            pids = [
                p.strip()
                for p in result.stdout.strip().splitlines()
                if p.strip() and p.strip() != "0"
            ]
            for pid in pids:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                killed += 1
                print(f"    已终止 MCP 适配器 PID {pid}")
        except OSError as exc:
            print(f"  查找 MCP 适配器进程失败: {exc}")
    else:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "adapters.qoder.mcp_server"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            pids = [p.strip() for p in result.stdout.strip().splitlines() if p.strip()]
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    killed += 1
                    print(f"    已终止 MCP 适配器 PID {pid}")
                except ProcessLookupError:
                    pass
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"  查找 MCP 适配器进程失败: {exc}")
    return killed


def force_restart_port(port: int, service_name: str | None = None) -> None:
    """强制释放 *port*（restart 模式用）。失败时抛出 RuntimeError。"""
    label = service_name or "服务"
    if port_is_free(port):
        return
    print(f"  端口 {port} 被占用（{label}），正在释放...")
    force_kill_port(port)
