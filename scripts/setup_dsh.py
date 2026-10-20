#!/usr/bin/env python3
"""为 DeepSeek Harness（dsh）配置 cwiki 接入。

dsh 连接外部 MCP 服务器只有一条路径：在 profile 的 patch 层
``$DSH_HOME/profiles/<profile>/cordis.patch.yml`` 里，用官方
``@deepseek-ai/dsh-mcp-client`` 桥声明一行 stdio 配置。早期版本写的
``~/.dsh/mcp.json`` DSH 根本不读——已废弃。

要点（均为实测）：
- 配置条目必须包在 ``- insert:`` 里；裸条目会被当成"按 id 覆盖已有行"，
  patch 时报 ``entry "mcp-cwiki" not found`` 并被静默丢弃。
- 字段是 ``transport: stdio``（DSH 契约），不是 Claude/Codex 的 ``type``。
- ``serverName`` 决定工具名前缀 ``mcp__<serverName>__<tool>``。
- DSH 的 dsh-mcp-client 不下发 roots，故工作区只能靠静态 ``CWIKI_WORKSPACE``。
- skill 只被 ``<projectRoot>/.dsh/skills``（或 ``.agents/skills``）发现，
  仓库内的 ``skills/`` 不在扫描范围。

用法：
    python scripts/setup_dsh.py --project /path/to/project            # 写入
    python scripts/setup_dsh.py --project /path/to/project --dry-run
    python scripts/setup_dsh.py --verify                              # 挂载后自检
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

# sys.executable 会被写进 DSH 的 MCP 配置，必须先切到 .venv 解释器，避免把
# 无项目依赖的系统 python 写进去（会让 MCP server 启动即崩）。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.common import ensure_venv_interpreter

ensure_venv_interpreter(ROOT)

from adapters.hooks.profiles import clean_workspace_name

BEGIN = "# cwiki:begin"
END = "# cwiki:end"
PLUGIN_NAME = "@deepseek-ai/dsh-mcp-client"
SERVER_NAME = "cwiki"  # → 工具名 mcp__cwiki__<tool>；[A-Za-z0-9_-]{1,32}
ENTRY_ID = "mcp-cwiki"


def workspace_for(project: Path) -> str | None:
    """与 hook/MCP 核心同源的清洗判据，避免安装器与运行期结论不一致。"""
    return clean_workspace_name(str(project))


def _q(value: str) -> str:
    # json.dumps 产出的双引号标量是合法 YAML 双引号标量（反斜杠被正确转义）。
    return json.dumps(value, ensure_ascii=False)


def dsh_home(home: Path | None = None) -> Path:
    if home is not None:
        return home.expanduser().resolve()
    return Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh"))).expanduser()


def resolve_profile(home: Path, profile: str | None) -> tuple[str, Path]:
    """确定要写入哪个 profile：显式 --profile > $DSH_PROFILE > 唯一 profile。"""
    profiles_root = home / "profiles"
    available = [p.name for p in sorted(profiles_root.glob("*")) if (p / "package.json").exists()]
    if not available:
        raise SystemExit(f"在 {profiles_root} 下没找到任何 dsh profile（先运行一次 dsh 生成）")
    chosen = profile or os.environ.get("DSH_PROFILE")
    if chosen is None:
        if "web" in available:
            chosen = "web"
        elif len(available) == 1:
            chosen = available[0]
        else:
            raise SystemExit(f"需 --profile 指定其一：{', '.join(available)}")
    if chosen not in available:
        raise SystemExit(f"profile {chosen!r} 不存在；可用：{', '.join(available)}")
    return chosen, profiles_root / chosen


def build_block(workspace: str, project: Path) -> str:
    """生成受管区块的 YAML 文本（不含 marker）。"""
    return "\n".join(
        [
            "- insert:",
            f"    - id: {ENTRY_ID}",
            f"      name: {_q(PLUGIN_NAME)}",
            "      config:",
            f"        serverName: {_q(SERVER_NAME)}",
            "        transport: stdio",
            f"        command: {_q(sys.executable)}",
            "        args: ['-m', 'adapters.mcp']",
            f"        cwd: {_q(str(ROOT))}",
            "        env:",
            f"          PYTHONPATH: {_q(str(ROOT))}",
            '          CWIKI_HOST: "dsh"',
            f"          CWIKI_WORKSPACE: {_q(workspace)}",
            f"          CWIKI_WORKSPACE_DIR: {_q(str(project))}",
            '          CWIKI_API_URL: "http://127.0.0.1:5172"',
        ]
    )


def patch_cordis(patch_file: Path, block: str, dry_run: bool) -> None:
    """在 cordis.patch.yml 里幂等维护受管区块（保留用户其余行与注释）。"""
    existing = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""
    if BEGIN in existing or END in existing:
        if existing.count(BEGIN) != 1 or existing.count(END) != 1:
            raise SystemExit(f"{patch_file} 里的 cwiki 标记不配对，请手工修正")
        start = existing.index(BEGIN)
        end = existing.index(END) + len(END)
        updated = existing[:start] + f"{BEGIN}\n{block}\n{END}" + existing[end:]
    else:
        head = existing.rstrip()
        updated = f"{head + chr(10) + chr(10) if head else ''}{BEGIN}\n{block}\n{END}\n"
    # 校验：区块必须能被 DSH 的 YAML 解析，且条目在 insert 之下
    _assert_patch_valid(updated, patch_file)
    if dry_run:
        print(f"[dry-run] write {patch_file}")
        print(f"{BEGIN}\n{block}\n{END}")
        return
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(updated, encoding="utf-8")


def _assert_patch_valid(text: str, patch_file: Path) -> None:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # 写坏不如不写
        raise SystemExit(f"生成的 patch 无法被 YAML 解析：{exc}") from exc
    if not isinstance(loaded, list):
        raise SystemExit(f"{patch_file} 顶层必须是 YAML 数组")
    # 条目必须挂在某个 `- insert:` 组下；顶层裸条目会被 DSH 当成"按 id 覆盖
    # 已有行"，patch 时报 entry not found 并静默丢弃。
    grouped = {
        row.get("id"): row
        for item in loaded
        if isinstance(item, dict) and isinstance(item.get("insert"), list)
        for row in item["insert"]
        if isinstance(row, dict)
    }
    top_level = {
        item.get("id") for item in loaded if isinstance(item, dict) and "insert" not in item
    }
    row = grouped.get(ENTRY_ID)
    if row is None:
        if ENTRY_ID in top_level:
            raise SystemExit("自检失败：cwiki 条目必须包在 `- insert:` 里，否则 DSH 会丢弃")
        raise SystemExit("自检失败：区块里的 cwiki 条目未被解析出来")
    cfg = row.get("config", {})
    if cfg.get("transport") != "stdio" or cfg.get("serverName") != SERVER_NAME:
        raise SystemExit("自检失败：config.transport/serverName 不符合 DSH 契约")
    if cfg.get("cwd") != str(ROOT) or not cfg.get("command"):
        raise SystemExit("自检失败：config.cwd/command 缺失（stdio 子进程会找不到模块）")


def install_skill(project: Path, dry_run: bool) -> Path:
    """把 cwiki-save 落到 DSH 会扫描的 <project>/.dsh/skills/。"""
    source = ROOT / "skills" / "cwiki-save"
    target_dir = project / ".dsh" / "skills"
    target = target_dir / source.name
    if dry_run:
        print(f"[dry-run] link {target} -> {source}")
        return target
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or target.exists():
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)
    try:
        os.symlink(source, target, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)
    return target


def verify(project: Path, workspace: str, timeout: float = 12.0) -> int:
    """直接起 stdio MCP server，验证握手 + tools/list + 一次实调用。

    不依赖模型：这是"挂上后一定能用"的确定性证据。
    """
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "CWIKI_HOST": "dsh",
        "CWIKI_WORKSPACE": workspace,
        "CWIKI_WORKSPACE_DIR": str(project),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "adapters.mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=str(ROOT),
    )
    # stdio MCP 必须使用 stdin/stdout；显式绑定到局部名，供闭包 send/recv 使用
    stdin = proc.stdin
    stdout = proc.stdout
    if stdin is None or stdout is None:  # pragma: no cover - Popen 契约保证
        raise RuntimeError("Popen failed to allocate stdio pipes")

    def send(obj: dict[str, Any]) -> None:
        data = (json.dumps(obj) + "\n").encode()
        stdin.write(data)
        stdin.flush()

    def recv() -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line_bytes = stdout.readline()
            if not line_bytes:
                time.sleep(0.05)
                continue
            text = line_bytes.decode().strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except ValueError:
                continue
            if isinstance(msg, dict) and "id" in msg:
                return msg
        raise TimeoutError(f"MCP 在 {timeout}s 内无响应")

    code = 0
    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "setup-dsh-verify", "version": "1"},
                },
            }
        )
        init = recv()
        info = init.get("result", {}).get("serverInfo", {})
        print(f"  handshake: serverInfo={info}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = recv().get("result", {}).get("tools", [])
        names = [t["name"] for t in tools]
        print(f"  tools/list: {len(names)} 个")
        if len(names) < 16:
            print("  [FAIL] 工具数少于 16")
            code = 1
        if "memory_status" in names:
            send(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "memory_status", "arguments": {}},
                }
            )
            res = recv().get("result", {})
            err = res.get("isError")
            print(f"  memory_status: {'ERROR' if err else 'OK'}")
            if err:
                code = 1
        print("  verify:", "PASS" if code == 0 else "FAIL")
    except (TimeoutError, OSError) as exc:
        print(f"  verify FAIL: {exc}")
        code = 1
    finally:
        proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--home", type=Path, default=None, help="测试用 DSH_HOME 覆盖")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-skill", action="store_true", help="不安装 cwiki-save skill")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="挂载后起 stdio server 自检（不经模型）",
    )
    args = parser.parse_args()

    project = args.project.expanduser().resolve()
    # 显式 --workspace 也走同一判据：写进配置的垃圾名会在运行期静默回落
    # default，导致配置与归属不一致，宁可在安装时就拒绝。
    workspace = clean_workspace_name(args.workspace) if args.workspace else workspace_for(project)
    if not workspace:
        print(f"无法从项目路径推导合法工作区名: {project}（用 --workspace 指定）")
        return 1

    home = dsh_home(args.home)
    profile, profile_dir = resolve_profile(home, args.profile)
    patch_file = profile_dir / "cordis.patch.yml"
    block = build_block(workspace, project)

    print(f"home={home} profile={profile} workspace={workspace} project={project}")
    patch_cordis(patch_file, block, args.dry_run)
    if not args.no_skill:
        install_skill(project, args.dry_run)

    if not args.dry_run:
        print(f"  已写入 {patch_file}")
        print(f"    entry id={ENTRY_ID} serverName={SERVER_NAME} transport=stdio")
        print(f"  工具将暴露为 mcp__{SERVER_NAME}__<tool>")
        pkg = profile_dir / "package.json"
        reload_live = '"patchReload": "live"' in (pkg.read_text("utf-8") if pkg.exists() else "")
        print(f"  {'patchReload: live — 保存即热重载' if reload_live else '需重启 dsh 生效'}")

    if args.verify:
        if args.dry_run:
            print("[dry-run] 跳过 --verify（未真正写入）")
        else:
            print("verify：启动 adapters.mcp 自检")
            return verify(project, workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
