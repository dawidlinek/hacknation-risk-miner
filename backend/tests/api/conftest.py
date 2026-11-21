"""Transactional API fixtures (api_contract §8): every test runs inside one outer transaction on one connection that is rolled
back at teardown, so tests never mutate the main DB. Writes use the request session (`get_session` is overridden with a session
that joins the outer transaction via savepoints); `db.commit()` inside handlers only releases a savepoint.

Fixtures: `db` (AsyncSession), `client` (anonymous), `expert` (logged-in expert client), `admin` (logged-in admin client).
Demo users are created in-process with RISKMINER_USERS (never read from .env)."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from riskminer.api import auth as A
from riskminer.api.main import app
from riskminer.config import settings
from riskminer.db.session import get_session

XRW = {"X-Requested-With": "ex-ante"}
TEST_USERS = {"test": ("expert", "test-pass"), "boss": ("admin", "boss-pass")}


@pytest.fixture(scope="session", autouse=True)
def _users():
    import os
    old = os.environ.get("RISKMINER_USERS")
    os.environ["RISKMINER_USERS"] = ";".join(
        f"{n}:{r}:{A.hash_password(p, n=2**10)}" for n, (r, p) in TEST_USERS.items())
    yield
    if old is None:
        os.environ.pop("RISKMINER_USERS", None)
    else:
        os.environ["RISKMINER_USERS"] = old


@pytest.fixture
async def db():
    engine = create_async_engine(settings().database_url)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

        async def override():
            yield session

        app.dependency_overrides[get_session] = override
        try:
            yield session
        finally:
            app.dependency_overrides.pop(get_session, None)
            await session.close()
            await outer.rollback()
    await engine.dispose()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=XRW)


@pytest.fixture
async def client(db):
    async with _client() as c:
        yield c


async def _login(c: httpx.AsyncClient, name: str) -> httpx.AsyncClient:
    r = await c.post("/api/auth/login", json={"username": name, "password": TEST_USERS[name][1]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
async def expert(db):
    async with _client() as c:
        yield await _login(c, "test")


@pytest.fixture
async def admin(db):
    async with _client() as c:
        yield await _login(c, "boss")
