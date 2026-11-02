"""注册每日 _meta 导出计划任务（不依赖 API 进程存活时长）。

Windows 建立 ``cwiki-meta-export`` 计划任务，每日运行
``scripts/meta_export_daily.py``（日志见 ``~/.cwiki/state/meta_export.log``）。
其他平台只打印 crontab 行，不修改用户 crontab。

用法::

    python scripts/install_meta_export_task.py            # 默认 04:00
    python scripts/install_meta_export_task.py --time 03:30
    python scripts/install_meta_export_task.py --remove
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "cwiki-meta-export"
SCRIPT = ROOT / "scripts" / "meta_export_daily.py"


def _interpreter() -> str:
    """优先 venv 的 pythonw（无控制台窗口），回退当前解释器。"""
    for rel in ("Scripts/pythonw.exe", "bin/python"):
        candidate = ROOT / ".venv" / rel
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _decode(data: bytes | None) -> str:
    """schtasks 在中文 Windows 输出 GBK，而终端/环境可能强制 UTF-8，逐级回退。"""
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _install(time_str: str) -> int:
    command = f'"{_interpreter()}" "{SCRIPT}"'
    result = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/SC",
            "DAILY",
            "/ST",
            time_str,
            "/TR",
            command,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = _decode(result.stderr) or _decode(result.stdout)
        print(f"注册计划任务失败：{message}")
        print("  提示：创建计划任务需要管理员权限，请在“以管理员身份运行”的终端中重试。")
        return result.returncode
    print(f"已注册计划任务 {TASK_NAME}：每日 {time_str} 执行")
    print(f"  命令：{command}")
    print("  立即验证：schtasks /run /tn " + TASK_NAME)
    print(f"  日志：{Path.home() / '.cwiki' / 'state' / 'meta_export.log'}")
    return 0


def _remove() -> int:
    result = subprocess.run(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        message = _decode(result.stderr) or _decode(result.stdout)
        print(f"删除计划任务失败：{message}")
        print("  提示：删除计划任务需要管理员权限，请在“以管理员身份运行”的终端中重试。")
        return result.returncode
    print(f"已删除计划任务 {TASK_NAME}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="注册每日 _meta 导出计划任务")
    parser.add_argument("--time", default="04:00", help="每日执行时间 HH:MM（默认 04:00）")
    parser.add_argument("--remove", action="store_true", help="删除已注册的计划任务")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("非 Windows 平台不自动修改 crontab，请手工加入以下行：")
        print(
            f"  {args.time.split(':')[1]} {args.time.split(':')[0]} * * * "
            f"cd {ROOT} && {sys.executable} {SCRIPT}"
        )
        return 0

    return _remove() if args.remove else _install(args.time)


if __name__ == "__main__":
    raise SystemExit(main())
