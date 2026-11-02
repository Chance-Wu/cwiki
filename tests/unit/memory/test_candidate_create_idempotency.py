"""候选创建幂等竞态测试。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base
from packages.domain.models import CandidateMemory, Workspace
from packages.memory.service import create_candidate


@pytest_asyncio.fixture
async def create_engine() -> AsyncGenerator:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def create_db(create_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(create_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


async def _workspace(db: AsyncSession) -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), name=f"idempotency-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    await db.flush()
    return workspace


async def test_idempotent_insert_race_keeps_outer_transaction_usable(
    create_db: AsyncSession,
) -> None:
    workspace = await _workspace(create_db)
    payload = {
        "db": create_db,
        "workspace_id": workspace.id,
        "title": "幂等候选竞态",
        "content": "## 场景\n模拟幂等写入竞态。\n\n## 结论\n唯一键冲突只回滚 savepoint。",
        "type": "fact",
        "client_write_id": "same-write-id",
    }

    first, _, created = await create_candidate(**payload)
    assert created is True
    second, _, created = await create_candidate(**payload)
    assert created is False
    assert second.id == first.id

    # 外层事务仍可继续写入并提交，而不是被 IntegrityError 置为 failed。
    extra = Workspace(id=uuid.uuid4(), name="after-savepoint")
    create_db.add(extra)
    await create_db.commit()
    assert await create_db.get(Workspace, extra.id) is not None

    rows = (
        await create_db.execute(
            select(CandidateMemory).where(CandidateMemory.client_write_id == "same-write-id")
        )
    ).scalars().all()
    assert len(rows) == 1


async def test_idempotent_insert_recovers_when_precheck_misses_competing_row(
    create_db: AsyncSession,
) -> None:
    """模拟两请求在幂等预查与 INSERT 之间交错，验证 savepoint 回滚边界。"""
    workspace = await _workspace(create_db)
    write_id = "raced-write-id"
    payload = {
        "db": create_db,
        "workspace_id": workspace.id,
        "title": "竞态获胜候选",
        "content": "## 场景\n预查遗漏并发写入。\n\n## 结论\n唯一约束负责最终幂等。",
        "type": "fact",
        "client_write_id": write_id,
    }
    competitor = CandidateMemory(
        workspace_id=workspace.id,
        title="并发请求先写入",
        content="## 并发\n另一请求先完成写入。",
        type="fact",
        source="race",
        status="pending_review",
        client_write_id=write_id,
    )

    async def interleave(*args, **kwargs):
        create_db.add(competitor)
        await create_db.flush()
        return [], None

    with patch(
        "packages.memory.service._find_similar_at_submit",
        new=AsyncMock(side_effect=interleave),
    ):
        found, _, created = await create_candidate(**payload)

    assert created is False
    assert found.id == competitor.id
    extra = Workspace(id=uuid.uuid4(), name="after-raced-savepoint")
    create_db.add(extra)
    await create_db.commit()
    assert await create_db.get(Workspace, extra.id) is not None
    rows = (
        await create_db.execute(
            select(CandidateMemory).where(CandidateMemory.client_write_id == write_id)
        )
    ).scalars().all()
    assert len(rows) == 1
