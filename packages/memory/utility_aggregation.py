"""效用分批量聚合：检索引擎与记忆列表 API 共用的信号采集层。

分量公式与权重见 packages/memory/utility_score.py（PRD 第 31 节）；
本模块只负责"从 usage / feedback / evidence 三表批量取信号"并代入
compute_utility_score——引擎（候选重排微调）与列表路由（价值分展示）
都走这里，避免两处各写一份批量 SQL 造成口径漂移。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import Evidence, MemoryFeedback, MemoryUsage
from packages.memory.utility_score import compute_utility_score

logger = logging.getLogger(__name__)


async def aggregate_utility_scores(
    db: AsyncSession,
    memories: Sequence[Any],
) -> dict[str, float]:
    """对给定记忆对象批量计算效用分，返回 ``{str(memory_id): utility}``。

    *memories* 只要求具备 ``.id``（UUID）与 ``.last_used_at``（datetime
    或 None）两个属性——ORM Memory 与引擎内部 mem_map 条目均满足。
    用三条 GROUP BY 批量 SQL 一次取回全部信号，避免逐条记忆各发一条
    查询的 N+1 开销。cited_count 目前无写入方恒传 0；ease_factor 用
    默认 2.5（批量场景不逐条查 ReviewSchedule）。

    任何查询异常时返回空映射（调用方按"未计算"处理），不让辅助信号
    阻断检索或列表主流程——与图扩展的降级策略一致。
    """
    utility_map: dict[str, float] = {}
    try:
        id_to_mem = {str(m.id): m for m in memories}
        if not id_to_mem:
            return utility_map
        uuid_ids = [uuid.UUID(mid) for mid in id_to_mem]

        # 使用流水：总检索次数 + 实际被采用（used/cited）次数
        usage_result = await db.execute(
            select(
                MemoryUsage.memory_id,
                func.count(MemoryUsage.id),
                func.count(case((MemoryUsage.stage.in_(["used", "cited"]), MemoryUsage.id))),
            )
            .where(MemoryUsage.memory_id.in_(uuid_ids))
            .group_by(MemoryUsage.memory_id)
        )
        usage_map = {str(row[0]): (row[1], row[2]) for row in usage_result.all()}

        # 反馈计数：useful 计正票；not_useful/outdated/wrong 一律视为负票
        # （outdated/wrong 是更强的负信号，单独存在时也压制排序）。
        feedback_result = await db.execute(
            select(
                MemoryFeedback.memory_id,
                MemoryFeedback.feedback_type,
                func.count(MemoryFeedback.id),
            )
            .where(MemoryFeedback.memory_id.in_(uuid_ids))
            .group_by(MemoryFeedback.memory_id, MemoryFeedback.feedback_type)
        )
        feedback_map: dict[str, dict[str, int]] = {}
        for row in feedback_result.all():
            feedback_map.setdefault(str(row[0]), {})[row[1]] = row[2]

        # 证据数：支撑 evidence_strength 分量（compute 内部按 5 条封顶）
        evidence_result = await db.execute(
            select(Evidence.memory_id, func.count(Evidence.id))
            .where(Evidence.memory_id.in_(uuid_ids))
            .group_by(Evidence.memory_id)
        )
        evidence_map = {str(row[0]): row[1] for row in evidence_result.all()}

        for mem_id, mem in id_to_mem.items():
            retrieval_count, used_count = usage_map.get(mem_id, (0, 0))
            votes = feedback_map.get(mem_id, {})
            negative_votes = sum(votes.get(kind, 0) for kind in ("not_useful", "outdated", "wrong"))
            utility = compute_utility_score(
                retrieval_count=retrieval_count,
                used_count=used_count,
                cited_count=0,
                useful_votes=votes.get("useful", 0),
                not_useful_votes=negative_votes,
                last_used_at=mem.last_used_at,
                evidence_count=evidence_map.get(mem_id, 0),
            )
            utility_map[mem_id] = round(utility.utility, 4)
    except Exception:
        # 效用聚合失败只损失排序微调/展示信号，不能让调用方整体失败
        utility_map = {}
        logger.debug("Utility aggregation failed, defaulting to empty", exc_info=True)
    return utility_map


def latest_used_at(*candidates: datetime | None) -> datetime | None:
    """取候选时间中最新者；naive 一律视为 UTC（与 days_since 口径一致）。

    memory.last_used_at 列只在导入/重建路径落值，运行期检索命中只写
    memory_usage 流水，因此"最后使用时间"需融合两个来源取较新者。
    返回 naive UTC，与 DB 列及既有 last_used_at 的序列化格式保持一致。
    """
    aware: list[datetime] = []
    for candidate in candidates:
        if candidate is None:
            continue
        aware.append(candidate if candidate.tzinfo else candidate.replace(tzinfo=UTC))
    if not aware:
        return None
    return max(aware).replace(tzinfo=None)
