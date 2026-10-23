"""cwiki 测试配置。"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from apps.api.auth import AgentIdentity
from apps.api.deps import get_current_agent, get_db
from packages.domain.database import Base

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session", autouse=True)
def _isolate_global_task_queue(tmp_path_factory):
    """全局任务队列落盘到临时目录，避免测试任务写进真机 ~/.cwiki/state。"""
    from packages.domain import task_queue as task_queue_module

    queue = task_queue_module.queue
    queue._persist_path = tmp_path_factory.mktemp("task-queue") / "task_queue.json"
    queue._tasks.clear()
    queue._pending_keys.clear()
    yield
    queue._tasks.clear()
    queue._pending_keys.clear()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    eng = create_async_engine(
        TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await trans.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from apps.api.main import app

    test_identity = AgentIdentity(
        agent_id="test-agent",
        workspace_id="default",
    )

    async def override_get_db():
        yield db_session

    async def override_get_current_agent():
        return test_identity

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_agent] = override_get_current_agent
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
