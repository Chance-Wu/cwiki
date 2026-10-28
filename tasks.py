"""跨平台任务入口，取代 Makefile 以兼容 Windows / Unix。

用法:
    python tasks.py <task> [args...]

示例:
    python tasks.py install
    python tasks.py migrate-create "add users table"
    python tasks.py web
"""

import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# 先切换到 .venv 解释器再导入第三方依赖（scripts.* 内部会 import yaml 等）
from scripts.common import ensure_venv_interpreter, load_app_config

ensure_venv_interpreter(ROOT)

from scripts.port_utils import (
    ensure_port_free,
    force_kill_port,
    kill_mcp_adapter,
    port_is_free,
)

logger = logging.getLogger(__name__)


def _python() -> str:
    return sys.executable


def _run(*cmd: str, cwd: Path | None = None) -> int:
    print(f"$ {' '.join(cmd)}")
    # Windows 下必须经 shell 执行，才能解析 npm.cmd / .bat 等非 exe 命令
    result = subprocess.run(cmd, cwd=cwd, shell=sys.platform == "win32", check=False)
    return result.returncode


def _py(*args: str, cwd: Path | None = None) -> int:
    return _run(_python(), *args, cwd=cwd)


def _api_port() -> int:
    return int(load_app_config(ROOT).get("app", {}).get("api_port", 5172))


def _api_host() -> str:
    return load_app_config(ROOT).get("app", {}).get("api_host", "127.0.0.1")


def _ensure_port(port: int) -> bool:
    try:
        return ensure_port_free(port)
    except RuntimeError as exc:
        print(f"  ✗ {exc}")
        return False


def _force_free_port(port: int) -> bool:
    try:
        force_kill_port(port)
        return True
    except RuntimeError as exc:
        print(f"  ✗ {exc}")
        return False


def _is_git_repo() -> bool:
    """判断项目根目录是否位于 git 仓库内。"""
    return (ROOT / ".git").exists()


def _db_path() -> Path:
    """从配置解析 SQLite 数据库路径（默认 cwiki-data/cwiki.db）。"""
    try:
        from packages.domain.config import settings

        url = settings.database_url
        # 去掉 scheme 前缀：sqlite+aiosqlite:///./cwiki-data/cwiki.db -> cwiki-data/cwiki.db
        if "///" in url:
            relative = url.split("///", 1)[1]
            relative = relative.removeprefix("./")
            return ROOT / relative
    except Exception:
        logger.debug("Could not read database URL from config, using default path")
    return ROOT / "cwiki-data" / "cwiki.db"


def _git_pull_rebase() -> None:
    """拉取代码仓库最新提交。失败只记录不阻塞（离线或有未提交改动时照常启动）。"""
    if not _is_git_repo():
        return
    print("[sync] git pull --rebase (code) ...")
    rc = _run("git", "pull", "--rebase")
    if rc != 0:
        print(
            f"[sync] git pull (code) failed (rc={rc}); continuing "
            "(offline, or local changes pending a commit)"
        )


def _ensure_db() -> None:
    """数据库文件缺失时，从 MD + _meta 重建 SQLite。

    ``scripts/rebuild_db.py`` 会一并处理向量索引与派生字段重算
    （二者在数据仍然最新时自动跳过），这里无需额外步骤。
    """
    db = _db_path()
    if db.exists():
        return
    print(f"[sync] {db} not found, rebuilding from MD + _meta ...")
    rc = _py("scripts/rebuild_db.py")
    if rc != 0:
        print("[sync] rebuild failed — database is required for service")
        sys.exit(1)
    if not db.exists():
        print("[sync] rebuild completed but database file still missing")
        sys.exit(1)


def _ensure_schema() -> None:
    """启动前应用未执行的迁移（幂等）。

    旧 schema 启动会在写入/审核路径触发 500，故迁移失败直接拒绝启动。
    """
    print("[sync] alembic upgrade head ...")
    rc = _py(str(ROOT / "scripts" / "run_alembic.py"), "upgrade", "head")
    if rc != 0:
        print("[sync] migration failed — refusing to start with stale schema")
        sys.exit(1)


def _ensure_index() -> None:
    """向量索引文件缺失/不完整时，仅重建索引。

    此时数据库本身完好（``_ensure_db`` 已先行执行），但派生的索引文件
    可能单独丢失（git 冲突取舍、手动误删等）。只重建索引可避免整库
    重建，并修复语义检索。失败不阻塞启动：服务照常起，检索可能降级。
    """
    db = _db_path()
    if not db.exists():
        # 该场景由 _ensure_db 处理，其全量重建会连带恢复索引。
        return

    from packages.storage.rebuilder import index_files_present

    present, missing = index_files_present()
    if present:
        return

    print(f"[sync] index files missing ({', '.join(missing)}), rebuilding index only ...")
    rc = _py("scripts/rebuild_db.py", "--index-only")
    if rc != 0:
        print("[sync] index rebuild failed (non-blocking, retrieval may be degraded)")


TASK_REGISTRY: dict[str, tuple] = {}


def task(name: str):
    def decorator(fn):
        TASK_REGISTRY[name] = fn
        return fn

    return decorator


@task("setup")
def setup():
    """运行项目配置脚本。"""
    return _py("scripts/setup.py")


@task("install")
def install():
    """一站式安装（环境预检 → 依赖 → 数据库 → Agent 接入）。透传 --dry-run/--skip-*。"""
    return _py("scripts/install.py", *sys.argv[2:])


@task("install-deps")
def install_deps():
    """仅安装 Python 依赖并验证核心模块可导入（install 的子集，向后兼容）。"""
    r = _py("-m", "pip", "install", "-e", ".[dev]")
    if r != 0:
        return r
    print("\n[verify] importing core modules...")
    mods = [
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
        "pytest",
        "ruff",
    ]
    failed = []
    for m in mods:
        try:
            __import__(m)
        except Exception as e:
            failed.append((m, str(e)[:80]))
    if failed:
        print("[verify] FAIL:")
        for m, err in failed:
            print(f"  - {m}: {err}")
        return 1
    print(f"[verify] OK ({len(mods)} modules)")
    return 0


@task("test")
def test():
    """运行测试套件。"""
    return _py("scripts/run_pytest.py", "tests/", "-v")


@task("lint")
def lint():
    """运行 lint 检查与格式校验。"""
    r = _py("-m", "ruff", "check", ".")
    if r != 0:
        return r
    return _py("-m", "ruff", "format", "--check", ".")


@task("format")
def format():
    """自动修复 lint 问题并格式化代码。"""
    r = _py("-m", "ruff", "check", "--fix", ".")
    if r != 0:
        return r
    return _py("-m", "ruff", "format", ".")


@task("serve")
def serve():
    """启动 API 服务（端口被占用时失败退出）。"""
    port = _api_port()
    host = _api_host()
    if not _ensure_port(port):
        return 1
    return _py(
        "-m", "uvicorn", "apps.api.main:app", "--reload", "--host", host, "--port", str(port)
    )


@task("restart-serve")
def restart_serve():
    """强制重启 API 服务（先释放端口）。"""
    port = _api_port()
    host = _api_host()
    if not port_is_free(port):
        print("正在停止旧服务...")
        if not _force_free_port(port):
            return 1
    return _py(
        "-m", "uvicorn", "apps.api.main:app", "--reload", "--host", host, "--port", str(port)
    )


@task("restart-mcp")
def restart_mcp():
    """终止 MCP 适配器进程；Qoder 会在下次工具调用时自动重新拉起。"""
    killed = kill_mcp_adapter()
    if killed:
        print(f"  已终止 {killed} 个 MCP 适配器进程，Qoder 将在下次工具调用时自动重新拉起")
        print("  提示：当前会话的工具注册表不会刷新，可能需要 manage_mcp retry 或新会话")
    else:
        print("  没有正在运行的 MCP 适配器进程")
    return 0


@task("worker")
def worker():
    """运行后台 worker。"""
    return _py("-m", "apps.worker.run_worker")


@task("migrate-init")
def migrate_init():
    """用全部迁移初始化数据库（migrate-up 的别名）。"""
    return migrate_up()


@task("migrate-create")
def migrate_create():
    """生成新迁移。用法: python tasks.py migrate-create "描述" """
    msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "auto"
    return _py(str(ROOT / "scripts" / "run_alembic.py"), "revision", "--autogenerate", "-m", msg)


@task("migrate-up")
def migrate_up():
    """应用所有未执行的迁移。"""
    return _py(str(ROOT / "scripts" / "run_alembic.py"), "upgrade", "head")


@task("migrate-down")
def migrate_down():
    """回滚最近一次迁移。"""
    return _py(str(ROOT / "scripts" / "run_alembic.py"), "downgrade", "-1")


@task("migrate-to-git")
def migrate_to_git():
    """将 SQLite 记忆导出为 Markdown + _meta 文件（Phase 1.4）。"""
    return _py("scripts/migrate_to_git.py")


@task("setup-dsh")
def setup_dsh():
    """为 DeepSeek Harness 注册 cwiki MCP 并绑定当前项目工作区。"""
    return _py("scripts/setup_dsh.py", *sys.argv[2:])


@task("setup-agent")
def setup_agent():
    """为 Claude Code / Cursor / Codex 写入全局 cwiki MCP、hooks 与指令。"""
    return _py("scripts/setup_agent.py", *sys.argv[2:])


@task("import-qoder-memory")
def import_qoder_memory():
    """导入 Qoder Auto-Memory 到 cwiki 待整理（默认 dry-run，--apply 落库）。"""
    return _py("scripts/import_qoder_memory.py", *sys.argv[2:])


@task("rebuild-db")
def rebuild_db():
    """从 Markdown + _meta 文件重建 SQLite（Phase 1.3）。

    索引仍最新时跳过向量索引；_meta 已恢复复习计划时跳过 recompute。
    传 --force-index 强制重新生成 embedding，--index-only 仅修复
    index.db + vectors.npz。
    """
    return _py("scripts/rebuild_db.py", *sys.argv[2:])


@task("recompute")
def recompute():
    """重算全部派生字段（SM-2 复习计划等）。"""
    return _py("scripts/recompute.py")


def _web_dev() -> int:
    web_dir = ROOT / "apps" / "web"
    r = _run("npm", "install", cwd=web_dir)
    if r != 0:
        return r
    return _run("npm", "run", "dev", cwd=web_dir)


@task("web")
def web():
    """启动前端开发服务器（端口被占用时失败退出）。"""
    if not _ensure_port(5173):
        return 1
    return _web_dev()


@task("preview")
def preview():
    """构建并以前端生产模式启动（内存约为 dev 模式一半，适合日常浏览）。"""
    web_dir = ROOT / "apps" / "web"
    r = _run("npm", "install", cwd=web_dir)
    if r != 0:
        return r
    r = _run("npm", "run", "build", cwd=web_dir)
    if r != 0:
        return r
    if not _ensure_port(4173):
        return 1
    return _run("npm", "run", "preview", cwd=web_dir)


@task("restart-web")
def restart_web():
    """强制重启前端开发服务器（先释放端口）。"""
    if not port_is_free(5173):
        print("正在停止旧服务...")
        if not _force_free_port(5173):
            return 1
    return _web_dev()


@task("start")
def start():
    """启动全部服务（先拉取代码仓库；数据库/索引缺失时自动重建）。"""
    _git_pull_rebase()
    _ensure_db()
    _ensure_index()
    _ensure_schema()
    return _py("start.py")


@task("restart")
def restart():
    """强制重启全部服务（先拉取代码仓库）。"""
    _git_pull_rebase()
    _ensure_schema()
    return _py("start.py", "--restart")


def _help():
    print("Usage: python tasks.py <task> [args...]\n")
    print("Available tasks:")
    for name, fn in TASK_REGISTRY.items():
        doc = (fn.__doc__ or "").strip().split("\n")[0]
        print(f"  {name:<18} {doc}")


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        _help()
        return 0

    name = sys.argv[1]
    fn = TASK_REGISTRY.get(name)
    if fn is None:
        print(f"Unknown task: {name}")
        print("Run 'python tasks.py help' to see available tasks.")
        return 1

    return fn() or 0


if __name__ == "__main__":
    sys.exit(main())
