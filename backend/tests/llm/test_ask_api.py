"""/ask, /questions and chats through the ASGI app inside one rolled-back transaction (fake LLM, no network).
Reads the national DB read-only (ask views)."""
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from riskminer.api.main import app
from riskminer.config import settings
from riskminer.db.session import get_session

pytestmark = pytest.mark.fulldb
XRW = {"X-Requested-With": "ex-ante"}


@pytest.fixture
async def client():
    engine = create_async_engine(settings().database_url)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

        async def override():
            yield session
        app.dependency_overrides[get_session] = override
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=XRW) as c:
                yield c
        finally:
            app.dependency_overrides.pop(get_session, None)
            await session.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
def cassettes(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKMINER_LLM_REPLAY_DIR", str(tmp_path))

    def put(task, match, obj):
        d = tmp_path / task
        d.mkdir(exist_ok=True)
        (d / f"{abs(hash(match))}.json").write_text(json.dumps({"match": match, "text": obj}), encoding="utf-8")
    return put


async def test_suggestions(client):
    r = await client.get("/api/ask/suggestions")
    assert r.status_code == 200 and {x["key"] for x in r.json()} >= {"zw", "woj_late"}
    assert "X-Fixture" not in r.headers


async def test_curated_ask_save_rows_rerun(client):
    r = await client.post("/api/ask", json={"question": "Zaprojektuj i wybuduj a samo wykonanie"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["role"] == "calc" and a["role_label"] == "obliczenie" and a["n"] > 1000 and len(a["bars"]) == 2
    s = await client.post("/api/questions", json={"question_id": a["id"], "title": "ZiW a wykonanie"})
    assert s.status_code == 201, s.text
    code = s.json()["code"]
    assert code.startswith("Q-")
    g = await client.get(f"/api/questions/{code}")
    assert g.status_code == 200 and g.json()["code"] == code
    lst = (await client.get("/api/questions")).json()
    assert any(i["code"] == code for i in lst["items"])
    csv = await client.get(f"/api/questions/{code}/rows.csv")
    assert csv.status_code == 200 and "formula" in csv.text
    rr = await client.post(f"/api/questions/{code}/rerun")
    assert rr.status_code == 200 and rr.json()["changed"] is False


async def test_ask_llm_sql_and_refusal(client, cassettes):
    cassettes("nl2sql", "odsetek po terminie w wielkopolskim", {
        "sql": "SELECT round(100.0 * avg(late::int), 1) AS pct, count(*) AS n FROM v_ask_contract WHERE woj_name = 'wielkopolskie'",
        "answer_template": "Po terminie skończyło się {pct}% z {n} umów.", "bars": None, "title": "Wielkopolskie po terminie",
        "cannot_answer": None})
    r = await client.post("/api/ask", json={"question": "Jaki odsetek po terminie w wielkopolskim?".replace("Jaki ", "").replace("?", "") })
    # the match above must be a substring of the rendered prompt
    if r.status_code != 200:
        pytest.fail(r.text)
    a = r.json()
    assert a["role"] == "calc" and "%" in a["text"] and a["method"]["kind"] == "sql"
    cassettes("nl2sql", "DROP-ME", {"sql": "DELETE FROM v_ask_contract", "answer_template": "x", "title": "x"})
    r = await client.post("/api/ask", json={"question": "DROP-ME"})
    assert r.json()["role"] == "no_data"


async def test_project_chat_labels(client, cassettes):
    cassettes("chat", "<pytanie>Skąd dane?</pytanie>", {"answer": "Tak, dane pochodzą z BZP.", "role": "calc", "fact_ids": ["F1"],
                                             "missing": [], "follow_ups": []})
    r = await client.post("/api/projects/RM-2026-001/chat", json={"message": "Skąd dane?"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["role"] in ("calc", "ai") and a["method"]["kind"] == "llm" and a["processing"]["provider"] == "gemini"


async def test_chat_invented_number_becomes_no_data(client, cassettes):
    cassettes("chat", "<pytanie>Ile opóźnienia?</pytanie>", {"answer": "Opóźnienie wyniosło 987654 dni.", "role": "calc", "fact_ids": ["F1"],
                                             "missing": [], "follow_ups": []})
    r = await client.post("/api/projects/RM-2026-002/chat", json={"message": "Ile opóźnienia?"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "no_data" and r.json()["text"].startswith("Nie odpowiem")


@pytest.fixture
async def admin(client, monkeypatch):
    from riskminer.api import auth as A
    from riskminer.llm import config as C
    monkeypatch.setenv("RISKMINER_USERS", f"boss:admin:{A.hash_password('boss-pass', n=2**10)};"
                                          f"test:expert:{A.hash_password('test-pass', n=2**10)}")
    r = await client.post("/api/auth/login", json={"username": "boss", "password": "boss-pass"})
    assert r.status_code == 200, r.text
    yield client
    C._OVERRIDES.clear()
    C.llm_config.cache_clear()


async def test_settings_view_and_confidential_rule(admin):
    r = await admin.get("/api/settings/llm")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "GEMINI" not in r.text and "AIza" not in r.text
    conf = [t for t in d["tasks"] if t["sensitivity"] == "confidential"]
    assert conf and all(t["data_location"].startswith("PL") and t["enforced"] for t in conf)
    bad = await admin.put("/api/settings/llm/routing", json={"routing": {"confidential": {"extract_features": "strong"}}})
    assert bad.status_code == 422 and bad.json()["code"] == "confidential_must_stay_pl"
    ok = await admin.put("/api/settings/llm/routing", json={"routing": {"public": {"chat": "fast"}}})
    assert ok.status_code == 200
    assert next(t for t in ok.json()["tasks"] if t["task"] == "chat" and t["sensitivity"] == "public")["alias"] == "fast"


async def test_settings_needs_login(client):
    assert (await client.get("/api/settings/llm")).status_code == 401
