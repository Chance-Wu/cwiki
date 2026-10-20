"""捕获会话与待整理笔记的 _meta 导出/重建测试。

内容完整性要求：待整理笔记不能只在 SQLite 里；换设备/重建后必须
从 ``_meta/_capture_notes.json`` 恢复全文、来源和 candidate 追溯链。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import AgentSession, Base, SessionNote, Workspace
from packages.storage.rebuilder import DatabaseRebuilder
from scripts.migrate_to_git import export_all

_WS_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_SESSION_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_NOTE_ID = uuid.UUID("99999999-8888-7777-6666-555555555555")
_CANDIDATE_ID = uuid.UUID("12121212-3434-5656-7878-909090909090")
_DT = datetime.fromisoformat("2026-01-01T00:00:00")


async def test_export_and_rebuild_preserve_capture_notes(tmp_path):
    src_db = tmp_path / "src.db"
    data_dir = tmp_path / "data"
    src_url = f"sqlite+aiosqlite:///{src_db.as_posix()}"
    source = create_async_engine(src_url)
    async with source.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    long_content = "完整捕获内容" + ("细节" * 3000)
    async with async_sessionmaker(source, expire_on_commit=False)() as session:
        session.add(Workspace(id=_WS_ID, name="cwiki"))
        session.add(
            AgentSession(
                id=_SESSION_ID,
                workspace_id=_WS_ID,
                agent="qoder",
                task="capture task",
                metadata_={"host_session_id": "host-1", "cwd": "/tmp/cwiki"},
                started_at=_DT,
                created_at=_DT,
            )
        )
        session.add(
            SessionNote(
                id=_NOTE_ID,
                session_id=_SESSION_ID,
                workspace_id=_WS_ID,
                content=long_content,
                signal_type="session_snapshot",
                candidate_id=_CANDIDATE_ID,
                formalized=True,
                created_at=_DT,
            )
        )
        await session.commit()
    await source.dispose()

    stats = await export_all(src_url, str(data_dir))
    assert stats["capture_session_count"] == 1
    assert stats["capture_note_count"] == 1

    payload = json.loads((data_dir / "_meta" / "_capture_notes.json").read_text())
    assert payload["sessions"][0]["agent"] == "qoder"
    assert payload["notes"][0]["content"] == long_content
    assert payload["notes"][0]["candidate_id"] == str(_CANDIDATE_ID)

    target_url = f"sqlite+aiosqlite:///{(tmp_path / 'target.db').as_posix()}"
    rebuilder = DatabaseRebuilder(db_url=target_url, data_dir=str(data_dir))
    async with rebuilder._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = await rebuilder.rebuild()
    assert result.capture_session_count == 1
    assert result.capture_note_count == 1

    async with rebuilder._session_factory() as session:
        note = (
            await session.execute(select(SessionNote).where(SessionNote.id == _NOTE_ID))
        ).scalar_one()
        assert note.content == long_content
        assert note.candidate_id == _CANDIDATE_ID
        assert note.formalized is True
        agent_session = (
            await session.execute(select(AgentSession).where(AgentSession.id == _SESSION_ID))
        ).scalar_one()
        assert agent_session.agent == "qoder"
        assert agent_session.metadata_["host_session_id"] == "host-1"
    await rebuilder._engine.dispose()
