"""G3/G4: documents with extracted facts are linked, validated and turned into proposals; "Co się zmieniło" diff (docs/impl/new_documents.md §1).
Facts follow the LLM session's `document_extract` hand-off shape; the golden values are the three organizer case documents."""
import json

from sqlalchemy import text

from riskminer.review import doclink


async def _scalar(db, sql, **p):
    return (await db.execute(text(sql), p)).scalar()


async def _doc(db, title, facts, *, project_rm=None, sensitivity="public", owner_user=None):
    pid = await _scalar(db, "SELECT id FROM project WHERE rm_id = :r", r=project_rm) if project_rm else None
    data = {"facts": facts, **({"owner_user": owner_user} if owner_user else {})}
    return await _scalar(db, """INSERT INTO document (title, filename, sensitivity, doc_type, fetch_state, project_id, pages, data)
        VALUES (:t, :f, :s, 'protokol', 'found', :p, 1, CAST(:d AS jsonb)) RETURNING id""", t=title, f=title + ".pdf", s=sensitivity, p=pid, d=json.dumps(data))


Q = lambda text_, page=1: {"quote": text_, "page": page, "verification": "exact"}  # noqa: E731

ZAGRODNO = {
    "version": 1, "doc_kind": "protokol_koniecznosci_aneksowania", "doc_kind_label": "Protokół konieczności aneksowania umowy", "phase": "realizacja",
    "doc_date": "2026-05-05", "level": "contract",
    "identifiers": {"kpo": ["KPOD.03.15-IW.13-0004/25"], "contract": {"number": "IR.271.1.2026", "date": "2026-03-05"}, "nip": [], "regon": [],
                    "buyer": "Gmina Zagrodno", "contractor": "Przedsiębiorstwo Transportowo Budowlane Sp. z o.o.", "task_title": "Budowa kanalizacji sanitarnej na terenie Gminy Zagrodno w miejscowości Modlikowice"},
    "change": {"kinds": ["termin"], "delta_months": 1, "delta_days": None, "new_term_months": 3, "planned_end_calc": "2026-06-05", "value": None,
               "legal_basis": [], "legal_basis_state": "DOKUMENT_NIE_WSPOMINA"},
    "causes": [{"code": "R03", "origin": "CALC", "method": "rule", "why": "Kolizja z siecią wodociągową", **Q("kolizji z siecią wodociągową uniemożliwiające posadowienie pompowni numer PM2")},
               {"code": "R02", "origin": "CALC", "method": "rule", "why": "Wysoki poziom wód gruntowych", **Q("wysoki poziom wód gruntowych przy wykopie pod pompownię PM2")}],
    "effects": [{"code": "R18", "kind": "effect_delay", "origin": "CALC", "months": 4, "linked_investment": "oczyszczalnia ścieków w Modlikowicach",
                 **Q("opóźnienie o około 4 miesiące z powodu budowy oczyszczalni ścieków w Modlikowicach")}],
    "flags": [], "catalogue_proposals": [{"code": "R18", "name": "Zależność efektu od zadań powiązanych"}],
    "facts": [{"field": "delta_months", "value": 1, "origin": "CALC", "method": "rule", **Q("o 1 miesiąc")},
              {"field": "planned_end_calc", "value": "2026-06-05", "origin": "CALC", "method": "rule", **Q("3 miesiące od dnia zawarcia umowy")}],
}

ZLAWIES = {
    "version": 1, "doc_kind": "protokol_koniecznosci", "doc_kind_label": "Protokół konieczności nr 1", "phase": "realizacja", "doc_date": "2025-10-28", "level": "contract",
    "identifiers": {"kpo": [], "contract": {"number": "272.4.27.1.0.2025", "date": "2025-02-14"}, "nip": [], "regon": [], "buyer": "Gmina Zławieś Wielka",
                    "contractor": "WIMAX Sp. z o.o.", "task_title": "Budowa sieci kanalizacji sanitarnej w miejscowości Zławieś Wielka i Zławieś Mała wraz z modernizacją stacji uzdatniania wody w miejscowości Pędzewo"},
    "change": {"kinds": ["zakres", "wynagrodzenie", "termin"], "old_end": "2025-10-30", "new_end": "2025-12-05", "delta_days": 36,
               "value": {"amount": "151481.54", "currency": "PLN", "vat_basis": "gross"}, "legal_basis": ["455.1.3"], "legal_basis_state": "stated"},
    "causes": [{"code": "R02", "origin": "CALC", "method": "rule", "why": "Stan techniczny istniejących filtrów", **Q("stan techniczny dwóch filtrów nie pozwala na ich dalsze użytkowanie po ich odkryciu")},
               {"code": "R07", "origin": "CALC", "method": "rule", "why": "Roboty dodatkowe", **Q("roboty dodatkowe")}],
    "effects": [], "flags": [{"code": "mixed_legal_basis", "text": "Uzasadnienie miesza przesłanki pkt 3 i pkt 4 art. 455 ust. 1."}],
    "facts": [{"field": "delta_value", "value": "151481.54", "origin": "CALC", "method": "rule", **Q("151 481,54 zł brutto")},
              {"field": "legal_basis", "value": "455.1.3", "origin": "CALC", "method": "rule", **Q("art. 455 ust. 1 pkt 3")}],
}

GRODZISKO = {
    "version": 1, "doc_kind": "pismo_do_instytucji", "doc_kind_label": "Pismo do instytucji pośredniczącej", "phase": "realizacja", "doc_date": "2025-11-06", "level": "grant",
    "identifiers": {"kpo": ["KPOD.03.15-IW.21-0025/25"], "contract": None, "nip": [{"value": "8161571014", "checksum_ok": False}], "regon": [], "sign": "RI.041.1.2025",
                    "buyer": "Gmina Grodzisko Dolne", "recipient": "Urząd Marszałkowski Województwa Podkarpackiego"},
    "change": {"kinds": ["termin"], "requested_end": "2025-12-31", "legal_basis": [], "legal_basis_state": "DOKUMENT_NIE_WSPOMINA"},
    "causes": [{"code": "R01", "origin": "CALC", "method": "rule", "why": "Projekt sprzed kilkunastu lat", **Q("projekt został opracowany kilkanaście lat wcześniej")},
               {"code": "R13", "origin": "CALC", "method": "rule", "why": "Termin finansowania", **Q("termin realizacji projektu KPO")}],
    "effects": [], "flags": [{"code": "nip_checksum", "value": "8161571014", "text": "NIP nie przechodzi sumy kontrolnej."}],
    "facts": [{"field": "requested_end", "value": "2025-12-31", "origin": "CALC", "method": "rule", **Q("do dnia 31.12.2025")}],
}


async def test_zagrodno_protocol_golden(expert, db):
    did = await _doc(db, "zagrodno", ZAGRODNO)
    r = await expert.post(f"/api/documents/{did}/link")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["project"] == {"rm_id": "RM-2026-002", "method": "exact_id", "score": 1.0, "features": {"kpo_exact": 1.0}}
    assert j["contract"]["contract_id"] == 153400 and j["contract"]["score"] >= 0.85
    assert j["contract"]["features"]["signed_on"] == 1.0 and j["contract"]["features"]["planned_end"] == 1.0
    ch = (await db.execute(text("SELECT kind, delta_days, review_status, origin, change_types, legal_basis, changed_on, document_id FROM contract_change WHERE key = :k"),
                           {"k": f"doc:{did}:change"})).mappings().one()
    assert ch["kind"] == "document_change" and round(ch["delta_days"]) == 31 and ch["review_status"] == "proposed" and ch["document_id"] == did
    assert ch["change_types"] == ["termin"] and ch["legal_basis"] == []
    cid = await _scalar(db, "SELECT id FROM contract_change WHERE key = :k", k=f"doc:{did}:change")
    assert await _scalar(db, "SELECT evidence_state FROM evidence WHERE claim_table='contract_change' AND claim_id=:c AND claim_field='legal_basis'", c=cid) == "DOKUMENT_NIE_WSPOMINA"
    codes = {r[0]: r[1] for r in (await db.execute(text("SELECT catalogue_code, review_status FROM risk_event WHERE key LIKE :k"), {"k": f"doc:{did}:%"})).all()}
    assert codes == {"R03": "proposed", "R02": "proposed", "R18": "proposed"}
    assert await _scalar(db, "SELECT count(*) FROM evidence WHERE document_id=:d AND claim_table='risk_event' AND verification='exact' AND quote IS NOT NULL", d=did) == 3
    kinds = [r[0] for r in (await db.execute(text("SELECT kind FROM review_item WHERE id = ANY(:i)"), {"i": j["review_items"]})).all()]
    assert kinds.count("event") == 3 and "link" in kinds and "fact" in kinds
    # the review question is a plain sentence about the contract
    q = await _scalar(db, "SELECT question FROM review_item WHERE key = :k", k=f"doc:{did}:change_item")
    assert "IR.271.1.2026" in q and "05.05.2026" in q
    # idempotent
    again = (await expert.post(f"/api/documents/{did}/link")).json()
    assert sorted(again["review_items"]) == sorted(j["review_items"])
    assert await _scalar(db, "SELECT count(*) FROM contract_change WHERE document_id=:d", d=did) == 1


async def test_zagrodno_changes_since(expert, db):
    did = await _doc(db, "zagrodno2", ZAGRODNO)
    await expert.post(f"/api/documents/{did}/link")
    r = await expert.get("/api/projects/RM-2026-002/changes-since", params={"document_id": did})
    assert r.status_code == 200, r.text
    d = r.json()
    g = d["groups"]
    labels = {x["key"] for x in g["potwierdzone"]}
    assert {"kpo", "signed_on", "old_end"} <= labels
    pe = next(x for x in g["zmienione"] if x["key"] == "planned_end")
    assert (pe["before"], pe["after"]) == ("05.05.2026", "05.06.2026")
    assert d["aggregates"]["delay_days"]["after"] == -4  # completed 01.06.2026 against the new term 05.06.2026
    assert any("R18" in x["value"] for x in g["nowe"]) and any("zmiana umowy" in x["label"].lower() for x in g["nowe"])
    assert d["counts"]["nowe"] >= 4 and d["review_items"]


async def test_zlawies_protocol_golden(expert, db):
    did = await _doc(db, "zlawies", ZLAWIES, project_rm="RM-2026-005")
    j = (await expert.post(f"/api/documents/{did}/link")).json()
    assert j["project"]["rm_id"] == "RM-2026-005" and j["project"]["method"] == "user_bound"
    assert j["contract"]["contract_id"] == 149407
    assert j["contract"]["features"]["signed_on"] < 1.0  # BZP date differs from the contract date in the protocol: a proposal for review
    assert j["contract"]["features"]["planned_end"] == 1.0 and j["contract"]["features"]["contractor"] > 0.7
    ch = (await db.execute(text("SELECT delta_days, delta_value_amount, delta_value_currency, delta_value_vat, legal_basis, change_types FROM contract_change WHERE key=:k"),
                           {"k": f"doc:{did}:change"})).mappings().one()
    assert ch["delta_days"] == 36 and str(ch["delta_value_amount"]) == "151481.54" and ch["delta_value_vat"] == "gross" and ch["legal_basis"] == ["455.1.3"]
    assert set(ch["change_types"]) == {"zakres", "wynagrodzenie", "termin"}
    flag = await _scalar(db, "SELECT title FROM review_item WHERE key = :k", k=f"doc:{did}:flag:mixed_legal_basis")
    assert "pkt 3 i pkt 4" in flag
    d = (await expert.get("/api/projects/RM-2026-005/changes-since", params={"document_id": did})).json()
    pe = next(x for x in d["groups"]["zmienione"] if x["key"] == "planned_end")
    assert (pe["before"], pe["after"]) == ("30.10.2025", "05.12.2025")
    val = next(x for x in d["groups"]["zmienione"] if x["key"] == "value")
    assert val["before"].startswith("2 936 010,00") and "3 087 491,54" in val["after"]
    assert any(x["key"] == "old_end" for x in d["groups"]["potwierdzone"])


async def test_grodzisko_letter_nip_and_grant_level(expert, db):
    did = await _doc(db, "grodzisko", GRODZISKO)
    j = (await expert.post(f"/api/documents/{did}/link")).json()
    assert j["project"]["rm_id"] == "RM-2026-010" and j["project"]["method"] == "exact_id"
    bad = [c for c in j["checks"] if not c["ok"]]
    assert [(c["kind"], c["value"], c.get("expected")) for c in bad] == [("nip", "8161571014", "8161570014")]
    assert [c["kind"] for c in j["checks"] if c["ok"]] == ["kpo"]
    # grant-level: a project event, no contract_change
    assert await _scalar(db, "SELECT count(*) FROM contract_change WHERE document_id=:d", d=did) == 0
    ev = (await db.execute(text("SELECT event_type, catalogue_code, review_status, occurred_on FROM risk_event WHERE key=:k"), {"k": f"doc:{did}:term"})).mappings().one()
    assert ev["event_type"] == "EV_PROJECT_TERM_CHANGE" and ev["review_status"] == "proposed"
    assert j["project_term"]["requested_end"] == "2025-12-31"
    item = (await db.execute(text("SELECT title, code, kind, detail FROM review_item WHERE key = :k"), {"k": f"doc:{did}:chk:nip:8161571014"})).mappings().one()
    assert "8161570014" in item["title"] and item["kind"] == "discrepancy" and item["code"] == "document_nip_invalid"
    # never relinked or "fixed" silently
    assert await _scalar(db, "SELECT beneficiary_nip FROM project WHERE rm_id='RM-2026-010'") == "8161570014"
    d = (await expert.get("/api/projects/RM-2026-010/changes-since", params={"document_id": did})).json()
    assert any(x["key"] == "project_end" for x in d["groups"]["zmienione"])
    assert any("8161570014" in (x["value"] or "") for x in d["groups"]["nowe"])
    assert not any(x["key"] == "nip" for x in d["groups"]["potwierdzone"])


async def test_kpo_woj_rule_and_nip_helpers():
    ok = doclink.validate_identifiers({"identifiers": {"kpo": ["KPOD.03.15-IW.21-0025/25"]}}, {"province": "PL18"}, [])
    assert ok[0]["ok"]
    bad = doclink.validate_identifiers({"identifiers": {"kpo": ["KPOD.03.15-IW.13-0025/25"]}}, {"province": "PL18"}, [])
    assert not bad[0]["ok"] and "IW.21" in bad[0]["detail"]
    assert doclink.nearest_registry_nip("8161571014", ["8161570014"]) == "8161570014"
    assert doclink.nearest_registry_nip("8161571014", ["6941566139"]) is None


async def test_review_decisions_on_document_items(expert, db):
    did = await _doc(db, "zagrodno3", ZAGRODNO)
    j = (await expert.post(f"/api/documents/{did}/link")).json()
    link_item = await _scalar(db, "SELECT id FROM review_item WHERE key LIKE :k AND kind='link'", k=f"doc:{did}:%")
    card = (await expert.get(f"/api/review-items/{link_item}")).json()
    assert [o["key"] for o in card["options"]] == ["accept", "none"] and card["chips"]
    assert (await expert.post(f"/api/review-items/{link_item}/decision", json={"option": "accept", "action": "approve"})).status_code == 200
    change_item = await _scalar(db, "SELECT id FROM review_item WHERE key = :k", k=f"doc:{did}:change_item")
    r = await expert.post(f"/api/review-items/{change_item}/decision", json={"option": "keep", "action": "approve"})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT review_status FROM contract_change WHERE key = :k", k=f"doc:{did}:change") == "approved"
    evt = await _scalar(db, "SELECT id FROM review_item WHERE key LIKE :k AND code='document_cause' ORDER BY id LIMIT 1", k=f"doc:{did}:%")
    assert (await expert.post(f"/api/review-items/{evt}/decision", json={"option": "R03", "action": "approve"})).status_code in (200, 422)
    d = (await expert.get("/api/projects/RM-2026-002/changes-since", params={"document_id": did})).json()
    assert d["groups"]["zamkniete"], "decided items are listed as closed"
    # approved change shows on the card as a done step
    card = (await expert.get("/api/projects/RM-2026-002/card")).json()
    assert any(s["title"].startswith("Zmiana z dokumentu") and s["state"] == "done" for s in card["steps"])


async def test_reject_contract_link_detaches_change(expert, db):
    did = await _doc(db, "zlawies2", ZLAWIES, project_rm="RM-2026-005")
    await expert.post(f"/api/documents/{did}/link")
    it = await _scalar(db, "SELECT id FROM review_item WHERE key LIKE :k AND kind='link'", k=f"doc:{did}:%")
    r = await expert.post(f"/api/review-items/{it}/decision", json={"option": "none", "action": "reject", "reason": "to inna umowa"})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT contract_id FROM contract_change WHERE key=:k", k=f"doc:{did}:change") is None


async def test_analysis_steps_and_access(expert, client, db):
    did = await _doc(db, "grodzisko2", GRODZISKO)
    a = (await expert.get(f"/api/documents/{did}/analysis")).json()
    assert [s["key"] for s in a["steps"]] == ["upload", "ocr", "extraction", "linking"]
    assert [s["state"] for s in a["steps"]] == ["done", "done", "done", "pending"] and a["facts"]
    await expert.post(f"/api/documents/{did}/link")
    a = (await expert.get(f"/api/documents/{did}/analysis")).json()
    assert a["steps"][3]["state"] == "done" and a["review_items"] and a["project_rm_id"] == "RM-2026-010"
    anon = (await client.get(f"/api/documents/{did}/analysis")).json()
    assert anon["review_items"] == []  # the queue is internal
    # confidential documents of somebody else look absent
    secret = await _doc(db, "poufny", GRODZISKO, sensitivity="confidential", owner_user="user:ktos-inny")
    assert (await expert.get(f"/api/documents/{secret}/analysis")).status_code == 404
    assert (await client.get(f"/api/documents/{secret}/analysis")).status_code == 404
    assert (await expert.post(f"/api/documents/{secret}/link")).status_code == 404


async def test_juror_cannot_link_and_no_facts_is_409(client, expert, db):
    did = await _doc(db, "x", ZAGRODNO)
    await client.post("/api/auth/demo-login", json={"persona": "juror"})
    assert (await client.post(f"/api/documents/{did}/link")).status_code == 403
    nof = await _scalar(db, "INSERT INTO document (title, filename, sensitivity, doc_type, fetch_state) VALUES ('b','b.pdf','public','x','found') RETURNING id")
    assert (await expert.post(f"/api/documents/{nof}/link")).status_code == 409




async def test_regon_check_against_registry_and_grodzisko_regon(expert, db):
    facts = json.loads(json.dumps(GRODZISKO))
    facts["identifiers"]["regon"] = [{"value": "690581210", "checksum_ok": False}]
    did = await _doc(db, "grodzisko-regon", facts)
    j = (await expert.post(f"/api/documents/{did}/link")).json()
    bad = {c["kind"]: c for c in j["checks"] if not c["ok"]}
    assert bad["regon"]["expected"] == "690581710" and bad["nip"]["expected"] == "8161570014"
    t = await _scalar(db, "SELECT title FROM review_item WHERE key = :k", k=f"doc:{did}:chk:regon:690581210")
    assert "690581710" in t
    assert await _scalar(db, "SELECT regon FROM organization WHERE nip='8161570014'") == "690581710"  # registry untouched


async def test_learning_loop_gold_and_audit_in_diff(expert, db):
    did = await _doc(db, "zagrodno-gold", ZAGRODNO)
    await expert.post(f"/api/documents/{did}/link")
    evt = await _scalar(db, "SELECT id FROM review_item WHERE key LIKE :k AND code='document_cause' ORDER BY id LIMIT 1", k=f"doc:{did}:%")
    r = await expert.post(f"/api/review-items/{evt}/decision", json={"option": "R03", "action": "approve"})
    assert r.status_code == 200, r.text
    assert "analyses_marked" in r.json()
    g = (await db.execute(text("SELECT task, catalogue_code, input_text, output FROM gold_example WHERE review_id = :r"), {"r": r.json()["review_id"]})).mappings().one()
    assert g["task"] == "document_facts" and g["catalogue_code"] == "R03" and "kolizji z siecią wodociągową" in g["input_text"]
    assert g["output"]["document_id"] == did and g["output"]["source"] == "document"
    assert await _scalar(db, "SELECT count(*) FROM review WHERE action='mark_gold' AND review_item_id=:i", i=evt) == 1
    # a rejection teaches nothing
    evt2 = await _scalar(db, "SELECT id FROM review_item WHERE key LIKE :k AND code='document_cause' AND id <> :e ORDER BY id LIMIT 1", k=f"doc:{did}:%", e=evt)
    await expert.post(f"/api/review-items/{evt2}/decision", json={"option": "not_risk", "action": "reject", "reason": "to nie to"})
    assert await _scalar(db, "SELECT count(*) FROM gold_example WHERE task='document_facts' AND target_id = (SELECT target_id FROM review_item WHERE id=:i)", i=evt2) == 0
    # the diff says who approved what, and what the document added
    d = (await expert.get("/api/projects/RM-2026-002/changes-since", params={"document_id": did})).json()
    ev_line = next(x for x in d["groups"]["nowe"] if x.get("decision") and x["decision"]["action"] == "approve")
    assert ev_line["decision"]["by"] == "user:test" and ev_line["decision"]["by_label"] == "Ekspert test" and ev_line["from_document"] is True
    assert d["growth"]["contract_changes"] == 1 and d["growth"]["risk_events"] == 2  # one cause was rejected
    assert d["growth"]["sentence"] == "Nowe w bazie dzięki temu dokumentowi: +1 zmiana umowy, +2 zdarzenia ryzyka"
    assert "analyses_to_rerun" in d


async def test_growth_on_card_and_documents_tab(expert, db):
    did = await _doc(db, "zagrodno-growth", ZAGRODNO, project_rm="RM-2026-002")
    await expert.post(f"/api/documents/{did}/link")
    card = (await expert.get("/api/projects/RM-2026-002/card")).json()
    mine = next(x for x in card["from_documents"] if x["document_id"] == did)
    assert mine["sentence"].startswith("Nowe w bazie dzięki temu dokumentowi: +1 zmiana umowy") and mine["href"].endswith(f"dokumenty?dok=doc:{did}")
    docs = (await expert.get("/api/projects/RM-2026-002/documents")).json()
    row = next(p for p in docs["public"] if p["key"] == f"doc:{did}")
    assert row["growth"] and "+1 zmiana umowy" in row["facts_label"]
    assert next(e for e in docs["expected"] if e["key"] == "protokol")["have"] is True


async def test_alert_via_monitoring_for_ongoing_contract(expert, db):
    did = await _doc(db, "alert", ZAGRODNO)
    j = (await expert.post(f"/api/documents/{did}/link")).json()
    assert "alert" in j and isinstance(j["alert"], dict) and "raised" in j["alert"]
