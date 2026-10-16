"""本地静态的 Qoder hook 提醒；不采集数据、不访问文件、不调用 API。"""

import json
import os
import sys
from typing import NoReturn

MAX_INPUT_BYTES = 1024 * 1024  # 与宿主约定的输入上限 1 MiB，超限即放弃（fail open）
REMINDERS = {
    "session-start": (
        "SessionStart",
        (
            "cwiki: 会话开始或话题切换时用 memory_search 检索相关记忆建立上下文。"
            "出现用户纠正、调试转折、技术决策、隐性规则、重复踩坑、代码约定、"
            "操作步骤、可复用资源、认知纠偏等信号时用 memory_save 提交。"
            "无真实信号就跳过，不凑条数。详见 cwiki-save skill。"
        ),
    ),
}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """拒绝重复键的 JSON 解析钩子：键重复时抛错而非静默覆盖。"""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    """拒绝 NaN/Infinity 等非标准 JSON 常量。"""
    raise ValueError("non-JSON constant")


def _diagnose(reason: str) -> None:
    # 调用方只传入固定的诊断文案，绝不内插用户输入或异常详情。
    try:
        os.write(sys.stderr.fileno(), f"cwiki-hook: reminder skipped ({reason}).\n".encode("ascii"))
    except (OSError, ValueError):
        pass


def main() -> int:
    """读取至多 1 MiB 的 UTF-8 JSON；输入非法时静默放行（fail open），始终返回 0 不阻断宿主。"""
    args = sys.argv[1:]
    if len(args) != 1 or args[0] not in REMINDERS:
        _diagnose("expected session-start")
        return 0

    event, context = REMINDERS[args[0]]
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            _diagnose("input too large")
            return 0
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if not isinstance(payload, dict) or payload.get("hook_event_name") != event:
            _diagnose("invalid event")
            return 0
    except (OSError, ValueError, RecursionError):
        _diagnose("invalid input")
        return 0

    # 输出只含固定提醒文案，不内插任何 stdin 字段（prompt、cwd、transcript_path 等）。
    response = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    try:
        # 直接用 os.write 逐段写出（无缓冲），避免管道已关闭时退出阶段二次 flush 失败。
        output = (json.dumps(response, ensure_ascii=True) + "\n").encode("ascii")
        while output:
            written = os.write(sys.stdout.fileno(), output)
            if written == 0:
                raise OSError("output unavailable")
            output = output[written:]
    except (OSError, ValueError):
        _diagnose("output unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
