"""记忆关系的 Hebbian 强化与时间衰减。"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.domain.models import MemoryRelation

DEFAULT_REINFORCEMENT_RATE = 0.2
DEFAULT_DECAY_HALF_LIFE_DAYS = 30.0


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def decay_strength(
    strength: float,
    last_reinforced_at: datetime | None,
    *,
    now: datetime,
    half_life_days: float,
) -> float:
    """按半衰期衰减强度；从未强化的边保持原值。"""
    if strength <= 0:
        return 0.0
    if last_reinforced_at is None or half_life_days <= 0:
        return strength
    elapsed_days = max(
        (_naive_utc(now) - _naive_utc(last_reinforced_at)).total_seconds() / 86400, 0.0
    )
    # math.pow 避免 float**float 在 typeshed 中返回 Any（负底数可能为 complex）
    return strength * math.pow(0.5, elapsed_days / half_life_days)


def reinforce_strength(
    strength: float,
    last_reinforced_at: datetime | None,
    *,
    now: datetime,
    rate: float,
    half_life_days: float,
) -> float:
    """先衰减再向 1 逼近，返回新的强度。"""
    base = decay_strength(strength, last_reinforced_at, now=now, half_life_days=half_life_days)
    return min(1.0, base + rate * (1.0 - base))


async def reinforce_relations(
    db: AsyncSession,
    memory_ids: Sequence[uuid.UUID],
    *,
    now: datetime | None = None,
    rate: float = DEFAULT_REINFORCEMENT_RATE,
    half_life_days: float = DEFAULT_DECAY_HALF_LIFE_DAYS,
) -> int:
    """强化两端都在本次结果中的既有关系边，返回更新条数。"""
    unique_ids = list(dict.fromkeys(memory_ids))
    if len(unique_ids) < 2:
        return 0

    resolved_now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(MemoryRelation).where(
                MemoryRelation.source_memory_id.in_(unique_ids),
                MemoryRelation.target_memory_id.in_(unique_ids),
            )
        )
    ).scalars()
    updated = 0
    for relation in rows:
        relation.strength = reinforce_strength(
            relation.strength or 0.0,
            relation.last_reinforced_at,
            now=resolved_now,
            rate=rate,
            half_life_days=half_life_days,
        )
        relation.last_reinforced_at = _naive_utc(resolved_now)
        updated += 1
    await db.flush()
    return updated
