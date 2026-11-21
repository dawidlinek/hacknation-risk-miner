"""Monitoring 4.1-4.1c (owner D). Uses the transactional fixtures in conftest.py: nothing is written to the main DB."""
from __future__ import annotations

import pytest
from sqlalchemy import text


def _walk_nums(x, out):
    if isinstance(x, dict):
        if "prov" in x and "display" in x and "unit" in x:
            out.append(x)
        for v in x.values():
            _walk_nums(v, out)
    elif isinstance(x, list):
        for v in x:
            _walk_nums(v, out)
    return out


def _check_prov(payload):
    nums = _walk_nums(payload, [])
    assert nums
    for n in nums:
        p = n["prov"]
        assert p["role"] in ("source", "calc", "case", "ai")
        if p["role"] == "calc":
            assert isinstance(p["n"], int) and p["method"]
            if p.get("insufficient"):
                assert n["value"] is None and n["display"] == "za mało danych"
        if p["role"] == "source":
            assert p["refs"]


async def test_regions_woj_done_and_open(client):
    r = await client.get("/api/monitoring/regions", params={"level": "woj"})
    assert r.status_code == 200 and r.headers.get("x-fixture") is None
    d = r.json()
    assert len(d["regions"]) == 16 and d["total"]["n"] > 10000
    assert all(x["value"]["prov"]["method"].startswith("rc_share(late)") for x in d["regions"])
    _check_prov(d)
    o = (await client.get("/api/monitoring/regions", params={"level": "woj", "mode": "open"})).json()
    assert o["metric"]["key"] == "sig" and o["total"]["n"] > 1000
    assert sum(x["metrics"]["signals"] for x in o["regions"]) == o["total"]["n"]


async def test_region_drilldown_and_small_n(client):
    d = (await client.get("/api/monitoring/regions/12")).json()
    assert d["level"] == "woj" and d["breadcrumb"][0]["name"] == "Polska" and d["children"]
    assert any(k["key"] == "signals" and k.get("attention") for k in d["kpis"])
    _check_prov(d)
    g = (await client.get("/api/monitoring/regions", params={"level": "gmi", "parent": "1209"})).json()
    small = [x for x in g["regions"] if x["value"]["prov"]["n"] < 10]
    assert all(x["value"]["value"] is None for x in small)
    assert (await client.get("/api/monitoring/regions/99")).status_code == 404


async def test_signals_page_and_replay(client):
    d = (await client.get("/api/monitoring/signals", params={"terc": "12", "limit": 5})).json()
    assert d["total"] >= len(d["items"]) > 0
    days = [s["days_overdue"]["value"] for s in d["items"]]
    assert days == sorted(days, reverse=True) and all(s["woj"] == "12" for s in d["items"])
    old = (await client.get("/api/monitoring/signals", params={"as_of": "2024-01-01", "limit": 1})).json()
    now = (await client.get("/api/monitoring/signals", params={"limit": 1})).json()
    assert old["total"] != now["total"]
    assert (await client.get("/api/monitoring/signals", params={"as_of": "nie-data"})).status_code == 422


async def test_contract_detail(client):
    cid = (await client.get("/api/monitoring/signals", params={"limit": 1})).json()["items"][0]["contract_id"]
    d = (await client.get(f"/api/monitoring/contracts/{cid}")).json()
    assert d["signal"]["contract_id"] == cid and d["actions"]["can_watch"] is False
    assert {s["k"] for s in d["sources"]} == {"ogłoszenie o wyniku", "ogłoszenia o zmianie", "ogłoszenie o wykonaniu"}
    _check_prov(d)


async def test_watch_and_report_need_login(client):
    assert (await client.post("/api/monitoring/watches", json={"contract_id": 1})).status_code == 401


async def test_watch_and_report_write_audit(expert, db):
    cid = (await expert.get("/api/monitoring/signals", params={"limit": 1})).json()["items"][0]["contract_id"]
    before = (await db.execute(text("SELECT count(*) FROM audit_log WHERE actor = 'user:test'"))).scalar()
    w = await expert.post("/api/monitoring/watches", json={"contract_id": cid, "reason": "test"})
    assert w.status_code == 201 and w.json()["active"]
    sig = (await expert.get(f"/api/monitoring/contracts/{cid}")).json()["signal"]
    assert sig["watched"] is True
    rc = await expert.post(f"/api/monitoring/contracts/{cid}/report-case", json={"note": "do sprawdzenia"})
    assert rc.status_code == 201 and rc.json()["review_item_id"]
    u = await expert.delete(f"/api/monitoring/watches/{w.json()['id']}")
    assert u.status_code == 200 and u.json()["active"] is False
    after = (await db.execute(text("SELECT count(*) FROM audit_log WHERE actor = 'user:test'"))).scalar()
    assert after == before + 3


async def test_search_hides_confidential_from_anonymous(client, expert, admin, db):
    """Search sensitivity filter (owner D) with B's visibility rule (auth.public_doc_filter): a confidential document is
    invisible to anonymous callers and to experts who did not upload it; admin sees it."""
    doc_id = (await db.execute(text("SELECT document_id FROM chunk WHERE tsv @@ to_tsquery('simple', 'kanalizacji') LIMIT 1"))).scalar()
    await db.execute(text("UPDATE document SET sensitivity = 'confidential' WHERE id = :id"), {"id": doc_id})
    anon = (await client.get("/api/search", params={"q": "kanalizacji", "document_id": doc_id})).json()
    assert anon["total"] == 0
    assert (await client.get(f"/api/documents/{doc_id}/pages")).status_code == 404
    other = (await expert.get("/api/search", params={"q": "kanalizacji", "document_id": doc_id})).json()
    assert other["total"] == 0
    seen = (await admin.get("/api/search", params={"q": "kanalizacji", "document_id": doc_id})).json()
    assert seen["total"] > 0
    assert (await admin.get(f"/api/documents/{doc_id}/pages")).status_code == 200


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/monitoring/watches", {"reason": "anon"}),
    ("delete", "/api/monitoring/watches/{watch_id}", None),
    ("post", "/api/monitoring/contracts/{cid}/report-case", {"note": "anon"}),
])
async def test_anonymous_cannot_write_monitoring(client, db, method, path, body):
    """An anonymous visitor reads monitoring but every write route answers 401 (nothing is written)."""
    cid = (await db.execute(text("SELECT contract_id FROM v_monitor_signal LIMIT 1"))).scalar()
    wid = (await db.execute(text("INSERT INTO monitor_watch (contract_id, reason, active) VALUES (:c, 'x', true) "
                                 "RETURNING id"), {"c": cid})).scalar()
    d = (await client.get(f"/api/monitoring/contracts/{cid}")).json()
    assert d["actions"]["can_watch"] is False and d["actions"]["can_report"] is False
    n_before = (await db.execute(text("SELECT (SELECT count(*) FILTER (WHERE active) FROM monitor_watch), (SELECT count(*) FROM review_item)"))).one()
    url = path.format(watch_id=wid, cid=cid)
    kw = {"json": {**body, "contract_id": cid}} if body is not None else {}
    r = await getattr(client, method)(url, **kw)
    assert r.status_code == 401, r.text
    assert (await db.execute(text("SELECT (SELECT count(*) FILTER (WHERE active) FROM monitor_watch), (SELECT count(*) FROM review_item)"))).one() == n_before


async def _case_contract(db, rm_id):
    return (await db.execute(text("""SELECT c.id FROM project pr JOIN project_procedure pp ON pp.project_id = pr.id
                                     AND pp.method <> 'cross_reference_related' JOIN contract c ON c.procedure_id = pp.procedure_id
                                     WHERE pr.rm_id = :r ORDER BY c.id LIMIT 1"""), {"r": rm_id})).scalar()


async def _doc(db, title, sensitivity="public", project_rm=None):
    return (await db.execute(text("""
        INSERT INTO document (title, filename, fetch_state, sensitivity, key, origin, review_status, project_id)
        VALUES (:t, :t, 'found', :s, :k, 'SOURCE', 'auto', (SELECT id FROM project WHERE rm_id = :r)) RETURNING id"""),
        {"t": title, "s": sensitivity, "k": f"test:alert:{title}", "r": project_rm})).scalar()


async def test_alert_for_document_on_ongoing_contract(client, admin, expert, db):
    """new_documents.md G4: the Zagrodno protocol (05.05.2026) changes a contract that was ongoing then (completed
    01.06.2026 per the BZP performance notice): one alert, idempotent; after completion no alert; hidden with the doc."""
    from riskminer.monitoring import alerts as AL
    cid = await _case_contract(db, "RM-2026-002")
    doc = await _doc(db, "protokol zagrodno (test)")
    ch = [{"summary": "termin +1 mies. (do 05.06.2026)", "kind": "termin", "delta_days": 31}]
    r = await AL.raise_for_document(db, document_id=doc, contract_id=cid, doc_date="2026-05-05", changes=ch, created_by="test")
    assert r["raised"] and r["inserted"] and r["still_open"] is False
    r2 = await AL.raise_for_document(db, document_id=doc, contract_id=cid, doc_date="2026-05-05", changes=ch, created_by="test")
    assert r2["alert_id"] == r["alert_id"] and r2["inserted"] is False
    late = await AL.raise_for_document(db, document_id=doc, contract_id=cid, doc_date="2026-07-01", changes=ch, kind="late_doc")
    assert late["raised"] is False and "not ongoing" in late["reason"]
    # scoped to this test's document: the main DB may already hold real alerts for the same contract (e.g. an upload
    # of the organizer's Zagrodno protocol linked by B's doclink)
    a = (await client.get("/api/monitoring/alerts", params={"contract_id": cid, "document_id": doc})).json()
    assert a["total"] == 1 and a["items"][0]["severity"] == "high" and "w realizacji" in a["items"][0]["title"]
    assert a["items"][0]["detail"]["contracts"][0]["still_open"] is False and a["items"][0]["prov"]["origin"] == "CALC"
    d = (await client.get(f"/api/monitoring/contracts/{cid}")).json()
    assert r["alert_id"] in [x["id"] for x in d["alerts"]]
    # a confidential document's alert is visible only to those who may read the document
    await db.execute(text("UPDATE document SET sensitivity = 'confidential' WHERE id = :d"), {"d": doc})
    assert (await client.get("/api/monitoring/alerts", params={"document_id": doc})).json()["total"] == 0
    assert (await admin.get("/api/monitoring/alerts", params={"document_id": doc})).json()["total"] == 1
    # status: writer only
    s = await expert.post(f"/api/monitoring/alerts/{r['alert_id']}/status", json={"status": "seen"})
    assert s.status_code == 200 and s.json()["status"] == "seen"


async def test_alert_for_grant_change_on_project(db):
    """Grodzisko letter (06.11.2025, grant-agreement term): project-level alert while its contract was ongoing."""
    from riskminer.monitoring import alerts as AL
    doc = await _doc(db, "pismo grodzisko (test)", project_rm="RM-2026-010")
    r = await AL.raise_for_document(db, document_id=doc, doc_date="2025-11-06", kind="grant_term_change",
                                    changes=[{"summary": "wniosek o wydłużenie terminu projektu KPO do 31.12.2025"}])
    assert r["raised"], r
    row = (await db.execute(text("SELECT project_id, contract_id, kind, origin, key FROM alert WHERE id = :i"),
                            {"i": r["alert_id"]})).one()
    assert row[0] and row[1] is None and row[2] == "grant_term_change" and row[3] == "CALC" and row[4].endswith(f"p{row[0]}")


async def test_anonymous_cannot_change_alert_status(client, db):
    from riskminer.monitoring import alerts as AL
    doc = await _doc(db, "anon alert (test)")
    r = await AL.raise_for_document(db, document_id=doc, contract_id=await _case_contract(db, "RM-2026-002"),
                                    doc_date="2026-05-05")
    s = await client.post(f"/api/monitoring/alerts/{r['alert_id']}/status", json={"status": "closed"})
    assert s.status_code == 401


async def test_regions_for_other_sector_packs(client):
    """Sector packs (catalogue/<sector>/pack.yaml): budynki and cieplo show their completed works by region; the
    overdue-contract signals exist for core wod-kan only; unknown sectors are a 422; the default stays wod-kan."""
    base = (await client.get("/api/monitoring/regions", params={"level": "woj"})).json()
    assert base["sector"] == "wod-kan" and base["signals_available"] is True
    for sector in ("budynki", "cieplo"):
        r = (await client.get("/api/monitoring/regions", params={"level": "woj", "sector": sector})).json()
        assert r["sector"] == sector and r["signals_available"] is False and r["total"]["n"] >= 30, r["total"]
        assert r["total"]["n"] < base["total"]["n"]
        s = (await client.get("/api/monitoring/signals", params={"sector": sector})).json()
        assert s["total"] == 0
    assert (await client.get("/api/monitoring/regions", params={"sector": "../etc"})).status_code == 422
