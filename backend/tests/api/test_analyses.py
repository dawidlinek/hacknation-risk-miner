"""Flow 1 /api/analyses: create -> patch -> run -> get -> versions, inside the rolled-back transaction (conftest)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

DEMO = ("Planujemy budowę kanalizacji sanitarnej ok. 6 km z 3 przepompowniami w formule zaprojektuj i wybuduj, "
        "budżet 7 mln zł brutto, 14 miesięcy, FEnIKS, województwo śląskie.")

pytestmark = pytest.mark.fulldb


def _walk_nums(o, path="$"):
    """Yield (path, obj) for every dict carrying a numeric `value` and a `unit` (Num-like)."""
    if isinstance(o, dict):
        if "unit" in o and "value" in o and "prov" in o:
            yield path, o
        for k, v in o.items():
            yield from _walk_nums(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk_nums(v, f"{path}[{i}]")


async def test_create_patch_run_get(client, db):
    n_audit = (await db.execute(text("SELECT count(*) FROM audit_log"))).scalar()
    r = await client.post("/api/analyses", json={"text": DEMO, "document_ids": []})
    assert r.status_code == 201, r.text
    d = r.json()
    code = d["id"]
    assert code.startswith("AN-") and len(code) == 12
    keys = {f["key"]: f for f in d["features"]}
    assert keys["podsektor"]["value"] == "SAN"
    assert keys["formula"]["value"] == "design_build"
    assert keys["budzet"]["value"]["amount"] == "7000000.00"
    assert keys["termin_mies"]["value"] == 14.0
    assert keys["dlugosc_km"]["unsure"] is True
    assert all(f["prov"]["role"] in ("calc", "source", "ai") for f in d["features"])

    r = await client.patch(f"/api/analyses/{code}/features", json={"values": {"dlugosc_km": 6.0}, "skipped": ["przylacza"]})
    assert r.status_code == 200, r.text
    d2 = r.json()
    assert d2["version"] == 2
    L = next(f for f in d2["features"] if f["key"] == "dlugosc_km")
    assert L["review_status"] == "edited" and L["unsure"] is False
    assert not any(f["key"] == "przylacza" for f in d2["follow_ups"])

    r = await client.post(f"/api/analyses/{code}/run")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"

    r = await client.get(f"/api/analyses/{code}")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["status"] == "ready" and rep["version"] == 2
    funnel = [f["n"] for f in rep["reference_class"]["funnel"]]
    assert 11150 <= funnel[0] <= 11450 and 4250 <= funnel[1] <= 4420 and 360 <= funnel[2] <= 395
    assert 78 <= funnel[3] <= 92
    q = {x["key"]: x for x in rep["questions"]}
    assert 0.28 <= q["time"]["key_value"] <= 0.42
    assert q["time"]["answer"] in ("Nie", "Raczej nie")
    assert 12.5 <= q["time"]["band"]["from"] <= 14.5 and 19.5 <= q["time"]["band"]["to"] <= 22.5
    assert q["budget"]["key_kind"] == "mln_per_km" and abs(q["budget"]["key_value"] - 7 / 6) < 0.01
    assert q["programme"]["programme_end"] is not None
    assert any(f["rule"] == "F6" for f in rep["flags"] if f.get("origin") == "CALC")
    assert not any(f.get("rule") == "F12" for f in rep["flags"])
    assert rep["summary"]["text"].startswith("Podobne inwestycje")
    assert "\u2014" not in str(rep) and "\u00b7" not in str(rep)
    assert len(rep["similar_cases"]) >= 1
    for sc in rep["similar_cases"]:
        assert abs(sum(c["value"] for c in sc["contributions"]) - sc["score"]) < 0.01
    # provenance: every Num-like object is calc/source/case/ai; calc has n and method
    for path, nobj in _walk_nums(rep):
        if path.startswith("$.features"):        # input chips, not computed metrics
            continue
        p = nobj["prov"]
        assert p["role"] in ("calc", "source", "case", "ai"), path
        if p["role"] == "calc":
            assert isinstance(p["n"], int) and p["method"], path
            if p["n"] < 10:
                assert nobj["value"] is None, path

    r = await client.get(f"/api/analyses/{code}/versions")
    assert r.status_code == 200 and [v["version"] for v in r.json()] == [2]

    r = await client.get(f"/api/analyses/{code}/reference-class/contracts?limit=5")
    assert r.status_code == 200 and r.json()["total"] == funnel[3] and len(r.json()["items"]) == 5

    r = await client.post(f"/api/analyses/{code}/run")
    assert r.json()["version"] == 3

    r = await client.get(f"/api/analyses/{code}?version=2")
    assert r.status_code == 200 and r.json()["version"] == 2

    n_audit2 = (await db.execute(text("SELECT count(*) FROM audit_log"))).scalar()
    assert n_audit2 >= n_audit + 4


async def test_snapshot_immutable(client, db):
    r = await client.post("/api/analyses", json={"text": DEMO})
    code = r.json()["id"]
    await client.post(f"/api/analyses/{code}/run")
    with pytest.raises(Exception):
        async with db.begin_nested():
            await db.execute(text("UPDATE analysis_version SET reason = 'x' WHERE analysis_id = "
                                  "(SELECT id FROM analysis WHERE code = :c)"), {"c": code})


async def test_other_owner_forbidden(client, expert, db):
    r = await client.post("/api/analyses", json={"text": DEMO})
    code = r.json()["id"]
    r = await expert.patch(f"/api/analyses/{code}/features", json={"values": {"termin_mies": 18}})
    assert r.status_code == 403


async def test_csrf_required(client):
    r = await client.post("/api/analyses", json={"text": DEMO}, headers={"X-Requested-With": ""})
    assert r.status_code == 403


def _interp(pts, x):
    import numpy as np
    return float(np.interp(x, [p[0] for p in pts], [p[1] for p in pts]))


def _inv(pts, y):
    import numpy as np
    return float(np.interp(y, [p[1] for p in pts], [p[0] for p in pts]))


async def test_simulation_allocation_pack(client, db):
    r = await client.post("/api/analyses", json={"text": DEMO})
    code = r.json()["id"]
    assert (await client.get(f"/api/analyses/{code}/simulation")).status_code == 409
    await client.post(f"/api/analyses/{code}/run")
    r = await client.get(f"/api/analyses/{code}/simulation")
    assert r.status_code == 200, r.text
    sim = r.json()
    keys = [o["key"] for o in sim["options"]]
    assert keys == ["geo", "plan18", "k07", "r08"]
    tm = sim["metrics"]["time"]
    assert len(tm["curves"]) == 16
    base = tm["curves"][""]
    assert 0.30 <= _interp(base, tm["eval_x"]) <= 0.42
    assert 17.5 <= _inv(base, 0.8) <= 19.5
    assert 0.70 <= _interp(base, 18) <= 0.85
    cm = sim["metrics"]["cost"]
    assert 0.85 <= _interp(cm["curves"][""], cm["eval_x"]) <= 0.92
    assert 0.93 <= sim["metrics"]["comp"]["curves"][""][1][1] <= 0.98
    top3 = [r["risk"] for r in tm["drivers"][""]["rows"][:3]]
    assert "R04" in top3 and "R07" in top3
    # monotone: no option worsens T80 (same plan) or cost P90
    for k in ("geo", "k07", "r08", "geo+k07+r08"):
        assert _inv(tm["curves"][k], 0.8) <= _inv(base, 0.8) + 0.05
        assert _inv(cm["curves"][k], 0.9) <= _inv(cm["curves"][""], 0.9) + 0.01
    # deterministic
    sim2 = (await client.post(f"/api/analyses/{code}/simulate", json={})).json()
    assert sim2["metrics"]["time"]["curves"] == tm["curves"]

    r = await client.get(f"/api/analyses/{code}/allocation")
    assert r.status_code == 200, r.text
    al = r.json()
    assert {x["code"] for x in al["risks"]} >= {"R02", "R04", "R13"}
    assert all(x["chosen"] == x["recommended"] for x in al["risks"])
    assert al["balance"]["off_recommendation"] == 0
    r = await client.put(f"/api/analyses/{code}/allocation", json={"choices": {"R02": 2}})
    assert r.status_code == 200, r.text
    al2 = r.json()
    assert next(x for x in al2["risks"] if x["code"] == "R02")["chosen"] == 2
    assert al2["balance"]["off_recommendation"] == 1

    r = await client.get(f"/api/analyses/{code}/pack")
    assert r.status_code == 200, r.text


async def test_redpen_with_public_docs(client, db):
    ids = (await db.execute(text(
        "SELECT d.id FROM document d WHERE d.doc_type IN ('pfu', 'ppu') AND d.sensitivity = 'public' "
        "AND EXISTS (SELECT 1 FROM document_page p WHERE p.document_id = d.id AND length(p.text) > 500) "
        "ORDER BY (d.doc_type = 'pfu') DESC, d.id LIMIT 2"))).scalars().all()
    if not ids:
        pytest.skip("no public PFU/PPU with text")
    r = await client.post("/api/analyses", json={"text": DEMO, "document_ids": list(ids)})
    code = r.json()["id"]
    assert len(r.json()["documents"]) == len(ids)
    await client.post(f"/api/analyses/{code}/run")
    rep = (await client.get(f"/api/analyses/{code}")).json()
    assert "missing" in rep
    r = await client.get(f"/api/analyses/{code}/redpen/{ids[0]}")
    assert r.status_code == 200, r.text
    rp = r.json()
    assert rp["document"]["id"] == ids[0] and rp["pages"]
    assert rp["counts"]["found"] + rp["counts"]["missing"] == len(rp["notes"])
    for n in rp["notes"]:
        if n["kind"] == "found":
            assert n["quote"]["verified"] is True
    for p in rp["pages"]:
        for para in p["paragraphs"]:
            for m in para["marks"]:
                assert 0 <= m["start"] < m["end"] <= len(para["text"])
    r = await client.get(f"/api/analyses/{code}/redpen/999999999")
    assert r.status_code == 404


async def test_ai_integration_paths(client, db):
    import json as _json

    from riskminer.analysis.features import chip
    ids = (await db.execute(text(
        "SELECT d.id FROM document d WHERE d.doc_type = 'pfu' AND d.sensitivity = 'public' AND EXISTS "
        "(SELECT 1 FROM document_page p WHERE p.document_id = d.id AND length(p.text) > 500) ORDER BY d.id LIMIT 1"
    ))).scalars().all()
    if not ids:
        pytest.skip("no public PFU with text")
    r = await client.post("/api/analyses", json={"text": DEMO, "document_ids": ids})
    d = r.json()
    code = d["id"]
    assert d["ai_features"]["status"] == "queued"
    job = (await db.execute(text("SELECT kind, payload FROM job WHERE id = :i"),
                            {"i": d["ai_features"]["job_id"]})).first()
    assert job[0] == "analysis_features_ai" and job[1]["analysis_code"] == code
    aid = (await db.execute(text("SELECT id FROM analysis WHERE code = :c"), {"c": code})).scalar()
    # what L's job writes: an AI chip (beats the regex chip) and a Red Pen note
    c = chip("termin_mies", 16.0, source_label="PFU s. 2", source={"document_id": ids[0], "page": 2}, origin="AI",
             review_status="proposed", method="llm:extract_features")
    await db.execute(text("INSERT INTO analysis_item (analysis_id, version, section, key, title, body, origin, "
                          "review_status) VALUES (:a, 1, 'feature', 'termin_mies', 'termin', CAST(:b AS jsonb), 'AI', "
                          "'proposed')"), {"a": aid, "b": _json.dumps(c)})
    page = (await db.execute(text("SELECT page_no, text FROM document_page WHERE document_id = :d AND length(text) "
                                  "> 200 ORDER BY page_no LIMIT 1"), {"d": ids[0]})).first()
    await db.execute(text(
        "INSERT INTO analysis_item (analysis_id, version, section, key, title, body, origin, review_status, "
        "document_id, page_no, char_start, char_end, quote, verification) VALUES (:a, 1, 'redpen_note', 'redpen:x:1', "
        "'Test', CAST(:b AS jsonb), 'AI', 'proposed', :d, :p, 0, 40, :q, 'exact')"),
        {"a": aid, "b": _json.dumps({"title": "Uwaga testowa", "why": "x", "risk_codes": ["R02.1"]}),
         "d": ids[0], "p": page[0], "q": page[1][:40]})
    dr = (await client.get(f"/api/analyses/{code}/draft")).json()
    t = next(f for f in dr["features"] if f["key"] == "termin_mies")
    assert t["value"] == 16.0 and t["origin"] == "AI" and t["prov"]["role"] == "ai"
    r = await client.post(f"/api/analyses/{code}/run")
    assert r.json()["redpen_job_id"]
    rep = (await client.get(f"/api/analyses/{code}")).json()
    ai = [f for f in rep["flags"] if f["origin"] == "AI"]
    assert ai and ai[0]["review_status"] == "proposed" and rep["pending_review"] >= 1
    rp = (await client.get(f"/api/analyses/{code}/redpen/{ids[0]}")).json()
    assert rp["status"] == "queued" and any(n["origin"] == "AI" for n in rp["notes"])
    # owner approves the AI note
    item_id = ai[0]["item_id"]
    r = await client.post(f"/api/analyses/{code}/items/{item_id}/decision", json={"action": "approve"})
    assert r.status_code == 200 and r.json()["review_status"] == "approved"


async def test_confidential_doc_of_someone_else(client, db):
    did = (await db.execute(text(
        "INSERT INTO document (doc_type, filename, sensitivity, data) VALUES ('pfu', 'x.pdf', 'confidential', "
        "CAST('{\"owner_anon\": \"zzzzzzzz\"}' AS jsonb)) RETURNING id"))).scalar()
    r = await client.post("/api/analyses", json={"text": DEMO, "document_ids": [did]})
    assert r.status_code == 403 and r.json()["code"] == "document_forbidden"


async def test_analytics_read_endpoints(client):
    h = (await client.get("/api/analytics/headline")).json()
    assert 0.295 <= h["late_share"]["value"] <= 0.31 and h["sentence"].startswith("Od 2021 r.")
    t = (await client.get("/api/analytics/tenders")).json()["years"]
    y2024 = next(r for r in t if r["year"] == 2024)
    assert abs(y2024["cancelled_pct"] - 19.1) <= 1.5 and abs(y2024["single_offer_pct"] - 12.4) <= 1.5
    u = (await client.get("/api/analytics/unit-cost?subsector=SAN&budget=7000000&length_km=6")).json()
    assert 0.6 <= u["user_percentile"] <= 0.72
    b = (await client.get("/api/analytics/backtest")).json()
    assert 0.83 <= b["delay_days"]["inside_p10_p90"] <= 0.87


async def test_pack_files(client):
    r = await client.post("/api/analyses", json={"text": DEMO})
    code = r.json()["id"]
    await client.post(f"/api/analyses/{code}/run")
    await client.put(f"/api/analyses/{code}/allocation", json={"choices": {"R02": 1}})
    for fmt, ctype in (("json", "json"), ("csv", "csv"), ("docx", "officedocument")):
        r = await client.get(f"/api/analyses/{code}/pack.{fmt}")
        assert r.status_code == 200, (fmt, r.text[:300])
        assert ctype in r.headers["content-type"], fmt
        assert len(r.content) > 200


async def test_affected_analyses(client, expert, db):
    r = await client.post("/api/analyses", json={"text": DEMO})
    code = r.json()["id"]
    await client.post(f"/api/analyses/{code}/run")
    rep = (await client.get(f"/api/analyses/{code}")).json()
    case = next(c for c in rep["similar_cases"] if c.get("rm_id"))
    assert (await client.post("/api/analyses-affected", json={"rm_id": case["rm_id"]})).status_code == 401
    assert (await client.post("/api/analyses-affected", json={})).status_code == 401      # auth before body validation
    r = await expert.get(f"/api/analyses-affected?rm_id={case['rm_id']}")
    assert code in [x["code"] for x in r.json()["items"]]
    r = await expert.post("/api/analyses-affected", json={"rm_id": case["rm_id"], "reason": "nowy protokół konieczności",
                                                          "document_id": None})
    assert r.status_code == 200 and code in r.json()["marked"]
    rep = (await client.get(f"/api/analyses/{code}")).json()
    assert rep["stale_cases"][0]["case"] == case["rm_id"] and rep["stale_cases"][0]["reason"] == "nowy protokół konieczności"
    await client.post(f"/api/analyses/{code}/run")
    assert "stale_cases" not in (await client.get(f"/api/analyses/{code}")).json()


async def test_affected_juror_forbidden(db):
    import httpx

    from riskminer.api.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                 headers={"X-Requested-With": "ex-ante"}) as c:
        r = await c.post("/api/auth/demo-login", json={"persona": "juror"})
        if r.status_code != 200:
            pytest.skip("demo login unavailable")
        r = await c.post("/api/analyses-affected", json={"rm_id": "RM-2026-013"})
        assert r.status_code == 403


ROAD = "Przebudowa drogi gminnej 2,4 km z chodnikiem, 3,1 mln zł, 10 mies."


async def test_road_analysis_end_to_end(client, db, monkeypatch):
    """Second sector from a sector pack (catalogue/drogi): road description → road reference class (n >= 30)."""
    from riskminer.analysis import features as FE
    monkeypatch.setattr(FE, "feature", lambda name, default=False: name == "sector_roads" or default)
    r = await client.post("/api/analyses", json={"text": ROAD})
    d = r.json()
    chips = {c["key"]: c for c in d["features"]}
    assert chips["sektor"]["value"] == "drogi" and chips["podsektor"]["value"] == "DG"
    assert any(o["value"] == "DG" for o in chips["podsektor"]["options"])
    code = d["id"]
    assert (await client.post(f"/api/analyses/{code}/run")).status_code == 200
    rep = (await client.get(f"/api/analyses/{code}")).json()
    rc = rep["reference_class"]
    assert rc["sector"] == "drogi"
    assert rc["funnel"][0]["label"].startswith("wszystkie wykonane umowy drogowe")
    assert rc["funnel"][1]["label"] == "droga gminna lub ulica"
    assert rc["n"] >= 30 and not rc["widened"]
    assert rep["limitations"][0].startswith("Sektor „Drogi")
    q = {x["key"]: x for x in rep["questions"]}
    assert q["time"]["n"] >= 30 and q["budget"]["key_kind"] == "mln_per_km"
    assert all(c.get("rm_id") is None for c in rep["similar_cases"])        # pilots are wod-kan only
    sim = (await client.get(f"/api/analyses/{code}/simulation")).json()
    assert sim["n"] == rc["n"] and len(sim["metrics"]["time"]["curves"]) == 16
    assert (await client.get(f"/api/analyses/{code}/allocation")).status_code == 200
    # switching the sector re-reads the subsector for that sector
    r = await client.patch(f"/api/analyses/{code}/features", json={"values": {"sektor": "wod-kan"}})
    chips2 = {c["key"]: c for c in r.json()["features"]}
    assert chips2["sektor"]["value"] == "wod-kan" and chips2.get("podsektor", {}).get("value") != "DG"
    # wod-kan stays the default when the flag is off
    monkeypatch.setattr(FE, "feature", lambda name, default=False: default)
    d2 = (await client.post("/api/analyses", json={"text": ROAD})).json()
    assert "sektor" not in {c["key"] for c in d2["features"]}


async def test_confidential_doc_sovereign_down_rules_only(client, db):
    """Confidential PFU + sovereign model down: 1.1 and 1.3 answer with the rules-only banner (never an error); the
    owner may mark the document public, which re-queues the AI jobs. Confidential data never goes to the cloud."""
    import json as _json
    me = (await client.get("/api/auth/me")).json()
    anon = me.get("anon_id") or ""
    did = (await db.execute(text(
        "INSERT INTO document (doc_type, filename, sensitivity, data, pages) VALUES ('pfu', 'PFU_poufny.pdf', "
        "'confidential', CAST(:d AS jsonb), 1) RETURNING id"), {"d": _json.dumps({"owner_anon": anon[:8]})})).scalar()
    await db.execute(text("INSERT INTO document_page (document_id, page_no, text) VALUES (:d, 1, :t)"),
                     {"d": did, "t": "Projektowane rurociągi zlokalizowane będą częściowo na działkach prywatnych. "
                                     "Długość sieci ok. 6 km. Wynagrodzenie ryczałtowe."})
    r = await client.post("/api/analyses", json={"text": DEMO, "document_ids": [did]})
    assert r.status_code == 201, r.text
    code = r.json()["id"]
    assert r.json()["sensitivity"] == "confidential"
    await client.post(f"/api/analyses/{code}/run")
    sov = {"status": "sovereign_unavailable", "documents": {str(did): {"status": "sovereign_unavailable"}},
           "errors": [{"code": "sovereign_unavailable", "detail": "Model w Polsce jest niedostępny.",
                       "sovereign_unavailable": True}]}
    jid = (await db.execute(text("INSERT INTO job (kind, payload, status, result) VALUES ('analysis_redpen', "
                                 "'{}'::jsonb, 'done', CAST(:r AS jsonb)) RETURNING id"),
                            {"r": _json.dumps(sov)})).scalar()
    await db.execute(text("UPDATE analysis SET results = jsonb_set(jsonb_set(results, '{jobs,redpen}', to_jsonb(CAST(:j AS bigint))), "
                          "'{jobs,features}', to_jsonb(CAST(:j AS bigint))) WHERE code = :c"), {"j": jid, "c": code})
    rp = await client.get(f"/api/analyses/{code}/redpen/{did}")
    assert rp.status_code == 200, rp.text
    body = rp.json()
    assert body["status"] == "sovereign_unavailable"
    assert any(lim.startswith("Model suwerenny niedostępny") for lim in body["limitations"])
    assert any(n["kind"] == "found" and n["origin"] == "CALC" for n in body["notes"])     # rule notes still there
    dr = (await client.get(f"/api/analyses/{code}/draft")).json()
    assert dr["ai_features"]["sovereign_unavailable"] is True and dr["confidential_documents"] == [did]
    r = await client.post(f"/api/analyses/{code}/documents/{did}/make-public")
    assert r.status_code == 200 and r.json()["jobs"]["features"] and r.json()["jobs"]["redpen"]
    assert (await db.execute(text("SELECT sensitivity FROM document WHERE id = :d"), {"d": did})).scalar() == "public"
    assert (await client.get(f"/api/analyses/{code}/draft")).json()["sensitivity"] == "public"
