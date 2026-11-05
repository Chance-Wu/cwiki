"""Verify the shared test session cannot commit past its outer transaction."""

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.conftest import configure_sqlite_transactions


async def test_savepoints_remain_inside_physical_outer_transaction(tmp_path):
    url = URL.create("sqlite+aiosqlite", database=str(tmp_path / "isolation.db"))
    engine = create_async_engine(url)
    configure_sqlite_transactions(engine)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE items (value TEXT NOT NULL)"))

        async with engine.connect() as conn:
            outer = await conn.begin()
            async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as session:
                await session.execute(text("INSERT INTO items VALUES ('first')"))
                await session.commit()
                await session.execute(text("INSERT INTO items VALUES ('discarded')"))
                await session.rollback()
                await session.execute(text("INSERT INTO items VALUES ('after rollback')"))
                await session.commit()
                assert outer.is_active
                assert await session.scalar(text("SELECT count(*) FROM items")) == 2
            await outer.rollback()

        await engine.dispose()
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM items")) == 0
    finally:
        await engine.dispose()
