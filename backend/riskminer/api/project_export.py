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
from riskminer.ingest import ids
from riskminer.reporting import docx_kit as K

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
             "ContractPerformingNotice": "ogłoszenie o wykonaniu umowy", "CompetitionResultNotice": "ogłoszenie o wynikach konkursu",
             "NoticeUpdateNotice": "ogłoszenie o zmianie ogłoszenia", "CorrectionNotice": "sprostowanie"}


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
            e0 = (item["evidence"] or [{}])[0]
            where = ", ".join(x for x in (e0.get("notice_number") or (f"dokument {e0['document_id']}" if e0.get("document_id") else ""),
                                          f"pole {e0['field_code']}" if e0.get("field_code") else "", f"s. {e0['page_no']}" if e0.get("page_no") else "") if x)
            ai.append({"what": "zdarzenie ryzyka", "event_id": e["id"], "proposal": True, "risk_code": code, "where": where,
                       "quote": e0.get("quote") or e.get("cause"),
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

    # ---- timeline and similar cases (same helpers as the project card) ----------------------------------------------
    try:
        timeline = PV.steps(ch)
    except Exception:  # noqa: BLE001 - the timeline is a convenience view of rows already in the export
        timeline = []
    try:
        similar = await PV.similar_cases(db, rm_id, 5)
    except Exception:  # noqa: BLE001 - empty or restoring database: the export still renders
        similar = []
    models = sorted({a["model"] for a in ai if a.get("model")})

    out = {
        "meta": {"generator": "ex ante (Risk Miner)", "export": "rekord projektu", "format_version": 2, "generated_at": datetime.now(UTC),
                 "app_url": "https://exante.linek.dev", "models": models,
                 "view": "ekspert" if logged else "publiczny", "rm_id": rm_id,
                 "legend": {"origin": ORIGIN_PL, "review_status": STATUS_PL},
                 "unverified_ai_hidden": ch["hidden"] if not logged else 0},
        "record": record, "links": links, "link_alternatives": alternatives, "contracts": contracts, "plan_vs_actual": plan_vs_actual,
        "changes": changes, "risk_events": events, "ai_proposals": ai, "review_items": review_items,
        "documents": [{k: d[k] for k in ("id", "doc_type", "title", "filename", "kind_label", "doc_date", "url", "sha256", "pages", "sensitivity", "fetch_state")}
                      for d in docs],
        "whats_changed": changed, "notices": notices, "sources": sources, "timeline": timeline, "similar_cases": similar,
    }
    return _clean(out)


# ------------------------------------------------------------------------------------------------------------- render
# One block list (reporting/docx_kit.py) renders to DOCX (-> PDF) and Markdown. Page 1 is the executive summary.

LEGAL_PL = {"455.1.1": "art. 455 ust. 1 pkt 1 Pzp (zmiana przewidziana w umowie)", "455.1.2": "art. 455 ust. 1 pkt 2 Pzp (nowy wykonawca)",
            "455.1.3": "art. 455 ust. 1 pkt 3 Pzp (roboty dodatkowe)", "455.1.4": "art. 455 ust. 1 pkt 4 Pzp (okoliczności nieprzewidywalne)",
            "455.2": "art. 455 ust. 2 Pzp (zmiana o małej wartości)"}
SEVERITY_PL = {"high": "wysoka", "medium": "średnia", "low": "niska"}
REVIEW_KIND_PL = {"discrepancy": "rozbieżność danych", "link": "powiązanie do potwierdzenia", "event": "zdarzenie ryzyka do potwierdzenia",
                  "fact": "fakt z dokumentu do potwierdzenia", "document": "dokument"}
SOURCE_KIND_PL = {"bzp_copy": "kopia BZP organizatora", "xlsx": "zestaw organizatora (XLSX)", "docs_22": "dokument postępowania (platforma zakupowa)",
                  "upload": "plik wgrany przez eksperta", "import": "import rekordu", "bzp": "BZP (API)", "ted": "TED"}
DECISION_PL = {"accept": "przyjęte automatycznie", "review": "do przeglądu", "reject": "odrzucone"}
STATUS_SHORT = {"Zakończone": "zakończone"}


def _sc(x: Any) -> str:
    return "brak" if x is None else K.fmt_num(float(x), 2)


def _b(v: Any) -> str:
    return "tak" if v is True else "nie" if v is False else str(v)


def _days(v: Any, signed: bool = False) -> str:
    if v is None:
        return ""
    v = float(v)
    return f"{'+' if signed and v > 0 else ''}{K.fmt_num(v, 0 if v.is_integer() else 1)} dni"


def _lot(n: Any) -> str:
    return "całość" if n in (0, None) else f"część {n}"


def _legal(codes: list[str] | None) -> str:
    return "; ".join(LEGAL_PL.get(c, c) for c in codes or []) or "brak w źródle"


def _short_url(u: str | None, n: int = 46) -> str:
    if not u:
        return ""
    s = u.split("://", 1)[-1]
    return s if len(s) <= n else s[: n - 1] + "…"


def _link(text: str, url: str | None) -> Any:
    return {"t": text, "link": url} if url else text


def _quote(q: str | None, n: int = 260) -> str:
    if not q:
        return ""
    q = " ".join(str(q).split())
    return f"„{q[:n]}{'…' if len(q) > n else ''}”"


def _tag_of(origin: str | None, status: str | None) -> dict:
    return K.tag(K.prov_key(origin, status))


def _ev_where(q: dict) -> list:
    who: Any = q.get("notice_number") or (f"dokument {q['document_id']}" if q.get("document_id") else SOURCE_KIND_PL.get(q.get("source_kind"), q.get("source_kind") or "źródło"))
    segs: list = [_link(who, q.get("url"))]
    if q.get("field_code"):
        segs.append(f", pole {q['field_code']}")
    if q.get("page_no"):
        segs.append(f", s. {q['page_no']}")
    if q.get("quote"):
        segs.append(f": {_quote(q['quote'], 200)}")
    return segs


def _dup_docs(x: dict) -> dict[int, int]:
    """Document id -> id of the first document with the same sha256 (the same file uploaded twice)."""
    first: dict[Any, int] = {}
    out: dict[int, int] = {}
    for d in x.get("documents") or []:
        keys = [k for k in (d.get("sha256"), ((d.get("filename") or "").lower(), d.get("pages")) if d.get("filename") else None) if k]
        hit = next((first[k] for k in keys if k in first), None)
        if hit is not None:
            out[d["id"]] = hit
        for k in keys:
            first.setdefault(k, d["id"])
    return out


def _change_repeats(changes: list[dict]) -> dict[int, str]:
    """change_id -> why it repeats another row (performance-notice block repeating a change notice, a document read twice)."""
    out: dict[int, str] = {}
    notices = [c for c in changes if c.get("kind") == "change_notice"]
    seen: dict[tuple, str] = {}
    for c in changes:
        amt = (c.get("delta_value") or {}).get("amount")
        if c.get("kind") == "performance_block" and amt not in (None, "0.00"):
            for n in notices:
                if (n.get("delta_value") or {}).get("amount") == amt:
                    out[c["change_id"]] = f"powtarza zmianę z ogłoszenia {n.get('notice') or ''}".strip()
                    break
        if c.get("kind") == "document_change":
            key = (c.get("changed_on"), c.get("delta_days"), amt, (c.get("cause") or "")[:160])
            if key in seen:
                out[c["change_id"]] = f"ta sama zmiana co z dokumentu {seen[key]}"
            else:
                seen[key] = str((c.get("document") or {}).get("id") or "")
    return out


def _event_groups(events: list[dict]) -> list[dict]:
    """Facts and rule results (not AI proposals), identical rows merged (same code, summary, date and impact) with all evidence kept."""
    groups: dict[tuple, dict] = {}
    for e in events:
        if e.get("proposal"):
            continue
        key = (e.get("risk_code"), e.get("summary"), e.get("occurred_on"), e.get("impact_days"), (e.get("impact_value") or {}).get("amount"))
        g = groups.setdefault(key, {**e, "count": 0, "all_evidence": []})
        g["count"] += 1
        g["all_evidence"].extend(e.get("evidence") or [])
    return list(groups.values())


def _iso_pl(s: Any) -> str:
    """'pierwsze ogłoszenie 2026-02-02' -> 'pierwsze ogłoszenie 02.02.2026' (our own explanation strings only, never quotes)."""
    import re
    return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", r"\3.\2.\1", "" if s is None else str(s))


RISK_FALLBACK = {"N-UNSPEC": "zmiana bez wskazanej przyczyny", "N-PRICE": "ceny materiałów i robocizny", "N-CLIENT": "decyzje zamawiającego"}


def _code_root(code: str | None) -> str:
    return (code or "").split(".")[0] or "bez kodu"


def quality(x: dict) -> list[dict]:
    """Discrepancies and gaps found while exporting. Reported, never fixed: {kind, text, action}."""
    out: list[dict] = []
    r, pva = x["record"], x.get("plan_vs_actual") or {}
    dups = _dup_docs(x)
    if dups:
        pairs = ", ".join(f"{a} i {b}" for a, b in dups.items())
        out.append({"kind": "powtórzony dokument", "text": f"Ten sam dokument wgrano więcej niż raz (dokumenty {pairs}: ten sam plik albo ta sama nazwa "
                    "i liczba stron). "
                    "Zmiany i zdarzenia z kopii pokazujemy z oznaczeniem powtórzenia.", "action": "ekspert: usunąć kopię w Przeglądzie"})
    reps = _change_repeats(x.get("changes") or [])
    if reps:
        out.append({"kind": "powtórzona zmiana", "text": f"{K.plural(len(reps), 'wiersz zmian powtarza', 'wiersze zmian powtarzają', 'wierszy zmian powtarza')} inne źródło (sekcja zmian ogłoszenia o wykonaniu "
                    "albo kopia dokumentu). W tabeli zmian są oznaczone; nie sumujemy ich podwójnie.", "action": "oznaczone w sekcji 5"})
    unk = [c for c in x.get("changes") or [] if (c.get("delta_value") or {}).get("vat_basis") == "unknown" and (c["delta_value"].get("amount") not in (None, "0.00"))]
    if unk:
        out.append({"kind": "podstawa VAT", "text": f"Kwoty zmian umowy bez podstawy VAT w źródle: {len(unk)}; pokazujemy je jako „podstawa VAT nieznana”. "
                    "Kwoty umów w BZP są brutto, więc w zdarzeniach ryzyka skutek liczymy jako brutto.", "action": "bez zmiany danych"})
    f = r.get("funding") or {}
    if (f.get("value") or {}).get("vat_basis") == "unknown":
        vc = next((lk.get("value_check") for lk in x.get("links") or [] if lk.get("value_check")), None)
        extra = ""
        if vc and vc.get("diff_pct") is not None:
            extra = (f" Wartość z rekordu różni się od sumy wartości umów brutto o {K.fmt_num(float(vc['diff_pct']), 1)}%"
                     + (", więc najpewniej jest kwotą brutto; podstawy nie zmieniamy bez decyzji eksperta." if abs(float(vc["diff_pct"])) < 1 else "."))
        out.append({"kind": "podstawa VAT", "text": "Wartość przedsięwzięcia i dofinansowanie z rekordu nie mają podanej podstawy VAT." + extra,
                    "action": "do potwierdzenia przez instytucję"})
    for lk in x.get("links") or []:
        vc = lk.get("value_check") or {}
        if vc.get("diff_pct") is not None and abs(float(vc["diff_pct"])) >= 1:
            out.append({"kind": "rozbieżność kwot", "text": f"Wartość z rekordu ({K.fmt_num(vc.get('project_value'), 2)} zł) różni się o "
                        f"{K.fmt_num(float(vc['diff_pct']), 1)}% od: {vc.get('closest')}.", "action": "do wyjaśnienia"})
    perf_n = [n for n in x.get("notices") or [] if n.get("type") == "ContractPerformingNotice"]
    used = {d.get("performance_notice") for d in pva.get("dates") or [] if d.get("performance_notice")}
    if len(perf_n) > max(1, len(x.get("contracts") or [])):
        out.append({"kind": "kilka ogłoszeń o wykonaniu", "text": f"W BZP są {len(perf_n)} ogłoszenia o wykonaniu (umów: {len(x.get('contracts') or [])}) "
                    f"({', '.join(n['notice_number'] for n in perf_n)}). Do obliczeń użyto: {', '.join(sorted(used)) or 'brak'}.", "action": "pokazane w sekcji 4"})
    for d in pva.get("dates") or []:
        if not d.get("completed_on"):
            out.append({"kind": "luka", "text": f"Brak ogłoszenia o wykonaniu umowy ({_lot(d.get('lot_no'))}): nie znamy faktycznego terminu ani wypłaty.",
                        "action": "uzupełni monitoring BZP"})
    nodate = [c for c in x.get("changes") or [] if not c.get("changed_on")]
    if nodate:
        out.append({"kind": "luka", "text": f"Zmiany bez daty w źródle (sekcja zmian ogłoszenia o wykonaniu): {len(nodate)}.", "action": "bez zmiany danych"})
    if x.get("links") and not (pva.get("values") or {}).get("estimate_bzp"):
        out.append({"kind": "luka", "text": "Ogłoszenie o zamówieniu nie podaje szacunku wartości zamówienia.", "action": "bez zmiany danych"})
    b = r.get("beneficiary") or {}
    if b.get("nip") and b.get("nip_valid") is False:
        out.append({"kind": "rozbieżność danych", "text": f"NIP {b['nip']} z rekordu ma błędną sumę kontrolną.", "action": "do poprawy przez instytucję"})
    if not x.get("links"):
        out.append({"kind": "luka", "text": "Nie znaleziono postępowania w BZP dla tego rekordu.", "action": "ekspert: powiązanie ręczne"})
    nocode = [e for e in x.get("risk_events") or [] if not e.get("risk_code") and not e.get("proposal")]
    if nocode:
        out.append({"kind": "luka", "text": f"Zdarzenia bez kodu R: {len(nocode)}. To skutki (opóźnienie, dopłata) bez przyczyny wskazanej w źródle.",
                    "action": "przyczyny w propozycjach AI i dokumentach"})
    for w in x.get("whats_changed") or []:
        if w.get("document_id") in dups:
            continue
        for it in w.get("zmienione") or []:
            out.append({"kind": "dokument a BZP", "text": f"Dokument „{w.get('document')}” zmienia: {it.get('label')}, z {it.get('before')} na {it.get('after')}"
                        + (f" ({it['why']})" if it.get("why") else "") + ".", "action": "ekspert: zatwierdzić albo odrzucić"})
    alts = [a for a in x.get("link_alternatives") or [] if a.get("rank") != 1 and a.get("decision") == "review"]
    if alts:
        out.append({"kind": "powiązanie", "text": f"Inni kandydaci powiązania czekają na decyzję: {len(alts)} (najwyższy wynik "
                    f"{K.fmt_num(max(float(a.get('score') or 0) for a in alts), 2)}).", "action": "ekspert: Przegląd"})
    if (x.get("meta") or {}).get("unverified_ai_hidden"):
        out.append({"kind": "widok publiczny", "text": f"Ukryto {x['meta']['unverified_ai_hidden']} niezweryfikowanych propozycji AI.", "action": "widoczne po zalogowaniu"})
    return out


def _unique_changes(x: dict) -> tuple[list[dict], dict[int, str]]:
    reps = _change_repeats(x.get("changes") or [])
    return [c for c in x.get("changes") or [] if c["change_id"] not in reps], reps


def _summary(x: dict) -> tuple[list[dict], list[Any], str]:
    """-> (tiles, bullets, state line) for page 1."""
    r, pva = x["record"], x.get("plan_vs_actual") or {}
    dates = pva.get("dates") or []
    done = [d for d in dates if d.get("completed_on")]
    n_c = len(dates)
    v = pva.get("values") or {}
    tiles: list[dict] = []
    bullets: list[Any] = []
    # time
    if done:
        dmax = max(float(d.get("delay_days") or 0) for d in done)
        d0 = max(done, key=lambda d: float(d.get("delay_days") or 0))
        tiles.append({"value": _days(dmax, True) if dmax > 0 else "w terminie", "label": "Termin wobec umowy",
                      "foot": f"plan {_days(d0.get('planned_days'))}, wykonanie {_days(d0.get('actual_days'))}; obliczenie, n = {len(done)} z {n_c} umów",
                      "tone": "attention" if dmax > 0 else None})
        for d in done:
            bullets.append(K.tagged("calc", f"Termin ({_lot(d.get('lot_no'))}): plan {_days(d.get('planned_days'))} do {K.fmt_date(d.get('planned_end_on'))}, "
                                    f"zakończono {K.fmt_date(d.get('completed_on'))} po {_days(d.get('actual_days'))}: "
                                    + (f"{_days(d.get('delay_days'), True)} po terminie" if (d.get("delay_days") or 0) > 0 else "w terminie")
                                    + f" (ogłoszenie o wykonaniu {d.get('performance_notice') or 'brak'}, n = 1 umowa)."))
    else:
        tiles.append({"value": "brak danych", "label": "Termin wobec umowy", "foot": "brak ogłoszenia o wykonaniu umowy", "tone": "attention"})
        bullets.append(K.tagged("calc", "Termin: brak ogłoszenia o wykonaniu umowy, więc nie znamy faktycznego zakończenia."))
    # cost
    if v.get("cost_dev_pct") is not None:
        cd = float(v["cost_dev_pct"])
        tiles.append({"value": f"{'+' if cd > 0 else ''}{K.fmt_num(cd, 1)}%", "label": "Wypłacono wobec umowy",
                      "foot": f"{K.mln(v['paid_total']['amount'])} wobec {K.mln(v['contracts_total']['amount'])}, oba brutto",
                      "tone": "attention" if cd > 0 else None})
        est = v.get("estimate_bzp")
        bullets.append(K.tagged("calc", f"Koszt: wartość umów {K.money_pl(v.get('contracts_total'))}, wypłacono {K.money_pl(v.get('paid_total'))} "
                                f"({'+' if cd > 0 else ''}{K.fmt_num(cd, 1)}%). "
                                + (f"Szacunek zamawiającego w BZP to {K.money_pl(est)}, więc nie porównujemy go z kwotami brutto." if est else "")))
    else:
        tiles.append({"value": "brak danych", "label": "Wypłacono wobec umowy", "foot": "brak kwoty wypłaconej w BZP"})
    # changes
    uniq, reps = _unique_changes(x)
    bzp = [c for c in uniq if c.get("kind") != "document_change"]
    docs = [c for c in uniq if c.get("kind") == "document_change"]
    bases = sorted({b for c in bzp for b in c.get("legal_basis") or []})
    tiles.append({"value": str(len(uniq)), "label": "Zmiany umowy", "foot": f"BZP: {len(bzp)}, z dokumentów: {len(docs)}"
                  + (f"; powtórzenia pominięte: {len(reps)}" if reps else "")})
    if uniq:
        kinds = sorted({CHANGE_TYPE_PL.get(t, t) for c in uniq for t in c.get("change_types") or []})
        bullets.append(K.tagged("src", f"Zmiany umowy: {len(bzp)} w ogłoszeniach BZP"
                                + (f", podstawa: {_legal(bases)}," if bases else "")
                                + (f" i {len(docs)} z dokumentów, do zatwierdzenia przez eksperta" if docs else "")
                                + (f"; zakres zmian: {', '.join(kinds)}" if kinds else "") + "."))
    else:
        bullets.append(K.tagged("src", "Zmiany umowy: brak w ogłoszeniach BZP i w dokumentach."))
    # link
    lk = (x.get("links") or [None])[0]
    if lk:
        tiles.append({"value": K.fmt_num(float(lk["score"]), 2) if lk.get("score") is not None else "tak", "label": "Powiązanie z BZP",
                      "foot": f"{lk.get('contract_notice_no') or lk['ocid']}; {lk.get('method_label')}"})
    else:
        tiles.append({"value": "brak", "label": "Powiązanie z BZP", "foot": "nie znaleziono postępowania", "tone": "attention"})
    # risk events
    facts = _event_groups(x.get("risk_events") or [])
    by_code: dict[str, int] = {}
    for g in facts:
        if g.get("risk_code"):
            by_code[_code_root(g["risk_code"])] = by_code.get(_code_root(g["risk_code"]), 0) + 1
    n_ai = sum(1 for e in x.get("risk_events") or [] if e.get("proposal"))
    if by_code or n_ai:
        bullets.append(K.tagged("calc", f"Ryzyka: {K.plural(sum(by_code.values()), 'zdarzenie', 'zdarzenia', 'zdarzeń')} z kodem R potwierdzone danymi"
                                + (f" ({', '.join(f'{c} x{k}' for c, k in sorted(by_code.items()))})" if by_code else "")
                                + (f"; kolejne {K.plural(n_ai, 'zdarzenie to propozycja', 'zdarzenia to propozycje', 'zdarzeń to propozycje')} AI do weryfikacji (sekcja 7)" if n_ai else "") + "."))
    # what changed
    dups = _dup_docs(x)
    for w in x.get("whats_changed") or []:
        if w.get("document_id") in dups:
            continue
        ag = w.get("aggregates") or {}
        bits = []
        if ag.get("planned_end"):
            bits.append(f"planowany koniec z {ag['planned_end'].get('before')} na {ag['planned_end'].get('after')}")
        if ag.get("delay_days"):
            bits.append(f"opóźnienie z {ag['delay_days'].get('display_before')} na {ag['delay_days'].get('display_after')}")
        if bits:
            bullets.append(K.tagged("pending", f"Co się zmieniło: dokument „{w.get('document')}” ({K.fmt_date(w.get('date'))}) zmienia {', '.join(bits)}. "
                                    "Czeka na decyzję eksperta, liczby w kaflach są jeszcze z BZP."))
            break
    # similar
    sim = x.get("similar_cases") or []
    if sim:
        late = [s for s in sim if ((s.get("outcome") or {}).get("delay_days") or {}).get("value") not in (None, 0, 0.0)
                and float(s["outcome"]["delay_days"]["value"]) > 0]
        bullets.append(K.tagged("calc", f"Podobne przypadki: {len(late)} z {len(sim)} najbardziej podobnych umów (ten sam podsektor, zbliżona wartość) "
                                "skończyło się po terminie (wyniki z ogłoszeń o wykonaniu)."))
    # quality
    ri = x.get("review_items") or []
    q = quality(x)
    n_ai_all = len(x.get("ai_proposals") or [])
    if ri or q or n_ai_all:
        bullets.append(K.tagged("pending", f"Jakość danych: przy eksporcie wykryto {K.plural(len(q), 'rozbieżność lub lukę', 'rozbieżności lub luki', 'rozbieżności lub luk')}; "
                                f"w Przeglądzie {K.plural(len(ri), 'otwarta sprawa', 'otwarte sprawy', 'otwartych spraw')}, w tym propozycje AI "
                                f"({n_ai_all}). Nic nie poprawiamy bez decyzji eksperta (sekcja 8)."))
    status = r.get("status") or "status nieznany"
    state = f"Stan rekordu: {status.lower()}. {pva.get('summary') or ''}".strip()
    return tiles, bullets[:6], state


def blocks(x: dict) -> K.Blocks:
    r, pva = x["record"], x.get("plan_vs_actual") or {}
    meta = x.get("meta") or {}
    gen = meta.get("generated_at")
    try:
        gen_dt = datetime.fromisoformat(str(gen)) if gen else None
    except ValueError:
        gen_dt = None
    B = K.Blocks(doc_title="Eksport rekordu projektu", doc_id=r["rm_id"], generated_at=gen_dt, subject=r.get("title") or "")
    bname = (r.get("beneficiary") or {}).get("name") or ""
    B.title("Eksport rekordu projektu", f"Rekord projektu {r['rm_id']}", [
        {"t": r.get("title") or "", "b": True, "c": K.INK, "s": 11.5},
        f"{bname}, {ids.WOJ.get((r.get('location') or {}).get('teryt_woj') or '', '')} | {r.get('public_id_type') or 'identyfikator'}: {r.get('public_id') or 'brak'}",
        f"Widok: {meta.get('view', 'ekspert')}. Dane z bazy ex ante w chwili eksportu; każdy fakt ma oznaczenie pochodzenia (legenda niżej)."])
    tiles, bullets, state = _summary(x)
    B.h1("Najważniejsze wnioski")
    B.p({"t": state, "b": True})
    B.tiles(tiles)
    B.bullets(bullets)
    B.legend(["src", "calc", "ai", "pending", "approved"])

    # 1 ------------------------------------------------------------------------------------------------------------
    B.page_break()
    B.h1("1. Identyfikacja i finansowanie")
    f = r.get("funding") or {}
    b = r.get("beneficiary") or {}
    src = r.get("source") or {}
    loc = r.get("location") or {}
    share = ""
    try:
        if f.get("value") and f.get("subsidy") and f["value"]["vat_basis"] == f["subsidy"]["vat_basis"]:
            share = f" ({K.fmt_num(float(f['subsidy']['amount']) / float(f['value']['amount']) * 100, 1)}% wartości, obliczenie)"
    except (TypeError, ValueError, ZeroDivisionError):
        share = ""
    t_src = _tag_of(r.get("origin"), r.get("review_status"))
    rows = [["Identyfikator rekordu", [t_src, " ", r["rm_id"]]],
            ["Nazwa przedsięwzięcia", r.get("title") or "brak"],
            ["Odbiorca (zamawiający)", f"{b.get('name') or 'brak'}, NIP {b.get('nip') or 'brak'}"
             + (" (suma kontrolna poprawna)" if b.get("nip_valid") else " (błędna suma kontrolna)" if b.get("nip_valid") is False else "")
             + (f"; w BZP: {b['name_in_bzp']}" if b.get("name_in_bzp") and b.get("name_in_bzp") != b.get("name") else "")],
            ["Lokalizacja", f"{ids.WOJ.get(loc.get('teryt_woj') or '', '') or 'województwo nieznane'} (TERYT {loc.get('teryt_woj') or 'brak'}), {loc.get('city') or 'brak'}"],
            ["Identyfikator publiczny", f"{r.get('public_id_type') or ''}: {r.get('public_id') or 'brak'}"],
            ["Zakres i status", f"{r.get('scope') or 'brak'}; {r.get('status') or 'brak'}"],
            ["Podsektor i formuła", f"{r.get('subsector_main') or 'brak'}, {DELIVERY_PL.get(r.get('delivery_model'), r.get('delivery_model') or 'brak')}"],
            ["Program", f.get("programme") or "brak"],
            ["Wartość przedsięwzięcia", K.money_pl(f.get("value"))],
            ["Dofinansowanie", K.money_pl(f.get("subsidy")) + share],
            ["Data i wersja rekordu", f"{K.fmt_date(r.get('record_date')) or 'brak'}, wersja {r.get('record_version') or 'brak'}"]]
    if r.get("description"):
        rows.append(["Przedmiot (z rekordu)", r["description"]])
    if r.get("annotation"):
        rows.append(["Adnotacja instytucji", r["annotation"]])
    if src:
        rows.append(["Plik źródłowy", [_link(src.get("url") or src.get("path") or "", src.get("url")),
                                       f", pobrano {K.fmt_date(src.get('retrieved_at'))}, sha256 ", {"t": (src.get("sha256") or "")[:16] + "…", "mono": True}]])
    B.kv(rows)
    if f.get("value"):
        B.note(f.get("note") or "")

    # 2 ------------------------------------------------------------------------------------------------------------
    B.h1("2. Powiązanie z postępowaniem w BZP i TED")
    links = x.get("links") or []
    if not links:
        B.callout("Nie znaleziono postępowania w BZP. Eksport pokazuje tylko dane z rekordu; powiązanie może wskazać ekspert w Przeglądzie.",
                  tone="attention", title="Brak powiązania")
    for lk in links:
        feats = lk.get("features") or {}
        fb = [f"{FEATURE_PL[k]}: {K.fmt_num(float(v), 2) if isinstance(v, float) else _b(v)}" for k, v in feats.items() if k in FEATURE_PL]
        vc = lk.get("value_check") or {}
        rows = [["Postępowanie", [K.tag("calc"), " ", {"t": lk.get("contract_notice_no") or "", "b": True}, f" {lk.get('title') or ''}"]],
                ["OCID", {"t": lk["ocid"], "mono": True, "s": 7.5}],
                ["Zamawiający w BZP", f"{lk.get('buyer') or 'brak'}, NIP {lk.get('buyer_nip') or 'brak'}"],
                ["Metoda powiązania", lk.get("method_label") or lk.get("method") or ""],
                ["Wynik dopasowania", f"{_sc(lk.get('score'))} w skali 0 do 1; {DECISION_PL.get(lk.get('decision'), STATUS_PL.get(lk.get('review_status'), ''))}"],
                ["Uzasadnienie", _iso_pl((lk.get("explanation") or "") + (f". Cechy: {'; '.join(fb)}" if fb else ""))],
                ["Szacunek zamawiającego", K.money_pl(lk.get("estimate"))]]
        if lk.get("chain"):
            rows.append(["Łańcuch ogłoszeń", ", ".join(lk["chain"])])
        if vc:
            rows.append(["Kontrola wartości", f"wartość z rekordu wobec: {vc.get('closest')}, różnica {K.fmt_num(float(vc.get('diff_pct') or 0), 1)}%"])
        ext = r.get("external_ids") or {}
        rows.append(["TED", ext.get("ted") or "brak ogłoszenia TED w danych tego projektu"])
        B.kv(rows)
    alts = [a for a in x.get("link_alternatives") or [] if a.get("rank") != 1]
    if alts:
        B.h2("Inni kandydaci (nie powiązani)")
        B.table(["Postępowanie (OCID)", "Metoda", "Wynik", "Decyzja", "Uzasadnienie"],
                [[{"t": a["ocid"], "mono": True, "s": 6.8}, METHOD_PL.get(a.get("method"), a.get("method")), _sc(a.get("score")),
                  DECISION_PL.get(a.get("decision"), a.get("decision") or ""), _iso_pl(a.get("explanation"))] for a in alts[:6]],
                [5.4, 2.6, 1.2, 2.0, 6.2], right=(2,))

    # 3 ------------------------------------------------------------------------------------------------------------
    B.h1("3. Umowy i przebieg")
    cs = x.get("contracts") or []
    if cs:
        B.table(["Część", "Wykonawca", "Podpisano", "Termin umowny", "Wartość umowy", "Ogłoszenie o wyniku"],
                [[[_tag_of(c.get("origin"), c.get("review_status")), " ", _lot(c.get("lot_no"))],
                  f"{c.get('contractor') or 'nieznany'}" + (f", NIP {c['contractor_nip']}" if c.get("contractor_nip") else ""),
                  K.fmt_date(c.get("signed_on")), f"{_days(c.get('planned_duration_days'))}, do {K.fmt_date(c.get('planned_end_on'))}",
                  K.money_pl(c.get("value")), c.get("result_notice_no") or "brak"] for c in cs],
                [2.4, 4.4, 1.9, 2.9, 3.4, 2.4])
    else:
        B.p("Brak umowy w BZP.")
    dups0 = _dup_docs(x)
    tl = [s for s in x.get("timeline") or [] if not ((s.get("ref") or {}).get("kind") == "document" and str((s.get("ref") or {}).get("id")) in {str(k) for k in dups0})]
    if tl:
        B.h2("Oś czasu")
        B.table(["Data", "Etap", "Szczegóły", "Źródło"],
                [[s.get("date_label") or K.fmt_date(s.get("date")) or "brak daty",
                  [_tag_of("SOURCE", s.get("review_status")), " ", {"t": s.get("title") or "", "b": True}],
                  s.get("text") or "",
                  _link(f"{(s.get('ref') or {}).get('label') or ''} {(s.get('ref') or {}).get('id') or ''}".strip(), (s.get("ref") or {}).get("url"))
                  if s.get("ref") else ""] for s in tl],
                [2.0, 4.2, 7.4, 3.8])

    # 4 ------------------------------------------------------------------------------------------------------------
    B.h1("4. Plan i wykonanie")
    B.p(pva.get("summary") or "")
    for d in pva.get("dates") or []:
        B.h2(f"Umowa: {_lot(d.get('lot_no'))}")
        dd = d.get("delay_days")
        B.table(["Miara", "Plan (umowa)", "Wykonanie", "Różnica"],
                [["Podpisanie umowy", K.fmt_date(d.get("signed_on")) or "brak", "", ""],
                 ["Czas realizacji", _days(d.get("planned_days")) or "brak", _days(d.get("actual_days")) or "brak",
                  [K.tag("calc"), " ", _days(dd, True) if dd is not None else "brak"]],
                 ["Zakończenie", K.fmt_date(d.get("planned_end_on")) or "brak", K.fmt_date(d.get("completed_on")) or "brak", ""],
                 ["Kwota", K.money_pl(d.get("contract_value")), K.money_pl(d.get("paid")),
                  [K.tag("calc"), " ", f"{K.fmt_num(float(d['cost_dev_pct']), 1)}%" if d.get("cost_dev_pct") is not None else "brak"]],
                 ["Zmiany zadeklarowane", "", "" if d.get("changes_count") is None else str(d.get("changes_count")), ""],
                 ["Należyte wykonanie", "", _b(d.get("properly_performed")) if d.get("properly_performed") is not None else "brak", ""],
                 ["Źródło", "ogłoszenie o wyniku i umowa",
                  _link(d.get("performance_notice") or "brak ogłoszenia o wykonaniu", d.get("performance_url")), "wzór: koniec minus podpisanie; wypłata / umowa minus 1"]],
                [3.4, 4.2, 4.6, 5.2], first_bold=True)
    v = pva.get("values") or {}
    B.p(f"Szacunek zamawiającego (BZP): {K.money_pl(v.get('estimate_bzp'))}. Umowy razem: {K.money_pl(v.get('contracts_total'))}. "
        f"Wypłacono razem: {K.money_pl(v.get('paid_total'))}. Wartość przedsięwzięcia z rekordu: {K.money_pl(v.get('funding_value'))}.")
    B.note(pva.get("vat_note") or "")

    # 5 ------------------------------------------------------------------------------------------------------------
    B.h1("5. Zmiany umowy")
    chg = x.get("changes") or []
    reps = _change_repeats(chg)
    if chg:
        rows = []
        for c in chg:
            cause: list = [_quote(c.get("cause") or c.get("description"), 220) or "przyczyna nie podana"]
            if c.get("ai_cause"):
                a = c["ai_cause"]
                cause += ["\n", K.tag("ai" if a.get("proposal") else "approved"), f" przyczyna: {a.get('risk_code')}"]
            if c["change_id"] in reps:
                cause += ["\n", {"t": f"Powtórzenie: {reps[c['change_id']]}.", "i": True, "c": K.MUTED}]
            srcl = c.get("notice") or (c.get("document") or {}).get("title") or ""
            rows.append([K.fmt_date(c.get("changed_on")) or "brak daty",
                         [_tag_of(c.get("origin"), c.get("review_status")), " ", c.get("kind_label") or "", " ", _link(srcl, c.get("url"))],
                         _legal(c.get("legal_basis")),
                         ", ".join(CHANGE_TYPE_PL.get(t, t) for t in c.get("change_types") or []) or "brak",
                         _days(c.get("delta_days"), True) or "brak",
                         K.money_pl(c.get("delta_value")), cause])
        B.table(["Data", "Źródło", "Podstawa prawna", "Zakres", "Termin", "Kwota", "Przyczyna (cytat)"], rows,
                [1.8, 3.4, 3.0, 1.5, 1.4, 2.3, 4.0], size=7.5, shade_rows={i: K.BAND for i, c in enumerate(chg) if c["change_id"] in reps}, zebra=False)
        B.note("Podstawy prawne według ustawy Prawo zamówień publicznych. Kwoty zmian podajemy tak, jak w źródle, z podstawą VAT; "
               "wiersze szare powtarzają inne źródło i nie są liczone drugi raz.")
    else:
        B.p("Brak zmian umowy w BZP i w dokumentach.")

    # 6 ------------------------------------------------------------------------------------------------------------
    B.h1("6. Zdarzenia ryzyka według kodów R")
    ev = x.get("risk_events") or []
    facts = _event_groups(ev)
    codes: dict[str, dict] = {}
    for e in ev:
        c = _code_root(e.get("risk_code"))
        d = codes.setdefault(c, {"name": e.get("risk_name") or RISK_FALLBACK.get(c) if c != "bez kodu" else "skutek bez wskazanej przyczyny",
                                 "facts": 0, "pending": 0, "ai": 0, "ex": None})
        k = "ai" if e.get("proposal") else "pending" if e.get("review_status") == "proposed" else "facts"
        d[k] += 1
        if not d["ex"] and e.get("evidence"):
            d["ex"] = e["evidence"][0]
        if not d.get("name") and e.get("risk_name"):
            d["name"] = e["risk_name"]
    if codes:
        B.table(["Kod R", "Ryzyko (Katalog)", "Fakty", "Do decyzji", "AI", "Przykładowy dowód"],
                [[{"t": c, "b": True}, d.get("name") or "", str(d["facts"]), str(d["pending"]), str(d["ai"]), _ev_where(d["ex"]) if d["ex"] else ""]
                 for c, d in sorted(codes.items(), key=lambda kv: (kv[0] == "bez kodu", kv[0]))],
                [1.8, 4.6, 1.2, 1.7, 1.0, 7.1], size=7.5, right=(2, 3, 4))
        B.note("Fakty: zdarzenia z ogłoszeń BZP i obliczenia. Do decyzji: wyczytane regułą z dokumentu, czekają na eksperta. AI: propozycje modelu "
               "(sekcja 7, Załącznik B). Liczby przed scaleniem powtórzeń.")
    if facts:
        B.h2("Zdarzenia potwierdzone danymi albo czekające na zatwierdzenie")
        rows = []
        for g in sorted(facts, key=lambda g: (g.get("risk_code") is None, g.get("risk_code") or "", str(g.get("occurred_on") or ""))):
            impact = ", ".join(s for s in (_days(g.get("impact_days"), True), K.money_pl(g.get("impact_value"), ""),
                                           f"{K.fmt_num(g['impact_pct'], 1)}%" if g.get("impact_pct") is not None else "") if s) or "brak"
            evs: list = []
            seen_q: dict[tuple, list] = {}
            for q in g["all_evidence"]:
                seen_q.setdefault((q.get("quote"), q.get("page_no"), q.get("field_code")), []).append(q)
            for i, qs in enumerate(list(seen_q.values())[:3]):
                if i:
                    evs.append("\n")
                evs += _ev_where(qs[0])
                if len(qs) > 1:
                    evs.append({"t": " (to samo także w: " + ", ".join(q.get("notice_number") or f"dokument {q.get('document_id')}" for q in qs[1:]) + ")",
                                "c": K.MUTED})
            rows.append([{"t": g.get("risk_code") or "bez kodu", "b": True},
                         [g.get("summary") or ""] + ([{"t": f" (x{g['count']})", "c": K.MUTED}] if g["count"] > 1 else []),
                         K.fmt_date(g.get("occurred_on")) or "brak", impact, evs or "brak", [_tag_of(g.get("origin"), g.get("review_status"))]])
        B.table(["Kod R", "Zdarzenie", "Data", "Skutek", "Dowód (źródło, pole albo strona, cytat)", "Status"], rows,
                [1.8, 3.8, 1.8, 1.8, 5.6, 2.6], size=7.5)
    sim = x.get("similar_cases") or []
    B.h2("Podobne przypadki")
    if sim:
        rows = []
        for s in sim:
            o = s.get("outcome") or {}
            refs = ((o.get("delay_days") or {}).get("prov") or {}).get("refs") or []
            ref = refs[0] if refs else {}
            rows.append([str(s.get("rank") or ""), s.get("title") or "", f"{s.get('buyer_name') or ''}" + (f", {s['year']}" if s.get("year") else ""),
                         (s.get("score") or {}).get("display") or "", (o.get("delay_days") or {}).get("display") or "",
                         (o.get("cost_dev_pct") or {}).get("display") or "", "" if s.get("changes_count") is None else str(s["changes_count"]),
                         _link(str(ref.get("id") or ""), ref.get("url"))])
        B.table(["#", "Umowa", "Zamawiający, rok", "Wynik", "Opóźnienie", "Koszt", "Zmiany", "Ogłoszenie o wykonaniu"], rows,
                [0.6, 5.0, 2.9, 1.3, 1.9, 1.5, 1.5, 2.7], size=7.5, right=(3, 4, 5, 6))
        B.note(f"Obliczenie: wynik podobieństwa 0 do 1 z podsektora, wartości umowy i formuły (metoda similarity_simple, pula n = "
               f"{((sim[0].get('score') or {}).get('prov') or {}).get('n', 'brak')} umów). Wynik każdej umowy z jej ogłoszenia o wykonaniu.")
    else:
        B.p("Brak podobnych umów w bazie dla tego podsektora i wartości.")

    # 7 ------------------------------------------------------------------------------------------------------------
    B.h1("7. Propozycje AI (do weryfikacji)")
    ai = x.get("ai_proposals") or []
    if ai:
        kinds: dict[str, dict] = {}
        for a in ai:
            d = kinds.setdefault(a.get("what") or "inne", {"n": 0, "codes": set()})
            d["n"] += 1
            if a.get("risk_code"):
                d["codes"].add(_code_root(a["risk_code"]))
        B.p(f"Model językowy zaproponował {K.plural(len(ai), 'pozycję', 'pozycje', 'pozycji')}. To nie są fakty: nie wchodzą do statystyk ani do wniosków na stronie 1, "
            "dopóki ekspert ich nie zatwierdzi. Każda ma cytat ze źródła; pełna lista z cytatami jest w Załączniku B.")
        B.table(["Rodzaj propozycji", "Liczba", "Kody R"], [[k, str(d["n"]), ", ".join(sorted(d["codes"])) or "brak"] for k, d in kinds.items()],
                [6.4, 1.6, 9.4], right=(1,))
    else:
        B.p("Brak propozycji AI dla tego projektu.")
    if meta.get("unverified_ai_hidden"):
        B.note(f"Widok publiczny: ukryto {meta['unverified_ai_hidden']} niezweryfikowanych propozycji AI.")

    # 8 ------------------------------------------------------------------------------------------------------------
    B.h1("8. Jakość danych: rozbieżności, luki i sprawy do przeglądu")
    q = quality(x)
    ri = x.get("review_items") or []
    B.callout(f"Wykryto: {K.plural(len(q), 'rozbieżność lub luka', 'rozbieżności lub luki', 'rozbieżności lub luk')}. W Przeglądzie: {K.plural(len(ri), 'otwarta sprawa', 'otwarte sprawy', 'otwartych spraw')}. Rozbieżności pokazujemy, ale ich nie poprawiamy: "
              "decyzję podejmuje ekspert, a każda decyzja trafia do dziennika zmian.", tone="attention" if q or ri else "info", title="Wymaga uwagi" if q or ri else "Bez uwag")
    if q:
        B.table(["Rodzaj", "Opis", "Co dalej"], [[{"t": it["kind"], "b": True}, it["text"], it["action"]] for it in q], [3.0, 10.4, 4.0], size=7.8)
    if ri:
        kinds2: dict[str, int] = {}
        for i in ri:
            kinds2[REVIEW_KIND_PL.get(i["kind"], i["kind"])] = kinds2.get(REVIEW_KIND_PL.get(i["kind"], i["kind"]), 0) + 1
        B.h2("Otwarte sprawy w Przeglądzie")
        B.p("; ".join(f"{k}: {v}" for k, v in kinds2.items()) + ".")
        main = [i for i in ri if i["kind"] in ("discrepancy", "fact", "document", "link")][:14]
        if main:
            B.table(["Nr", "Rodzaj", "Opis", "Waga"], [[str(i["id"]), REVIEW_KIND_PL.get(i["kind"], i["kind"]), i["title"], SEVERITY_PL.get(i.get("severity"), i.get("severity") or "")]
                                                    for i in main], [1.1, 3.6, 11.0, 1.7], size=7.5)
        if len(ri) > len(main):
            B.note(f"Pełna lista {len(ri)} spraw: Załącznik D.")

    # 9 ------------------------------------------------------------------------------------------------------------
    B.h1("9. Dokumenty i „Co się zmieniło”")
    docs = x.get("documents") or []
    dups = _dup_docs(x)
    B.p(f"Projekt ma w bazie {K.plural(len(docs), 'dokument', 'dokumenty', 'dokumentów')} (lista z sha256: Załącznik C)." if docs else "Brak dokumentów projektu w bazie.")
    wc = [w for w in x.get("whats_changed") or [] if w.get("document_id") not in dups]
    if wc:
        for w in wc:
            B.h2(f"{w.get('document')} ({K.fmt_date(w.get('date')) or 'bez daty'}), dokument {w.get('document_id')}")
            rows = []
            for key, label, tg in (("zmienione", "zmienione", "pending"), ("nowe", "nowe", "pending"), ("potwierdzone", "potwierdzone", "src"),
                                   ("zamkniete", "zamknięte", "pending")):
                for it in w.get(key) or []:
                    val = it.get("value") or (f"z {it.get('before')} na {it.get('after')}" if it.get("before") or it.get("after") else "")
                    rows.append([[K.tag(tg), " ", label], it.get("label") or "", str(val), it.get("where") or it.get("why") or ""])
            if rows:
                B.table(["Zmiana", "Co", "Wartość", "Skąd wiemy"], rows, [3.3, 4.4, 4.0, 5.7], size=7.5)
        if dups:
            B.note("Kopie tego samego pliku (" + ", ".join(f"dokument {a} = {b}" for a, b in dups.items()) + ") pominięto, bo dają te same zmiany.")
    else:
        B.p("Brak nowych dokumentów z wyczytanymi faktami, więc nic się nie zmieniło od rekordu i BZP.")

    # 10 -----------------------------------------------------------------------------------------------------------
    B.page_break()
    B.h1("10. Źródła, metoda i ograniczenia")
    srcs = x.get("sources") or []
    groups: dict[str, dict] = {}
    for s in srcs:
        g = groups.setdefault(s.get("kind") or "inne", {"n": 0, "dates": set(), "licence": s.get("licence") or ""})
        g["n"] += 1
        if s.get("retrieved_at"):
            g["dates"].add(K.fmt_date(s["retrieved_at"]))
    B.h2("Zbiory danych")
    B.table(["Zbiór", "Plików", "Pobrano", "Licencja"],
            [[SOURCE_KIND_PL.get(k, k), str(g["n"]), ", ".join(sorted(g["dates"])), g["licence"]] for k, g in groups.items()],
            [5.6, 1.4, 3.6, 6.8], right=(1,))
    B.h2("Lista źródeł")
    B.table(["Nr", "Rodzaj", "Adres albo plik", "Pobrano", "sha256"],
            [[str(s["id"]), SOURCE_KIND_PL.get(s.get("kind"), s.get("kind") or ""), _link(_short_url(s.get("url") or s.get("path"), 52), s.get("url")),
              K.fmt_date(s.get("retrieved_at")), {"t": s.get("sha256") or "", "mono": True, "s": 6.2}] for s in srcs],
            [1.3, 3.4, 5.4, 1.9, 5.4], size=7.2)
    B.h2("Metoda")
    models = meta.get("models") or []
    B.bullets([
        ("Powiązanie rekordu z BZP: kolejno numer ogłoszenia z rekordu, numer KPO powołany w ogłoszeniach zamawiającego, a gdy ich brak NIP, nazwa, CPV "
         "i data; wynik dopasowania 0 do 1, poniżej progu sprawa trafia do Przeglądu."),
        ("Plan i wykonanie: obliczenia z ogłoszenia o wyniku (podpisanie, termin, wartość) i ogłoszenia o wykonaniu (zakończenie, wypłata, zmiany). "
         "Opóźnienie = zakończenie minus planowany koniec; odchylenie kosztu = wypłata / wartość umowy minus 1, oba brutto."),
        "Kody R z Katalogu ryzyk wod-kan (sektorowy pakiet ekspertów); zdarzenia z ogłoszeń BZP i z dokumentów reguły przypisują deterministycznie.",
        "Reguły bez AI: powiązanie, plan i wykonanie, rozbieżności, podobne przypadki. Model językowy: tylko propozycje (przyczyny zmian, zdarzenia z "
        "dokumentów), zawsze z cytatem i weryfikacją cytatu w tekście źródła."
        + (f" Użyty model: {', '.join(models)}." if models else ""),
        "Każda decyzja eksperta jest zapisana w dzienniku (append-only); zatwierdzonych danych model nie nadpisuje."])
    B.h2("Ograniczenia")
    B.bullets([
        "Kwoty z rekordu instytucji nie mają podstawy VAT; szacunek w BZP jest netto, umowy i wypłaty brutto, więc porównujemy tylko kwoty tej samej podstawy.",
        "Ogłoszenie o wykonaniu umowy podaje stan na dzień publikacji; późniejsze aneksy widać dopiero w nowych ogłoszeniach albo dokumentach.",
        "Dopłata liczona wobec wartości umowy z ogłoszenia o wykonaniu jest dolną granicą (nie widać kosztów poza umową).",
        "Propozycje AI mogą się mylić (ok. 8 na 10 trafień na próbie wzorcowej przyczyn zmian); dlatego czekają na eksperta.",
        f"Eksport pokazuje stan bazy w chwili wygenerowania; bieżąca wersja: {K.APP_URL}/projekty/{r['rm_id']}."])

    # appendices -----------------------------------------------------------------------------------------------------
    nts = x.get("notices") or []
    if nts:
        B.page_break()
        B.h1("Załącznik A. Ogłoszenia BZP w łańcuchu postępowania")
        B.table(["Ogłoszenie", "Rodzaj", "Opublikowano", "Adres"],
                [[{"t": n["notice_number"], "b": True}, n.get("type_label") or "", K.fmt_date(n.get("published_at")), _link(_short_url(n.get("url"), 60), n.get("url"))]
                 for n in nts], [3.6, 4.0, 2.2, 7.6], size=7.5)
    if ai:
        B.h1("Załącznik B. Propozycje AI (niezatwierdzone)")
        B.table(["#", "Rodzaj", "Dotyczy", "Kod R", "Cytat ze źródła (miejsce)", "Zgodność", "Pewność"],
                [[str(i), a.get("what") or "", a.get("on") or "", a.get("risk_code") or "",
                  [_quote(a.get("quote"), 220)] + ([{"t": f" ({a['where']})", "c": K.MUTED}] if a.get("where") else []),
                  {"exact": "dokładny", "fuzzy": "przybliżony"}.get(a.get("verification"), a.get("verification") or ""),
                  K.fmt_num(float(a["confidence"]), 2) if a.get("confidence") is not None else ""] for i, a in enumerate(ai, 1)],
                [0.7, 2.3, 3.8, 1.4, 6.2, 1.6, 1.4], size=7.2)
        B.note("Weryfikacja cytatu: „dokładny” = cytat występuje słowo w słowo w tekście źródła; „przybliżony” = po normalizacji odstępów i znaków.")
    if docs:
        B.h1("Załącznik C. Dokumenty projektu")
        B.table(["Nr", "Dokument", "Rodzaj", "Strony", "sha256"],
                [[str(d["id"]), _link(d.get("title") or d.get("filename") or "", d.get("url")) if d.get("url") else (d.get("title") or d.get("filename") or ""),
                  d.get("kind_label") or d.get("doc_type") or "", K.fmt_num(d["pages"]) if d.get("pages") else "",
                  [{"t": d.get("sha256") or "", "mono": True, "s": 6.2}] + ([{"t": f" kopia dokumentu {dups[d['id']]}", "i": True, "c": K.MUTED}] if d["id"] in dups else [])]
                 for d in docs], [1.3, 6.4, 2.0, 1.3, 6.4], size=7.2, right=(3,))
    if ri:
        B.h1("Załącznik D. Wszystkie otwarte sprawy w Przeglądzie")
        B.table(["Nr", "Rodzaj", "Opis", "Waga", "Utworzono"],
                [[str(i["id"]), REVIEW_KIND_PL.get(i["kind"], i["kind"]), i["title"], SEVERITY_PL.get(i.get("severity"), i.get("severity") or ""),
                  K.fmt_date(i.get("created_at"))] for i in ri], [1.1, 3.4, 9.3, 1.5, 2.1], size=7.2)
    return B


def to_markdown(x: dict) -> str:
    return blocks(x).to_markdown()


def to_docx(x: dict) -> bytes:
    return blocks(x).to_docx()


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
