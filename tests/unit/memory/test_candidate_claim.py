"""候选状态原子占用测试：并发批准最多成功一次。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base
from packages.domain.models import CandidateMemory, Workspace
from packages.memory.service import CandidateStateError, claim_candidate

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def claim_engine() -> AsyncGenerator:
    engine = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def claim_db(claim_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(claim_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


async def test_claim_pending_once_then_conflict(claim_db: AsyncSession) -> None:
    ws = Workspace(id=uuid.uuid4(), name=f"claim-{uuid.uuid4().hex[:6]}")
    claim_db.add(ws)
    await claim_db.flush()
    candidate = CandidateMemory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="原子占用测试",
        content="## 场景\n候选状态原子迁移测试。\n\n## 知识\n仅 pending_review 可被占用一次。",
        type="fact",
        source="memory_save",
        status="pending_review",
    )
    claim_db.add(candidate)
    await claim_db.commit()

    await claim_candidate(claim_db, candidate, "approved")
    await claim_db.commit()
    assert candidate.status == "approved"

    with pytest.raises(CandidateStateError):
        await claim_candidate(claim_db, candidate, "rejected")
