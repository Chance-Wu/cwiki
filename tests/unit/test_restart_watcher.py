"""重启守护脚本的行为测试。

回归背景一：watcher 是旧 API 的子进程，曾用 ``taskkill /T`` 结束旧进程，
结果把自己也杀了——重启实际依赖监督者兜底。因此只能精确结束目标 PID。

回归背景二：派生新服务时曾继承旧 API 的 stdout 句柄，旧进程失效后新进程
一写日志就阻塞（端口可连但永远不响应），因此兜底进程必须显式重定向 stdio。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import restart_watcher


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / "cwiki-data").mkdir()
    return tmp_path


def test_kills_only_target_pid_then_spawns_fallback(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []
    spawns: list[tuple[list[str], dict]] = []

    def fake_run(cmd: list[str], **kwargs):
        commands.append(cmd)

    def fake_popen(cmd: list[str], **kwargs):
        spawns.append((cmd, kwargs))
        return object()

    monkeypatch.setattr(restart_watcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(restart_watcher, "_wait_healthy", lambda _port, timeout=0: False)
    monkeypatch.setattr(restart_watcher.subprocess, "run", fake_run)
    monkeypatch.setattr(restart_watcher.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sys, "argv", ["restart_watcher.py", "123456", str(project_root)])

    restart_watcher.main()

    assert commands == [["taskkill", "/PID", "123456", "/F"]]
    assert len(spawns) == 1
    cmd, kwargs = spawns[0]
    assert cmd[1].endswith("tasks.py")
    assert cmd[2] == "restart-serve"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.STDOUT
    log_name = getattr(kwargs["stdout"], "name", "")
    assert Path(log_name).name == "restart.log"


def test_skips_fallback_when_supervisor_revives_service(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawns: list[list[str]] = []

    monkeypatch.setattr(restart_watcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(restart_watcher, "_wait_healthy", lambda _port, timeout=0: True)
    monkeypatch.setattr(restart_watcher.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        restart_watcher.subprocess,
        "Popen",
        lambda cmd, **kwargs: spawns.append(cmd),
    )
    monkeypatch.setattr(sys, "argv", ["restart_watcher.py", "123456", str(project_root)])

    restart_watcher.main()

    assert spawns == []
