"""Auth: login/me/logout, role gates, public-route leaks (api_contract §5, §8.7). Uses the transactional fixtures."""
import httpx

from riskminer.api import auth as A
from riskminer.api.main import app


async def test_me_anonymous_gets_cookie(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    j = r.json()
    assert j["user"] is None and j["role"] == "public" and len(j["anon_id"]) == 8
    assert "rm_session" in r.headers.get("set-cookie", "")


async def test_login_bad_and_good(client):
    r = await client.post("/api/auth/login", json={"username": "test", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Nieprawidłowy login lub hasło."
    r = await client.post("/api/auth/login", json={"username": "test", "password": "test-pass"})
    assert r.status_code == 200
    assert r.json()["user"] == {"name": "test", "role": "expert", "initials": "TE", "persona": None, "read_only": False}
    me = (await client.get("/api/auth/me")).json()
    assert me["role"] == "expert" and me["name"] == "test"
    out = await client.post("/api/auth/logout")
    assert out.status_code == 204
    assert (await client.get("/api/auth/me")).json()["role"] == "public"


async def test_csrf_header_required_for_writes(db):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/auth/login", json={"username": "test", "password": "test-pass"})
        assert r.status_code == 403


async def test_tampered_cookie_is_anonymous(client):
    client.cookies.set("rm_session", "garbage.value.here")
    assert (await client.get("/api/auth/me")).json()["role"] == "public"


async def test_login_gated_routes_anonymous(client):
    for path in ("/api/review-items", "/api/review-items/counts", "/api/runs", "/api/sources", "/api/link-candidates",
                 "/api/export/review_items.json", "/api/export/audit.csv", "/api/export/runs.json"):
        r = await client.get(path)
        assert r.status_code == 401, path


async def test_login_gated_routes_expert(expert):
    for path in ("/api/review-items", "/api/review-items/counts", "/api/runs?limit=1", "/api/sources?limit=1",
                 "/api/link-candidates?limit=1", "/api/export/review_items.json?limit=1"):
        r = await expert.get(path)
        assert r.status_code == 200, (path, r.text[:200])


async def test_public_project_detail_hides_queue_and_unverified(client, expert):
    anon = (await client.get("/api/projects/RM-2026-022")).json()
    assert anon["review_items"] == []
    full = (await expert.get("/api/projects/RM-2026-022")).json()
    assert any(i["code"] == "contract_notice_missing" for i in full["review_items"])


async def test_public_catalogue_only_approved(client, expert):
    anon = (await client.get("/api/catalogue/risk", params={"status": "proposed"})).json()
    assert anon and all(r["status"] == "approved" for r in anon)
    allrows = (await expert.get("/api/catalogue/risk", params={"status": "proposed"})).json()
    assert allrows and all(r["status"] == "proposed" for r in allrows)


async def test_confidential_documents_hidden(client, db):
    from sqlalchemy import text
    await db.execute(text("""INSERT INTO document (title, filename, sensitivity, doc_type, fetch_state)
                             VALUES ('tajny-test', 'tajny.pdf', 'confidential', 'PFU', 'found')"""))
    r = (await client.get("/api/documents", params={"limit": 1000})).json()
    assert all(d["filename"] != "tajny.pdf" for d in r["items"])


async def test_password_roundtrip_and_rate_limit():
    h = A.hash_password("abc", n=2**10)
    assert A.verify_password("abc", h) and not A.verify_password("abd", h)
    assert not A.verify_password("abc", "garbage")
    key = "t:rate"
    assert not any(A.rate_limited(key, 3, now=100.0) for _ in range(3))
    assert A.rate_limited(key, 3, now=101.0)
    assert not A.rate_limited(key, 3, now=170.0)


def test_users_parse():
    u = A.load_users("a:expert:scrypt$1$2$3$x$y;b:admin:hash;bad:root:h;c:expert")
    assert set(u) == {"a", "b"} and u["b"][0] == "admin"


async def test_demo_personas_listed_and_login_audited(client, db):
    from sqlalchemy import text
    ps = (await client.get("/api/auth/demo-personas")).json()
    assert [p["persona"] for p in ps] == ["juror", "expert", "admin"]
    r = await client.post("/api/auth/demo-login", json={"persona": "juror"})
    assert r.status_code == 200
    j = r.json()
    assert j["role"] == "expert" and j["read_only"] is True and j["persona"] == "juror" and j["user"]["name"] == "juror"
    row = (await db.execute(text("SELECT actor, after->>'persona', after->>'method' FROM audit_log WHERE action='auth.login' ORDER BY id DESC LIMIT 1"))).one()
    assert tuple(row) == ("user:juror", "juror", "demo")
    me = (await client.get("/api/auth/me")).json()
    assert me["persona"] == "juror" and me["read_only"] is True
    assert (await client.post("/api/auth/demo-login", json={"persona": "root"})).status_code == 422


async def test_juror_reads_but_cannot_write(client, db):
    from sqlalchemy import text
    await client.post("/api/auth/demo-login", json={"persona": "juror"})
    assert (await client.get("/api/review-items/counts")).status_code == 200
    assert (await client.get("/api/dashboard")).status_code == 200
    iid = (await db.execute(text("SELECT id FROM review_item WHERE status='open' LIMIT 1"))).scalar()
    for method, path, body in (("post", f"/api/review-items/{iid}/decision", {"option": "x", "action": "approve"}),
                               ("post", f"/api/review-items/{iid}/skip", None),
                               ("post", "/api/projects/RM-2026-003/links", {"action": "add", "bzp_number": "x"}),
                               ("patch", "/api/catalogue/risk/R01", {"patch": {"description": "x"}}),
                               ("put", "/api/catalogue/similarity/weights", {"weights": {"value": 0.1}}),
                               ("post", "/api/audit/1/restore", {"reason": "x"})):
        r = await getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json().get("code", "read_only") in ("read_only", None), (path, r.text)


async def test_expert_and_admin_personas_can_write(client, db):
    from sqlalchemy import text
    r = await client.post("/api/auth/demo-login", json={"persona": "expert"})
    assert r.json()["read_only"] is False and r.json()["user"]["name"] == "ekspert"
    iid = (await db.execute(text("SELECT id FROM review_item WHERE status='open' LIMIT 1"))).scalar()
    assert (await client.post(f"/api/review-items/{iid}/skip")).status_code == 200
    assert (await client.post("/api/catalogue/versions/v1.1/restore", json={"reason": "x"})).status_code == 403  # admin only
    a = await client.post("/api/auth/demo-login", json={"persona": "admin"})
    assert a.json()["role"] == "admin"
    assert (await client.get("/api/auth/me")).json()["name"] == "administrator"


async def test_demo_login_can_be_disabled(client, monkeypatch):
    monkeypatch.setenv("RISKMINER_DEMO_LOGIN", "false")
    assert (await client.get("/api/auth/demo-personas")).json() == []
    r = await client.post("/api/auth/demo-login", json={"persona": "admin"})
    assert r.status_code == 403
