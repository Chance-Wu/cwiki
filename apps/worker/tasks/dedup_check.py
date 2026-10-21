"""候选去重检查任务。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from apps.worker.dedup import find_similar
from packages.domain.database import async_session_maker
from packages.domain.models import CandidateMemory
from packages.domain.models.memory import MemoryConflict

logger = logging.getLogger(__name__)


async def task_dedup_check(
    ctx: dict[str, Any], candidate_id: str, workspace_id: str
) -> dict[str, Any]:
    """检查重复或相似的既有记忆。"""
    logger.info("Running dedup check for candidate %s", candidate_id)

    async with async_session_maker() as db_session:
        cid = uuid.UUID(candidate_id)
        wid = uuid.UUID(workspace_id)

        candidate_query = select(CandidateMemory).where(
            CandidateMemory.id == cid,
            CandidateMemory.workspace_id == wid,
        )
        candidate_result = await db_session.execute(candidate_query)
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            return {"status": "not_found"}

        candidate_dict = {
            "title": candidate.title,
            "content": candidate.content,
            "embedding": list(candidate.embedding) if candidate.embedding else None,
        }

        similar_results = await find_similar(candidate_dict, db_session, wid)

        similar_dicts = []
        for sr in similar_results:
            similar_dicts.append(
                {
                    "memory_id": str(sr.memory_id),
                    "title": sr.title,
                    "similarity": sr.similarity,
                    "relation": sr.relation,
                    "source": sr.source,
                }
            )

        recommended_action = "approve"
        top_relation = "NEW"
        for sr in similar_results:
            if sr.relation == "MERGE":
                recommended_action = "merge"
                top_relation = sr.relation
                break
            elif sr.relation == "CONFLICT":
                recommended_action = "review_conflict"
                top_relation = sr.relation
                break
            elif sr.relation == "UPDATE":
                recommended_action = "review_update"
                top_relation = sr.relation

        candidate.dedup_relation_type = top_relation
        await db_session.flush()

        if top_relation == "CONFLICT" and similar_results:
            from packages.domain.config import parasitic_evolution_config as _pec

            if _pec.write_time_conflict_enabled:
                for sr in similar_results:
                    if sr.relation == "CONFLICT":
                        conflict = MemoryConflict(
                            workspace_id=wid,
                            memory_id=sr.memory_id,
                            candidate_id=cid,
                            conflict_type="contradiction",
                            evidence={
                                "similarity": sr.similarity,
                                "source": sr.source,
                            },
                        )
                        db_session.add(conflict)
                await db_session.flush()

        return {
            "status": "completed",
            "candidate_id": candidate_id,
            "similar_count": len(similar_dicts),
            "similar_memories": similar_dicts,
            "recommended_action": recommended_action,
        }
