"""Projects: list metrics, stats, card, graph, documents, history, provenance (api_contract §2.4, §8.4, §8.6). Read-only on the main DB."""
import pytest
from sqlalchemy import text

ROLES = {"source", "calc", "case", "ai"}
# single-record calculations over the project's own contracts (n = that project's contracts, refs to its notices)
SINGLE_CASE = {"count", "completed_on - signed_on", "actual - planned", "project_contracts", "paid/contract - 1"}


def walk_nums(o, path="$"):
    """Yield (path, num) for every Num-like dict: has numeric-or-null `value`, `display`, `unit` and `prov`."""
    if isinstance(o, dict):
        if {"value", "display", "unit", "prov"} <= set(o):
            yield path, o
        for k, v in o.items():
            yield from walk_nums(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk_nums(v, f"{path}[{i}]")


def check_prov(payload):
    n_checked = 0
    for path, n in walk_nums(payload):
        p = n["prov"]
        assert p["role"] in ROLES, path
        assert p["review_status"] in {"auto", "proposed", "approved", "edited", "rejected"}, path
        if p["role"] == "calc":
            assert isinstance(p.get("n"), int) and p.get("method"), path
            if p["n"] < 10 and p["method"] not in SINGLE_CASE:
                assert n["value"] is None and p.get("insufficient"), path
        if p["role"] == "source":
            assert p.get("refs"), path
        if p["role"] == "ai":
            assert p.get("llm") is not None, path
        n_checked += 1
    return n_checked


async def test_list_has_metrics_and_filters(client):
    r = (await client.get("/api/projects", params={"pilot": True, "limit": 50})).json()
    assert r["total"] == 22 and r["facets"]["all"] == 22
    by = {p["rm_id"]: p for p in r["items"]}
    st = by["RM-2026-003"]["metrics"]
    assert st["delay_days"]["value"] == 277 and st["delay_days"]["display"] == "+277 dni"
    assert st["cost_dev_pct"]["display"] == "+40,3%"
    assert st["contract_value"] == {"amount": "2131590.00", "currency": "PLN", "vat_basis": "gross"}
    late = (await client.get("/api/projects", params={"late": True, "limit": 50})).json()
    assert late["total"] == 20
    assert all(p["metrics"]["delay_days"]["value"] > 0 for p in late["items"])
    srt = (await client.get("/api/projects", params={"sort": "-delay_days", "limit": 3})).json()["items"]
    assert [p["rm_id"] for p in srt][0] == "RM-2026-019"  # +395 days
    two = (await client.get("/api/projects", params={"rm_ids": "RM-2026-003,RM-2026-019"})).json()
    assert {p["rm_id"] for p in two["items"]} == {"RM-2026-003", "RM-2026-019"}
    assert check_prov(r["items"]) > 20


async def test_public_hides_review_counts(client, expert):
    anon = (await client.get("/api/projects", params={"to_review": True})).json()
    assert anon["total"] == 0 and anon["facets"]["review"] is None
    ex = (await expert.get("/api/projects", params={"to_review": True})).json()
    assert ex["total"] >= 1


async def test_stats_27_contracts(client):
    s = (await client.get("/api/projects/stats")).json()
    assert s["late"]["value"]["display"] == "20 z 27" and s["n_contracts"] == 27
    assert s["overpaid"]["value"]["prov"]["n"] == 27
    check_prov(s)


async def test_card_golden_steklin(client):
    c = (await client.get("/api/projects/RM-2026-003/card")).json()
    assert c["summary"]["sentence"] == "Skończono 277 dni po terminie i zapłacono o 40,3% więcej niż w umowie."
    time_, cost = c["plan_vs_actual"]
    assert time_["planned"]["value"] == 396 and time_["actual"]["value"] == 673 and time_["delta"]["display"] == "+277 dni"
    assert cost["planned_money"]["amount"] == "2131590.00" and cost["actual_money"]["amount"] == "2990000.00"
    assert cost["delta"]["display"] == "+40,3%"
    assert c["auto_card"] is False
    assert any(s["title"].startswith("Dopłata") for s in c["steps"])
    assert {i["k"] for i in c["identifiers"]} >= {"Rekord", "BZP", "OCID", "NIP"}
    check_prov(c)
    assert "—" not in str(c) and "·" not in str(c)


async def test_card_public_hides_unverified_ai(client, expert, db):
    from sqlalchemy import text
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id='RM-2026-003'"))).scalar()
    base = (await client.get("/api/projects/RM-2026-003/card")).json()["unverified_hidden"]  # AI runs may add proposals meanwhile
    await db.execute(text("""INSERT INTO risk_event (project_id, event_type, catalogue_code, summary, origin, review_status)
                             VALUES (:p, 'EV_T', 'R04', 'Testowy wniosek AI', 'AI', 'proposed')"""), {"p": pid})
    anon = (await client.get("/api/projects/RM-2026-003/card")).json()
    assert all(e["title"] != "Testowy wniosek AI" for e in anon["events"]) and anon["unverified_hidden"] == base + 1
    full = (await expert.get("/api/projects/RM-2026-003/card")).json()
    assert any(e["title"] == "Testowy wniosek AI" for e in full["events"])
    g_anon = (await client.get("/api/projects/RM-2026-003/graph")).json()
    assert "concl:R04" not in {n["id"] for n in g_anon["nodes"]}
    g = (await expert.get("/api/projects/RM-2026-003/graph")).json()
    assert "concl:R04" in {n["id"] for n in g["nodes"]}


async def test_card_unknown_project_404(client):
    assert (await client.get("/api/projects/RM-9999-999/card")).status_code == 404


async def test_graph_structure(client):
    g = (await client.get("/api/projects/RM-2026-003/graph")).json()
    ids = {n["id"] for n in g["nodes"]}
    assert [c["key"] for c in g["columns"]] == ["sources", "facts", "conclusions"]
    assert all(l["source"] in ids and l["target"] in ids and l["value"] > 0 and l["fact_ids"] for l in g["links"])
    cols = {n["id"]: n["column"] for n in g["nodes"]}
    assert all(cols[l["source"]] + 1 == cols[l["target"]] for l in g["links"])
    assert g["summary"]["facts"] == sum(g["summary"]["by_role"].values())
    assert set(g["details"]) <= ids


async def test_documents_view_and_facts(client):
    d = (await client.get("/api/projects/RM-2026-003/documents")).json()
    assert d["expected_total"] >= 4 and d["public"] and d["have"] <= d["expected_total"]
    assert all(x["evidence_state"] in ("POTWIERDZONO", "BRAK_W_PACZCE") for x in d["expected"])
    oid = next(p["object_id"] for p in d["public"] if p["kind"] == "notice")
    f = await client.get(f"/api/notices/{oid}/facts")
    assert f.status_code == 200 and "meta" in f.json() and f.json()["meta"]["url"]


async def test_history_login_only(client, expert, db):
    assert (await client.get("/api/projects/RM-2026-022/history")).status_code == 401
    h = (await expert.get("/api/projects/RM-2026-022/history")).json()
    assert h["record_version"].startswith("v") and isinstance(h["items"], list)


async def test_similar_has_outcomes_as_case(client):
    s = (await client.get("/api/projects/RM-2026-003/similar", params={"k": 3})).json()
    assert 1 <= len(s) <= 3
    assert s[0]["outcome"]["delay_days"]["prov"]["role"] == "case"
    assert abs(sum(c["value"] for c in s[0]["contributions"]) - s[0]["score"]["value"]) < 0.02
    # B3 rows: buyer, year, annex count and a link to an existing card
    assert all({"buyer_name", "year", "changes_count"} <= set(x) for x in s)
    assert all(x["href"].startswith("/projekty/") for x in s)
    assert any(x["buyer_name"] for x in s) and any(x["year"] for x in s)


async def test_dashboard_and_headline(client, expert):
    assert (await client.get("/api/dashboard")).status_code == 401
    d = (await expert.get("/api/dashboard")).json()
    assert {t["key"] for t in d["tiles"]} == {"review_open", "monitoring_new", "my_analyses"}
    check_prov(d)
    h = (await client.get("/api/national/headline")).json()
    assert 11000 < h["completed"]["value"] < 12500 and 0.25 < h["late_share"]["value"] < 0.35
    check_prov(h)
    c = (await expert.get("/api/nav/counts")).json()
    assert set(c) == {"review_open", "monitoring_new"}


async def _ocids(db):
    sig = (await db.execute(text("SELECT ocid FROM v_monitor_signal WHERE n_change_notices > 0 ORDER BY days_overdue DESC LIMIT 1"))).scalar()
    done = (await db.execute(text("SELECT ocid FROM rc_contract WHERE relevance='core' AND changes_count > 1 AND delay_days > 60 AND ocid NOT IN "
                                  "(SELECT pr.ocid FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id) LIMIT 1"))).scalar()
    return sig, done


async def test_ocid_card_from_radar_signal_and_completed_contract(client, db):
    sig, done = await _ocids(db)
    assert sig and done
    for ocid in (sig, done):
        r = await client.get(f"/api/projects/{ocid}/card")
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["kind"] == "bzp_procedure" and c["auto_card"] is True and c["rm_id"] == ocid and c["title"]
        assert {"summary", "plan_vs_actual", "steps", "events", "gaps", "doc_counts", "identifiers", "similar", "metrics", "buyer"} <= set(c)
        assert any(i["k"] == "OCID" and i["v"] == ocid for i in c["identifiers"])
        assert c["steps"], "contracts, changes and performance notices form the course"
        check_prov(c)
    c_sig = (await client.get(f"/api/projects/{sig}/card")).json()
    assert "Termin z umowy minął" in c_sig["summary"]["sentence"] or "nie ma ogłoszenia o wykonaniu" in c_sig["summary"]["sentence"]
    c_done = (await client.get(f"/api/projects/{done}/card")).json()
    assert "po terminie" in c_done["summary"]["sentence"]
    assert c_done["plan_vs_actual"][0]["delta"]["value"] > 60


async def test_ocid_graph_documents_similar_and_404(client, db):
    sig, done = await _ocids(db)
    g = (await client.get(f"/api/projects/{done}/graph")).json()
    ids = {n["id"] for n in g["nodes"]}
    assert g["kind"] == "bzp_procedure" and "src:xlsx" not in ids and "concl:link" not in ids and "concl:delay" in ids
    assert all(l["source"] in ids and l["target"] in ids for l in g["links"])
    assert (await client.get(f"/api/projects/{sig}/documents")).status_code == 200
    s = (await client.get(f"/api/projects/{done}/similar", params={"k": 3})).json()
    assert len(s) >= 1 and all(x["ocid"] != done for x in s)
    assert (await client.get("/api/projects/ocds-000000-nope/card")).status_code == 404
    assert (await client.get("/api/projects/ocds-000000-nope/graph")).status_code == 404


async def test_ocid_card_public_hides_unverified_ai(client, expert, db):
    _, done = await _ocids(db)
    pid = (await db.execute(text("SELECT id FROM procedure WHERE ocid = :o"), {"o": done})).scalar()
    base = (await client.get(f"/api/projects/{done}/card")).json()["unverified_hidden"]
    await db.execute(text("""INSERT INTO risk_event (procedure_id, event_type, catalogue_code, summary, origin, review_status)
                             VALUES (:p, 'EV_CHANGE_CAUSE_AI', 'R04', 'Testowy wniosek AI (OCID)', 'AI', 'proposed')"""), {"p": pid})
    anon = (await client.get(f"/api/projects/{done}/card")).json()
    assert all(e["title"] != "Testowy wniosek AI (OCID)" for e in anon["events"]) and anon["unverified_hidden"] == base + 1
    full = (await expert.get(f"/api/projects/{done}/card")).json()
    assert any(e["title"] == "Testowy wniosek AI (OCID)" for e in full["events"])


async def test_history_includes_derived_pipeline_entries(expert):
    h = (await expert.get("/api/projects/RM-2026-003/history")).json()
    labels = [i["action_label"] for i in h["items"]]
    assert "zaimportował rekord z zestawu organizatora" in labels and "dopasował postępowanie BZP do projektu" in labels
    assert h["record_version"] == f"v{len(h['items'])}" and h["items"][0]["version"] == h["record_version"]
    assert all(i["can_restore"] is False for i in h["items"] if i["audit_id"] < 0)
    only_system = (await expert.get("/api/projects/RM-2026-003/history", params={"actor_kind": "system"})).json()["items"]
    assert only_system and all(i["actor_kind"] == "system" for i in only_system)
    cmp_ = (await expert.get("/api/projects/RM-2026-003/history/compare", params={"from": "v1", "to": h["record_version"]})).json()
    assert cmp_["changes"] and all(c["before"] for c in cmp_["changes"])


async def test_documents_summary_polish_plural(client):
    s = (await client.get("/api/projects/RM-2026-003/documents")).json()["summary"]
    assert "dokumentów z budowy" not in s or "Brakuje 1 dokumentów" not in s
    assert "1 dokumentu" in s or "dokumentów" in s or "komplet" in s


async def test_headline_empty_state_never_500(client, monkeypatch):
    import riskminer.analytics.headline as H

    def boom(_cb):
        raise ZeroDivisionError("empty case base")
    monkeypatch.setattr(H, "headline", boom)
    r = await client.get("/api/national/headline")
    assert r.status_code == 200
    j = r.json()
    assert j["empty"] is True and j["sentence"] == "" and j["completed"]["value"] is None and j["completed"]["prov"]["insufficient"] is True
    monkeypatch.setattr(H, "headline", lambda _cb: {"completed": {"value": 0}, "sentence": "x"})
    assert (await client.get("/api/national/headline")).json()["empty"] is True
    ok = await client.get("/api/national/headline", params={"sector": "wod-kan"})
    assert ok.status_code == 200
