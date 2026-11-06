"""召回交付信号回流：把 hook 注入的记忆告知后端。

背景：自动召回走本地只读检索（不写使用流水），后端只知道"没检索过"，
不知道"命中并已交付"。utility 分的 retrieval_success / agent_usage
两个分量因此恒为 0，排序与进化拿不到真实使用信号。

约束：
- 只写本地 spool（微秒级），绝不在 UserPromptSubmit 里发 HTTP——注入不能等网络；
- 投递在 SessionStart / drain 时批量进行，API 不可用就留在 spool 里下次补投；
- record_id 由内容派生，重试与重复注入不会产生重复计量。
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from typing import Any

from .spool import append, load, remove_delivered

NAMESPACE = "usage"
# 必须小于宿主 hook 超时（SessionStart 5s），API 慢时内层先超时
POST_TIMEOUT_SECONDS = 2
MAX_BATCH = 50
# 单条 prompt 最多上报几条：与 recall 的注入上限一致
MAX_EVENTS_PER_RECORD = 3


def _api_base() -> str:
    return os.environ.get("CWIKI_API_URL", "http://127.0.0.1:5172").rstrip("/")


def record_id_for(session_id: str, prompt: str, workspace: str, memory_ids: list[str]) -> str:
    """内容派生的批次 id：同一会话内同一 prompt + 同一批命中 = 同一 id。

    会话 id 必须并入：跨会话的相同提问是两次真实交付，不该被服务端幂等键吞掉。
    """
    raw = f"{session_id}|{workspace}|{prompt}|{','.join(sorted(memory_ids))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def store(
    *,
    host: str,
    session_id: str,
    workspace: str,
    prompt: str,
    memory_ids: list[str],
) -> None:
    """记录一次"已交付"事件（hook 注入给模型的那批记忆）。

    任何异常都吞掉：使用信号是辅助遥测，不能影响宿主会话。
    """
    ids = [str(mid) for mid in memory_ids[:MAX_EVENTS_PER_RECORD] if mid]
    if not ids:
        return
    record = {
        "record_id": record_id_for(session_id, prompt, workspace, ids),
        "session_id": session_id,
        "events": [
            {"memory_id": mid, "stage": "used", "position": index} for index, mid in enumerate(ids)
        ],
    }
    try:
        append(host, session_id, record, namespace=NAMESPACE)
    except Exception:
        return


def _post(records: list[dict[str, Any]]) -> bool:
    body = json.dumps({"records": records}, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    request = urllib.request.Request(
        f"{_api_base()}/v1/usage/batch",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=POST_TIMEOUT_SECONDS) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
    return True


def drain(host: str, max_batches: int = 2) -> dict[str, int]:
    """补投积压的交付信号；失败保留积压，不阻塞 hook。"""
    delivered = 0
    try:
        for _ in range(max_batches):
            items = load(host, limit=MAX_BATCH, namespace=NAMESPACE)
            if not items:
                break
            records = [record for _, record in items]
            if not _post(records):
                break
            remove_delivered(
                host,
                {str(r.get("record_id")) for r in records if r.get("record_id")},
                namespace=NAMESPACE,
            )
            delivered += len(records)
        return {"delivered": delivered}
    except Exception:
        return {"delivered": delivered}
