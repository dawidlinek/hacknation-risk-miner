"""Async engine/session (SQLAlchemy 2 + asyncpg) and a raw asyncpg pool for bulk COPY."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

import asyncpg
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from riskminer.config import settings


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(settings().database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)


@lru_cache
def sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as s:
        yield s


@asynccontextmanager
async def raw_conn() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(settings().dsn)
    try:
        await set_codecs(conn)
        yield conn
    finally:
        await conn.close()


async def set_codecs(conn: asyncpg.Connection) -> None:
    """jsonb/json as Python objects, binary format (works for COPY too)."""
    await conn.set_type_codec("jsonb", encoder=_jsonb_enc, decoder=_jsonb_dec, schema="pg_catalog", format="binary")
    await conn.set_type_codec("json", encoder=_dumps, decoder=_loads, schema="pg_catalog")


def _jsonb_enc(v) -> bytes:
    import orjson
    return b"\x01" + orjson.dumps(v, default=str, option=orjson.OPT_NON_STR_KEYS)


def _jsonb_dec(b: bytes):
    import orjson
    return orjson.loads(b[1:])


def _dumps(v) -> str:
    import orjson
    return orjson.dumps(v, default=str).decode()


def _loads(s: str):
    import orjson
    return orjson.loads(s)
