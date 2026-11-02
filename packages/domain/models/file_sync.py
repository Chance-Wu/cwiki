"""Transactional repair log for DB-authoritative memory mirrors."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import event, func, insert, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from packages.domain.models.base import Base, UUIDType


class FileSyncJob(Base):
    """Append-only intents; deliberately no FK so deletion survives its memory."""

    __tablename__ = "file_sync_job"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType(), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(UUIDType(), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), server_default=func.now())


@event.listens_for(Session, "after_flush")
def _record_memory_mirrors(session: Session, flush_context: Any) -> None:
    from packages.domain.models.memory import Memory

    if session.info.get("skip_file_sync_intents"):
        return
    changed = (*session.new, *session.dirty, *session.deleted)
    ids = {obj.id for obj in changed if isinstance(obj, Memory) and obj.id is not None}
    # 来源、版本、复习/反馈等侧车变更也需要持久补偿。
    for obj in changed:
        if isinstance(obj, FileSyncJob):
            continue
        for field in ("memory_id", "source_memory_id", "target_memory_id"):
            mid = getattr(obj, field, None)
            if isinstance(mid, uuid.UUID):
                ids.add(mid)
    if ids:
        session.connection().execute(
            insert(FileSyncJob.__table__),
            [{"id": uuid.uuid4(), "memory_id": mid} for mid in ids],
        )


@event.listens_for(Session, "do_orm_execute")
def _record_bulk_memory_deletes(state: Any) -> None:
    """Core-style ORM DELETE bypasses after_flush; log before it in the same txn."""
    from packages.domain.models.memory import Memory

    if state.session.info.get("skip_file_sync_intents"):
        return
    if not state.is_delete or state.bind_mapper is None or state.bind_mapper.class_ is not Memory:
        return
    stmt = select(Memory.id).where(*state.statement._where_criteria)
    ids = state.session.execute(stmt).scalars().all()
    if ids:
        state.session.connection().execute(
            insert(FileSyncJob.__table__),
            [{"id": uuid.uuid4(), "memory_id": mid} for mid in ids],
        )
