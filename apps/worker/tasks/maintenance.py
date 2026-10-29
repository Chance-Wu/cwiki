"""维护类任务：复习提醒与定期 meta 导出。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from packages.domain.config import parasitic_evolution_config
from packages.domain.database import async_session_maker
from packages.domain.models import Memory, MemoryRelation
from packages.domain.models.memory import ReviewSchedule

logger = logging.getLogger(__name__)


async def task_check_review_reminders(ctx: dict[str, Any]) -> dict[str, Any]:
    """检查逾期待审项并生成提醒记录。

    扫描全部工作区中 next_review 已过期的 ReviewSchedule，
    把提醒摘要写入 state 文件供主动推送机制使用。
    受 review_reminders_enabled 特性开关控制。
    """
    if not parasitic_evolution_config.review_reminders_enabled:
        return {"status": "disabled"}

    async with async_session_maker() as db_session:
        now = datetime.now(UTC).replace(tzinfo=None)

        query = (
            select(
                ReviewSchedule.workspace_id,
                ReviewSchedule.memory_id,
                ReviewSchedule.next_review,
                Memory.title,
            )
            .join(Memory, ReviewSchedule.memory_id == Memory.id)
            .where(ReviewSchedule.next_review <= now)
            .order_by(ReviewSchedule.next_review.asc())
            .limit(200)
        )
        result = await db_session.execute(query)
        due_items = result.all()

        if not due_items:
            return {"status": "completed", "due_count": 0, "reminders": []}

        # 按 workspace 分组
        by_workspace: dict[str, list[dict[str, Any]]] = {}
        for ws_id, mem_id, next_review, title in due_items:
            ws_key = str(ws_id)
            if ws_key not in by_workspace:
                by_workspace[ws_key] = []
            days_overdue = (now - next_review).days if next_review else 0
            by_workspace[ws_key].append(
                {
                    "memory_id": str(mem_id),
                    "title": title,
                    "days_overdue": days_overdue,
                }
            )

        reminders = []
        for ws_key, items in by_workspace.items():
            reminders.append(
                {
                    "workspace_id": ws_key,
                    "due_count": len(items),
                    "top_items": items[:5],  # 逾期最久的前 5 条
                }
            )

        # 写入 state 文件供推送机制使用（内容未变则跳过写盘）
        reminders_path = Path.home() / ".cwiki" / "state" / "review_reminders.json"
        reminders_path.parent.mkdir(parents=True, exist_ok=True)
        reminders_data = {
            "total_due": len(due_items),
            "reminders": reminders,
        }
        new_content = json.dumps(reminders_data, ensure_ascii=False, indent=2, sort_keys=True)

        # 与现有文件比较，避免冗余写入
        should_write = True
        try:
            existing_content = await asyncio.to_thread(reminders_path.read_text, encoding="utf-8")
            if existing_content == new_content:
                should_write = False
        except FileNotFoundError:
            pass

        if should_write:
            reminders_data["generated_at"] = datetime.now(UTC).isoformat()
            await asyncio.to_thread(
                reminders_path.write_text,
                json.dumps(reminders_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        logger.info(
            "Review reminders: %d items due across %d workspaces",
            len(due_items),
            len(by_workspace),
        )

        return {
            "status": "completed",
            "due_count": len(due_items),
            "workspace_count": len(by_workspace),
            "reminders": reminders,
        }


async def task_periodic_meta_export(ctx: dict[str, Any]) -> dict[str, Any]:
    """定期将 DB 侧车数据导出到 _meta/*.json，防止重建时回退。

    由周期调度器按 scheduler.meta_export_interval_hours 间隔触发。
    复用 scripts/migrate_to_git.py 的 export_all 逻辑。
    """
    from packages.domain.settings import get_settings
    from packages.storage import config as storage_config
    from scripts.migrate_to_git import export_all

    db_url = get_settings().database_url
    data_dir = str(storage_config.memory_dir)

    try:
        stats = await export_all(db_url, data_dir)
        logger.info(
            "Periodic meta export: %d memories, %d meta, %d workspaces",
            stats.get("memory_count", 0),
            stats.get("meta_count", 0),
            stats.get("workspace_count", 0),
        )
        return {"status": "completed", **stats}
    except Exception:
        logger.exception("Periodic meta export failed")
        return {"status": "error"}


async def task_auto_discover_relations(ctx: dict[str, Any]) -> dict[str, Any]:
    """基于向量相似度自动发现并创建记忆间关系。

    扫描所有工作区，对 embedding 余弦相似度 >= threshold 的记忆对
    自动创建 related 类型关系。受 auto_relation_enabled 特性开关控制。
    """
    from packages.domain.config import parasitic_evolution_config
    from packages.memory.auto_relation import discover_relations

    if not parasitic_evolution_config.auto_relation_enabled:
        return {"status": "disabled"}

    threshold = parasitic_evolution_config.auto_relation_threshold
    max_per_memory = parasitic_evolution_config.auto_relation_max_per_memory

    async with async_session_maker() as db_session:
        # 查询所有工作区
        from packages.domain.models import Workspace

        ws_result = await db_session.execute(select(Workspace))
        workspaces = ws_result.scalars().all()

        total_created = 0
        workspace_stats = []

        for ws in workspaces:
            try:
                created = await discover_relations(
                    db_session,
                    ws.id,
                    threshold=threshold,
                    max_relations_per_memory=max_per_memory,
                )
                total_created += created
                if created > 0:
                    workspace_stats.append(
                        {
                            "workspace_id": str(ws.id),
                            "workspace_name": ws.name,
                            "relations_created": created,
                        }
                    )
            except Exception:
                logger.exception(f"自动关系发现失败: workspace={ws.name}")

        logger.info(
            "Auto relation discovery: %d new relations across %d workspaces (threshold=%.2f)",
            total_created,
            len(workspace_stats),
            threshold,
        )

        return {
            "status": "completed",
            "total_created": total_created,
            "workspaces_with_new_relations": len(workspace_stats),
            "threshold": threshold,
            "details": workspace_stats,
        }


async def task_prune_stale_relations(ctx: dict[str, Any]) -> dict[str, Any]:
    """清理长期未强化的自动关系边。

    条件：created_by='auto'、从未被强化（strength<=0 且无强化时间）、
    置信低于 auto_relation_threshold、创建时间超过 relation_auto_edge_ttl_days。
    TTL 配置为 0（默认）时不执行，人工/审核/合并产生的边永不清理。
    """
    ttl_days = parasitic_evolution_config.relation_auto_edge_ttl_days
    if ttl_days <= 0:
        return {"status": "disabled"}

    threshold = parasitic_evolution_config.auto_relation_threshold
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=ttl_days)
    async with async_session_maker() as db_session:
        result = await db_session.execute(
            delete(MemoryRelation).where(
                MemoryRelation.created_by == "auto",
                MemoryRelation.confidence < threshold,
                MemoryRelation.strength <= 0,
                MemoryRelation.last_reinforced_at.is_(None),
                MemoryRelation.created_at < cutoff,
            )
        )
        await db_session.commit()

    deleted = int(getattr(result, "rowcount", 0) or 0)
    logger.info(
        "Relation aging: deleted %d auto edges older than %.0f days (threshold=%.2f)",
        deleted,
        ttl_days,
        threshold,
    )
    return {
        "status": "completed",
        "deleted": deleted,
        "ttl_days": ttl_days,
        "threshold": threshold,
    }
