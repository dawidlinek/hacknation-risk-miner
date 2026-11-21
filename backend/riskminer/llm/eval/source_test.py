"""Own "test źródłowy": a seeded random sample of conclusions, each re-verified mechanically against the cited text.

AI origins: change-cause classifications (change_cause_ai), AI risk_event proposals (evidence quote), chips
(analysis_item feature, origin AI), Red Pen notes (stored analysis_item + the recorded runs on 4 public documents, replayed
from cassettes), document facts on the 3 organizer documents (rules + recorded LLM, replayed). SOURCE/CALC: BZP facts with
a field code (quote in parsed_fields[field] or value printed in it). No model is called: replay only.

    RISKMINER_LLM_FAKE=1 uv run python -m riskminer.llm.eval.source_test --seed 2026
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from riskminer.config import REPO_ROOT, settings
from riskminer.llm.verify import match_in_text, numbers_supported, verify_quote

N = {"cause_ai": 18, "risk_event_ai": 8, "chip": 10, "redpen": 14, "document_facts": 10, "bzp_quote": 10, "bzp_value": 10}
ORIGIN_LABEL = {"cause_ai": "Klasyfikacja przyczyny zmiany (AI)", "risk_event_ai": "Propozycja zdarzenia ryzyka (AI)",
                "chip": "Cecha inwestycji z opisu lub dokumentu (AI)", "redpen": "Uwaga czerwonego długopisu (AI)",
                "document_facts": "Fakt z nowego dokumentu (reguły i AI)", "bzp_quote": "Cytat z pola ogłoszenia BZP (źródło)",
                "bzp_value": "Wartość z pola ogłoszenia BZP (źródło)"}
AI_ORIGINS = ("cause_ai", "risk_event_ai", "chip", "redpen", "document_facts")


def _field_text(r) -> tuple[str, str]:
    """Text of the cited field occurrence: the anchored span in html_body when the evidence row has one (repeated fields in
    multi-part / multi-change notices, data-db's `anchors` stage), else parsed_fields[field_code]."""
    if r["char_start"] is not None and r["char_end"] and r["html_body"]:
        from riskminer.parsing.bzp_parse import html_to_text
        return html_to_text(r["html_body"][r["char_start"]:r["char_end"]]), "wystąpienie pola wskazane zakresem w treści ogłoszenia"
    return r["field"] or "", ""


def html_text(h: str) -> str:
    import html as _h
    import re as _re
    return _h.unescape(_re.sub(r"<[^>]+>", " ", h))


def _status(qc) -> str:
    return qc.status if qc.status in ("exact", "fuzzy") else "failed"


async def sample_db(conn, seed: int) -> list[dict]:
    rows: list[dict] = []
    s = str(seed)
    # 1. national change-cause classifications: quote inside the item's own text
    for r in await conn.fetch("""
        SELECT a.id, a.primary_code, a.quote, a.verification AS stored, cc.id AS change_id, cc.cause_text, cc.description_text,
               cc.notice_id, n.object_id
        FROM change_cause_ai a JOIN contract_change cc ON cc.id = a.sample_change_id LEFT JOIN notice n ON n.id = cc.notice_id
        ORDER BY md5(a.id::text || $1) LIMIT $2""", s, N["cause_ai"]):
        from riskminer.llm.tasks.classify_causes import item_text
        qc = match_in_text(r["quote"], item_text(r["cause_text"], r["description_text"]))
        rows.append({"origin": "cause_ai", "id": f"change_cause_ai:{r['id']}", "claim": r["primary_code"], "quote": r["quote"],
                     "cited": f"zmiana umowy {r['change_id']} (przyczyna i opis z ogłoszenia)", "status": _status(qc),
                     "score": qc.score, "numbers": "n/d", "stored": r["stored"],
                     "url": f"/api/notices/{r['object_id']}" if r["object_id"] else f"/api/changes?id={r['change_id']}"})
    # 2. AI risk_event proposals: evidence quote inside the change's text
    for r in await conn.fetch("""
        SELECT e.id, e.catalogue_code, ev.quote, ev.verification AS stored, cc.cause_text, cc.description_text, n.object_id
        FROM risk_event e JOIN evidence ev ON ev.claim_table = 'risk_event' AND ev.claim_id = e.id
        JOIN contract_change cc ON cc.id = e.change_id LEFT JOIN notice n ON n.id = cc.notice_id
        WHERE e.origin = 'AI' ORDER BY md5(e.id::text || $1) LIMIT $2""", s, N["risk_event_ai"]):
        from riskminer.llm.tasks.classify_causes import item_text
        qc = match_in_text(r["quote"], item_text(r["cause_text"], r["description_text"]))
        rows.append({"origin": "risk_event_ai", "id": f"risk_event:{r['id']}", "claim": r["catalogue_code"], "quote": r["quote"],
                     "cited": "przyczyna i opis zmiany w ogłoszeniu BZP", "status": _status(qc), "score": qc.score,
                     "numbers": "n/d", "stored": r["stored"],
                     "url": f"/api/evidence?claim_table=risk_event&claim_id={r['id']}"})
    # 3. AI chips stored on analyses: quote in the description or on the cited document page
    for r in await conn.fetch("""
        SELECT i.id, i.key, i.body, i.quote, i.document_id, i.page_no, i.verification AS stored, a.code, a.input_text
        FROM analysis_item i JOIN analysis a ON a.id = i.analysis_id
        WHERE i.section = 'feature' AND i.origin = 'AI' AND i.quote IS NOT NULL
        ORDER BY md5(i.id::text || $1) LIMIT $2""", s, N["chip"]):
        if r["document_id"]:
            pages = {p["page_no"]: p["text"] or "" for p in await conn.fetch(
                "SELECT page_no, text FROM document_page WHERE document_id = $1", r["document_id"])}
            qc = verify_quote(r["quote"], pages, r["page_no"])
            cited = f"dokument {r['document_id']}, s. {r['page_no']}"
        else:
            qc = match_in_text(r["quote"], r["input_text"] or "")
            cited = f"opis użytkownika w analizie {r['code']}"
        body = r["body"] or {}
        v = body.get("value")
        num = "n/d"
        if r["key"] in ("dlugosc_km", "przepompownie", "przylacza", "termin_mies", "budzet") and v is not None and qc.ok:
            amt = float(v["amount"]) if isinstance(v, dict) else float(v)
            unit = "km" if r["key"] == "dlugosc_km" else None
            num = "ok" if (numbers_supported(amt, r["quote"], unit=unit, money=r["key"] == "budzet") or body.get("unsure")) else "brak liczby w cytacie"
        rows.append({"origin": "chip", "id": f"analysis_item:{r['id']}", "claim": f"{r['key']} = {body.get('display')}",
                     "quote": r["quote"], "cited": cited, "status": _status(qc), "score": qc.score, "numbers": num,
                     "stored": r["stored"], "url": f"/api/analyses/{r['code']}"})
    # 4a. stored Red Pen notes
    for r in await conn.fetch("""
        SELECT i.id, i.catalogue_code, i.quote, i.document_id, i.page_no, i.verification AS stored, a.code
        FROM analysis_item i JOIN analysis a ON a.id = i.analysis_id
        WHERE i.section = 'redpen_note' AND i.origin = 'AI' AND i.quote IS NOT NULL ORDER BY i.id"""):
        pages = {p["page_no"]: p["text"] or "" for p in await conn.fetch(
            "SELECT page_no, text FROM document_page WHERE document_id = $1", r["document_id"])}
        qc = verify_quote(r["quote"], pages, r["page_no"])
        rows.append({"origin": "redpen", "id": f"analysis_item:{r['id']}", "claim": r["catalogue_code"], "quote": r["quote"],
                     "cited": f"dokument {r['document_id']}, s. {r['page_no']}", "status": _status(qc), "score": qc.score,
                     "numbers": "n/d", "stored": r["stored"], "url": f"/api/analyses/{r['code']}/redpen/{r['document_id']}"})
    # 6. BZP facts: quotes from a field, and values printed in their field
    for r in await conn.fetch("""
        SELECT ev.id, ev.claim_table, ev.claim_field, ev.field_code, ev.quote, n.object_id, n.parsed_fields->>ev.field_code AS field,
               n.html_body, ev.char_start, ev.char_end, ev.note AS anchor_note
        FROM evidence ev JOIN notice n ON n.id = ev.notice_id
        WHERE ev.verification = 'structured_field' AND ev.quote IS NOT NULL AND ev.field_code IS NOT NULL
          AND ev.id % 97 = $1 % 97
        ORDER BY md5(ev.id::text || $1::text) LIMIT $2""", seed, N["bzp_quote"]):
        field, cited_extra = _field_text(r)
        qc = match_in_text(r["quote"], field)
        note = cited_extra
        if not qc.ok:
            # parsed_fields keeps one value per field code; notices listing several changes repeat 5.4.x, and some forms
            # number fields differently, so search the whole official notice text as well
            body = html_text(r["html_body"] or "")
            qb = match_in_text(r["quote"], body)
            if qb.ok:
                qc = qb
                note = "cytat jest w treści ogłoszenia, w innym wystąpieniu pola (pole powtórzone albo inna numeracja)"
            else:
                note = "cytatu nie ma ani w polu, ani w treści ogłoszenia"
        rows.append({"origin": "bzp_quote", "id": f"evidence:{r['id']}", "claim": f"{r['claim_table']}.{r['claim_field']}",
                     "quote": r["quote"], "cited": f"ogłoszenie {r['object_id']}, pole {r['anchor_note'] or r['field_code']}",
                     "status": _status(qc), "score": qc.score, "numbers": "n/d", "stored": "structured_field",
                     "url": f"/api/notices/{r['object_id']}", "note": note})
    for r in await conn.fetch("""
        SELECT ev.id, ev.field_code, c.value_amount, c.signed_on, n.object_id, n.parsed_fields->>ev.field_code AS field,
               ev.claim_field, n.html_body, ev.char_start, ev.char_end, ev.note AS anchor_note
        FROM evidence ev JOIN contract c ON c.id = ev.claim_id JOIN notice n ON n.id = ev.notice_id
        WHERE ev.claim_table = 'contract' AND ev.claim_field IN ('value', 'signed_on') AND ev.id % 89 = $1 % 89
        ORDER BY md5(ev.id::text || $1::text) LIMIT $2""", seed, N["bzp_value"]):
        field, _ = _field_text(r)
        if r["claim_field"] == "value":
            ok = r["value_amount"] is not None and numbers_supported(float(r["value_amount"]), field, money=True)
            claim = f"contract.value = {r['value_amount']}"
        else:
            d: date | None = r["signed_on"]
            ok = d is not None and (d.isoformat() in field or d.strftime("%d.%m.%Y") in field)
            claim = f"contract.signed_on = {d}"
        rows.append({"origin": "bzp_value", "id": f"evidence:{r['id']}", "claim": claim, "quote": field[:200],
                     "cited": f"ogłoszenie {r['object_id']}, pole {r['anchor_note'] or r['field_code']}", "status": "exact" if ok else "failed",
                     "score": 100.0 if ok else 0.0, "numbers": "ok" if ok else "inna wartość", "stored": "structured_field",
                     "url": f"/api/notices/{r['object_id']}"})
    return rows


async def sample_replay(seed: int, conn) -> list[dict]:
    """Recorded model outputs (cassettes) replayed through the same code path; no network."""
    os.environ["RISKMINER_LLM_FAKE"] = "1"
    os.environ.setdefault("RISKMINER_LLM_LOG", "memory")
    from riskminer.llm.docs import load_documents
    from riskminer.llm.tasks.document_facts import document_facts
    from riskminer.llm.tasks.redpen_scan import redpen_scan
    rng = random.Random(seed)
    rows: list[dict] = []
    docs = await load_documents([20119, 22095, 14531, 30011])
    notes = []
    for did, d in docs.items():
        res = await redpen_scan(d, subject="source_test")
        for n in res.notes:
            notes.append((did, d, n))
    for did, d, n in rng.sample(notes, min(N["redpen"], len(notes))):
        qc = verify_quote(n["quote"], d["pages"], n["page_no"])
        rows.append({"origin": "redpen", "id": f"nagranie:document:{did}:uwaga:{n['n']}", "claim": f"{n['code']}: {n['title']}",
                     "quote": n["quote"], "cited": f"dokument {did} ({d.get('doc_type')}), s. {n['page_no']}",
                     "status": _status(qc), "score": qc.score, "numbers": "n/d", "stored": n["verification"],
                     "url": f"/api/documents/{did}/file#page={n['page_no']}"})
    fix = Path(__file__).parents[3] / "tests" / "fixtures" / "llm" / "docs"
    facts = []
    for key in ("zagrodno", "zlawies", "grodzisko"):
        dd = json.loads((fix / f"{key}.json").read_text(encoding="utf-8"))
        doc = {"id": f"fixture:{key}", "filename": dd["filename"], "sensitivity": "public",
               "pages": {i + 1: t for i, t in enumerate(dd["pages"])}}
        o = await document_facts(doc, sensitivity="public", r18_status="proposed")
        for c in o["causes"] + o["effects"]:
            facts.append((key, doc, c, f"{c['code']} ({c['method']})"))
        for f in o["facts"]:
            if f.get("quote"):
                facts.append((key, doc, f, f"{f['field']} = {f['display']}"))
    for key, doc, c, claim in rng.sample(facts, min(N["document_facts"], len(facts))):
        qc = verify_quote(c["quote"], doc["pages"], c.get("page"))
        num = "n/d"
        if c.get("field") in ("delta_value", "delta_months", "new_term", "old_end", "new_end", "requested_end", "doc_date"):
            v = c["value"]
            if isinstance(v, dict):
                num = "ok" if numbers_supported(float(v["amount"]), c["quote"], money=True) else "brak liczby w cytacie"
            elif isinstance(v, (int, float)):
                num = "ok" if numbers_supported(v, c["quote"]) else "brak liczby w cytacie"
            else:
                dv = date.fromisoformat(v)
                num = "ok" if (dv.strftime("%d.%m.%Y") in c["quote"] or dv.isoformat() in c["quote"]) else "brak daty w cytacie"
        rows.append({"origin": "document_facts", "id": f"dokument organizatora:{key}", "claim": claim, "quote": c["quote"],
                     "cited": f"{doc['filename']}, s. {c.get('page')}", "status": _status(qc), "score": qc.score,
                     "numbers": num, "stored": c.get("verification"), "url": "POST /api/documents/upload (dokument organizatora)"})
    _ = conn
    return rows


async def run(seed: int = 2026) -> dict:
    from riskminer.db.session import raw_conn
    async with raw_conn() as conn:
        rows = await sample_db(conn, seed)
        rows += await sample_replay(seed, conn)
    by = defaultdict(Counter)
    for r in rows:
        ok = r["status"] != "failed" and r["numbers"] in ("n/d", "ok")
        r["pass"] = ok
        by[r["origin"]]["n"] += 1
        by[r["origin"]][r["status"]] += 1
        by[r["origin"]]["pass"] += ok
    out = Path(settings().exports_dir) / f"source_test_sample_seed{seed}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["origin", "id", "claim", "quote", "cited", "status", "score", "numbers", "pass",
                                          "stored", "url", "note"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    return {"rows": rows, "by_origin": {k: dict(v) for k, v in by.items()}, "csv": str(out.relative_to(REPO_ROOT))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    res = asyncio.run(run(a.seed))
    for k, v in res["by_origin"].items():
        print(k, v)
    print(res["csv"])
    print(json.dumps([r for r in res["rows"] if not r["pass"]], ensure_ascii=False, default=str, indent=1)[:6000])


if __name__ == "__main__":
    main()
