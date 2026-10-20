#!/usr/bin/env python3
"""cwiki 一键配置脚本

跨平台（Mac / Windows / Linux），用法：
    python scripts/setup.py
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, NoReturn

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 先切换到 .venv 解释器再继续：sys.executable 会被写入 ~/.qoder 下的
# MCP / hooks 配置，系统 python（Homebrew 3.15 等）没有 httpx 等项目依赖，
# 会让 Qoder MCP server 启动即崩（连接失败）。
# scripts 包在 .venv 里经 editable 安装可导入；直接用系统 python 运行时
# sys.path[0] 是 scripts/ 目录而非项目根，故先 bootstrap 再导入。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.common import ensure_venv_interpreter

ensure_venv_interpreter(PROJECT_ROOT)

PLUGIN_NAME = "cwiki-qoder"
PLUGIN_SOURCE_DIR = PROJECT_ROOT / "adapters" / "qoder"
PLUGINS_DIR = Path.home() / ".qoder" / "plugins"

API_PORT = 5172
# Qoder 旧入口（adapters.qoder.mcp_server）与新核心（adapters.mcp）均可启动；
# Qoder 插件缓存继续写旧入口（shim 会把宿主标识固定为 qoder），
# 自检对两个入口都放行。
MCP_MODULE = "adapters.qoder.mcp_server"
MCP_CORE_MODULE = "adapters.mcp"

# MCP 发现自检阈值：initialize + tools/list 总耗时超过该秒数即告警。
DISCOVERY_WARN_SECONDS = 8.0
# 单个 JSON-RPC 步骤的最长等待秒数，超出视为服务器无响应；Qoder 自身发现超时约 20s。
DISCOVERY_STEP_TIMEOUT_SECONDS = 10.0
DISCOVERY_STDERR_TAIL = 2000

AGENTS: dict[str, dict[str, Any]] = {
    "qoder": {
        "name": "Qoder",
        "config_dir": Path.home() / ".qoder",
        "settings_file": Path.home() / ".qoder" / "settings.json",
        "agents_md": Path.home() / ".qoder" / "AGENTS.md",
        "skills_dir": Path.home() / ".qoder" / "skills",
        "skill_source": PROJECT_ROOT / "skills" / "cwiki-save",
    },
}


# ── 通用工具 ──────────────────────────────────────────────────────────


def print_message(msg: str = "") -> None:
    # Windows 重定向输出可能使用 GBK/ASCII，不让装饰符号导致配置中断。
    encoding = sys.stdout.encoding or "utf-8"
    print(msg.encode(encoding, errors="replace").decode(encoding))


def info(msg: str) -> None:
    print_message(f"  ✓ {msg}")


def warn(msg: str) -> None:
    print_message(f"  ⚠ {msg}")


def fail(msg: str) -> NoReturn:
    print_message(f"  ✗ {msg}")
    sys.exit(1)


def read_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def write_text_atomic(path: Path, text: str) -> None:
    """原子写入：先写同目录临时文件再替换，避免目标被宿主进程占用时截断失败。

    Agent 宿主（Qoder 等）可能映射或锁定自己的配置文件，直接 open("w")
    截断会抛 PermissionError；替换文件不受该限制，也避免写入中断损坏配置。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, data: dict[str, Any]) -> None:
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def run(cmd: list[str], **kw: Any) -> int:
    try:
        return subprocess.call(cmd, **kw)
    except FileNotFoundError:
        fail(f"命令不存在: {cmd[0]}，请先安装依赖")


def choose_agent() -> str:
    names = list(AGENTS.keys())
    if len(names) == 1:
        return names[0]
    print_message("\n请选择要接入的 Agent：")
    for i, key in enumerate(names, 1):
        print_message(f"  {i}. {AGENTS[key]['name']}")
    while True:
        try:
            print_message(f"\n输入编号 [1-{len(names)}] (默认 1): ")
            choice = input().strip()
            if not choice:
                return names[0]
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                return names[idx]
        except (ValueError, EOFError):
            pass
        print_message("  无效输入，请重试")


# ── MCP ──────────────────────────────────────────────────────────────


def remove_settings_mcp(settings: dict[str, Any], agent_key: str) -> None:
    """移除 settings.json 中的 mcpServers.cwiki。

    MCP 配置由插件缓存目录的 .mcp.json 提供，settings.json 中不应再有重复条目。
    双重定义会导致工具翻倍或名称冲突。
    """
    servers = settings.get("mcpServers", {})
    if "cwiki" in servers:
        del servers["cwiki"]
        info("已移除 settings.json 中的 mcpServers.cwiki（由插件提供）")
        if not servers:
            del settings["mcpServers"]


# ── 插件 .mcp.json 修补 ──────────────────────────────────────────────


def plugin_version() -> str:
    """从源码 plugin.json 读取版本，插件缓存路径以此为准。"""
    data = read_json(PLUGIN_SOURCE_DIR / ".qoder-plugin" / "plugin.json")
    version = data.get("version", "")
    return version if isinstance(version, str) and version else "0.0.0"


def plugin_cache_dir() -> Path:
    return PLUGINS_DIR / "cache" / "local" / PLUGIN_NAME / plugin_version()


def patch_plugin_mcp(agent_key: str) -> None:
    """修补插件缓存目录中的 .mcp.json，注入正确的 cwd 和 PYTHONPATH。

    Qoder 从插件缓存目录加载 MCP 配置，而非源码目录。
    源码模板不含绝对路径（保证可移植），安装时在此处注入。
    """
    plugin_cache = plugin_cache_dir()
    mcp_json = plugin_cache / ".mcp.json"
    if not mcp_json.is_file():
        warn(f"插件缓存 .mcp.json 不存在，跳过修补: {mcp_json}")
        return
    data = read_json(mcp_json)
    server = data.setdefault("mcpServers", {}).setdefault("cwiki", {})
    server["command"] = sys.executable
    server["cwd"] = str(PROJECT_ROOT)
    env = server.setdefault("env", {})
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    write_json(mcp_json, data)
    info(f"插件缓存 .mcp.json 已修补 (python={sys.executable}, cwd={PROJECT_ROOT})")


def ensure_global_mcp_json() -> None:
    """将 cwiki MCP 服务器注入全局 ~/.qoder/mcp.json，保留已有服务器。

    Qoder 插件系统对本地插件的 marketplace 解析不可靠，
    全局 mcp.json 是 Qoder CLI 在所有项目中直接读取的可靠交付方式。
    从源码模板 adapters/qoder/.mcp.json 读取结构，注入 python/cwd/PYTHONPATH。
    """
    source_template = PLUGIN_SOURCE_DIR / ".mcp.json"
    if not source_template.is_file():
        warn(f"源码模板 .mcp.json 不存在，跳过: {source_template}")
        return
    template = read_json(source_template)
    src_server = template.get("mcpServers", {}).get("cwiki", {})
    src_server["command"] = sys.executable
    src_server["cwd"] = str(PROJECT_ROOT)
    env = src_server.setdefault("env", {})
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    agent = AGENTS["qoder"]
    global_mcp = agent["config_dir"] / "mcp.json"
    if global_mcp.is_file():
        try:
            data = read_json(global_mcp)
        except (OSError, UnicodeError, ValueError):
            data = {}
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    servers["cwiki"] = src_server
    global_mcp.parent.mkdir(parents=True, exist_ok=True)
    write_json(global_mcp, data)
    info(f"全局 mcp.json 已注入 cwiki (python={sys.executable}, cwd={PROJECT_ROOT})")


# ── 插件（hooks）─────────────────────────────────────────────────────

HOOK_COMMAND = "-m adapters.hooks qoder session-start"


def _project_workspace(project: str | None) -> str | None:
    """从项目路径推导工作区名（合法时），供项目级 MCP 配置写入 CWIKI_WORKSPACE。"""
    if not project:
        return None
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(project).name).strip("-")
    if not name or re.match(r"^[A-Za-z]--", name) or re.fullmatch(r"[0-9a-f]{8}", name):
        return None
    return name[:64]


def write_project_mcp(project: Path, workspace: str) -> Path:
    """在 Qoder 项目级 .qoder/mcp.json 写入 cwiki 条目（绑定该项目工作区）。

    全局条目靠目录推导工作区；项目级条目显式声明 CWIKI_WORKSPACE，
    让 Qoder 在该项目下的所有会话都写入正确工作区。
    """
    target = project / ".qoder" / "mcp.json"
    data: dict[str, Any] = {}
    if target.is_file():
        try:
            data = read_json(target)
        except (OSError, UnicodeError, ValueError):
            warn(f"项目 mcp.json 解析失败，跳过项目级配置: {target}")
            return target
    server = data.setdefault("mcpServers", {}).setdefault("cwiki", {})
    server["type"] = "stdio"
    server["command"] = sys.executable
    server["args"] = ["-m", "adapters.qoder.mcp_server"]
    server["cwd"] = str(PROJECT_ROOT)
    server["env"] = {
        "PYTHONPATH": str(PROJECT_ROOT),
        "CWIKI_HOST": "qoder",
        "CWIKI_WORKSPACE": workspace,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, data)
    info(f"项目级 MCP 已写入 {target}（workspace={workspace}）")
    return target


def patch_plugin_hooks(agent_key: str) -> None:
    """修补插件缓存目录中的 hooks/hooks.json，注入正确的 python 和 PYTHONPATH。

    与 patch_plugin_mcp 对称：源码模板不含绝对路径（保证可移植），
    安装时在此处注入。Qoder 通过 shell 执行 command 字符串，
    含空格的 python 路径需加引号。
    """
    hooks_json = plugin_cache_dir() / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        warn(f"插件缓存 hooks.json 不存在，跳过修补: {hooks_json}")
        return
    data = read_json(hooks_json)
    exe = sys.executable
    command_exe = f'"{exe}"' if " " in exe else exe
    patched = 0
    for matchers in data.get("hooks", {}).values():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                # 保留模板里的模块与事件参数，只替换解释器前缀，
                # 避免把 UserPromptSubmit/PostCompact 等事件全部改成 session-start
                current = str(hook.get("command", ""))
                marker = current.find(" -m ")
                suffix = current[marker + 1 :] if marker >= 0 else HOOK_COMMAND
                hook["command"] = f"{command_exe} {suffix}"
                hook.setdefault("env", {})["PYTHONPATH"] = str(PROJECT_ROOT)
                patched += 1
    if not patched:
        warn("hooks.json 中未找到 command 类型 hook，跳过修补")
        return
    write_json(hooks_json, data)
    info(f"插件缓存 hooks.json 已修补 (python={exe}, PYTHONPATH={PROJECT_ROOT})")


def ensure_plugin_installed(agent_key: str) -> None:
    """确保本地插件已安装到 Qoder 插件缓存，缺失时调用 qodercli 安装。

    本地插件由 `qodercli plugins install <源目录>` 安装到
    ~/.qoder/plugins/cache/local/<name>/<version>/ 并注册为 <name>@local。
    未安装 qodercli 时只告警（fail-open），其余配置照常完成。
    """
    mcp_json = plugin_cache_dir() / ".mcp.json"
    if mcp_json.is_file():
        info(f"本地插件已安装：{plugin_cache_dir()}")
        return

    exe = shutil.which("qodercli")
    if exe is None:
        warn(
            "未找到 qodercli，无法安装本地插件，插件 MCP 与 hooks 不会生效。"
            "请先安装 Qoder CLI（brew install qoderai/qoder/qodercli 或 "
            "npm install -g @qoder-ai/qodercli），之后重跑 setup.py 或手动执行："
            f"qodercli plugins install {PLUGIN_SOURCE_DIR}"
        )
        return

    cmd = [exe, "plugins", "install", str(PLUGIN_SOURCE_DIR)]
    if os.name == "nt" and Path(exe).suffix.lower() in (".cmd", ".bat"):
        # CreateProcess 无法直接执行 .cmd/.bat，需经命令解释器。
        cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/c", *cmd]
    if run(cmd) != 0:
        warn(f"qodercli 安装插件失败，请手动运行：qodercli plugins install {PLUGIN_SOURCE_DIR}")
        return
    if mcp_json.is_file():
        info(f"本地插件已安装：{plugin_cache_dir()}")
    else:
        warn(f"qodercli 执行后仍未找到插件缓存，请检查插件源目录：{PLUGIN_SOURCE_DIR}")


# ── 插件（缓存内容）──────────────────────────────────────────────────

# 安装后可被源码修改的内容项：按字节比对，差异即复制进缓存
PLUGIN_SYNC_CONTENT = ("skills", "commands", "README.md", ".qoder-plugin")
# 含安装期注入绝对路径的配置项：与模板规范化比对（剥离注入字段后），
# 不一致（旧快照缺事件/结构漂移）即从模板刷新，随后由 patch_plugin_* 重新注入
PLUGIN_SYNC_SEED = (".mcp.json", "hooks")


def _normalize_mcp_config(data: dict[str, Any]) -> dict[str, Any]:
    """剥离 patch_plugin_mcp 注入的机器相关字段，得到可与模板比对的结构。"""
    data = copy.deepcopy(data)
    server = data.get("mcpServers", {}).get("cwiki")
    if isinstance(server, dict):
        server.pop("command", None)
        server.pop("cwd", None)
        env = server.get("env")
        if isinstance(env, dict):
            env.pop("PYTHONPATH", None)
    return data


def _normalize_hooks_config(data: dict[str, Any]) -> dict[str, Any]:
    """剥离 patch_plugin_hooks 注入的解释器前缀与 PYTHONPATH，得到可比对结构。"""
    data = copy.deepcopy(data)
    for matchers in data.get("hooks", {}).values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            for hook in matcher.get("hooks", []) if isinstance(matcher, dict) else []:
                if hook.get("type") != "command":
                    continue
                current = str(hook.get("command", ""))
                marker = current.find(" -m ")
                if marker >= 0:
                    hook["command"] = "PY" + current[marker:]
                env = hook.get("env")
                if isinstance(env, dict):
                    env.pop("PYTHONPATH", None)
    return data


def _seed_file_diverged(rel: str, source: Path, target: Path) -> bool:
    """缓存配置项是否与模板结构性不一致（需要刷新）。解析失败按不一致处理。"""
    template_path = source if source.is_file() else source / "hooks.json"
    cache_path = target if target.is_file() else target / "hooks.json"
    if not template_path.is_file() or not cache_path.is_file():
        return True
    try:
        template = read_json(template_path)
        cached = read_json(cache_path)
    except (OSError, UnicodeError, ValueError):
        return True
    normalize = _normalize_mcp_config if rel == ".mcp.json" else _normalize_hooks_config
    return normalize(cached) != normalize(template)


def sync_plugin_cache(agent_key: str) -> None:
    """把源码内容同步进插件缓存，修复“安装后修改不生效”的旧快照问题。

    插件缓存是 `qodercli plugins install` 时的快照，其后对 adapters/qoder
    内容文件（skill/命令/插件清单）的修改不会自动进入缓存，宿主加载的仍是
    旧版。内容项按字节比对复制；配置项（.mcp.json/hooks）与模板做规范化
    比对——剥离注入的绝对路径字段后结构一致则保留缓存（注入保持有效），
    不一致（旧快照缺事件、结构漂移）则从模板刷新，随后由
    patch_plugin_mcp / patch_plugin_hooks 重新注入。
    """
    cache = plugin_cache_dir()
    if not cache.is_dir():
        warn(f"插件缓存不存在，跳过内容同步：{cache}")
        return

    synced = 0
    for rel in PLUGIN_SYNC_CONTENT:
        source = PLUGIN_SOURCE_DIR / rel
        if not source.exists():
            continue
        files = [source] if source.is_file() else [p for p in source.rglob("*") if p.is_file()]
        for file in files:
            target = cache / file.relative_to(PLUGIN_SOURCE_DIR)
            if target.is_file() and target.read_bytes() == file.read_bytes():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
            synced += 1

    seeded = 0
    refreshed = 0
    for rel in PLUGIN_SYNC_SEED:
        source = PLUGIN_SOURCE_DIR / rel
        target = cache / rel
        if not source.exists():
            continue
        if not target.exists():
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            seeded += 1
        elif _seed_file_diverged(rel, source, target):
            # 旧快照与模板结构性不一致：从模板刷新，交由随后的 patch 注入
            if target.is_dir():
                shutil.rmtree(target)
            shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
            refreshed += 1

    if synced or seeded or refreshed:
        info(
            f"插件缓存内容已同步（更新 {synced} 个文件，补齐 {seeded} 项，"
            f"刷新 {refreshed} 项配置）：{cache}"
        )
    else:
        info(f"插件缓存内容已是最新：{cache}")


def ensure_plugin_registry() -> None:
    """修正 installed_plugins_v2.json 中的插件注册信息。

    Qoder 宿主从该文件读取插件来源显示。本地插件应注册为 <name>@local；
    若残留 <name>@qoder-marketplace 或裸名键（source=marketplace），UI 会
    错误显示 "Qoder 市场"。此函数检测并修正，防止重装或升级后来源异常。

    官方文档（docs.qoder.com/cli/plugins）：
    - 本地插件 ID 格式：name@local
    - 市场插件 ID 格式：name@marketplace-name
    - qodercli plugins install <path> 应自动注册为 @local
    """
    registry_file = PLUGINS_DIR / "installed_plugins_v2.json"
    if not registry_file.is_file():
        return

    try:
        data = read_json(registry_file)
    except (json.JSONDecodeError, OSError):
        return

    plugins: dict[str, Any] = data.get("plugins", {})
    local_key = f"{PLUGIN_NAME}@local"
    # 所有非 @local 的键均为残留（裸名、@qoder-marketplace 等）
    stale_keys = [k for k in plugins if k.startswith(PLUGIN_NAME) and k != local_key]

    has_local = local_key in plugins
    has_stale = bool(stale_keys)

    if has_local and not has_stale:
        # 检查 local 条目是否干净（无 source/marketId）
        entry = plugins[local_key][0] if plugins[local_key] else {}
        if "source" not in entry and "marketId" not in entry:
            return  # 已完全正确

    changed = False

    # 清理残留键，必要时从第一个残留条目恢复元数据
    for stale_key in stale_keys:
        stale_entries = plugins.pop(stale_key)
        info(f"已清理注册表残留键 {stale_key}")
        if not has_local and stale_entries:
            # 复用旧条目元数据，移除非本地插件字段
            entry = dict(stale_entries[0])
            entry.pop("source", None)
            entry.pop("marketId", None)
            plugins[local_key] = [entry]
            has_local = True
            info(f"已从旧条目恢复 {local_key}")
            changed = True

    # 清理 local 条目中的非本地插件字段
    if has_local:
        for entry in plugins[local_key]:
            for field in ("source", "marketId"):
                if field in entry:
                    del entry[field]
                    changed = True

    if changed:
        data["plugins"] = plugins
        write_json(registry_file, data)
        info(f"已修正插件注册表：{registry_file}")
    elif not has_local and plugin_cache_dir().is_dir():
        # 插件缓存存在但注册表无条目——qodercli install 可能未正确执行
        warn(f"插件缓存存在但注册表无 {local_key} 条目，请运行 qodercli plugins install 重新注册")


def ensure_plugin_enabled(settings: dict[str, Any], agent_key: str) -> None:
    """在 settings.json 的 enabledPlugins 中启用 cwiki 插件，清理残留条目。

    本地安装的插件 ID 为 <name>@local；裸名与旧市场键无法被宿主解析，
    会以 "Ignoring enabled plugin intent" 记录后忽略，这里一并清理。
    """
    enabled = settings.setdefault("enabledPlugins", {})

    for stale_key in (f"{PLUGIN_NAME}@qoder-marketplace", PLUGIN_NAME):
        if stale_key in enabled:
            del enabled[stale_key]
            info(f"已清理残留条目 {stale_key}")

    local_key = f"{PLUGIN_NAME}@local"
    if enabled.get(local_key) is True:
        info(f"插件 {local_key} 已启用")
        return
    enabled[local_key] = True
    info(f"插件 {local_key} 已启用（hooks 随新会话生效；MCP 服务器需重启 Qoder 加载）")


# ── AGENTS.md ────────────────────────────────────────────────────────


CWIKI_AGENTS_START = "<!-- cwiki:begin -->"
CWIKI_AGENTS_END = "<!-- cwiki:end -->"
# 受管区块正文独立维护在 scripts/templates/cwiki-agents-block.md，安装脚本读取后注入
AGENTS_TEMPLATE_FILE = Path(__file__).resolve().parent / "templates" / "cwiki-agents-block.md"
CWIKI_AGENTS_MD = AGENTS_TEMPLATE_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
if not CWIKI_AGENTS_MD.endswith("\n"):
    CWIKI_AGENTS_MD += "\n"

GLOBAL_AGENTS_MD = (
    """\
# Global Instructions

## Language

Always respond in Chinese (Simplified) unless the user explicitly writes in another language or requests otherwise. Code, commands, and technical identifiers stay as-is; explanations, summaries, and conversational text should be in Chinese.

## Cross-Platform

提供 shell 命令或脚本时，确保跨平台兼容（Mac / Windows / Linux）：
- 优先使用跨平台工具（Node.js、Python）
- 需要平台特定命令时，同时给出 PowerShell / bash 版本
- 避免使用仅 macOS/Linux 可用的命令（如 `sed -i`、`xargs`）而不提供替代方案

"""
    + f"{CWIKI_AGENTS_START}\n{CWIKI_AGENTS_MD}{CWIKI_AGENTS_END}\n"
)


def ensure_agents_md(agent_key: str) -> None:
    agent = AGENTS[agent_key]
    agents_md = agent["agents_md"]
    agent["config_dir"].mkdir(parents=True, exist_ok=True)
    block = f"{CWIKI_AGENTS_START}\n{CWIKI_AGENTS_MD}{CWIKI_AGENTS_END}"

    if not agents_md.exists():
        write_text_atomic(agents_md, GLOBAL_AGENTS_MD)
        info(f"AGENTS.md 已写入 cwiki 工具契约：{agents_md}")
        return

    existing = agents_md.read_text(encoding="utf-8")
    if CWIKI_AGENTS_START in existing or CWIKI_AGENTS_END in existing:
        if (
            existing.count(CWIKI_AGENTS_START) != 1
            or existing.count(CWIKI_AGENTS_END) != 1
            or existing.index(CWIKI_AGENTS_START) > existing.index(CWIKI_AGENTS_END)
        ):
            fail(f"cwiki 区块标记不完整或重复，未修改文件：{agents_md}")
        start = existing.index(CWIKI_AGENTS_START)
        end = existing.index(CWIKI_AGENTS_END) + len(CWIKI_AGENTS_END)
        updated = existing[:start] + block + existing[end:]
    else:
        legacy = re.search(r"(?m)^## cwiki 记忆系统[ \t]*\n", existing)
        if legacy:
            next_heading = re.search(r"(?m)^#{1,2} ", existing[legacy.end() :])
            end = legacy.end() + next_heading.start() if next_heading else len(existing)
            fd, backup = tempfile.mkstemp(
                prefix=f"{agents_md.name}.cwiki-", suffix=".bak", dir=agents_md.parent
            )
            os.close(fd)
            shutil.copy2(agents_md, backup)
            info(f"旧版 cwiki 指引已备份：{backup}")
            updated = existing[: legacy.start()] + block + "\n\n" + existing[end:]
        else:
            separator = "" if not existing or existing.endswith("\n\n") else "\n\n"
            updated = existing + separator + block + "\n"

    if updated == existing:
        info(f"cwiki 工具契约已是最新：{agents_md}")
        return
    write_text_atomic(agents_md, updated)
    info(f"cwiki 工具契约已更新，区块外内容保持不变：{agents_md}")


# ── skill ────────────────────────────────────────────────────────────


def ensure_skill(agent_key: str) -> None:
    agent = AGENTS[agent_key]
    skills_dir = agent.get("skills_dir")
    source_dir = agent.get("skill_source")
    if not skills_dir or not source_dir:
        return

    source = source_dir / "SKILL.md"
    if not source.is_file():
        fail(f"Skill 源文件不存在或不是文件：{source}")

    link_dir = skills_dir / source_dir.name
    target = link_dir / "SKILL.md"

    if link_dir.is_symlink():
        if link_dir.resolve() == source_dir.resolve():
            info(f"cwiki Skill 软链已就位：{link_dir}")
            return
        link_dir.unlink()
    elif link_dir.exists():
        shutil.rmtree(link_dir)

    link_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(source_dir, link_dir, target_is_directory=True)
        info(f"cwiki Skill 软链就位：{link_dir} → {source_dir}")
    except OSError:
        link_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        warn(f"软链失败，已复制文件：{target}（修改源文件后需重新运行）")


# ── 数据库与服务 ─────────────────────────────────────────────────────


def init_db() -> None:
    print_message("\n[4/5] 初始化数据库")
    if run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=str(PROJECT_ROOT)) != 0:
        warn("数据库迁移失败，可稍后手动运行：python tasks.py migrate-init")


def serve() -> None:
    run(
        [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--reload", "--port", str(API_PORT)],
        cwd=str(PROJECT_ROOT),
    )


# ── 自检诊断 ─────────────────────────────────────────────────────────


def _read_jsonrpc_response(
    lines: queue.Queue[str | None], want_id: int, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"等待 JSON-RPC 响应 id={want_id} 超时（{timeout}s）")
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        if line is None:
            raise RuntimeError(f"MCP 进程在返回 id={want_id} 响应前退出")
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("id") != want_id:
            # 通知/日志等非目标响应行直接跳过
            continue
        error = message.get("error")
        if error:
            raise RuntimeError(f"JSON-RPC 返回错误：{error}")
        return message


def _summarize_probe_failure(
    exc: BaseException, stderr_chunks: list[str], secrets: list[str]
) -> str:
    detail = str(exc) or exc.__class__.__name__
    tail = "".join(stderr_chunks)[-DISCOVERY_STDERR_TAIL:].strip()
    for secret in secrets:
        if secret:
            tail = tail.replace(secret, "***")
    if tail:
        detail = f"{detail}；stderr 末尾：{tail}"
    return detail[:1000]


def _shutdown_probe_process(proc: subprocess.Popen[str]) -> None:
    # 优先发 exit 通知让服务器自行退出；只操作本函数 spawn 的进程。
    try:
        if proc.stdin is not None:
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "exit"}) + "\n")
            proc.stdin.flush()
    except (OSError, ValueError):
        pass
    try:
        proc.wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def probe_mcp_discovery(server: dict[str, Any]) -> dict[str, Any]:
    """按插件缓存 .mcp.json 的 command/args/cwd/env 短暂 spawn MCP 服务器，
    计时 initialize + tools/list 握手，用于暴露 Defender 扫描等导致的冷启动超时。

    只终止本函数 spawn 的进程；env 中的值（可能含 token）不会进入返回结果。
    """
    probe: dict[str, Any] = {
        "ok": False,
        "total_seconds": None,
        "tools_count": None,
        "error": None,
    }
    command = server.get("command")
    args = server.get("args") or []
    if not isinstance(command, str) or not command:
        probe["error"] = "插件 MCP 缺少 command"
        return probe
    env = dict(os.environ)
    extra_env = server.get("env") or {}
    secrets: list[str] = []
    if isinstance(extra_env, dict):
        for key, value in extra_env.items():
            text = str(value)
            env[str(key)] = text
            secrets.append(text)
    cwd = server.get("cwd") or str(PROJECT_ROOT)

    started = time.monotonic()
    proc: subprocess.Popen[str] | None = None
    lines: queue.Queue[str | None] = queue.Queue()
    stderr_chunks: list[str] = []
    try:
        proc = subprocess.Popen(
            [command, *[str(a) for a in args]],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def collect_stdout() -> None:
            assert proc is not None and proc.stdout is not None
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        def collect_stderr() -> None:
            assert proc is not None and proc.stderr is not None
            stderr_chunks.extend(proc.stderr)

        # 后台线程持续读取输出，避免管道缓冲区写满导致子进程卡死
        threading.Thread(target=collect_stdout, daemon=True).start()
        threading.Thread(target=collect_stderr, daemon=True).start()

        stdin = proc.stdin
        assert stdin is not None

        def send(message: dict[str, Any]) -> None:
            stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            stdin.flush()

        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cwiki-doctor", "version": "0.1.0"},
                },
            }
        )
        _read_jsonrpc_response(lines, 1, DISCOVERY_STEP_TIMEOUT_SECONDS)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        response = _read_jsonrpc_response(lines, 2, DISCOVERY_STEP_TIMEOUT_SECONDS)
        tools = response.get("result", {}).get("tools")
        probe["ok"] = True
        probe["tools_count"] = len(tools) if isinstance(tools, list) else None
    except (
        OSError,
        ValueError,
        AttributeError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        probe["error"] = _summarize_probe_failure(exc, stderr_chunks, secrets)
    finally:
        if proc is not None:
            _shutdown_probe_process(proc)
    probe["total_seconds"] = round(time.monotonic() - started, 2)
    return probe


def check_installation(agent_key: str) -> dict[str, Any]:
    """检查磁盘上的安装状态并探测 MCP 发现时延；只读，不写任何文件。"""
    agent = AGENTS[agent_key]
    errors: list[str] = []
    warnings: list[str] = []
    result: dict[str, Any] = {
        "scope": "disk_and_spawn_probe",
        "host_verified": False,
        "hint": "磁盘一致且发现自检通过，不代表 Qoder 当前会话已加载；hooks 与 skill 随新会话刷新，插件 MCP 服务器列表在 Qoder 启动时确定，安装或更新插件后需完全重启 Qoder，再以 tools/list 和 memory_status 核对。",
    }
    try:
        instructions = agent["agents_md"].read_text(encoding="utf-8")
        block = f"{CWIKI_AGENTS_START}\n{CWIKI_AGENTS_MD}{CWIKI_AGENTS_END}"
        result["instructions_current"] = (
            instructions.count(CWIKI_AGENTS_START) == 1
            and instructions.count(CWIKI_AGENTS_END) == 1
            and block in instructions
        )
        if not result["instructions_current"]:
            errors.append("全局 AGENTS 托管区块需要同步")
    except (OSError, UnicodeError):
        result["instructions_current"] = False
        errors.append("无法读取全局 AGENTS")

    source = agent["skill_source"] / "SKILL.md"
    installed = agent["skills_dir"] / "cwiki-save" / "SKILL.md"
    try:
        result["skill_current"] = source.read_bytes() == installed.read_bytes()
        result["skill_symlink"] = installed.parent.is_symlink()
        if not result["skill_current"]:
            errors.append("已安装 skill 与项目源文件不同")
    except OSError:
        result["skill_current"] = False
        errors.append("无法读取项目或已安装的 cwiki-save skill")

    try:
        config = json.loads(agent["settings_file"].read_text(encoding="utf-8-sig"))
        result["plugin_enabled"] = bool(
            config.get("enabledPlugins", {}).get(f"{PLUGIN_NAME}@local")
        )
        if not result["plugin_enabled"]:
            errors.append(f"插件 {PLUGIN_NAME}@local 未启用，hooks 不会触发")

        stale_keys = [
            key
            for key in (PLUGIN_NAME, f"{PLUGIN_NAME}@qoder-marketplace")
            if key in config.get("enabledPlugins", {})
        ]
        for stale_key in stale_keys:
            errors.append(f"残留条目 {stale_key} 需要清理，重新运行 setup.py")

        if config.get("mcpServers", {}).get("cwiki"):
            errors.append("settings.json 中存在 mcpServers.cwiki，与插件冲突，重新运行 setup.py")
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        errors.append("无法解析 Qoder MCP 配置")

    # 检查 installed_plugins_v2.json 注册表
    registry_file = PLUGINS_DIR / "installed_plugins_v2.json"
    try:
        if registry_file.is_file():
            reg = json.loads(registry_file.read_text(encoding="utf-8"))
            reg_plugins = reg.get("plugins", {})
            local_reg_key = f"{PLUGIN_NAME}@local"
            # 所有非 @local 的键均为残留
            stale_reg_keys = [
                k for k in reg_plugins if k.startswith(PLUGIN_NAME) and k != local_reg_key
            ]
            for stale_key in stale_reg_keys:
                errors.append(f"注册表残留 {stale_key}，UI 会显示错误来源，重新运行 setup.py")
            if local_reg_key in reg_plugins:
                for entry in reg_plugins[local_reg_key]:
                    if entry.get("source") == "marketplace":
                        errors.append("注册表 local 条目仍有 source=marketplace，重新运行 setup.py")
                        break
    except (OSError, ValueError):
        pass  # 非关键检查，失败不阻断

    plugin_cache = plugin_cache_dir() / ".mcp.json"
    try:
        plugin_mcp = json.loads(plugin_cache.read_text(encoding="utf-8"))
        server = plugin_mcp.get("mcpServers", {}).get("cwiki", {})
        command = server.get("command")
        args = server.get("args", [])
        result["mcp_configured"] = bool(command) and not server.get("disabled", False)
        result["mcp_command_available"] = bool(
            isinstance(command, str) and (Path(command).is_file() or shutil.which(command))
        )
        result["mcp_uses_module_mode"] = (
            isinstance(args, list)
            and "-m" in args
            and (MCP_MODULE in args or MCP_CORE_MODULE in args)
        )
        result["mcp_uses_full_python_path"] = bool(
            isinstance(command, str) and Path(command).is_file()
        )
        if not result["mcp_configured"] or not result["mcp_command_available"]:
            warnings.append(
                "插件缓存 MCP 未配置或 Python 解释器不可用，"
                "请重新运行 setup.py 安装本地插件（全局 mcp.json 可兜底）"
            )
        if not result.get("mcp_uses_module_mode"):
            warnings.append("插件缓存 MCP 未使用 python -m 模块模式")
        if not result.get("mcp_uses_full_python_path"):
            warnings.append("插件缓存 MCP command 未使用完整 Python 路径")

        if result["mcp_configured"] and result["mcp_command_available"]:
            probe = probe_mcp_discovery(server)
            result["discovery"] = probe
            if probe["ok"]:
                if (
                    probe["total_seconds"] is not None
                    and probe["total_seconds"] > DISCOVERY_WARN_SECONDS
                ):
                    warnings.append(
                        f"MCP 发现耗时 {probe['total_seconds']}s 超过阈值 {DISCOVERY_WARN_SECONDS}s，"
                        f"Qoder 启动时可能因此超时；可将插件缓存目录与项目目录加入 Windows Defender "
                        f"排除项：{PLUGINS_DIR}、{PROJECT_ROOT}"
                    )
            else:
                warnings.append(f"MCP 发现自检失败：{probe['error']}")
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
        warnings.append(
            "无法读取插件缓存 .mcp.json，请重新运行 setup.py 安装本地插件（全局 mcp.json 仍可兜底）"
        )

    global_mcp = agent["config_dir"] / "mcp.json"
    if global_mcp.is_file():
        try:
            gmcp = json.loads(global_mcp.read_text(encoding="utf-8"))
            gserver = gmcp.get("mcpServers", {}).get("cwiki", {})
            result["global_mcp_configured"] = bool(gserver.get("command"))
            if not result["global_mcp_configured"]:
                errors.append("全局 mcp.json 存在但 cwiki server 缺少 command")
        except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
            result["global_mcp_configured"] = False
            errors.append("全局 mcp.json 解析失败")
    else:
        result["global_mcp_configured"] = False
        errors.append("全局 mcp.json 不存在，重新运行 setup.py")

    result["status"] = "ok" if not errors else "attention_required"
    result["errors"] = errors
    result["warnings"] = warnings
    return result


# ── 主流程 ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="只读检查安装文件并自检 MCP 发现时延（会短暂 spawn 本插件服务器，不写入任何文件）",
    )
    mode.add_argument(
        "--sync-instructions",
        action="store_true",
        help="同步全局 AGENTS、skill 与插件启用状态（不初始化数据库）",
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="项目路径：在该项目下写 .qoder/mcp.json 并绑定工作区（CWIKI_WORKSPACE）",
    )
    args = parser.parse_args()
    if args.check:
        report = check_installation("qoder")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(0 if report["status"] == "ok" else 1)
    if args.sync_instructions:
        ensure_agents_md("qoder")
        ensure_skill("qoder")
        ensure_plugin_installed("qoder")
        sync_plugin_cache("qoder")
        patch_plugin_mcp("qoder")
        patch_plugin_hooks("qoder")
        agent = AGENTS["qoder"]
        settings_file = agent["settings_file"]
        if settings_file.exists():
            settings = read_json(settings_file)
            remove_settings_mcp(settings, "qoder")
            ensure_plugin_enabled(settings, "qoder")
            write_json(settings_file, settings)
        ensure_plugin_registry()
        ensure_global_mcp_json()
        if args.project:
            project_path = Path(args.project).expanduser().resolve()
            workspace = _project_workspace(str(project_path))
            if workspace:
                write_project_mcp(project_path, workspace)
            else:
                warn(f"项目路径无法推导合法工作区名，跳过项目级配置: {project_path}")
        return

    print_message("╔══════════════════════════════════════╗")
    print_message("║      cwiki 一键配置向导              ║")
    print_message("╚══════════════════════════════════════╝")

    # 1. 选择 Agent
    print_message("\n[1/5] 选择 Agent")
    agent_key = choose_agent()
    agent = AGENTS[agent_key]
    agent_cfg = agent["config_dir"]
    info(f"已选择: {agent['name']}")

    # 2. 检查环境
    print_message("\n[2/5] 检查环境")
    info(f"项目根目录: {PROJECT_ROOT}")

    # 3. 注册 MCP 服务 & Agent 约束
    print_message("\n[3/5] 注册 MCP 服务 & Agent 约束")
    agent_cfg.mkdir(parents=True, exist_ok=True)

    settings_file = agent["settings_file"]
    settings = {}
    if settings_file.exists():
        settings = read_json(settings_file)

    remove_settings_mcp(settings, agent_key)
    ensure_plugin_enabled(settings, agent_key)
    write_json(settings_file, settings)
    ensure_plugin_registry()
    info(f"配置已写入: {settings_file}")

    ensure_plugin_installed(agent_key)
    sync_plugin_cache(agent_key)
    patch_plugin_mcp(agent_key)
    patch_plugin_hooks(agent_key)
    ensure_global_mcp_json()

    ensure_agents_md(agent_key)
    ensure_skill(agent_key)

    if args.project:
        project_path = Path(args.project).expanduser().resolve()
        workspace = _project_workspace(str(project_path))
        if workspace:
            write_project_mcp(project_path, workspace)
        else:
            warn(f"项目路径无法推导合法工作区名，跳过项目级配置: {project_path}")

    # 4. 初始化数据库
    init_db()

    # 5. 完成
    print_message("\n[5/5] 配置完成！")
    print_message()
    print_message("  MCP 工具:  memory_search / memory_save / memory_status")
    print_message("             memory_types / memory_history / memory_relations")
    print_message("             memory_update / memory_retry_failed / memory_checkpoint")
    print_message("             memory_export / memory_import")
    print_message("  Skill:     /cwiki-save")
    print_message(f"  API:       http://localhost:{API_PORT}")
    print_message()

    try:
        print_message("是否启动 API 服务？(Y/n): ")
        ans = input().strip().lower()
    except EOFError:
        ans = "y"
    if ans in ("", "y", "yes"):
        print_message("\n启动 API 服务… (Ctrl+C 退出)\n")
        serve()


if __name__ == "__main__":
    main()
