"""Per-flag smoke (S0): for every feature flag switched on in config, the calls its screen makes answer with real data.
A flag goes true only after (1) the screen is wired to real routes, (2) the frontend owner confirms, (3) this smoke passes.
Transactional (rolled back); writes run as the expert persona. Table: side notes s0-flags.md."""
from __future__ import annotations

import pytest

from riskminer.config import app_config

pytestmark = pytest.mark.fulldb


def _ok(r, what: str):
    assert r.status_code == 200, f"{what}: {r.status_code} {r.text[:300]}"
    assert r.headers.get("x-fixture") != "true", f"{what} still serves a fixture"
    return r.json()


async def test_case_graph(client):
    for rm in ("RM-2026-003", "RM-2026-017"):
        g = _ok(await client.get(f"/api/projects/{rm}/graph"), f"graph {rm}")
        assert g["nodes"] and g["links"] and {c["key"] for c in g["columns"]} == {"sources", "facts", "conclusions"}
        ids = {n["id"] for n in g["nodes"]}
        assert all(link["source"] in ids and link["target"] in ids for link in g["links"]), "dangling Sankey link"


async def test_radar(client):
    woj = _ok(await client.get("/api/monitoring/regions", params={"level": "woj"}), "regions woj")
    assert len(woj["regions"]) == 16
    for r in woj["regions"]:
        v = r["value"]
        assert v["prov"]["role"] == "calc" and isinstance(v["prov"]["n"], int)
    pw = _ok(await client.get("/api/monitoring/regions", params={"level": "pow", "parent": "12"}), "regions pow 12")
    assert pw["regions"] and all(r["terc"].startswith("12") for r in pw["regions"])
    sig = _ok(await client.get("/api/monitoring/signals", params={"limit": 500, "geo": True}), "signals")
    assert sig["total"] > 0 and sig["items"]
    s0 = sig["items"][0]
    assert s0["days_overdue"]["prov"]["role"] == "calc"
    geo = await client.get("/api/geo/woj.geojson")
    assert geo.status_code == 200 and geo.json()["features"]


async def test_radar_drill(client, expert):
    reg = _ok(await client.get("/api/monitoring/regions/12"), "region 12")
    assert reg["kpis"] and reg["breadcrumb"][-1]["terc"] == "12"
    sig = _ok(await client.get("/api/monitoring/signals", params={"terc": "12", "level": "woj", "limit": 5}), "signals 12")
    cid = sig["items"][0]["contract_id"]
    detail = _ok(await client.get(f"/api/monitoring/contracts/{cid}"), "contract detail")
    assert detail["signal"]["contract_id"] == cid
    csv = await client.get("/api/export/signals.csv", params={"terc": "12", "level": "woj", "sep": "semicolon"})
    assert csv.status_code == 200 and ";" in csv.text.splitlines()[0]
    # the two login-gated buttons on the contract panel ("Obserwuj", "Zgłoś jako przypadek"), exactly as the frontend sends them
    assert (await client.post("/api/monitoring/watches", json={"contract_id": cid})).status_code == 401
    w = await expert.post("/api/monitoring/watches", json={"contract_id": cid})
    assert w.status_code in (200, 201), w.text
    wid = w.json()["id"]
    d = await expert.delete(f"/api/monitoring/watches/{wid}")
    assert d.status_code == 200 and d.json()["active"] is False
    rc = await expert.post(f"/api/monitoring/contracts/{cid}/report-case", json={"note": ""})
    assert rc.status_code in (200, 201), rc.text
    assert rc.json()["review_item_id"]


async def _open_item(db, kind: str) -> int | None:
    from sqlalchemy import text
    return (await db.execute(text("SELECT id FROM review_item WHERE status = 'open' AND kind = :k ORDER BY id LIMIT 1"),
                             {"k": kind})).scalar()


async def test_review_queue(expert, db):
    """Exactly what features/review/api.ts sends: counts, list, card, decision {option, action, gold, value|reason}, undo, skip."""
    counts = _ok(await expert.get("/api/review-items/counts"), "counts")
    assert counts["total"] > 0
    lst = _ok(await expert.get("/api/review-items", params={"limit": 20}), "list")
    assert lst["items"]
    for kind in ("discrepancy", "event", "link"):
        iid = await _open_item(db, kind)
        if iid is None:
            continue
        card = _ok(await expert.get(f"/api/review-items/{iid}"), f"card {kind}")
        assert card["options"], f"{kind} card without options"
        opt = next((o for o in card["options"] if not o.get("needs_input")), card["options"][0])
        body = {"option": opt["key"], "action": opt["action"], "gold": False}
        if opt.get("needs_input") == "value":
            body["value"] = "R04 decyzja organu"
        elif opt.get("needs_input") == "reason":
            body["reason"] = "test"
        dec = await expert.post(f"/api/review-items/{iid}/decision", json=body)
        assert dec.status_code == 200, f"decision {kind}: {dec.status_code} {dec.text[:300]}"
        und = await expert.post(f"/api/reviews/{dec.json()['review_id']}/undo")
        assert und.status_code == 200, f"undo {kind}: {und.text[:300]}"
    iid = await _open_item(db, "discrepancy")
    sk = await expert.post(f"/api/review-items/{iid}/skip")
    assert sk.status_code == 200


async def test_review_edit_with_free_text_value(expert, db):
    """The 'Inne ryzyko z katalogu' option sends `value` as a plain string (frontend review/api.ts)."""
    iid = await _open_item(db, "event")
    if iid is None:
        pytest.skip("no open event item")
    card = _ok(await expert.get(f"/api/review-items/{iid}"), "event card")
    opt = next((o for o in card["options"] if o.get("needs_input") == "value"), None)
    if opt is None:
        pytest.skip("event card has no free-text option")
    dec = await expert.post(f"/api/review-items/{iid}/decision",
                            json={"option": opt["key"], "action": opt["action"], "gold": False, "value": "R04 decyzja organu"})
    assert dec.status_code in (200, 422), dec.text
    if dec.status_code == 422:
        assert dec.json().get("code"), "422 must carry a machine code the UI can show"


async def test_catalogue_edit(expert, db):
    """Exactly what features/catalogue/api.ts sends: view, PATCH risk {patch, comment}, PUT weights (fractions), proposal decision."""
    view = _ok(await expert.get("/api/catalogue/view", params={"sector": "wod-kan"}), "catalogue view")
    assert view["risks"]
    code = view["risks"][0]["code"]
    p = await expert.patch(f"/api/catalogue/risk/{code}", json={"patch": {"description": "test opisu (smoke)"}, "comment": ""})
    assert p.status_code == 200, p.text
    assert p.json()["catalogue_version"]
    w = {x["feature"]: x["w"] for x in view["weights"]}
    r = await expert.put("/api/catalogue/similarity/weights", json={"weights": w, "comment": "zmiana wag w Katalogu"})
    assert r.status_code == 200, r.text
    if view.get("proposals"):
        pid = view["proposals"][0]["id"]
        d = await expert.post(f"/api/catalogue/proposals/{pid}/decision", json={"action": "reject", "reason": "smoke"})
        assert d.status_code == 200, d.text
    ver = _ok(await expert.get("/api/catalogue/versions"), "versions")
    assert ver


async def _new_analysis(c, monkeypatch) -> str:
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")
    r = await c.post("/api/analyses", json={"input_text": "[e2e] Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj i "
                                                         "wybuduj, budżet 7 mln zł brutto, termin 14 miesięcy, FEnIKS.",
                                            "sensitivity": "public"})
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    run = await c.post(f"/api/analyses/{code}/run", json={})
    assert run.status_code == 200, run.text
    return code


async def test_monte_carlo(client, monkeypatch):
    code = await _new_analysis(client, monkeypatch)
    sim = _ok(await client.get(f"/api/analyses/{code}/simulation"), "simulation")
    assert sim, "empty simulation"
    post = await client.post(f"/api/analyses/{code}/simulate", json={"metric": "time", "toggles": [], "draws": 2000})
    assert post.status_code == 200, post.text


async def test_allocation_and_pack(client, monkeypatch):
    """Exactly what features/allocation sends: GET, PUT {choices}, then pack.{json,csv,docx,pdf} downloads."""
    code = await _new_analysis(client, monkeypatch)
    alloc = _ok(await client.get(f"/api/analyses/{code}/allocation"), "allocation")
    risks = alloc.get("risks") or []
    if risks:
        choices = {r["code"]: (r.get("recommended") or "buyer") for r in risks}
        put = await client.put(f"/api/analyses/{code}/allocation", json={"choices": choices})
        assert put.status_code == 200, put.text
    _ok(await client.get(f"/api/analyses/{code}/pack"), "pack manifest")
    for fmt, ctype in (("json", "json"), ("csv", "csv"), ("docx", "officedocument"), ("pdf", "pdf")):
        f = await client.get(f"/api/analyses/{code}/pack.{fmt}")
        assert f.status_code == 200, f"pack.{fmt}: {f.status_code} {f.text[:200]}"
        assert ctype in f.headers.get("content-type", ""), f"pack.{fmt} content-type {f.headers.get('content-type')}"
        assert len(f.content) > 200
    assert (await client.get(f"/api/analyses/{code}/pack.pdf")).content[:4] == b"%PDF"


async def test_learning_loop(expert, db):
    """A gold decision on an AI event item writes gold_example + a rescore job whose kind the worker knows."""
    from sqlalchemy import text

    from riskminer.jobs import worker
    iid = (await db.execute(text("""SELECT r.id FROM review_item r JOIN risk_event e ON e.id = r.target_id AND r.target_table = 'risk_event'
                                    WHERE r.status = 'open' AND r.kind = 'event' AND e.origin = 'AI' ORDER BY r.id LIMIT 1"""))).scalar()
    if iid is None:
        pytest.skip("no open AI event item")
    card = _ok(await expert.get(f"/api/review-items/{iid}"), "event card")
    opt = next((o for o in card["options"] if o.get("action") == "approve" and not o.get("needs_input")), None)
    if opt is None:
        pytest.skip("no approve option")
    before = (await db.execute(text("SELECT coalesce(max(id), 0) FROM job"))).scalar()
    dec = await expert.post(f"/api/review-items/{iid}/decision", json={"option": opt["key"], "action": "approve", "gold": True})
    assert dec.status_code == 200, dec.text
    g = dec.json().get("gold")
    assert g and g.get("job_id"), f"gold decision returned no job: {dec.json()}"
    kinds = [k for (k,) in (await db.execute(text("SELECT kind FROM job WHERE id > :b"), {"b": before})).all()]
    assert kinds, "no job row inserted"
    assert all(worker.known_kind(k) for k in kinds), f"worker does not know job kinds {kinds}"
    assert (await db.execute(text("SELECT count(*) FROM gold_example WHERE review_id = :r"), {"r": dec.json()["review_id"]})).scalar() >= 1


async def test_project_docs(client, expert, db, tmp_path, monkeypatch):
    """features/documents: GET /projects/{rm_id}/documents, notice facts, project-bound upload (expert)."""
    from riskminer.documents import upload as U
    from riskminer.jobs import worker
    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "known_kind", lambda kind: False)
    docs = _ok(await client.get("/api/projects/RM-2026-003/documents"), "project documents")
    assert "expected" in docs and "public" in docs
    if docs["public"]:
        oid = docs["public"][0].get("object_id")
        if oid:
            _ok(await client.get(f"/api/notices/{oid}/facts"), "notice facts")
    from test_documents_upload import PFU
    up = await expert.post("/api/documents/upload", files={"file": ("PFU_test.pdf", PFU, "application/pdf")},
                           data={"project_rm_id": "RM-2026-003", "sensitivity": "public"})
    assert up.status_code == 201, up.text
    assert (await client.post("/api/documents/upload", files={"file": ("PFU_test.pdf", PFU, "application/pdf")},
                              data={"project_rm_id": "RM-2026-003"})).status_code == 401


async def test_project_history(expert, client):
    """features/audit: project history + compare, global audit + CSV export (login), anonymous refused."""
    h = _ok(await expert.get("/api/projects/RM-2026-003/history"), "history")
    assert "items" in h
    vers = [i.get("version") for i in h["items"] if i.get("version")]
    if len(vers) >= 2:
        _ok(await expert.get("/api/projects/RM-2026-003/history/compare", params={"from": vers[-1], "to": vers[0]}), "compare")
    a = _ok(await expert.get("/api/audit", params={"category": "expert", "limit": 5}), "audit")
    assert "items" in a
    csv = await expert.get("/api/export/audit.csv", params={"category": "expert", "sep": "semicolon"})
    assert csv.status_code == 200
    assert (await client.get("/api/projects/RM-2026-003/history")).status_code == 401
    assert (await client.get("/api/audit")).status_code == 401


async def test_import_agent(expert, client):
    """The full agent flow (upload, inspect, propose-mapping, answers, test-run, approve, run) is covered by D's
    tests/api/test_imports.py::test_import_agent_flow; here only what /zrodla loads first, plus the login gate."""
    _ok(await expert.get("/api/importers"), "importers")
    assert (await client.get("/api/importers")).status_code == 401
    assert (await expert.get("/api/imports/IMP-2026-9999")).status_code == 404


async def _analysis_with_doc(client, monkeypatch, tmp_path) -> tuple[str, int]:
    from riskminer.documents import upload as U
    from riskminer.jobs import worker

    async def fake_enqueue(kind, payload=None, priority=100, created_by="cli"):
        return {"id": -1, "kind": kind}

    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "enqueue", fake_enqueue)
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")
    from test_documents_upload import PFU
    up = await client.post("/api/documents/upload", files={"file": ("PFU_kanalizacja.pdf", PFU, "application/pdf")},
                           data={"sensitivity": "public"})
    assert up.status_code == 201, up.text
    doc = up.json()["document_id"]
    r = await client.post("/api/analyses", json={"input_text": "[e2e] Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj "
                                                               "i wybuduj, budżet 7 mln zł brutto, termin 14 miesięcy, FEnIKS.",
                                                 "document_ids": [doc], "sensitivity": "public"})
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert (await client.post(f"/api/analyses/{code}/run", json={})).status_code == 200
    return code, doc


async def test_report_unit_cost_backtest_red_pen(client, monkeypatch, tmp_path):
    """features/report + features/redpen: GET /analyses/{code} (budget question = unit_cost, backtest_note), redpen for the
    attached document, POST /pack/clauses {code}."""
    code, doc = await _analysis_with_doc(client, monkeypatch, tmp_path)
    rep = _ok(await client.get(f"/api/analyses/{code}"), "report")
    keys = {q["key"] for q in rep.get("questions", [])}
    assert "budget" in keys or "unit_cost" in keys, f"no budget/unit-cost question: {keys}"
    assert "backtest_note" in rep, "report has no backtest_note field"
    rp = _ok(await client.get(f"/api/analyses/{code}/redpen/{doc}"), "redpen")
    assert rp["document"]["id"] == doc and rp.get("pages") and rp.get("status")
    clause = (rep.get("clauses") or [{}])[0].get("code")
    if clause:
        c = await client.post(f"/api/analyses/{code}/pack/clauses", json={"code": clause})
        assert c.status_code == 200, c.text


async def test_dashboard(expert, client):
    d = _ok(await expert.get("/api/dashboard"), "dashboard")
    assert d["tiles"] and all(t["value"]["prov"]["role"] == "calc" for t in d["tiles"])
    h = _ok(await client.get("/api/analytics/headline"), "analytics headline")
    assert h
    assert (await client.get("/api/dashboard")).status_code == 401


async def test_ask_memory(client, monkeypatch, tmp_path):
    """/zapytaj + chats: suggestion chip (template SQL, no LLM) -> Answer, save as Q-record, list, get; project and analysis
    chat with the LLM faked."""
    sug = _ok(await client.get("/api/ask/suggestions", params={"context": "zapytaj"}), "suggestions")
    assert sug
    a = await client.post("/api/ask", json={"question": sug[0]["label"]})
    assert a.status_code == 200, a.text
    ans = a.json()
    assert ans["role"] in ("calc", "ai", "no_data") and ans["text"]
    if ans["role"] == "calc":
        assert ans["n"] and ans["method"]["kind"] in ("sql", "template")
    sv = await client.post("/api/questions", json={"question_id": ans["id"], "title": "[e2e] smoke"})
    assert sv.status_code in (200, 201), sv.text
    code = sv.json()["code"]
    _ok(await client.get("/api/questions"), "questions")
    _ok(await client.get(f"/api/questions/{code}"), "question")
    rr = await client.post(f"/api/questions/{code}/rerun")
    assert rr.status_code == 200, f"rerun: {rr.status_code} {rr.text[:300]}"
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")
    pc = await client.post("/api/projects/RM-2026-003/chat", json={"message": "Dlaczego ten projekt się opóźnił?"})
    assert pc.status_code in (200, 503), pc.text
    if pc.status_code == 200:
        assert pc.json()["text"]
    code_an, _doc = await _analysis_with_doc(client, monkeypatch, tmp_path)
    ac = await client.post(f"/api/analyses/{code_an}/chat", json={"message": "Co jeśli przetarg ogłosimy 2 miesiące później?",
                                                                     "context": "simulation"})
    assert ac.status_code in (200, 503), ac.text


async def test_settings_view(expert):
    """Read-only Ustawienia: providers with data_location, routing per task (brief: where data is processed)."""
    st = _ok(await expert.get("/api/settings/llm"), "settings")
    assert st["providers"] and all(p.get("data_location") for p in st["providers"])
    assert st["tasks"] and any(t["sensitivity"] == "confidential" for t in st["tasks"])
    assert all(t.get("sovereign") for t in st["tasks"] if t["sensitivity"] == "confidential" and t.get("provider")), \
        "a confidential route points at a non-PL provider"


async def test_monitoring_replay(client):
    """Wehikuł czasu: as_of replays regions (open + done) and signals; an earlier date sees fewer completed contracts."""
    now = _ok(await client.get("/api/monitoring/regions", params={"level": "woj", "mode": "done"}), "regions now")
    past = _ok(await client.get("/api/monitoring/regions", params={"level": "woj", "mode": "done", "as_of": "2024-06-30"}), "regions past")
    assert past["total"]["n"] < now["total"]["n"], "as_of does not change the completed set"
    _ok(await client.get("/api/monitoring/regions", params={"level": "woj", "mode": "open", "as_of": "2024-06-30"}), "open past")
    s_now = _ok(await client.get("/api/monitoring/signals", params={"limit": 1}), "signals now")["total"]
    s_past = _ok(await client.get("/api/monitoring/signals", params={"limit": 1, "as_of": "2024-06-30"}), "signals past")["total"]
    assert s_past != s_now, "as_of does not change the signal set"
    assert (await client.get("/api/monitoring/signals", params={"as_of": "nie-data"})).status_code == 422


def test_new_document_reanalysis():
    """The real check is G6 (tests/api/test_new_documents.py, organizer files end to end); here: every pipeline step resolves."""
    from riskminer.documents.pipeline import missing_steps
    from riskminer.jobs import worker
    assert not missing_steps()
    assert all(worker.known_kind(k) for k in ("document_ocr", "document_extract", "document_link"))


def test_sector_roads():
    """The real check is A's tests/api/test_analyses.py::test_road_analysis_end_to_end (golden funnel 30 335 → 893, 73%) plus
    S0's headless run through 1.1; here: the drogi sector pack is present."""
    from riskminer.config import REPO_ROOT
    assert (REPO_ROOT / "catalogue" / "drogi" / "lexicon.yaml").exists()


def test_flags_on_have_a_smoke():
    """Every flag that is on must have a test above (add one before flipping a new flag)."""
    covered = {"case_graph", "radar", "radar_drill", "review_queue", "catalogue_edit", "monte_carlo", "allocation", "pack_export", "learning_loop", "project_docs", "project_history", "import_agent", "red_pen", "unit_cost", "backtest", "dashboard", "ask_memory", "settings_view", "monitoring_replay", "new_document_reanalysis", "sector_roads"}  # replay smoke = backend only
    feats = app_config().get("features") or {}
    ui_flags = {"red_pen", "unit_cost", "backtest", "case_graph", "monte_carlo", "radar", "learning_loop", "sovereign_switch",
                "sector_pack_wizard", "ask_memory", "allocation", "pack_export", "radar_drill", "monitoring_replay", "review_queue",
                "catalogue_edit", "import_agent", "project_docs", "project_history", "jelly", "new_document_reanalysis", "dashboard", "settings_view", "sector_roads"}
    missing = sorted(f for f in ui_flags if feats.get(f) and f not in covered)
    assert not missing, f"flags on without a smoke test here: {missing}"
