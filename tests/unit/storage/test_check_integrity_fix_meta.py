"""--fix-meta：仅从数据库补导出缺失的 active 记忆侧车。"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.domain.models import Base, Memory, Workspace
from scripts.check_integrity import _fix_missing_meta


def test_fix_missing_meta_exports_active_only(tmp_path):
    db_path = tmp_path / "src.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    ws_id, active_id, superseded_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def seed() -> None:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(Workspace(id=ws_id, name="fix-meta"))
            session.add_all(
                [
                    Memory(
                        id=active_id,
                        workspace_id=ws_id,
                        title="active",
                        content="内容",
                        type="fact",
                    ),
                    Memory(
                        id=superseded_id,
                        workspace_id=ws_id,
                        title="superseded",
                        content="内容",
                        type="fact",
                        status="superseded",
                    ),
                ]
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())
    data_dir = tmp_path / "data"

    fixed = _fix_missing_meta(db_url, data_dir)

    assert fixed == [str(active_id)]
    meta_path = data_dir / "_meta" / f"{active_id}.json"
    assert meta_path.is_file()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert set(payload) >= {"relation", "review_schedule", "versions"}
    assert not (data_dir / "_meta" / f"{superseded_id}.json").exists()

    # 幂等：再跑一次没有可补项
    assert _fix_missing_meta(db_url, data_dir) == []
