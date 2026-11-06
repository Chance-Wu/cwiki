"""SessionStart 复习到期提示：让 Agent 有机会主动带用户复习。

背景：到期提醒只写入 ~/.cwiki/state/review_reminders.json，没有任何消费方；
前端通知要求页面打开，间隔重复闭环因此停摆（真实库 36/36 全部到期、零执行）。
这里补上 Agent 侧出口：会话开始注入一行"到期 N 条"提示，Agent 据此调用
memory_review_due / memory_review_submit 组织复习；无到期或 DB 不可读则静默。

约束：只读查询、单条 SQL、任何异常返回空串，不影响会话启动。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

MAX_HINT_ITEMS = 3
_QUERY = """
select m.id, m.title, count(*) over () as due_total
from review_schedule rs
join memory m on m.id = rs.memory_id
where rs.next_review <= datetime('now')
  and rs.suspended_at is null
  and m.status = 'active'
  and (?1 = '' or m.workspace_id = ?1)
order by rs.next_review asc
limit ?2
"""


def _workspace_id(conn: sqlite3.Connection, name: str) -> str | None:
    if not name:
        return ""
    row = conn.execute("select id from workspace where name = ?", (name,)).fetchone()
    return str(row[0]) if row else None


def _shown_today(host: str, workspace: str, total: int) -> bool:
    """同一 (host, workspace) 每天最多提示一次，避免每次会话开始都刷屏。

    记录数变化（复习后到期减少）时重新提示。状态写坏就当作未提示过——
    提示是增强，不因为状态异常而丢失。
    """
    from .spool import host_dir

    marker = host_dir(host) / f"review_hint_{workspace or 'all'}.date"
    today = time.strftime("%Y-%m-%d")
    try:
        if marker.read_text(encoding="utf-8").strip() == f"{today}|{total}":
            return True
    except OSError:
        pass
    try:
        marker.write_text(f"{today}|{total}", encoding="utf-8")
    except OSError:
        return False
    return False


def due_hint(workspace: str, host: str = "generic") -> str:
    """返回一行到期提示文本；无到期或任何失败返回空串。"""
    try:
        from adapters.mcp.local_index import _resolve_db_path

        path = _resolve_db_path(None)
        if path is None or not Path(path).is_file():
            return ""
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.5)
        try:
            ws_id = _workspace_id(conn, workspace)
            if ws_id is None:
                return ""
            rows = conn.execute(_QUERY, (ws_id or "", MAX_HINT_ITEMS)).fetchall()
        finally:
            conn.close()
    except Exception:
        return ""
    if not rows:
        return ""
    total = int(rows[0][2])
    if _shown_today(host, workspace, total):
        return ""
    titles = "；".join(str(t)[:30] for _mid, t, _n in rows)
    return (
        f"cwiki 复习提醒：当前工作区 {total} 条记忆已到复习窗口"
        f"（如「{titles}」）。可用 memory_review_due 取到期清单，"
        "征得用户同意后逐条 memory_review_submit 巩固；用户不需要就跳过。"
    )


def enabled() -> bool:
    """与后台周期任务共用 parasitic_evolution.review_reminders_enabled 开关。"""
    try:
        from packages.domain.config import parasitic_evolution_config

        return bool(parasitic_evolution_config.review_reminders_enabled)
    except Exception:
        return False
