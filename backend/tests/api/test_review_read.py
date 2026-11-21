"""Review queue read side: card context (subject, source, proposal), type and strength on list rows, facets that add up.
Transactional (rolled back); no decision is written."""
from sqlalchemy import text


async def _scalar(db, sql, **p):
    return (await db.execute(text(sql), p)).scalar()


async def _doc_signal(db, *, conf=0.8, verification="exact", rm="RM-2026-003"):
    pid = await _scalar(db, "SELECT id FROM project WHERE rm_id = :r", r=rm)
    did = await _scalar(db, """INSERT INTO document (project_id, doc_type, title, filename, pages, key)
                               VALUES (:p, 'swz', 'SWZ testowa', 'swz.pdf', 12, 'test:doc:' || gen_random_uuid()) RETURNING id""", p=pid)
    eid = await _scalar(db, """INSERT INTO risk_event (project_id, event_type, catalogue_code, summary, cause, origin, review_status)
                               VALUES (:p, 'EV_DOC_SIGNAL', 'R02', 'Inspekcja istniejącej sieci po stronie wykonawcy',
                                       'Zakres napraw nieznany przed umową.', 'AI', 'proposed') RETURNING id""", p=pid)
    await db.execute(text("""INSERT INTO evidence (claim_table, claim_id, document_id, page_no, quote, verification)
                             VALUES ('risk_event', :e, :d, 9, 'wykonanie inspekcji TV istniejącej kanalizacji', :v)"""),
                     {"e": eid, "d": did, "v": verification})
    iid = await _scalar(db, """INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, model_pick, confidence, key, created_by)
                               VALUES ('event', 'ai_event', 'risk_event', :e, :p, 'Inspekcja istniejącej sieci po stronie wykonawcy',
                                       'Które ryzyko opisuje to zdarzenie?', 'R02', :c, :k, 'test') RETURNING id""",
                        e=eid, p=pid, c=conf, k=f"test:read:{eid}")
    return iid, did


async def test_event_card_names_subject_and_readable_source(expert, db):
    iid, did = await _doc_signal(db)
    r = await expert.get(f"/api/review-items/{iid}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["about"]["title"] == "Inspekcja istniejącej sieci po stronie wykonawcy"
    labels = {f["label"]: f for f in card["about"]["facts"]}
    assert labels["Projekt"]["href"] == "/projekty/RM-2026-003"
    assert labels["Rodzaj"]["value"] == "Sygnał z dokumentu przetargowego"
    assert labels["Ryzyko według modelu"]["value"].startswith("R02 ")
    src = card["source"]
    assert src["kind"] == "document" and src["label"] == "SWZ testowa, s. 9" and src["href"] == f"/api/documents/{did}/file#page=9"
    assert card["strength"]["level"] == "ready"
    # options and evidence are the decision path's, unchanged
    assert [o["key"] for o in card["options"]] == ["R02", "other", "not_risk"]
    assert card["evidence"]["verification"] == "exact"
    assert "—" not in r.text and "·" not in r.text


async def test_list_rows_carry_type_and_strength_and_sort_ready_first(expert, db):
    weak, _ = await _doc_signal(db, conf=0.3, verification="fuzzy", rm="RM-2026-004")
    ready, _ = await _doc_signal(db, conf=0.9, rm="RM-2026-004")
    r = await expert.get("/api/review-items", params={"kind": "event", "rm_id": "RM-2026-004", "type": "EV_DOC_SIGNAL", "sort": "strength"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [i["id"] for i in items]
    assert ids.index(ready) < ids.index(weak)
    row = next(i for i in items if i["id"] == ready)
    assert row["type"] == "EV_DOC_SIGNAL" and row["type_label"] == "Sygnał z dokumentu przetargowego"
    assert row["strength"]["level"] == "ready"
    assert next(i for i in items if i["id"] == weak)["strength"]["level"] == "check"


async def test_facets_add_up_to_the_list_total(expert, db):
    await _doc_signal(db, rm="RM-2026-004")
    f = (await expert.get("/api/review-items/facets", params={"kind": "event"})).json()
    total = (await expert.get("/api/review-items", params={"kind": "event", "limit": 1})).json()["total"]
    assert f["total"] == total
    assert sum(t["n"] for t in f["types"]) == total
    assert sum(p["n"] for p in f["projects"]) == total
    assert sum(s["n"] for s in f["strength"]) == total
    # a project filter narrows the type facet, and the type facet still adds up
    fp = (await expert.get("/api/review-items/facets", params={"kind": "event", "rm_id": "RM-2026-004"})).json()
    assert sum(t["n"] for t in fp["types"]) == fp["total"] >= 1
    assert all(t["label"] for t in f["types"])


async def test_code_filter_matches_the_models_risk_code(expert, db):
    iid, _ = await _doc_signal(db)
    r = await expert.get("/api/review-items", params={"kind": "event", "code": "R02", "limit": 1000})
    assert iid in [i["id"] for i in r.json()["items"]]


async def test_catalogue_proposal_card_says_which_risk(expert, db):
    cid = await _scalar(db, """INSERT INTO catalogue_risk (code, level, name, description, sector, status, version, origin, proposed_by, data)
        VALUES ('R97', 1, 'Testowe ryzyko pogody', 'Przestoje z powodu pogody.', 'wod-kan', 'proposed', 1, 'AI', 'test',
                '{"events": ["EV_TERM_EXTENSION"], "rationale": "Brak osobnej kategorii w R01 do R15.",
                  "effects": {"empirical": {"n": 12, "category": "pogoda"}}}'::jsonb) RETURNING id""")
    iid = await _scalar(db, """INSERT INTO review_item (kind, code, target_table, target_id, title, question, key, created_by)
        VALUES ('catalogue', 'catalogue_proposal', 'catalogue_risk', :c, 'Propozycja ryzyka: Testowe ryzyko pogody',
                'Czy dodać to ryzyko do katalogu?', 'test:cat:R97', 'test') RETURNING id""", c=cid)
    r = await expert.get(f"/api/review-items/{iid}")
    assert r.status_code == 200, r.text
    card = r.json()
    assert "R97" in card["question"] and "Testowe ryzyko pogody" in card["question"]
    p = card["proposal"]
    assert p["code"] == "R97" and p["name"] == "Testowe ryzyko pogody" and p["description"] == "Przestoje z powodu pogody."
    assert p["rationale"].startswith("Brak osobnej") and p["empirical"]["n"] == 12
    assert p["events"][0]["code"] == "EV_TERM_EXTENSION" and p["events"][0]["name"] != "EV_TERM_EXTENSION"
    assert isinstance(p["closest"], list) and isinstance(p["examples"], list)
    assert card["gold"] is not None  # the Wzorcowy przykład checkbox is offered for every kind
    assert [o["key"] for o in card["options"]] == ["add", "reject"]
