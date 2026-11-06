"""Evidence 生命周期：审批/合并/更新后正式记忆拥有可追溯来源。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from packages.domain.database import Base
from packages.domain.models import CandidateMemory, Evidence, Memory, Workspace
from packages.memory.service import approve_candidate, merge_candidate, update_candidate_into

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def evidence_engine() -> AsyncGenerator:
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
async def evidence_db(evidence_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(evidence_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


async def _workspace_and_candidate(
    db: AsyncSession,
    *,
    content: str = "## 场景\n证据生命周期测试。\n\n## 知识\n审批后应产生来源证据。",
) -> tuple[Workspace, CandidateMemory]:
    ws = Workspace(id=uuid.uuid4(), name=f"evidence-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    await db.flush()
    candidate = CandidateMemory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="证据生命周期测试候选",
        content=content,
        type="fact",
        source="memory_save",
        status="pending_review",
        confidence=0.8,
        importance=0.8,
    )
    db.add(candidate)
    await db.commit()
    return ws, candidate


async def _evidence_rows(db: AsyncSession, memory_id: uuid.UUID) -> list[Evidence]:
    return list(
        (await db.execute(select(Evidence).where(Evidence.memory_id == memory_id))).scalars().all()
    )


async def test_approval_creates_provenance_evidence(evidence_db: AsyncSession) -> None:
    _, candidate = await _workspace_and_candidate(evidence_db)
    memory = await approve_candidate(evidence_db, candidate)
    await evidence_db.commit()

    rows = await _evidence_rows(evidence_db, memory.id)
    assert len(rows) == 1
    assert rows[0].candidate_id == candidate.id
    assert rows[0].source_type == "candidate_approval"
    assert rows[0].source_ref == str(candidate.id)
    assert rows[0].metadata_["change_type"] == "approval"
    assert rows[0].metadata_["source"] == "memory_save"


async def test_existing_candidate_evidence_is_linked(evidence_db: AsyncSession) -> None:
    _, candidate = await _workspace_and_candidate(evidence_db)
    episode_evidence = Evidence(
        candidate_id=candidate.id,
        source_type="episode",
        source_ref="episode-1",
        content="来自工具失败的 episode 证据",
    )
    evidence_db.add(episode_evidence)
    await evidence_db.commit()

    memory = await approve_candidate(evidence_db, candidate)
    await evidence_db.commit()
    await evidence_db.refresh(episode_evidence)

    assert episode_evidence.memory_id == memory.id
    rows = await _evidence_rows(evidence_db, memory.id)
    assert len(rows) == 2
    assert {row.source_type for row in rows} == {"episode", "candidate_approval"}


async def test_merge_attaches_merge_evidence(evidence_db: AsyncSession) -> None:
    ws, candidate = await _workspace_and_candidate(evidence_db)
    target = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="已有目标记忆",
        content="## 知识\n目标记忆原始内容。",
        type="fact",
        source="memory_save",
        status="active",
        version=1,
    )
    evidence_db.add(target)
    await evidence_db.commit()

    memory = await merge_candidate(
        evidence_db,
        candidate,
        target,
        "## 知识\n目标记忆原始内容。\n\n## 补充\n来自候选的新事实。",
    )
    await evidence_db.commit()

    rows = await _evidence_rows(evidence_db, memory.id)
    assert len(rows) == 1
    assert rows[0].source_type == "candidate_merge"
    assert rows[0].candidate_id == candidate.id


async def test_update_attaches_update_evidence(evidence_db: AsyncSession) -> None:
    ws, candidate = await _workspace_and_candidate(evidence_db)
    target = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="待更新记忆",
        content="## 知识\n旧内容。",
        type="fact",
        source="memory_save",
        status="active",
        version=1,
    )
    evidence_db.add(target)
    await evidence_db.commit()

    memory = await update_candidate_into(evidence_db, candidate, target)
    await evidence_db.commit()

    rows = await _evidence_rows(evidence_db, memory.id)
    assert len(rows) == 1
    assert rows[0].source_type == "candidate_update"
    assert rows[0].candidate_id == candidate.id


async def test_merge_unions_candidate_tags_into_target(evidence_db: AsyncSession) -> None:
    """合并时标签取并集：目标已有的人工标签不能被候选覆盖或抹掉。"""
    ws, candidate = await _workspace_and_candidate(evidence_db)
    candidate.tags = ["python", "asyncio"]
    target = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="已有目标记忆",
        content="## 知识\n目标记忆原始内容。",
        type="fact",
        source="memory_save",
        status="active",
        version=1,
        tags=["pinned", "Python"],
    )
    evidence_db.add(target)
    await evidence_db.commit()

    memory = await merge_candidate(
        evidence_db,
        candidate,
        target,
        "## 知识\n目标记忆原始内容。\n\n## 补充\n来自候选的新事实。",
    )
    await evidence_db.commit()
    # 规范化 + 首次出现顺序：目标标签在前，候选新标签在后，大小写去重
    assert memory.tags == ["pinned", "python", "asyncio"]


async def test_update_candidate_unions_tags_not_replaces(evidence_db: AsyncSession) -> None:
    """候选整体替换正文时同样并集标签：候选常只带自动标签，直接替换会丢人工标签。"""
    ws, candidate = await _workspace_and_candidate(evidence_db)
    candidate.tags = ["new-tag"]
    target = Memory(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        title="待更新记忆",
        content="## 知识\n旧内容。",
        type="fact",
        source="memory_save",
        status="active",
        version=1,
        tags=["pinned"],
    )
    evidence_db.add(target)
    await evidence_db.commit()

    memory = await update_candidate_into(evidence_db, candidate, target)
    await evidence_db.commit()
    assert memory.tags == ["pinned", "new-tag"]
