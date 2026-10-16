"""启动脚本回归测试：所有子进程、信号和进程树操作均使用 mock。"""

import ctypes
import io
import signal
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

import start
from scripts import process_utils
from scripts.common import load_app_config


@pytest.fixture(autouse=True)
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    root = tmp_path / "中文 项目"
    root.mkdir()
    other = tmp_path / "其他目录"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setattr(start, "PROJECT_ROOT", root)
    monkeypatch.setattr(start, "IS_WINDOWS", False)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", False)
    monkeypatch.setenv("CWIKI_DEV_MODE", "true")
    # 64 位宿主使用超过 DWORD 宽度的句柄，且与 PID 不同。
    job_handle = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8 - 2)) + 17
    backend = Mock(pid=12345, _handle=job_handle + 1)
    backend.poll.return_value = None
    backend.wait.return_value = 0
    frontend = Mock(pid=23456, _handle=job_handle + 2)
    frontend.poll.return_value = 0
    frontend.wait.return_value = 0
    kernel32 = Mock()
    kernel32.CreateJobObjectW.return_value = job_handle
    kernel32.SetInformationJobObject.return_value = 1
    kernel32.AssignProcessToJobObject.return_value = 1
    kernel32.CloseHandle.return_value = 1
    with (
        patch.object(process_utils.ctypes, "WinDLL", return_value=kernel32, create=True) as windll,
        patch.object(process_utils.ctypes, "get_last_error", return_value=5, create=True),
        patch.object(
            process_utils.ctypes,
            "WinError",
            side_effect=lambda code, text: OSError(code, text),
            create=True,
        ),
        patch.object(start.subprocess, "Popen", side_effect=[backend, frontend]) as popen,
        patch.object(start.subprocess, "run") as run,
        patch.object(start.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
        patch.object(start.os, "killpg", create=True) as killpg,
        patch.object(start.signal, "SIGKILL", 9, create=True),
        patch.object(start.signal, "signal", return_value=signal.SIG_DFL) as set_signal,
        patch.object(start.shutil, "which", side_effect=lambda name: f"/tools/{name}") as which,
        patch.object(start, "ensure_port_free", return_value=True),
        patch.object(start, "force_restart_port"),
    ):
        run.return_value = Mock(returncode=0)
        yield SimpleNamespace(
            root=root,
            other=other,
            backend=backend,
            frontend=frontend,
            popen=popen,
            run=run,
            killpg=killpg,
            signal=set_signal,
            which=which,
            kernel32=kernel32,
            windll=windll,
            job_handle=job_handle,
        )


def test_windows_job_configuration_and_abi(runtime: SimpleNamespace) -> None:
    job = process_utils.WindowsJob()
    runtime.windll.assert_called_once_with("kernel32", use_last_error=True)
    kernel32 = runtime.kernel32
    kernel32.CreateJobObjectW.assert_called_once_with(None, None)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
        "SetInformationJobObject": (
            [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32],
            ctypes.c_int32,
        ),
        "AssignProcessToJobObject": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int32),
        "CloseHandle": ([ctypes.c_void_p], ctypes.c_int32),
    }
    for name, (args, result) in signatures.items():
        assert getattr(kernel32, name).argtypes == args
        assert getattr(kernel32, name).restype is result
    handle, info_class, pointer, size = kernel32.SetInformationJobObject.call_args.args
    assert handle == runtime.job_handle
    assert info_class == 9
    info = ctypes.cast(pointer, ctypes.POINTER(process_utils._JobExtendedLimitInformation)).contents
    assert info.BasicLimitInformation.LimitFlags == 0x2000
    assert info.BasicLimitInformation.ActiveProcessLimit == 0
    assert info.ProcessMemoryLimit == info.JobMemoryLimit == 0
    assert size == ctypes.sizeof(info)
    assert ctypes.sizeof(process_utils._JobIoCounters) == 48
    basic_fields = dict(process_utils._JobBasicLimitInformation._fields_)
    for field in ("LimitFlags", "ActiveProcessLimit", "PriorityClass", "SchedulingClass"):
        assert ctypes.sizeof(basic_fields[field]) == 4
    for field in ("MinimumWorkingSetSize", "MaximumWorkingSetSize", "Affinity"):
        assert ctypes.sizeof(basic_fields[field]) == ctypes.sizeof(ctypes.c_void_p)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(process_utils._JobBasicLimitInformation) == 64
        assert process_utils._JobBasicLimitInformation.Affinity.offset == 48
        assert process_utils._JobExtendedLimitInformation.IoInfo.offset == 64
        assert process_utils._JobExtendedLimitInformation.ProcessMemoryLimit.offset == 112
        assert size == 144
    job.assign(runtime.backend)
    kernel32.AssignProcessToJobObject.assert_called_once_with(handle, runtime.backend._handle)
    job.close()
    job.close()
    kernel32.CloseHandle.assert_called_once_with(handle)


@pytest.mark.parametrize(
    "api",
    ["CreateJobObjectW", "SetInformationJobObject", "AssignProcessToJobObject", "CloseHandle"],
)
def test_windows_job_api_failure_is_explicit_and_handle_is_closed(
    runtime: SimpleNamespace, api: str
) -> None:
    getattr(runtime.kernel32, api).return_value = 0
    job = None
    with pytest.raises(OSError, match=api) as exc:
        job = process_utils.WindowsJob()
        if api == "AssignProcessToJobObject":
            job.assign(runtime.backend)
        else:
            job.close()
    assert exc.value.errno == 5
    if api == "CreateJobObjectW":
        runtime.kernel32.SetInformationJobObject.assert_not_called()
        runtime.kernel32.CloseHandle.assert_not_called()
    elif api == "SetInformationJobObject":
        runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    else:
        assert job is not None
        runtime.kernel32.CloseHandle.return_value = 1
        job.close()
        job.close()
        expected_count = 2 if api == "CloseHandle" else 1
        assert (
            runtime.kernel32.CloseHandle.call_args_list
            == [call(runtime.job_handle)] * expected_count
        )


def test_load_config_reads_project_root_as_utf8(runtime: SimpleNamespace) -> None:
    (runtime.root / "config.yaml").write_text(
        "storage:\n  memory_dir: ./中文记忆\n", encoding="utf-8"
    )
    (runtime.other / "config.yaml").write_text("invalid: cwd\n", encoding="utf-8")
    with patch.object(Path, "read_text", autospec=True, side_effect=Path.read_text) as read:
        assert load_app_config(runtime.root) == {"storage": {"memory_dir": "./中文记忆"}}
    read.assert_called_once_with(runtime.root / "config.yaml", encoding="utf-8")


@pytest.mark.parametrize("windows, npm_name", [(True, "npm.cmd"), (False, "npm")])
def test_dependencies_resolve_npm(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, windows: bool, npm_name: str
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", windows)
    assert start.check_npm() == f"/tools/{npm_name}"
    assert runtime.which.call_args_list == [call(npm_name)]


@pytest.mark.parametrize("missing, message", [("npm", "请安装 Node.js LTS")])
def test_missing_dependency_fails_before_any_side_effect(
    runtime: SimpleNamespace, capsys: pytest.CaptureFixture[str], missing: str, message: str
) -> None:
    runtime.which.side_effect = lambda name: None if name == missing else f"/tools/{name}"
    assert start.main() == 1
    assert message in capsys.readouterr().out
    runtime.popen.assert_not_called()
    runtime.run.assert_not_called()
    runtime.signal.assert_not_called()
    assert list(runtime.root.iterdir()) == []


@pytest.mark.parametrize("windows", [False, True])
def test_main_starts_in_project_root_with_isolated_processes(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", windows)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", windows)
    npm = "C:/Program Files/nodejs/npm.cmd" if windows else "/tools/npm"
    runtime.which.side_effect = lambda name: npm
    # 固定 api_host 断言值，避免随本机 config.yaml 漂移（Android 联调会临时改 0.0.0.0）
    monkeypatch.setattr(start.settings, "api_host", "127.0.0.1", raising=False)
    (runtime.root / "config.yaml").write_text(
        "storage:\n  memory_dir: ./中文记忆\n", encoding="utf-8"
    )
    order = Mock()
    order.attach_mock(runtime.popen, "popen")
    order.attach_mock(runtime.kernel32.AssignProcessToJobObject, "assign")
    start.main()
    backend, frontend = runtime.popen.call_args_list
    assert backend.args[0] == [
        start.sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "5172",
        "--reload",
    ]
    options = {"creationflags": 512} if windows else {"start_new_session": True}
    assert backend.kwargs == {"cwd": str(runtime.root), **options}
    assert frontend == call([npm, "run", "dev"], cwd=str(runtime.root / "apps/web"), **options)
    assert (runtime.root / "中文记忆").is_dir()
    assert not (runtime.other / "中文记忆").exists()
    assert runtime.signal.call_args_list[-2:] == [
        call(signal.SIGINT, signal.SIG_DFL),
        call(signal.SIGTERM, signal.SIG_DFL),
    ]
    if windows:
        assert [c[0] for c in order.mock_calls] == ["popen", "assign", "popen", "assign"]
        assert runtime.kernel32.AssignProcessToJobObject.call_args_list == [
            call(runtime.job_handle, runtime.backend._handle),
            call(runtime.job_handle, runtime.frontend._handle),
        ]
        runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
        assert runtime.run.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    else:
        runtime.windll.assert_not_called()
        assert runtime.killpg.call_args_list == [
            call(23456, signal.SIGTERM),
            call(23456, signal.SIGKILL),
            call(12345, signal.SIGTERM),
            call(12345, signal.SIGKILL),
        ]


@pytest.mark.parametrize("windows", [False, True])
def test_frontend_start_failure_cleans_backend(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", windows)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", windows)
    runtime.popen.side_effect = [runtime.backend, OSError("npm start failed")]
    assert start.main() == 1
    runtime.backend.wait.assert_called_with(timeout=5)
    if windows:
        runtime.kernel32.AssignProcessToJobObject.assert_called_once_with(
            runtime.job_handle, runtime.backend._handle
        )
        runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
        assert runtime.run.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    else:
        assert runtime.killpg.call_args_list == [
            call(12345, signal.SIGTERM),
            call(12345, signal.SIGKILL),
        ]
    assert runtime.signal.call_args_list[-1] == call(signal.SIGTERM, signal.SIG_DFL)


def test_frontend_exit_is_detected_while_backend_is_running(runtime: SimpleNamespace) -> None:
    runtime.frontend.poll.side_effect = [None, 7]
    runtime.backend.wait.side_effect = [subprocess.TimeoutExpired("uvicorn", 0.5), 0, 0]
    assert start.main() == 7
    assert runtime.backend.wait.call_args_list[0] == call(timeout=0.5)
    assert {c.args[0] for c in runtime.killpg.call_args_list} == {12345, 23456}


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_signal_cleans_both_trees_and_restores_handlers(runtime: SimpleNamespace, sig: int) -> None:
    runtime.frontend.poll.return_value = None

    def interrupt(**_kwargs: object) -> None:
        runtime.backend.wait.side_effect = None
        handler = next(c.args[1] for c in runtime.signal.call_args_list if c.args[0] == sig)
        handler(sig, None)

    runtime.backend.wait.side_effect = interrupt
    with pytest.raises(SystemExit) as exc:
        start.main()
    assert exc.value.code == 0
    assert {c.args[0] for c in runtime.killpg.call_args_list} == {12345, 23456}
    assert runtime.signal.call_args_list[-2:] == [
        call(signal.SIGINT, signal.SIG_DFL),
        call(signal.SIGTERM, signal.SIG_DFL),
    ]


@pytest.mark.parametrize("windows", [False, True])
def test_cleanup_failure_does_not_skip_other_process(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, windows: bool
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", windows)
    with patch.object(
        start, "stop_process_tree", side_effect=[OSError("cleanup failed"), None]
    ) as stop:
        start.main()
    assert stop.call_args_list == [call(runtime.frontend), call(runtime.backend)]
    if windows:
        runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    assert runtime.signal.call_args_list[-1] == call(signal.SIGTERM, signal.SIG_DFL)


@pytest.mark.parametrize("api", ["CreateJobObjectW", "SetInformationJobObject"])
def test_windows_job_init_failure_prevents_process_start(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, api: str
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    getattr(runtime.kernel32, api).return_value = 0
    assert start.main() == 1
    runtime.popen.assert_not_called()
    if api == "SetInformationJobObject":
        runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    else:
        runtime.kernel32.CloseHandle.assert_not_called()


@pytest.mark.parametrize("failed_index", [0, 1])
@pytest.mark.parametrize("taskkill_fails", [False, True])
def test_windows_assign_failure_cleans_started_processes_and_closes_job(
    runtime: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed_index: int,
    taskkill_fails: bool,
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", True)
    runtime.frontend.poll.return_value = None
    runtime.kernel32.AssignProcessToJobObject.side_effect = [1] * failed_index + [0]
    if taskkill_fails:
        runtime.run.side_effect = [Mock()] + [subprocess.CalledProcessError(1, "taskkill")] * (
            failed_index + 1
        )
    with (
        patch.object(start, "stop_process_tree", wraps=process_utils.stop_process_tree) as stop,
    ):
        assert start.main() == 1
    assert "AssignProcessToJobObject 失败" in capsys.readouterr().out
    started = [runtime.backend, runtime.frontend][: failed_index + 1]
    assert runtime.popen.call_count == len(started)
    assert stop.call_args_list == [call(process) for process in reversed(started)]
    assert [c.args[0] for c in runtime.run.call_args_list[1:]] == [
        ["taskkill", "/PID", str(process.pid), "/T", "/F"] for process in reversed(started)
    ]
    for process in started:
        process.wait.assert_called_once_with(timeout=5)
        if taskkill_fails:
            process.kill.assert_called_once_with()
        else:
            process.kill.assert_not_called()
    runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    assert runtime.signal.call_args_list[-1] == call(signal.SIGTERM, signal.SIG_DFL)


@pytest.mark.parametrize("returncode", [0, 7])
def test_windows_exited_parents_still_close_job_without_taskkill(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", True)
    runtime.backend.poll.return_value = returncode
    if returncode:
        assert start.main() == returncode
    else:
        start.main()
    # 有 npm install 调用；不通过已退出的父 PID 寻找后代，Job 关闭不受 poll 结果影响。
    assert runtime.run.call_count == 1
    assert runtime.kernel32.AssignProcessToJobObject.call_count == 2
    runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    for process in (runtime.backend, runtime.frontend):
        process.wait.assert_called_once_with(timeout=5)
        process.kill.assert_not_called()


@pytest.mark.parametrize("stage", ["signal", "process"])
def test_windows_job_closes_even_on_unexpected_cleanup_failure(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    error = RuntimeError("unexpected cleanup failure")

    def set_signal(_sig: int, handler: object) -> int:
        if handler == signal.SIG_IGN:
            raise error
        return signal.SIG_DFL

    if stage == "signal":
        runtime.signal.side_effect = set_signal
    with (
        patch.object(start, "stop_process_tree", side_effect=error),
        pytest.raises(RuntimeError, match="unexpected cleanup failure"),
    ):
        start.main()
    runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    assert runtime.signal.call_args_list[-2:] == [
        call(signal.SIGINT, signal.SIG_DFL),
        call(signal.SIGTERM, signal.SIG_DFL),
    ]


def test_windows_job_close_failure_still_restores_handlers(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    runtime.kernel32.CloseHandle.return_value = 0
    with pytest.raises(OSError, match="CloseHandle"):
        start.main()
    runtime.kernel32.CloseHandle.assert_called_once_with(runtime.job_handle)
    assert runtime.signal.call_args_list[-2:] == [
        call(signal.SIGINT, signal.SIG_DFL),
        call(signal.SIGTERM, signal.SIG_DFL),
    ]


@pytest.mark.parametrize("returncode", [None, 0])
def test_windows_taskkill_only_targets_own_live_pid(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, returncode: int | None
) -> None:
    monkeypatch.setattr(start, "IS_WINDOWS", True)
    monkeypatch.setattr(process_utils, "IS_WINDOWS", True)
    runtime.backend.poll.return_value = returncode
    process_utils.stop_process_tree(runtime.backend)
    if returncode is None:
        runtime.run.assert_called_once_with(
            ["taskkill", "/PID", "12345", "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    else:
        runtime.run.assert_not_called()
    runtime.killpg.assert_not_called()
    runtime.backend.wait.assert_called_once_with(timeout=5)


def test_posix_timeout_kills_entire_group(runtime: SimpleNamespace) -> None:
    runtime.backend.wait.side_effect = [subprocess.TimeoutExpired("uvicorn", 5), 0]
    process_utils.stop_process_tree(runtime.backend)
    assert runtime.killpg.call_args_list == [
        call(12345, signal.SIGTERM),
        call(12345, signal.SIGKILL),
    ]
    runtime.backend.kill.assert_not_called()


def test_posix_already_exited_group_is_harmless(runtime: SimpleNamespace) -> None:
    runtime.killpg.side_effect = ProcessLookupError
    process_utils.stop_process_tree(runtime.backend)
    runtime.backend.wait.assert_called_with(timeout=5)


@pytest.mark.parametrize("encoding", ["ascii", "cp1252", "gbk", "utf-8"])
@pytest.mark.parametrize("failure", [None, "dependency", "startup", "cleanup"])
def test_redirected_output_does_not_interrupt_start_or_cleanup(
    runtime: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, encoding: str, failure: str | None
) -> None:
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding=encoding, errors="strict", newline="\n")
    monkeypatch.setattr(start.sys, "stdout", stream)
    if failure == "dependency":
        runtime.which.return_value = None
        runtime.which.side_effect = None
    elif failure == "startup":
        runtime.popen.side_effect = [runtime.backend, OSError("前端启动失败")]
    if failure == "cleanup":
        runtime.killpg.side_effect = OSError("清理进程失败")

    if failure == "dependency" or failure == "startup":
        assert start.main() == 1
    else:
        start.main()
    stream.flush()
    text = output.getvalue().decode(encoding)
    assert "cwiki" in text
    if encoding in {"gbk", "utf-8"}:
        assert "启动 cwiki" in text
    if failure in {None, "startup", "cleanup"}:
        assert runtime.killpg.called
        assert runtime.signal.call_args_list[-1] == call(signal.SIGTERM, signal.SIG_DFL)


@pytest.mark.parametrize("encoding", ["ascii", "cp1252", "gbk", "utf-8"])
def test_print_message_preserves_supported_characters(
    monkeypatch: pytest.MonkeyPatch, encoding: str
) -> None:
    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding=encoding, errors="strict", newline="\n")
    monkeypatch.setattr(start.sys, "stdout", stream)
    message = "中文 log \U00020000"
    start.print_message(message)
    stream.flush()
    assert (
        output.getvalue().decode(encoding)
        == message.encode(encoding, errors="replace").decode(encoding) + "\n"
    )
