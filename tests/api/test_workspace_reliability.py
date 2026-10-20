"""Workspace API 竞态与迁移测试，仅使用隔离的测试数据库。"""

import asyncio
import importlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from adapters.mcp.client import CwikiClient
from apps.api.deps import get_db
from apps.api.routes.workspaces import router
from packages.domain.database import Base
from packages.domain.models import Memory, Workspace


@pytest.fixture
async def workspace_api(tmp_path):
    url = sa.URL.create("sqlite+aiosqlite", database=str(tmp_path / "workspaces.db"))
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def test_db():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # 不导入生产应用，也不运行其 lifespan/存储初始化。
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = test_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, engine
    finally:
        await engine.dispose()


async def test_workspace_create_obeys_request_transaction(workspace_api):
    from apps.api.routes.workspaces import create_workspace
    from packages.domain.schemas import WorkspaceCreate

    _, engine = workspace_api
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn) as session:
            await create_workspace(WorkspaceCreate(name="rolled-back"), session)
        await transaction.rollback()
        assert await conn.scalar(sa.select(sa.func.count()).select_from(Workspace)) == 0


async def test_api_existing_name_is_deterministic_conflict(workspace_api):
    client, engine = workspace_api
    first = await client.post("/v1/workspaces", json={"name": "shared"})
    assert first.status_code == 201
    second = await client.post("/v1/workspaces", json={"name": "shared"})
    assert second.status_code == 409
    assert second.json() == {"detail": {"code": "workspace_name_conflict", "name": "shared"}}
    async with engine.connect() as conn:
        assert await conn.scalar(sa.select(sa.func.count()).select_from(Workspace)) == 1


async def test_api_concurrent_create_handles_unique_violation(workspace_api, monkeypatch):
    client, engine = workspace_api
    barrier = asyncio.Barrier(2)
    original_scalar = AsyncSession.scalar

    async def simultaneous_lookup(session, *args, **kwargs):
        result = await original_scalar(session, *args, **kwargs)
        if result is None:
            # 两个调用方都在对方插入前看到了缺失的名称（竞态窗口）。
            await asyncio.wait_for(barrier.wait(), timeout=5)
        return result

    monkeypatch.setattr(AsyncSession, "scalar", simultaneous_lookup)
    responses = await asyncio.gather(
        *(client.post("/v1/workspaces", json={"name": "race"}) for _ in range(2))
    )
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"]["code"] == "workspace_name_conflict"
    async with engine.connect() as conn:
        assert await conn.scalar(sa.select(sa.func.count()).select_from(Workspace)) == 1


async def test_api_pagination_stable_with_equal_timestamps(workspace_api):
    http, engine = workspace_api
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        {"id": uuid.UUID(int=n + 1), "name": f"ws-{n}", "created_at": timestamp} for n in range(105)
    ]
    async with engine.begin() as conn:
        # 逆序插入以证明排序不是偶然的行序。
        await conn.execute(Workspace.__table__.insert(), list(reversed(rows)))
    response = await http.get("/v1/workspaces")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 20
    client = CwikiClient("http://test")
    client._http = http
    result = await client.list_workspaces()
    assert result["total"] == 105
    assert [item["id"] for item in result["items"]] == [str(row["id"]) for row in rows]


async def test_unrelated_integrity_error_is_not_name_conflict(workspace_api, monkeypatch):
    http, _ = workspace_api
    error = IntegrityError("insert", {}, RuntimeError("unrelated integrity error"))

    async def failed_flush(*args, **kwargs):
        raise error

    monkeypatch.setattr(AsyncSession, "flush", failed_flush)
    with pytest.raises(IntegrityError) as caught:
        await http.post("/v1/workspaces", json={"name": "new"})
    assert caught.value is error


@pytest.fixture
def legacy_database():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    workspace = sa.Table(
        "workspace",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Index("ix_workspace_name", "name"),
    )
    child = sa.Table(
        "child",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.String, sa.ForeignKey("workspace.id")),
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        metadata.create_all(conn)
        yield conn, workspace, child
    engine.dispose()


def run_migration(conn, monkeypatch, direction="upgrade"):
    migration = importlib.import_module("migrations.versions.024_workspace_name_unique")
    monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
    getattr(migration, direction)()


def test_migration_preserves_data_and_enforces_unique_names(legacy_database, monkeypatch):
    conn, workspace, child = legacy_database
    conn.execute(workspace.insert(), {"id": "one", "name": "existing"})
    conn.execute(child.insert(), {"id": 1, "workspace_id": "one"})
    run_migration(conn, monkeypatch)
    indexes = sa.inspect(conn).get_indexes("workspace")
    assert [(index["name"], bool(index["unique"])) for index in indexes] == [
        ("uq_workspace_name", True)
    ]
    assert conn.execute(sa.select(workspace)).all() == [("one", "existing")]
    assert conn.execute(sa.select(child)).all() == [(1, "one")]
    with pytest.raises(IntegrityError):
        conn.execute(workspace.insert(), {"id": "two", "name": "existing"})
    run_migration(conn, monkeypatch, "downgrade")
    conn.execute(workspace.insert(), {"id": "two", "name": "existing"})
    assert conn.scalar(sa.select(sa.func.count()).select_from(workspace)) == 2


def test_migration_rejects_duplicates_without_changing_data(legacy_database, monkeypatch):
    conn, workspace, child = legacy_database
    rows = [{"id": "one", "name": "duplicate"}, {"id": "two", "name": "duplicate"}]
    conn.execute(workspace.insert(), rows)
    conn.execute(child.insert(), {"id": 1, "workspace_id": "two"})
    with pytest.raises(RuntimeError, match=r"duplicate.*\(2\).*manually"):
        run_migration(conn, monkeypatch)
    assert conn.execute(sa.select(workspace).order_by(workspace.c.id)).all() == [
        ("one", "duplicate"),
        ("two", "duplicate"),
    ]
    assert conn.execute(sa.select(child)).all() == [(1, "two")]
    assert [index["name"] for index in sa.inspect(conn).get_indexes("workspace")] == [
        "ix_workspace_name"
    ]
    # 迁移被拒绝后仍可继续插入重名：schema 未被改动。
    conn.execute(workspace.insert(), {"id": "three", "name": "duplicate"})


async def test_default_workspace_prefers_most_active(workspace_api):
    """默认工作区取 active 记忆最多者，而非最新创建的空工作区。"""
    client, engine = workspace_api
    alpha_id = (await client.post("/v1/workspaces", json={"name": "alpha"})).json()["id"]
    await client.post("/v1/workspaces", json={"name": "beta"})
    async with AsyncSession(bind=engine) as session:
        session.add_all(
            [
                Memory(workspace_id=uuid.UUID(alpha_id), title="a1", content="a1", type="fact"),
                Memory(workspace_id=uuid.UUID(alpha_id), title="a2", content="a2", type="fact"),
            ]
        )
        await session.commit()

    resp = await client.get("/v1/workspaces/default")
    assert resp.status_code == 200
    assert resp.json()["name"] == "alpha"


async def test_default_workspace_without_memories_falls_back_to_latest(workspace_api):
    """全部工作区都无记忆时按创建时间取最新。"""
    client, engine = workspace_api
    await client.post("/v1/workspaces", json={"name": "older"})
    await client.post("/v1/workspaces", json={"name": "newer"})
    # 同秒创建的 created_at 并列，显式错开以保证确定性
    async with AsyncSession(bind=engine) as session:
        ws = (
            await session.execute(sa.select(Workspace).where(Workspace.name == "newer"))
        ).scalar_one()
        ws.created_at = datetime.now(UTC) + timedelta(seconds=5)
        await session.commit()

    resp = await client.get("/v1/workspaces/default")
    assert resp.status_code == 200
    assert resp.json()["name"] == "newer"


async def test_default_workspace_no_workspaces_returns_404(workspace_api):
    client, _ = workspace_api
    resp = await client.get("/v1/workspaces/default")
    assert resp.status_code == 404
