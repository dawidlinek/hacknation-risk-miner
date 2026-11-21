"""Catalogue: view, versioned edits, weights, proposals, restore (api_contract §3.2). Transactional."""
from sqlalchemy import text


async def _scalar(db, sql, **p):
    return (await db.execute(text(sql), p)).scalar()


async def test_view_requires_login_and_has_parts(client, expert):
    assert (await client.get("/api/catalogue/view")).status_code == 401
    v = (await expert.get("/api/catalogue/view")).json()
    assert v["version"].startswith("v1.") and v["risks"] and v["versions"]
    r01 = next(r for r in v["risks"] if r["code"] == "R01")
    assert r01["name"] and "counts" in r01
    assert v["weights"] and abs(sum(w["w"] for w in v["weights"]) - 1) < 0.01


async def test_edit_creates_new_version_and_pack_label(expert, db):
    v0 = (await expert.get("/api/catalogue/view")).json()["version"]
    r = await expert.patch("/api/catalogue/risk/R01", json={"patch": {"description": "Nowy opis testowy"}, "comment": "test"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["version"] == 2 and j["status"] == "approved" and j["catalogue_version"] != v0
    rows = (await db.execute(text("SELECT version, status, origin, approved_by FROM catalogue_risk WHERE sector = 'wod-kan' AND code='R01' ORDER BY version"))).all()
    assert [r[1] for r in rows] == ["retired", "approved"] and rows[1][2] == "SOURCE" and rows[1][3] == "user:test"
    assert await _scalar(db, "SELECT count(*) FROM audit_log WHERE action='catalogue.edit' AND actor='user:test'") == 1
    assert await _scalar(db, "SELECT count(*) FROM catalogue_version WHERE label=:l", l=j["catalogue_version"]) == 1
    # no-op edit is a 409, unknown field 422
    again = await expert.patch("/api/catalogue/risk/R01", json={"patch": {"description": "Nowy opis testowy"}})
    assert again.status_code == 409
    assert (await expert.patch("/api/catalogue/risk/R01", json={"patch": {"data": {"a": 1}, "name": None}})).status_code in (200, 409)
    # public view only sees approved rows
    pub = (await expert.get("/api/catalogue/risk")).json()
    assert [r for r in pub if r["code"] == "R01" and r["status"] == "approved"][0]["description"] == "Nowy opis testowy"


async def test_restore_admin_only_and_creates_new_version(expert, admin, db):
    await expert.patch("/api/catalogue/risk/R01", json={"patch": {"description": "Zmiana A"}})
    labels = [v["label"] for v in (await expert.get("/api/catalogue/versions")).json()]
    base = labels[1]  # version before the edit
    assert (await expert.post(f"/api/catalogue/versions/{base}/restore", json={"reason": "x"})).status_code == 403
    r = await admin.post(f"/api/catalogue/versions/{base}/restore", json={"reason": "cofnięcie testu"})
    assert r.status_code == 200, r.text
    d = await admin.get("/api/catalogue/risk")
    cur = [x for x in d.json() if x["code"] == "R01" and x["status"] == "approved"][0]
    assert cur["description"] != "Zmiana A" and cur["version"] == 3


async def test_weights_validation_and_version(expert, db):
    v = (await expert.get("/api/catalogue/view")).json()
    cur = {w["feature"]: w["w"] for w in v["weights"]}
    bad = await expert.put("/api/catalogue/similarity/weights", json={"weights": {**cur, "value": 0.9}})
    assert bad.status_code == 422
    assert (await expert.put("/api/catalogue/similarity/weights", json={"weights": {"nonsense": 0.5}})).status_code == 422
    assert (await expert.put("/api/catalogue/similarity/weights", json={"weights": {"value": -0.1}})).status_code == 422
    ok = await expert.put("/api/catalogue/similarity/weights", json={"weights": {"budget": 0.2, "scope": 0.1}, "comment": "test"})
    assert ok.status_code == 200, ok.text
    j = ok.json()
    assert abs(sum(w["w"] for w in j["weights"]) - 1) < 0.002
    assert "wartość" in j["summary"] or "zakres" in j["summary"]


async def test_proposal_approve_and_reject(expert, db):
    props = (await expert.get("/api/catalogue/view")).json()["proposals"]
    assert props, "L's AI proposals should exist"
    pid = props[0]["id"]
    r = await expert.post(f"/api/catalogue/proposals/{pid}/decision", json={"action": "approve"})
    assert r.status_code == 200, r.text
    row = (await db.execute(text("SELECT status, origin, approved_by FROM catalogue_risk WHERE id=:i"), {"i": pid})).one()
    assert tuple(row) == ("approved", "SOURCE", "user:test")
    pid2 = props[1]["id"]
    assert (await expert.post(f"/api/catalogue/proposals/{pid2}/decision", json={"action": "reject"})).status_code == 422
    r = await expert.post(f"/api/catalogue/proposals/{pid2}/decision", json={"action": "reject", "reason": "duplikat"})
    assert r.status_code == 200
    assert await _scalar(db, "SELECT status FROM catalogue_risk WHERE id=:i", i=pid2) == "rejected"


async def test_catalogue_pack_public(client):
    r = await client.get("/api/catalogue/pack.json")
    assert r.status_code == 200 and r.json()["risk"]
    y = await client.get("/api/catalogue/pack.yaml")
    assert y.status_code == 200 and "risk:" in y.text


async def test_sector_param_validated(client, expert):
    for path in ("/api/catalogue/pack.json?sector=wód", "/api/catalogue/pack.yaml?sector=wód"):
        assert (await client.get(path)).status_code == 422
    assert (await expert.get("/api/catalogue/view?sector=%C5%BC%C5%82")).status_code == 422
    assert (await client.get("/api/catalogue/pack.yaml?sector=wod-kan")).status_code == 200


async def test_codes_resolve_with_their_sector(expert, db):
    """R01 exists for wod-kan and drogi: edits, approvals and the view must never cross sectors."""
    n_drogi = await _scalar(db, "SELECT count(*) FROM catalogue_risk WHERE sector='drogi' AND code='R01'")
    if not n_drogi:
        import pytest
        pytest.skip("no road pack seeded")
    before = await _scalar(db, "SELECT count(*) FROM catalogue_risk WHERE sector='drogi'")
    r = await expert.patch("/api/catalogue/risk/R01", json={"patch": {"description": "tylko wod-kan"}})
    assert r.status_code == 200 and (await _scalar(db, "SELECT count(*) FROM catalogue_risk WHERE sector='drogi'")) == before
    assert await _scalar(db, "SELECT count(*) FROM catalogue_risk WHERE sector='drogi' AND description = 'tylko wod-kan'") == 0
    # a drogi row is only reachable through its own sector and is not approved yet
    assert (await expert.patch("/api/catalogue/risk/R01", params={"sector": "drogi"}, json={"patch": {"description": "x"}})).status_code == 404
    v = (await expert.get("/api/catalogue/view", params={"sector": "wod-kan"})).json()
    sectors = {r[0] for r in (await db.execute(text("SELECT sector FROM catalogue_risk WHERE id = ANY(:i)"), {"i": [p["id"] for p in v["proposals"]] or [0]})).all()}
    assert sectors <= {"wod-kan"}
    # a risk event approval looks up the code in wod-kan only
    pid = await _scalar(db, "SELECT id FROM project WHERE rm_id='RM-2026-003'")
    eid = await _scalar(db, "INSERT INTO risk_event (project_id, event_type, catalogue_code, summary, origin, review_status) VALUES (:p,'EV_T','R01','t','AI','proposed') RETURNING id", p=pid)
    iid = await _scalar(db, "INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, model_pick, key) VALUES ('event','ai_event','risk_event',:e,:p,'t','R01','test:sector:1') RETURNING id", e=eid, p=pid)
    ok = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "R01", "action": "approve"})
    assert ok.status_code == 200


async def test_drogi_proposal_decision_stays_in_its_sector_pack(expert, db):
    row = (await db.execute(text("SELECT id FROM catalogue_risk WHERE sector='drogi' AND origin='AI' AND status='proposed' LIMIT 1"))).first()
    if not row:
        import pytest
        pytest.skip("no road AI proposal")
    wk = await _scalar(db, "SELECT label FROM catalogue_version WHERE sector='wod-kan' ORDER BY id DESC LIMIT 1")
    r = await expert.post(f"/api/catalogue/proposals/{row[0]}/decision", json={"action": "reject", "reason": "test sektora"})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT label FROM catalogue_version WHERE sector='wod-kan' ORDER BY id DESC LIMIT 1") == wk  # wod-kan pack untouched
    assert await _scalar(db, "SELECT count(*) FROM catalogue_version WHERE sector='drogi'") >= 1
