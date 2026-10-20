#!/usr/bin/env python3
"""cwiki 一站式安装脚本 — 环境预检 → 依赖安装 → 数据初始化 → 下一步提示。

跨平台（Mac / Windows / Linux），用法：
    python scripts/install.py                # 完整安装
    python scripts/install.py --dry-run      # 只打印将要执行的操作
    python scripts/install.py --skip-db      # 跳过数据库初始化
    python scripts/install.py --skip-web     # 跳过前端依赖
    python scripts/install.py --skip-setup   # 跳过 Agent 接入配置
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, NamedTuple, Self

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.common import ensure_venv_interpreter, load_app_config, patch_metadata, print_message

ensure_venv_interpreter(PROJECT_ROOT)


class NodeCheckResult(NamedTuple):
    """Node.js 环境检查结果。"""

    available: bool
    version: tuple[int, ...] | None


# ── 版本要求 ─────────────────────────────────────────────────────────

MIN_PYTHON = (3, 11)
MIN_NODE = (18, 0, 0)

# Windows STATUS_DLL_INIT_FAILED：子进程在解释器初始化前就失败（安全软件注入 / 资源瞬时紧张），可重试
DLL_INIT_FAILED = 0xC0000142

# 核心 Python 依赖：安装后必须能导入，作为环境健康的硬指标
CORE_PYTHON_MODULES = (
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "aiosqlite",
    "pydantic",
    "pydantic_settings",
    "alembic",
    "httpx",
    "typer",
    "ulid",
    "orjson",
    "openai",
    "numpy",
    "jieba",
    "yaml",
    "watchdog",
)


# ── 通用工具 ─────────────────────────────────────────────────────────


# ANSI 颜色码（Windows 10+ 支持）
class Colors:
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"


def _supports_color() -> bool:
    """检测终端是否支持颜色。"""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def info(msg: str) -> None:
    prefix = f"{Colors.GREEN}  ✓{Colors.RESET}" if _supports_color() else "  ✓"
    print_message(f"{prefix} {msg}")


def warn(msg: str) -> None:
    prefix = f"{Colors.YELLOW}  ⚠{Colors.RESET}" if _supports_color() else "  ⚠"
    print_message(f"{prefix} {msg}")


def fail(msg: str) -> None:
    prefix = f"{Colors.RED}  ✗{Colors.RESET}" if _supports_color() else "  ✗"
    print_message(f"{prefix} {msg}")
    sys.exit(1)


def step_header(number: int, total: int, title: str) -> None:
    if _supports_color():
        print_message(f"\n{Colors.BOLD}{Colors.CYAN}[{number}/{total}] {title}{Colors.RESET}")
    else:
        print_message(f"\n[{number}/{total}] {title}")


class Spinner:
    """简单的进度指示器 — 用于长时间命令。"""

    def __init__(self, message: str):
        self.message = message
        self.running = False

    def __enter__(self) -> Self:
        if not _supports_color():
            print_message(f"  {self.message}...")
            return self
        self.running = True
        import itertools
        import threading

        def spin() -> None:
            for char in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
                if not self.running:
                    break
                print(f"\r  {Colors.CYAN}{char}{Colors.RESET} {self.message}", end="", flush=True)
                import time

                time.sleep(0.1)
            print(f"\r  {Colors.GREEN}✓{Colors.RESET} {self.message}{' ' * 20}")

        self.thread = threading.Thread(target=spin, daemon=True)
        self.thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        self.running = False
        if hasattr(self, "thread"):
            self.thread.join(timeout=0.5)
        return False


def _needs_shell(cmd: list[str]) -> bool:
    """Windows 上只有 npm.cmd / .bat 等脚本需要 shell 解析；exe 直接调用少一层 cmd.exe。"""
    if os.name != "nt":
        return False
    return Path(cmd[0]).suffix.lower() != ".exe"


def run(
    cmd: list[str], *, cwd: Path | None = None, dry_run: bool = False, show_spinner: bool = False
) -> int:
    if dry_run:
        print_message(f"  [dry-run] {' '.join(cmd)}")
        return 0

    cmd_str = " ".join(cmd)
    if show_spinner and _supports_color():
        # 长时间命令：显示进度指示器
        with Spinner(f"执行: {cmd_str[:50]}..."):
            try:
                return subprocess.call(
                    cmd,
                    cwd=str(cwd) if cwd else None,
                    shell=_needs_shell(cmd),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                warn(f"命令不存在: {cmd[0]}")
                return 127
            except KeyboardInterrupt:
                return 130
    else:
        try:
            return subprocess.call(cmd, cwd=str(cwd) if cwd else None, shell=_needs_shell(cmd))
        except FileNotFoundError:
            warn(f"命令不存在: {cmd[0]}")
            return 127
        except KeyboardInterrupt:
            return 130


def which(name: str) -> str | None:
    """跨平台 which：Windows 自动识别 .cmd/.bat/.exe。"""
    if os.name == "nt" and not name.endswith((".cmd", ".bat", ".exe")):
        for suffix in (".cmd", ".bat", ".exe"):
            found = shutil.which(name + suffix)
            if found:
                return found
    return shutil.which(name)


def parse_version(text: str) -> tuple[int, ...]:
    """从版本字符串中提取数字元组；无法解析返回 ()。"""
    import re

    match = re.search(r"(\d+(?:\.\d+)+)", text)
    if not match:
        return ()
    return tuple(int(p) for p in match.group(1).split("."))


def version_str(version: tuple[int, ...]) -> str:
    return ".".join(str(p) for p in version)


# ── 阶段 1：环境预检 ──────────────────────────────────────────────────


def check_python() -> tuple[int, ...]:
    current = sys.version_info[:3]
    if current < MIN_PYTHON:
        fail(
            f"Python 版本过低：{version_str(current)}（要求 >= {version_str(MIN_PYTHON)}）。"
            "请先安装 Python 3.11+：https://www.python.org/downloads/"
        )
    return current


def check_node(dry_run: bool) -> NodeCheckResult:
    node = which("node")
    if node is None:
        if dry_run:
            return NodeCheckResult(False, None)
        warn(
            "未找到 node，前端无法安装。请安装 Node.js LTS：https://nodejs.org/"
            "（若只开发后端可传 --skip-web 跳过）"
        )
        return NodeCheckResult(False, None)
    try:
        out = subprocess.check_output([node, "--version"], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        warn("node --version 执行失败")
        return NodeCheckResult(False, None)
    version = parse_version(out)
    if version and version < MIN_NODE:
        warn(
            f"Node.js 版本过低：{version_str(version)}（要求 >= {version_str(MIN_NODE)}）。"
            "请升级到 Node.js LTS"
        )
        return NodeCheckResult(False, version)
    return NodeCheckResult(True, version)


def check_npm(dry_run: bool) -> str | None:
    npm = which("npm")
    if npm is None and not dry_run:
        warn("未找到 npm（随 Node.js 一起安装）")
    return npm


def check_git(dry_run: bool) -> bool:
    git = which("git")
    if git is None and not dry_run:
        warn("未找到 git。cwiki 用 git 同步多设备数据，建议安装：https://git-scm.com/downloads")
        return False
    return git is not None


# ── 阶段 2：虚拟环境 ─────────────────────────────────────────────────


def ensure_venv(dry_run: bool) -> None:
    """确保 .venv 存在；缺失时用系统 python 创建。"""
    venv_dir = PROJECT_ROOT / ".venv"
    if venv_dir.is_dir():
        info(f"虚拟环境已存在：{venv_dir}")
        return
    if dry_run:
        print_message(f"  [dry-run] 创建虚拟环境：{venv_dir}")
        return

    print_message(f"  创建虚拟环境：{venv_dir}")
    # 用当前解释器（已满足 MIN_PYTHON）创建，保证 venv 内版本一致
    rc = subprocess.call([sys.executable, "-m", "venv", str(venv_dir)])
    if rc != 0:
        fail(f"创建虚拟环境失败（exit {rc}），请手动运行：python -m venv .venv")

    info(f"已创建虚拟环境：{venv_dir}")
    print_message("  提示：请重新运行 install 脚本以使用 .venv 解释器继续安装")
    print_message(f"    source {venv_dir}/bin/activate  # Linux/Mac")
    print_message(f"    {venv_dir}\\Scripts\\activate     # Windows")


# ── 阶段 3：Python 依赖 ─────────────────────────────────────────────


def install_python_deps(dry_run: bool, force: bool = False) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "-e", ".[dev]"]
    if force:
        cmd.append("--force-reinstall")
    print_message("  安装 Python 依赖（pip install -e .[dev]）...")
    rc = run(cmd, dry_run=dry_run, show_spinner=True)
    if rc != 0:
        warn(f"pip install 失败（exit {rc}）")
        print_message("    重试命令: python -m pip install -e .[dev]")
        return False
    return True


def verify_python_deps() -> bool:
    # 加密软件会让 entry_points.txt 不可读，alembic 等模块导入时会扫描全部
    # 发行版元数据；先打补丁再验证，避免把环境问题误报成依赖缺失。
    patch_metadata()
    missing: list[tuple[str, str]] = []
    for module in CORE_PYTHON_MODULES:
        try:
            __import__(module)
        except Exception as exc:
            missing.append((module, str(exc)[:60]))
    if missing:
        warn(f"{len(missing)} 个核心模块无法导入：")
        for module, err in missing:
            print_message(f"      - {module}: {err}")
        return False
    info(f"核心模块验证通过（{len(CORE_PYTHON_MODULES)} 个）")
    return True


# ── 阶段 4：前端依赖 ────────────────────────────────────────────────


def install_web_deps(npm: str | None, dry_run: bool, force: bool = False) -> bool:
    web_dir = PROJECT_ROOT / "apps" / "web"
    if not (web_dir / "package.json").is_file():
        warn(f"前端 package.json 不存在：{web_dir}")
        return False
    if npm is None:
        warn("跳过前端依赖安装（未找到 npm）")
        return False
    print_message("  安装前端依赖（npm install）...")
    cmd = [npm, "install"]
    if force:
        cmd.append("--force")
    rc = run(cmd, cwd=web_dir, dry_run=dry_run, show_spinner=True)
    if rc != 0:
        warn(f"npm install 失败（exit {rc}）")
        print_message(f"    重试命令: cd {web_dir} && npm install")
        return False
    return True


# ── 阶段 5：数据目录与数据库 ───────────────────────────────────────


def ensure_data_dir(dry_run: bool) -> Path:
    cfg = load_app_config(PROJECT_ROOT)
    memory_dir_rel: str = cfg.get("storage", {}).get("memory_dir", "./cwiki-data")
    memory_dir = PROJECT_ROOT / memory_dir_rel
    if memory_dir.is_dir():
        info(f"数据目录已存在：{memory_dir}")
        return memory_dir
    if dry_run:
        print_message(f"  [dry-run] 创建数据目录：{memory_dir}")
    else:
        memory_dir.mkdir(parents=True, exist_ok=True)
        info(f"已创建数据目录：{memory_dir}")
    return memory_dir


def init_database(dry_run: bool) -> bool:
    cfg = load_app_config(PROJECT_ROOT)
    db_url = cfg.get("database", {}).get("url", "sqlite+aiosqlite:///./cwiki-data/cwiki.db")
    if "///" in db_url:
        relative = db_url.split("///", 1)[1].removeprefix("./")
        db_path = PROJECT_ROOT / relative
    else:
        db_path = PROJECT_ROOT / "cwiki-data" / "cwiki.db"

    if db_path.exists():
        info(f"数据库已存在：{db_path}")
        return True

    if dry_run:
        print_message(f"  [dry-run] 初始化数据库：{db_path}")
        return True

    print_message("  运行 Alembic 迁移初始化数据库...")
    rc = run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PROJECT_ROOT)
    if rc != 0:
        warn(f"Alembic 迁移失败（exit {rc}）")
        print_message("    重试命令: python -m alembic upgrade head")
        return False
    info(f"数据库已初始化：{db_path}")
    return True


# ── 阶段 6：Agent 接入配置 ─────────────────────────────────────────


def run_agent_setup(dry_run: bool) -> bool:
    setup_script = PROJECT_ROOT / "scripts" / "setup.py"
    if not setup_script.is_file():
        warn(f"setup.py 不存在：{setup_script}")
        return False
    print_message("  运行 Agent 接入配置（setup.py --sync-instructions）...")
    cmd = [sys.executable, str(setup_script), "--sync-instructions"]
    rc = run(cmd, dry_run=dry_run)
    if rc == DLL_INIT_FAILED:
        warn("子进程初始化失败（0xC0000142），重试一次...")
        rc = run(cmd, dry_run=dry_run)
    if rc != 0:
        warn(f"setup.py 失败（exit {rc}）")
        print_message(f"    重试命令: {sys.executable} {setup_script} --sync-instructions")
        return False
    return True


# ── 完成提示 ─────────────────────────────────────────────────────────


def print_next_steps(cfg: dict[str, Any]) -> None:
    api_port = cfg.get("app", {}).get("api_port", 5172)
    print_message("\n" + "═" * 50)
    print_message("  安装完成！")
    print_message("═" * 50)
    print_message()
    print_message("  下一步：")
    print_message("    1. 启动服务：   python tasks.py start")
    print_message("    2. 打开控制台： http://localhost:5173")
    print_message(f"    3. API 地址：   http://localhost:{api_port}")
    print_message()
    print_message("  常用命令：")
    print_message("    python tasks.py start          # 一键启动前后端")
    print_message("    python tasks.py serve          # 仅启动后端 API")
    print_message("    python tasks.py web            # 仅启动前端界面")
    print_message("    python tasks.py test           # 运行测试")
    print_message("    python tasks.py help           # 查看全部命令")
    print_message()
    print_message("  文档：")
    print_message("    README.md                       项目总览")
    print_message("    docs/development.md             开发与配置指南")
    print_message("    docs/agent-onboarding.md        Agent 接入指南")
    print_message()


# ── 主流程 ───────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="cwiki 一站式安装：环境预检 → 依赖安装 → 数据初始化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的操作，不实际修改系统",
    )
    parser.add_argument(
        "--skip-web",
        action="store_true",
        help="跳过前端依赖安装（未装 Node.js 或只开发后端时使用）",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="跳过数据库初始化",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="跳过 Agent 接入配置（setup.py）",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="跳过 Python 依赖导入验证",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新安装已存在的依赖（清除缓存）",
    )
    return parser.parse_args()


TOTAL_STEPS = 6


def main() -> int:
    args = parse_args()
    dry_run = args.dry_run

    print_message("╔══════════════════════════════════════════╗")
    print_message("║      cwiki 一站式安装向导                ║")
    print_message("╚══════════════════════════════════════════╝")
    if dry_run:
        print_message("\n  [dry-run 模式] 不会实际修改系统\n")

    print_message(f"\n  项目根目录：{PROJECT_ROOT}")
    print_message(f"  Python：     {sys.executable} ({version_str(sys.version_info[:3])})")

    # 阶段 1：环境预检
    step_header(1, TOTAL_STEPS, "环境预检")
    py_version = check_python()
    info(f"Python {version_str(py_version)}")
    node_result = check_node(dry_run)
    if node_result.version:
        info(f"Node.js {version_str(node_result.version)}")
    npm = check_npm(dry_run)
    if npm:
        info("npm 已找到")
    git_ok = check_git(dry_run)
    if git_ok:
        info("git 已找到")

    if not node_result.available and not args.skip_web:
        warn("Node.js 不可用，自动跳过前端安装（等同于 --skip-web）")
        args.skip_web = True

    # 阶段 2：虚拟环境
    step_header(2, TOTAL_STEPS, "虚拟环境")
    ensure_venv(dry_run)

    # 阶段 3：Python 依赖
    step_header(3, TOTAL_STEPS, "安装 Python 依赖")
    py_ok = install_python_deps(dry_run, force=args.force)
    if py_ok and not args.skip_verify:
        verify_python_deps()
    elif not py_ok:
        warn("Python 依赖安装失败，后续步骤可能受影响")

    # 阶段 4：前端依赖
    step_header(4, TOTAL_STEPS, "安装前端依赖")
    if args.skip_web:
        info("已跳过（--skip-web 或 Node.js 不可用）")
    else:
        install_web_deps(npm, dry_run, force=args.force)

    # 阶段 5：数据目录与数据库
    step_header(5, TOTAL_STEPS, "初始化数据与数据库")
    ensure_data_dir(dry_run)
    if args.skip_db:
        info("已跳过数据库初始化（--skip-db）")
    else:
        init_database(dry_run)

    # 阶段 6：Agent 接入配置
    step_header(6, TOTAL_STEPS, "Agent 接入配置")
    if args.skip_setup:
        info("已跳过（--skip-setup）")
    else:
        run_agent_setup(dry_run)

    if not dry_run:
        cfg = load_app_config(PROJECT_ROOT)
        print_next_steps(cfg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
