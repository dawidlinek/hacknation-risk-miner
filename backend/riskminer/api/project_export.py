"""Per-project record export: `GET /api/projects/{rm_id}/export.{json|md|docx|pdf}` (reads only).

One file with everything the case base knows about a project, every fact with its origin and source:
identification and funding, the linked BZP procedure(s) with link method/score/features, contracts, plan vs actual
(dates and values with their VAT basis), contract changes, risk events with R-codes and evidence (source, field code
or page, quote), AI proposals marked as proposals, review items, documents with "Co się zmieniło", and the list of
sources (URL, retrieved date, sha256). Public callers get the same view as the public card (no unverified AI rows).
DOCX uses python-docx like the analysis pack; PDF is that DOCX through LibreOffice (`documents/convert.py`).
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api import project_views as PV
from riskminer.api.prov import fmt_num
from riskminer.ingest import ids

FORMATS = ("json", "md", "docx", "pdf")
MEDIA = {"json": "application/json", "md": "text/markdown; charset=utf-8",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf"}
VAT_PL = {"net": "netto", "gross": "brutto", "unknown": "podstawa VAT nieznana", None: ""}
ORIGIN_PL = {"SOURCE": "źródło", "CALC": "wyliczenie", "AI": "model AI"}
STATUS_PL = {"auto": "automatycznie", "proposed": "propozycja do weryfikacji", "approved": "zatwierdzone przez eksperta",
             "edited": "poprawione przez eksperta", "rejected": "odrzucone"}
CHANGE_KIND_PL = {"change_notice": "ogłoszenie o zmianie umowy (BZP)", "performance_block": "ogłoszenie o wykonaniu umowy, sekcja zmian (BZP)",
                  "document_change": "dokument (propozycja z dokumentu)"}
METHOD_PL = {"exact_id": "numer ogłoszenia BZP z rekordu", "cross_reference": "numer z rekordu powołany w późniejszych ogłoszeniach",
             "fuzzy": "NIP zamawiającego + nazwa + CPV + data", "kpo_cited": "numer projektu KPO powołany w ogłoszeniach zamawiającego",
             "cross_reference_related": "postępowanie powiązane (powołuje numery z łańcucha)", "bzp": "karta postępowania BZP",
             "manual": "powiązanie eksperta"}
CHANGE_TYPE_PL = {"scope": "zakres", "price": "wynagrodzenie", "time": "termin", "other": "inne", "parties": "strony"}
DELIVERY_PL = {"build": "wybuduj (projekt zamawiającego)", "design_build": "zaprojektuj i wybuduj"}
FEATURE_PL = {"title_jaccard": "zgodność nazwy", "fuzzy_score": "wynik dopasowania nazwy", "cpv_wodkan": "CPV wod-kan",
              "kpo_era": "ogłoszone od 2024 (okres KPO)", "nip_match": "NIP zgodny", "first_published": "pierwsze ogłoszenie"}
NOTICE_PL = {"ContractNotice": "ogłoszenie o zamówieniu", "TenderResultNotice": "ogłoszenie o wyniku", "AgreementUpdateNotice": "ogłoszenie o zmianie umowy",
             "ContractPerformingNotice": "ogłoszenie o wykonaniu umowy", "CompetitionResultNotice": "ogłoszenie o wynikach konkursu"}


class NotFound(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------------- data

def money(amount: Any, vat: str | None, currency: str | None = "PLN") -> dict | None:
    if amount is None:
        return None
    return {"amount": str(Decimal(str(amount)).quantize(Decimal("0.01"))), "currency": currency or "PLN", "vat_basis": vat or "unknown"}


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat() if v.tzinfo else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return _iso(o)


async def build(db: AsyncSession, rm_id: str, user: A.User | None) -> dict:
    ch = await PV.load_chain(db, rm_id, user)
    if ch is None:
        raise NotFound(rm_id)
    p, procs = ch["project"], ch["procs"]
    pid = p.get("id")
    pids = [x["id"] for x in procs] or [0]
    logged = user is not None
    rows = PV.rows

    # ---- identification + funding -------------------------------------------------------------------------
    src = None
    if pid is not None:
        src = (await rows(db, "SELECT id, kind, url, retrieved_at, sha256, path, licence FROM source WHERE id = :i", i=p.get("source_id")) or [None])[0]
    org = ch["org"] or {}
    record = {
        "rm_id": rm_id, "kind": p["kind"], "title": p.get("title"), "description": p.get("description"),
        "beneficiary": {"name": p.get("beneficiary_name") or org.get("name"), "name_in_bzp": org.get("name"), "nip": p.get("beneficiary_nip"),
                        "nip_valid": org.get("nip_valid")},
        "location": {"teryt_woj": p.get("teryt_woj"), "province": p.get("province"), "city": p.get("city")},
        "public_id_type": p.get("public_id_type"), "public_id": p.get("public_id"), "external_ids": p.get("external_ids") or {},
        "scope": p.get("scope_text"), "scope_part": p.get("scope_part"), "status": p.get("status"),
        "subsector_main": p.get("subsector_main"), "works_type": p.get("works_type"), "delivery_model": p.get("delivery_model"),
        "record_date": p.get("record_date"), "record_version": p.get("record_version"), "is_pilot": p.get("is_pilot"),
        "funding": {"programme": p.get("funding_programme"),
                    "value": money(p.get("value_amount"), p.get("value_vat"), p.get("value_currency")),
                    "subsidy": money(p.get("subsidy_amount"), p.get("subsidy_vat"), p.get("subsidy_currency")),
                    "note": "Kwoty z rekordu (adnotacja instytucji); rekord nie podaje, czy są netto czy brutto."},
        "annotation": p.get("annotation"),
        "origin": p.get("origin"), "review_status": p.get("review_status"),
        "source": src,
    }

    # ---- links: procedure(s) with method, score, features ----------------------------------------------------
    links: list[dict] = []
    if pid is not None:
        for r in await rows(db, """SELECT pp.method, pp.score, pp.review_status, pp.lots, pp.explanation AS pp_explanation, pr.id AS procedure_id,
                                          pr.ocid, pr.title, pr.contract_notice_no, pr.buyer_name, pr.buyer_nip, pr.mode, pr.design_build,
                                          pr.subsector_main, pr.first_published_on, pr.estimated_value_amount, pr.estimated_value_currency,
                                          pr.estimated_value_vat, lc.features, lc.explanation, lc.decision
                                   FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
                                   LEFT JOIN link_candidate lc ON lc.id = pp.link_candidate_id
                                   WHERE pp.project_id = :p AND pp.review_status <> 'rejected' ORDER BY pp.score DESC NULLS LAST""", p=pid):
            links.append({"ocid": r["ocid"], "title": r["title"], "contract_notice_no": r["contract_notice_no"], "buyer": r["buyer_name"],
                          "buyer_nip": r["buyer_nip"], "method": r["method"], "method_label": METHOD_PL.get(r["method"], r["method"]),
                          "score": r["score"], "review_status": r["review_status"], "decision": r["decision"], "explanation": r["explanation"],
                          "features": r["features"] or {}, "lots": r["lots"] or [], "design_build": r["design_build"],
                          "subsector": r["subsector_main"], "first_published_on": r["first_published_on"],
                          "estimate": money(r["estimated_value_amount"], r["estimated_value_vat"], r["estimated_value_currency"]),
                          "chain": (r["pp_explanation"] or {}).get("chain"), "title_similarity": (r["pp_explanation"] or {}).get("title_similarity"),
                          "value_check": (r["pp_explanation"] or {}).get("value_check")})
        alternatives = await rows(db, """SELECT right_ref AS ocid, method, score, rank, decision, explanation FROM link_candidate
                                         WHERE left_table = 'project' AND left_id = :p AND right_table = 'procedure'
                                         ORDER BY rank NULLS LAST, score DESC LIMIT 6""", p=pid)
    else:
        for pr in procs:
            links.append({"ocid": pr["ocid"], "title": pr["title"], "contract_notice_no": pr["contract_notice_no"], "method": "bzp",
                          "method_label": METHOD_PL["bzp"], "score": None, "review_status": "auto", "features": {}})
        alternatives = []

    # ---- contracts, plan vs actual -----------------------------------------------------------------------------
    perf_by_c = {x["contract_id"]: x for x in ch["perf"]}
    contracts, dates = [], []
    for c in ch["contracts"]:
        contracts.append({"contract_id": c["id"], "lot_no": c["lot_no"], "contractor": c.get("contractor_name"), "contractor_nip": c.get("contractor_nip"),
                          "signed_on": c.get("signed_on"), "planned_duration_days": c.get("planned_duration_days"),
                          "planned_end_on": c.get("planned_end_on"), "value": money(c.get("value_amount"), c.get("value_vat"), c.get("value_currency")),
                          "result_notice_no": c.get("result_notice_no"), "origin": c.get("origin"), "review_status": c.get("review_status"),
                          "source_id": c.get("source_id")})
        pf = perf_by_c.get(c["id"])
        dates.append({"contract_id": c["id"], "lot_no": c["lot_no"], "signed_on": c.get("signed_on"),
                      "planned_days": (pf or {}).get("planned_days") or c.get("planned_duration_days"),
                      "planned_end_on": (pf or {}).get("planned_end_on") or c.get("planned_end_on"),
                      "completed_on": (pf or {}).get("completed_on"), "actual_days": (pf or {}).get("actual_days"),
                      "delay_days": (pf or {}).get("delay_days"), "on_time_declared": (pf or {}).get("on_time_declared"),
                      "changes_count": (pf or {}).get("changes_count"), "properly_performed": (pf or {}).get("properly_performed"),
                      "contract_value": money((pf or {}).get("contract_value_amount") or c.get("value_amount"), "gross"),
                      "paid": money((pf or {}).get("total_paid_amount"), (pf or {}).get("total_paid_vat") or "gross") if pf else None,
                      "cost_dev_pct": round(pf["cost_dev_pct"], 2) if pf and pf.get("cost_dev_pct") is not None else None,
                      "performance_notice": (pf or {}).get("notice_number"), "performance_url": (pf or {}).get("notice_url"),
                      "origin": "CALC" if pf else "SOURCE", "method": "completed_on - signed_on; paid / contract value - 1" if pf else None})
    m = ch["metric"]
    estimates = [lk["estimate"] for lk in links if lk.get("estimate")]
    plan_vs_actual = {
        "summary": PV.summary_sentence(m, ch["perf"], ch["contracts"]),
        "dates": dates,
        "values": {"estimate_bzp": estimates[0] if estimates else None,
                   "contracts_total": money(m.get("value"), "gross") if m.get("value") is not None else None,
                   "paid_total": money(m.get("paid"), "gross") if m.get("paid") is not None else None,
                   "cost_dev_pct": round(m["cost_dev_pct"], 2) if m.get("cost_dev_pct") is not None else None,
                   "funding_value": record["funding"]["value"]},
        "delay_days_max": m.get("delay_days"),
        "vat_note": "Porównujemy tylko kwoty tej samej podstawy: szacunek zamawiającego w BZP jest netto, wartości umów i wypłaty brutto.",
    }

    # ---- contract changes (+ AI cause proposals) -------------------------------------------------------------------
    chg = await rows(db, f"""SELECT ch.*, n.notice_number, n.url AS notice_url, d.title AS doc_title, d.filename AS doc_filename,
                                    a.primary_code AS ai_code, a.secondary_code AS ai_code2, a.quote AS ai_quote, a.verification AS ai_verification,
                                    a.confidence AS ai_confidence, a.model AS ai_model, a.review_status AS ai_status
                             FROM contract_change ch LEFT JOIN notice n ON n.id = ch.notice_id LEFT JOIN document d ON d.id = ch.document_id
                             LEFT JOIN LATERAL (SELECT * FROM change_cause_ai x WHERE x.norm_md5 = md5(rm_cause_norm(ch.cause_text, ch.description_text))
                                                AND x.review_status <> 'rejected' ORDER BY x.id DESC LIMIT 1) a ON true
                             WHERE ch.procedure_id = ANY(:p) AND ch.review_status <> 'rejected'
                               AND {"true" if logged else "(ch.origin <> 'AI' OR ch.review_status IN ('approved','edited'))"}
                             ORDER BY ch.changed_on NULLS LAST, ch.id""", p=pids)
    changes, ai = [], []
    for c in chg:
        item = {"change_id": c["id"], "contract_id": c["contract_id"], "kind": c["kind"], "kind_label": CHANGE_KIND_PL.get(c["kind"], c["kind"]),
                "change_no": c.get("change_no"), "changed_on": c.get("changed_on"), "legal_basis": c.get("legal_basis") or [],
                "legal_basis_raw": c.get("legal_basis_raw"), "change_types": c.get("change_types") or [], "delta_days": c.get("delta_days"),
                # BZP change amounts are contract amounts, i.e. gross (invariant 4, same basis as events.py impact values)
                "delta_value": money(c.get("delta_value_amount"), c.get("delta_value_vat") or "gross", c.get("delta_value_currency")),
                "delta_value_pct": c.get("delta_value_pct"), "cause": c.get("cause_text"), "description": c.get("description_text"),
                "notice": c.get("notice_number"), "url": c.get("notice_url"),
                "document": {"id": c["document_id"], "title": c.get("doc_title") or c.get("doc_filename")} if c.get("document_id") else None,
                "origin": c.get("origin"), "review_status": c.get("review_status"), "source_id": c.get("source_id")}
        if c.get("ai_code") and logged and c.get("ai_status") not in ("approved", "edited"):
            item["ai_cause"] = {"proposal": True, "risk_code": c["ai_code"], "secondary_code": c.get("ai_code2"), "quote": c.get("ai_quote"),
                                "verification": c.get("ai_verification"), "confidence": c.get("ai_confidence"), "model": c.get("ai_model"),
                                "review_status": c.get("ai_status")}
            ai.append({"what": "przyczyna zmiany umowy", "change_id": c["id"], **item["ai_cause"],
                       "on": f"{item['kind_label']} {item['notice'] or ''} {PV.pl_date(c.get('changed_on')) if c.get('changed_on') else ''}".strip()})
        elif c.get("ai_code") and c.get("ai_status") in ("approved", "edited"):
            item["ai_cause"] = {"proposal": False, "risk_code": c["ai_code"], "quote": c.get("ai_quote"), "review_status": c["ai_status"]}
        if c.get("origin") == "AI" or (c["kind"] == "document_change" and c.get("review_status") == "proposed"):
            ai.append({"what": "zmiana umowy z dokumentu", "change_id": c["id"], "proposal": True, "review_status": c.get("review_status"),
                       "quote": c.get("cause_text"), "on": (item["document"] or {}).get("title")})
        changes.append(item)

    # ---- risk events + evidence ---------------------------------------------------------------------------------
    cat = {r["code"]: r["name"] for r in await rows(db, """SELECT DISTINCT ON (code) code, name FROM catalogue_risk WHERE sector = 'wod-kan'
                                                         ORDER BY code, (status = 'approved') DESC, version DESC""")}
    ev_ids = [e["id"] for e in ch["events"]] or [0]
    evid: dict[int, list[dict]] = {}
    for r in await rows(db, """SELECT ev.claim_id, ev.source_id, ev.notice_id, ev.document_id, ev.page_no, ev.field_code, ev.url, ev.retrieved_at,
                                      ev.quote, ev.verification, ev.evidence_state, s.kind AS source_kind, s.sha256, n.notice_number
                               FROM evidence ev LEFT JOIN source s ON s.id = ev.source_id LEFT JOIN notice n ON n.id = ev.notice_id
                               WHERE ev.claim_table = 'risk_event' AND ev.claim_id = ANY(:ids) ORDER BY ev.claim_id, ev.id""", ids=ev_ids):
        evid.setdefault(r["claim_id"], []).append({k: r[k] for k in ("source_id", "source_kind", "notice_number", "document_id", "page_no", "field_code",
                                                                       "url", "retrieved_at", "quote", "verification", "evidence_state", "sha256")})
    events = []
    for e in ch["events"]:
        code = e.get("catalogue_code")
        item = {"event_id": e["id"], "event_type": e.get("event_type"), "risk_code": code, "risk_name": cat.get(code) or cat.get((code or "").split(".")[0]),
                "summary": e.get("summary"), "cause": e.get("cause"), "occurred_on": e.get("occurred_on"), "impact_days": e.get("impact_days"),
                "impact_value": money(e.get("impact_value_amount"), e.get("impact_value_vat"), e.get("impact_value_currency")),
                "impact_pct": round(e["impact_pct"], 2) if e.get("impact_pct") is not None else None, "mitigation": e.get("mitigation"),
                "evidence_state": e.get("evidence_state"), "origin": e.get("origin"), "review_status": e.get("review_status"),
                "proposal": e.get("origin") == "AI" and e.get("review_status") not in ("approved", "edited"),
                "change_notice": e.get("change_notice"), "evidence": evid.get(e["id"], [])}
        if item["proposal"]:
            ai.append({"what": "zdarzenie ryzyka", "event_id": e["id"], "proposal": True, "risk_code": code, "quote": (item["evidence"] or [{}])[0].get("quote") or e.get("cause"),
                       "review_status": e.get("review_status"), "on": e.get("summary")})
        events.append(item)

    # ---- review items, documents, "Co się zmieniło" -----------------------------------------------------------------
    review_items = []
    if logged and pid is not None:
        review_items = await rows(db, """SELECT id, kind, code, title, severity, status, created_by, created_at FROM review_item
                                         WHERE project_id = :p AND status = 'open' ORDER BY severity, id""", p=pid)
    docs = []
    if pid is not None:
        docs = await rows(db, f"""SELECT d.id, d.doc_type, d.title, d.filename, d.url, d.sha256, d.pages, d.sensitivity, d.source_id, d.fetch_state,
                                         d.data->'facts'->>'doc_kind_label' AS kind_label, d.data->'facts'->>'doc_date' AS doc_date,
                                         (d.data ? 'facts') AS has_facts
                                  FROM document d WHERE d.project_id = :p AND d.fetch_state = 'found' AND {A.public_doc_filter(user)} AND {A.public_filter(user, 'd')}
                                  ORDER BY d.id""", p=pid)
    changed = []
    if p["kind"] == "pilot_project":
        from riskminer.review import doclink
        for d in docs:
            if not d.get("has_facts"):
                continue
            try:
                cs = await doclink.changes_since(db, rm_id, d["id"])
            except Exception:  # noqa: BLE001, S112 - a document without linked facts has no diff yet
                continue
            groups = cs.get("groups") or {}
            if not any(groups.get(k) for k in ("potwierdzone", "zmienione", "nowe", "zamkniete")):
                continue                                    # a document that changed nothing is not news
            changed.append({"document_id": d["id"], "document": d.get("kind_label") or d.get("title") or d.get("filename"),
                            "date": (cs.get("document") or {}).get("date"),
                            **{k: groups.get(k) or [] for k in ("potwierdzone", "zmienione", "nowe", "zamkniete")},
                            "aggregates": cs.get("aggregates") or {}, "analyses_to_rerun": cs.get("analyses_to_rerun") or []})

    # ---- sources ------------------------------------------------------------------------------------------------
    sids = {p.get("source_id")} | {c.get("source_id") for c in ch["contracts"]} | {x.get("source_id") for x in ch["perf"]} | \
           {c.get("source_id") for c in chg} | {e.get("source_id") for e in ch["events"]} | {d.get("source_id") for d in docs} | \
           {x["source_id"] for v in evid.values() for x in v}
    sids = sorted(s for s in sids if s)
    sources = await rows(db, "SELECT id, kind, url, retrieved_at, sha256, path, licence, note FROM source WHERE id = ANY(:i) ORDER BY id", i=sids or [0])
    notices = [{"notice_number": n["notice_number"], "type": n["notice_type"], "type_label": NOTICE_PL.get(n["notice_type"], n["notice_type"]),
                "published_at": n["published_at"], "url": n["url"]} for n in ch["notices"]]

    out = {
        "meta": {"generator": "Risk Miner", "export": "rekord projektu", "format_version": 1, "generated_at": datetime.now(UTC),
                 "view": "ekspert" if logged else "publiczny", "rm_id": rm_id,
                 "legend": {"origin": ORIGIN_PL, "review_status": STATUS_PL},
                 "unverified_ai_hidden": ch["hidden"] if not logged else 0},
        "record": record, "links": links, "link_alternatives": alternatives, "contracts": contracts, "plan_vs_actual": plan_vs_actual,
        "changes": changes, "risk_events": events, "ai_proposals": ai, "review_items": review_items,
        "documents": [{k: d[k] for k in ("id", "doc_type", "title", "filename", "kind_label", "doc_date", "url", "sha256", "pages", "sensitivity", "fetch_state")}
                      for d in docs],
        "whats_changed": changed, "notices": notices, "sources": sources,
    }
    return _clean(out)


# ------------------------------------------------------------------------------------------------------------- render

def _m(x: dict | None) -> str:
    if not x:
        return "brak"
    return f"{fmt_num(float(x['amount']), 2)} {'zł' if x.get('currency') == 'PLN' else x.get('currency')} ({VAT_PL.get(x.get('vat_basis'), x.get('vat_basis'))})"


def _d(s: Any) -> str:
    if not s:
        return "brak"
    try:
        return PV.pl_date(str(s)[:10])
    except ValueError:
        return str(s)


def _n(x: Any, unit: str = "") -> str:
    if x is None:
        return "brak"
    return f"{fmt_num(x, 1 if isinstance(x, float) and not float(x).is_integer() else 0)}{unit}"


def _sc(x: Any) -> str:
    return "brak" if x is None else fmt_num(float(x), 2)


def _b(v: Any) -> str:
    return "tak" if v is True else "nie" if v is False else str(v)


def _lot(n: Any) -> str:
    return "całość" if n in (0, None) else f"część {n}"


def _st(origin: str | None, status: str | None) -> str:
    return f"{ORIGIN_PL.get(origin or '', origin or '')}, {STATUS_PL.get(status or '', status or '')}".strip(", ")


def _cell(s: Any) -> str:
    return str("" if s is None else s).replace("|", "/").replace("\n", " ")


def sections(x: dict) -> list[tuple[str, list[str] | None, list[list[str]] | None, list[str] | None]]:
    """-> [(heading, paragraphs, (header, rows) table or None, notes)] shared by Markdown and DOCX."""
    r, pva = x["record"], x["plan_vs_actual"]
    out: list = []
    f = r["funding"]
    ident = [["Identyfikator rekordu", r["rm_id"]], ["Nazwa przedsięwzięcia", r["title"]],
             ["Odbiorca (zamawiający)", f"{r['beneficiary']['name'] or ''}, NIP {r['beneficiary']['nip'] or 'brak'}"
              + (" (suma kontrolna poprawna)" if r["beneficiary"].get("nip_valid") else "")],
             ["Województwo (TERYT), siedziba", (f"{ids.WOJ.get(r['location'].get('teryt_woj') or '', '')} ({r['location'].get('teryt_woj') or 'brak'}), "
                                               f"{r['location'].get('city') or 'brak'}")],
             ["Identyfikator publiczny", f"{r.get('public_id_type') or ''}: {r.get('public_id') or 'brak'}"],
             ["Zakres rekordu", r.get("scope") or "brak"], ["Status", r.get("status") or "brak"],
             ["Podsektor, formuła", f"{r.get('subsector_main') or 'brak'}, {DELIVERY_PL.get(r.get('delivery_model'), r.get('delivery_model') or 'brak')}"],
             ["Program", f.get("programme") or "brak"], ["Wartość przedsięwzięcia", _m(f.get("value"))], ["Dofinansowanie", _m(f.get("subsidy"))],
             ["Data i wersja rekordu", f"{_d(r.get('record_date'))}, wersja {r.get('record_version') or 'brak'}"],
             ["Pochodzenie", _st(r.get("origin"), r.get("review_status"))]]
    if r.get("source"):
        s = r["source"]
        ident.append(["Plik źródłowy", f"{s.get('url') or s.get('path')}, pobrano {_d(s.get('retrieved_at'))}, sha256 {s.get('sha256')}"])
    out.append(("1. Identyfikacja i finansowanie", [r["description"]] if r.get("description") else None, [["Pole", "Wartość"], *ident],
                [f["note"]] if f.get("value") else None))
    lk_rows = [["Postępowanie", "Metoda", "Wynik", "Status", "Uzasadnienie"]]
    for lk in x["links"]:
        feats = lk.get("features") or {}
        why = lk.get("explanation") or ""
        fbits = [f"{FEATURE_PL[k]}: {_sc(v) if isinstance(v, float) else _b(v)}" for k, v in feats.items() if k in FEATURE_PL]
        lk_rows.append([f"{lk.get('contract_notice_no') or ''} {lk['ocid']}, {lk.get('title') or ''}", lk.get("method_label") or lk.get("method"),
                        _sc(lk.get("score")), STATUS_PL.get(lk.get("review_status"), lk.get("review_status")), f"{why}. {'; '.join(fbits)}".strip(". ")])
    alt = [f"{a['ocid']}: {a['method']} {_sc(a.get('score'))} ({a.get('decision')})" for a in x.get("link_alternatives") or [] if a.get("rank") != 1]
    cn = [f"{_lot(c.get('lot_no'))}: {c.get('contractor') or 'wykonawca nieznany'}, podpisana {_d(c.get('signed_on'))}, "
          f"ogłoszenie o wyniku {c.get('result_notice_no') or 'brak'}" for c in x["contracts"]]
    paras2 = ([f"Umowy przypisane przez powiązane postępowanie: {'; '.join(cn)}."] if cn else []) if len(lk_rows) > 1 else ["Nie znaleziono postępowania w BZP."]
    out.append(("2. Powiązanie z postępowaniem i umową w BZP", paras2, lk_rows if len(lk_rows) > 1 else None,
                (["Inni kandydaci: " + "; ".join(alt[:5])] if alt else None)))
    c_rows = [["Część", "Wykonawca", "Podpisano", "Termin", "Wartość umowy", "Ogłoszenie o wyniku", "Pochodzenie"]]
    for c in x["contracts"]:
        c_rows.append([_lot(c.get("lot_no")), c.get("contractor") or "", _d(c.get("signed_on")),
                       f"{_n(c.get('planned_duration_days'), ' dni')}, do {_d(c.get('planned_end_on'))}", _m(c.get("value")),
                       c.get("result_notice_no") or "", _st(c.get("origin"), c.get("review_status"))])
    out.append(("3. Umowy", None if len(c_rows) > 1 else ["Brak umowy w BZP."], c_rows if len(c_rows) > 1 else None, None))
    d_rows = [["Część", "Plan (dni, koniec)", "Faktycznie (dni, koniec)", "Opóźnienie", "Wartość umowy", "Wypłacono", "Odchylenie kosztu", "Ogłoszenie o wykonaniu"]]
    for d in pva["dates"]:
        d_rows.append([_lot(d.get("lot_no")), f"{_n(d.get('planned_days'))}, {_d(d.get('planned_end_on'))}",
                       f"{_n(d.get('actual_days'))}, {_d(d.get('completed_on'))}", _n(d.get("delay_days"), " dni"),
                       _m(d.get("contract_value")), _m(d.get("paid")), _n(d.get("cost_dev_pct"), "%"), d.get("performance_notice") or "brak"])
    v = pva["values"]
    out.append(("4. Plan i wykonanie", [pva["summary"],
                                        (f"Szacunek zamawiającego (BZP): {_m(v.get('estimate_bzp'))}. Umowy razem: {_m(v.get('contracts_total'))}. "
                                        f"Wypłacono razem: {_m(v.get('paid_total'))}. Odchylenie kosztu: {_n(v.get('cost_dev_pct'), '%')}. "
                                        f"Wartość przedsięwzięcia z rekordu: {_m(v.get('funding_value'))}.")],
                d_rows if len(d_rows) > 1 else None, [pva["vat_note"], "Opóźnienie i odchylenie to wyliczenia (CALC) z ogłoszenia o wykonaniu umowy."]))
    ch_rows = [["Data", "Źródło", "Podstawa", "Rodzaj zmiany", "Termin", "Kwota", "Przyczyna (cytat)", "Pochodzenie"]]
    for c in x["changes"]:
        cause = (c.get("cause") or "")[:300]
        if c.get("ai_cause"):
            a = c["ai_cause"]
            cause += f" [{'PROPOZYCJA AI' if a.get('proposal') else 'AI zatwierdzone'}: {a.get('risk_code')}]"
        ch_rows.append([_d(c.get("changed_on")), f"{c.get('kind_label')} {c.get('notice') or (c.get('document') or {}).get('title') or ''}".strip(),
                        ", ".join(c.get("legal_basis") or []) or "brak", ", ".join(CHANGE_TYPE_PL.get(t, t) for t in c.get("change_types") or []) or "brak",
                        _n(c.get("delta_days"), " dni"), _m(c.get("delta_value")), cause, _st(c.get("origin"), c.get("review_status"))])
    out.append(("5. Zmiany umowy", None if len(ch_rows) > 1 else ["Brak zmian umowy w BZP i w dokumentach."], ch_rows if len(ch_rows) > 1 else None,
                ["Podstawa 455.1.3 = art. 455 ust. 1 pkt 3 Pzp (roboty dodatkowe), 455.1.4 = pkt 4 (okoliczności nieprzewidywalne)."]
                if len(ch_rows) > 1 else None))
    e_rows = [["Kod R", "Zdarzenie", "Data", "Skutek", "Dowód (źródło, pole lub strona, cytat)", "Pochodzenie"]]
    for e in x["risk_events"]:
        ev = "; ".join(f"{q.get('notice_number') or (('dokument ' + str(q['document_id'])) if q.get('document_id') else q.get('source_kind') or '')}"
                       f"{', pole ' + q['field_code'] if q.get('field_code') else ''}{', str. ' + str(q['page_no']) if q.get('page_no') else ''}"
                       f"{': „' + q['quote'][:200] + '”' if q.get('quote') else ''}{', ' + q['url'] if q.get('url') else ''}" for q in e["evidence"]) or "brak"
        impact = ", ".join(s for s in (_n(e.get("impact_days"), " dni") if e.get("impact_days") is not None else "",
                                       _m(e.get("impact_value")) if e.get("impact_value") else "",
                                       _n(e.get("impact_pct"), "%") if e.get("impact_pct") is not None else "") if s) or "brak"
        e_rows.append([f"{e.get('risk_code') or 'bez kodu'}{' ' + e['risk_name'] if e.get('risk_name') else ''}",
                       ("[PROPOZYCJA AI] " if e.get("proposal") else "") + (e.get("summary") or ""), _d(e.get("occurred_on")), impact, ev,
                       _st(e.get("origin"), e.get("review_status"))])
    out.append(("6. Zdarzenia ryzyka", None if len(e_rows) > 1 else ["Brak zdarzeń ryzyka."], e_rows if len(e_rows) > 1 else None, None))
    ai = x["ai_proposals"]
    a_rows = [["Co", "Dotyczy", "Kod R", "Cytat", "Weryfikacja cytatu", "Model, pewność", "Status"]]
    for a in ai:
        a_rows.append([a.get("what"), a.get("on") or "", a.get("risk_code") or "", (a.get("quote") or "")[:200], a.get("verification") or "",
                       f"{a.get('model') or ''} {_n(a.get('confidence')) if a.get('confidence') is not None else ''}".strip(),
                       "PROPOZYCJA, czeka na eksperta"])
    notes = ["Propozycje modelu AI nie są faktami: nie wchodzą do statystyk, dopóki ekspert ich nie zatwierdzi."]
    if x["meta"].get("unverified_ai_hidden"):
        notes.append(f"Widok publiczny: ukryto {x['meta']['unverified_ai_hidden']} niezweryfikowanych propozycji AI.")
    out.append(("7. Propozycje AI (do weryfikacji)", None if ai else ["Brak propozycji AI dla tego projektu."], a_rows if ai else None, notes))
    ri = x["review_items"]
    out.append(("8. Sprawy do przeglądu i rozbieżności", None if ri else ["Brak otwartych spraw."],
                [["Nr", "Rodzaj", "Kod", "Opis", "Waga"], *[[str(i["id"]), i["kind"], i.get("code") or "", i["title"], i.get("severity") or ""] for i in ri]]
                if ri else None, None))
    wc = x["whats_changed"]
    paras = []
    for w in wc:
        paras.append(f"Dokument {w['document_id']} ({w.get('document')}):")
        for key, label in (("potwierdzone", "potwierdzone"), ("zmienione", "zmienione"), ("nowe", "nowe"), ("zamkniete", "zamknięte")):
            for it in w.get(key) or []:
                val = it.get("value") or (f"{it.get('before')} na {it.get('after')}" if it.get("before") or it.get("after") else "")
                paras.append(f"  {label}: {it.get('label')}{': ' + str(val) if val else ''}")
    docs = x["documents"]
    d2 = [["Nr", "Dokument", "Rodzaj", "Strony", "sha256"], *[[str(d["id"]), d.get("title") or d.get("filename") or "", d.get("kind_label") or d.get("doc_type") or "",
                                                              _n(d.get("pages")), d.get("sha256") or ""] for d in docs]]
    out.append(("9. Dokumenty i „Co się zmieniło”", paras or ["Brak nowych dokumentów z wyczytanymi faktami, więc nic się nie zmieniło od rekordu i BZP."],
                d2 if docs else None, None))
    s_rows = [["Nr", "Rodzaj", "Adres", "Pobrano", "sha256", "Licencja"]]
    for s in x["sources"]:
        s_rows.append([str(s["id"]), s.get("kind") or "", s.get("url") or s.get("path") or "", _d(s.get("retrieved_at")), s.get("sha256") or "", s.get("licence") or ""])
    n_rows = [["Ogłoszenie", "Rodzaj", "Opublikowano", "Adres"], *[[n["notice_number"], n["type_label"], _d(n.get("published_at")), n.get("url") or ""]
                                                                 for n in x["notices"]]]
    out.append(("10. Źródła", None, s_rows, ["Ogłoszenia BZP pochodzą z kopii BZP organizatora (sha256 pliku w tabeli); każde ma adres w ezamowienia.gov.pl."]))
    out.append(("10a. Ogłoszenia BZP w łańcuchu postępowania", None if len(n_rows) > 1 else ["Brak ogłoszeń."], n_rows if len(n_rows) > 1 else None, None))
    return out


def to_markdown(x: dict) -> str:
    r = x["record"]
    lines = [f"# Rekord projektu {r['rm_id']}", "", f"**{r.get('title') or ''}**", "",
             (f"Eksport z Risk Miner, {PV.pl_date(str(x['meta']['generated_at'])[:10])}, widok: {x['meta']['view']}. "
             "Każdy fakt ma pochodzenie: źródło (SOURCE), wyliczenie (CALC) albo model AI (AI, zawsze jako propozycja)."), ""]
    for head, paras, table, notes in sections(x):
        lines += [f"## {head}", ""]
        for p in paras or []:
            lines += [p, ""]
        if table:
            lines.append("| " + " | ".join(_cell(h) for h in table[0]) + " |")
            lines.append("|" + "---|" * len(table[0]))
            for row in table[1:]:
                lines.append("| " + " | ".join(_cell(c) for c in row) + " |")
            lines.append("")
        for n in notes or []:
            lines += [f"_{n}_", ""]
    return "\n".join(lines)


def to_docx(x: dict) -> bytes:
    import io

    from docx import Document
    from docx.shared import Pt

    from riskminer.analysis.pack import _table
    r = x["record"]
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10)
    doc.add_heading(f"Rekord projektu {r['rm_id']}", 0)
    doc.add_paragraph(r.get("title") or "")
    doc.add_paragraph(f"Eksport z Risk Miner, {PV.pl_date(str(x['meta']['generated_at'])[:10])}, widok: {x['meta']['view']}. "
                      "Każdy fakt ma pochodzenie: źródło (SOURCE), wyliczenie (CALC) albo model AI (AI, zawsze jako propozycja).")
    for head, paras, table, notes in sections(x):
        doc.add_heading(head, 1)
        for p in paras or []:
            doc.add_paragraph(p)
        if table:
            _table(doc, table[0], table[1:])
        for n in notes or []:
            q = doc.add_paragraph(n)
            for run in q.runs:
                run.italic = True
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def render(db: AsyncSession, rm_id: str, fmt: str, user: A.User | None) -> tuple[bytes, str, str]:
    """-> (bytes, filename, media type). Raises NotFound / ValueError (unknown format)."""
    if fmt not in FORMATS:
        raise ValueError(fmt)
    x = await build(db, rm_id, user)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in rm_id)
    name = f"rekord_{safe}.{fmt}"
    if fmt == "json":
        return json.dumps(x, ensure_ascii=False, indent=1, default=str).encode(), name, MEDIA[fmt]
    if fmt == "md":
        return to_markdown(x).encode(), name, MEDIA[fmt]
    data = to_docx(x)
    if fmt == "docx":
        return data, name, MEDIA[fmt]
    from riskminer.analysis.pack import to_pdf_bytes
    return await asyncio.to_thread(to_pdf_bytes, data), name, MEDIA[fmt]


async def export_to_file(rm_id: str, fmt: str, out: str | None = None) -> dict:
    """CLI fallback (`riskminer export-project`): the expert view, written to exports/ or `out`."""
    from riskminer.config import settings
    from riskminer.db.session import sessionmaker
    async with sessionmaker()() as db:
        data, name, _ = await render(db, rm_id, fmt, A.demo_user())
    path = Path(out) if out else Path(settings().exports_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"rm_id": rm_id, "fmt": fmt, "path": str(path), "bytes": len(data)}
