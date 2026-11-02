"""复习计划的 leech/暂停字段随 _meta 导出并重建恢复。"""

from __future__ import annotations

import uuid
from datetime import datetime

from packages.domain.database import Base
from packages.domain.models import Memory, ReviewSchedule, Workspace
from packages.storage.meta_export import collect_memory_relations
from packages.storage.rebuilder import DatabaseRebuilder


async def test_review_schedule_leech_fields_round_trip(db_session, tmp_path) -> None:
    ws = Workspace(id=uuid.uuid4(), name=f"leech-{uuid.uuid4().hex[:6]}")
    db_session.add(ws)
    await db_session.flush()
    memory = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="leech 测试",
        content="## 知识\n顽固记忆字段测试。",
        type="fact",
        status="active",
        version=1,
    )
    db_session.add(memory)
    await db_session.flush()
    suspended_at = datetime(2026, 1, 2, 3, 4, 5)
    db_session.add(
        ReviewSchedule(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            memory_id=memory.id,
            ease_factor=1.4,
            interval_days=2,
            repetitions=1,
            next_review=datetime(2026, 1, 3),
            total_reviews=7,
            lapse_streak=3,
            suspended_at=suspended_at,
        )
    )
    await db_session.commit()

    relations = await collect_memory_relations(db_session, memory.id)
    schedule_meta = relations["review_schedule"]
    assert schedule_meta["lapse_streak"] == 3
    assert schedule_meta["suspended_at"] == suspended_at.isoformat()

    rebuilder = DatabaseRebuilder(
        db_url=f"sqlite+aiosqlite:///{(tmp_path / 'rebuild.db').as_posix()}",
        data_dir=str(tmp_path / "data"),
    )
    async with rebuilder._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(rebuilder._engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Workspace(id=ws.id, name=ws.name))
        await session.flush()
        session.add(
            Memory(
                id=memory.id,
                workspace_id=ws.id,
                title=memory.title,
                content=memory.content,
                type=memory.type,
                status="active",
                version=1,
            )
        )
        await session.commit()

        batch: list[ReviewSchedule] = []
        counts = {"review_schedule": 0}
        await rebuilder._process_review_schedule(
            {"review_schedule": schedule_meta},
            str(memory.id),
            session,
            batch,
            counts,
        )
        assert counts["review_schedule"] == 1
        restored = batch[0]
        assert restored.lapse_streak == 3
        assert restored.suspended_at == suspended_at
    await rebuilder.close()
