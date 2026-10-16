"""子进程生命周期管理 — Windows Job 对象与进程树终止。

供 start.py / serve_backend.py 共用；tests/integration/test_start.py 对
WindowsJob 的 Win32 ABI 与 stop_process_tree 的行为有回归测试。
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess

IS_WINDOWS = os.name == "nt"


def stop_process_tree(process: subprocess.Popen | None, timeout: float = 5.0) -> None:
    """优雅终止进程树：SIGTERM/taskkill → 等待 → SIGKILL。

    幂等：process 为 None 时直接返回；已退出的进程跳过信号但仍等待回收。
    失败时抛出 OSError / SubprocessError，由调用方决定如何报告。
    """
    if process is None:
        return
    pid = process.pid
    if IS_WINDOWS:
        try:
            if process.poll() is None:
                try:
                    # taskkill /T 连整棵进程树一起强杀；Windows 无进程组语义可用
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        check=True,
                    )
                except (OSError, subprocess.SubprocessError):
                    # taskkill 失败时退回进程句柄 kill，并向上抛出原始错误
                    process.kill()
                    raise
        finally:
            process.wait(timeout=timeout)
        return

    # SIGTERM 给整个进程组优雅退出；超时后 SIGKILL 兜底，避免残留孙进程
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=timeout)


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JobIoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _JobIoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryLimit", ctypes.c_size_t),
    ]


class WindowsJob:
    """私有、不可继承的 Job：最后一个句柄关闭时回收已纳入的所有后代。

    仅限 Windows 调用方使用（调用方自行以 IS_WINDOWS 判断）。
    """

    def __init__(self) -> None:
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        for name, argtypes, restype in (
            ("CreateJobObjectW", [ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
            (
                "SetInformationJobObject",
                [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32],
                ctypes.c_int32,
            ),
            ("AssignProcessToJobObject", [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int32),
            ("CloseHandle", [ctypes.c_void_p], ctypes.c_int32),
        ):
            function = getattr(self._kernel32, name)
            function.argtypes = argtypes
            function.restype = restype
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error(), "CreateJobObjectW 失败")
        try:
            info = _JobExtendedLimitInformation()
            # KILL_ON_JOB_CLOSE：Job 句柄关闭时终止其内全部关联进程
            info.BasicLimitInformation.LimitFlags = 0x2000
            if not self._kernel32.SetInformationJobObject(
                self._handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise ctypes.WinError(ctypes.get_last_error(), "SetInformationJobObject 失败")
        except BaseException:
            self.close()
            raise

    def assign(self, process: subprocess.Popen) -> None:
        """把子进程纳入 Job，此后其创建的后代进程也随之被 Job 管理。"""
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error(), "AssignProcessToJobObject 失败")

    def close(self) -> None:
        """关闭 Job 句柄，触发 KILL_ON_JOB_CLOSE 回收全部后代进程。"""
        if self._handle is not None:
            if not self._kernel32.CloseHandle(self._handle):
                raise ctypes.WinError(ctypes.get_last_error(), "CloseHandle 失败")
            self._handle = None
