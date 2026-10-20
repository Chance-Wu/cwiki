"""记忆文件的 Git 版本控制集成。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GitVersionControl:
    """管理记忆文件的 Git 版本控制。

    标准布局下 ``cwiki-data`` 自带独立仓库（代码仓库的兄弟目录，见
    docs/git-sync.md），直接使用即可。当 *repo_path* 嵌套在父工作树内
    且自身没有仓库时，直接使用父仓库 —— 不会在那里自动创建嵌套仓库。
    只有当路径位于任何工作树之外时才初始化独立仓库。

    公开方法均为 async（非阻塞），可在 FastAPI 路由处理函数中调用而
    不阻塞事件循环。构造函数保持同步，因为它只在模块导入时执行一次。
    """

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        self._ensure_repo()

    def _ensure_repo(self) -> None:
        """仅当路径位于任何工作树之外时才初始化独立仓库。"""
        if (self.repo_path / ".git").exists():
            return
        self.repo_path.mkdir(parents=True, exist_ok=True)
        if self._inside_work_tree():
            # 嵌套路径且自身没有仓库（尚未迁移，或全新克隆缺少数据仓库）：
            # 退回使用父仓库；绝不自动创建嵌套 .git。
            return
        self._run_sync(["git", "init"], cwd=self.repo_path)
        self._run_sync(["git", "config", "user.email", "cwiki@local"], cwd=self.repo_path)
        self._run_sync(["git", "config", "user.name", "cwiki"], cwd=self.repo_path)

        gitignore = self.repo_path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*.npz\n*.db\n")

    def _inside_work_tree(self) -> bool:
        """判断 *repo_path* 是否已被某个父 git 仓库覆盖。"""
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=self.repo_path,
            capture_output=True,
            check=False,
        )
        return probe.returncode == 0

    def _run_sync(self, cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
        """同步子进程执行器（构造函数与探测路径使用）。"""
        result = subprocess.run(
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=check,
        )
        if result.returncode != 0:
            if check:
                logger.warning("Git command failed: %s -> %s", " ".join(cmd), result.stderr.strip())
            return ""
        return result.stdout.strip()

    async def _run(self, cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
        """运行 git 命令且不阻塞事件循环。"""
        return await asyncio.to_thread(self._run_sync, cmd, cwd, check)

    async def commit(self, message: str) -> None:
        """暂存全部变更并提交。

        提交身份逐仓库兜底：该仓库（含外部带入的既有仓库，如测试里
        git init 出来的嵌套仓库）缺 user.email/user.name 时就地补写，
        避免依赖宿主机的全局 git 配置——CI/测试沙箱常没有。
        """
        for key, value in (("user.email", "cwiki@local"), ("user.name", "cwiki")):
            probe = await self._run(
                ["git", "config", key],
                cwd=self.repo_path,
                check=False,
            )
            if not probe:
                await self._run(["git", "config", key, value], cwd=self.repo_path)
        await self._run(["git", "add", "-A"], cwd=self.repo_path)
        await self._run(["git", "commit", "-m", message], cwd=self.repo_path)

    async def log(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取涉及本目录的提交历史。仓库尚无提交时返回空列表。

        ``-- .`` pathspec 将历史限定在 *repo_path* 的子树内，因此嵌套在
        父仓库中时只列出改动过本目录的提交。
        """
        fmt = "%H|%s|%ai"
        try:
            output = await self._run(
                ["git", "log", f"--format={fmt}", f"-n{limit}", "--", "."],
                cwd=self.repo_path,
            )
        except subprocess.CalledProcessError as e:
            if "does not have any commits yet" in (e.stderr or ""):
                return []
            raise
        entries = []
        for line in output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append(
                    {
                        "hash": parts[0],
                        "message": parts[1],
                        "date": parts[2],
                    }
                )
        return entries

    async def has_changes(self) -> bool:
        """本目录是否存在未提交的变更。

        ``-- .`` pathspec 将检查限定在 *repo_path* 的子树内，
        父仓库中其他无关变更会被忽略。
        """
        output = await self._run(["git", "status", "--porcelain", "--", "."], cwd=self.repo_path)
        return bool(output.strip())
