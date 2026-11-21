import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from riskminer.config import settings
from riskminer.db import models  # noqa: F401  (register tables)
from riskminer.db.base import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings().database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    eng = create_async_engine(settings().database_url)
    async with eng.connect() as conn:
        await conn.run_sync(do_run)
    await eng.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async())
