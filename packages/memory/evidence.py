"""证据挂接：让正式记忆拥有可追溯的来源记录。

候选转正 / 合并 / 更新时：
1. 把候选已有的 Evidence（如 episode 证据）改挂到正式记忆；
2. 写入一条 provenance Evidence，记录候选、来源渠道与命中规则。

这样检索/详情里的 evidence_count 不再恒为 0，Agent 可以引用来源。
"""

from __future__ import annotations

import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models.memory import CandidateMemory, Evidence, Memory

logger = logging.getLogger(__name__)


async def attach_candidate_evidence(
    db: AsyncSession,
    candidate: CandidateMemory,
    memory: Memory,
    *,
    change_type: str = "approval",
) -> int:
    """把候选证据挂到正式记忆，并补一条 provenance 记录。

    change_type: approval / merge / update，写入 source_type 与 metadata。
    返回本次新增/改挂的证据条数；同一候选同一变更类型重复调用不会重复写。
    """
    source_type = f"candidate_{change_type}"
    existing = (
        await db.execute(
            select(Evidence.id)
            .where(
                Evidence.candidate_id == candidate.id,
                Evidence.memory_id == memory.id,
                Evidence.source_type == source_type,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return 0

    linked = await db.execute(
        update(Evidence)
        .where(
            Evidence.candidate_id == candidate.id,
            Evidence.memory_id.is_(None),
        )
        .values(memory_id=memory.id)
    )
    linked_count = int(getattr(linked, "rowcount", 0) or 0)

    db.add(
        Evidence(
            memory_id=memory.id,
            candidate_id=candidate.id,
            episode_id=candidate.episode_id,
            source_type=source_type,
            source_ref=candidate.client_write_id or str(candidate.id),
            content=candidate.title,
            metadata_={
                "change_type": change_type,
                "candidate_id": str(candidate.id),
                "source": candidate.source,
                "memory_type": candidate.type,
                "policy_rule_id": candidate.policy_rule_id,
                "decision_rule_id": candidate.decision_rule_id,
            },
        )
    )
    await db.flush()
    return linked_count + 1
