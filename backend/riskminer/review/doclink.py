"""G3: link a document with extracted facts (`document.data->'facts'`, written by the LLM session's `document_extract`) to the
case base, validate identifiers and turn everything into PROPOSALS for the expert.

Resolves: project (exact KPO number 1.0, upload binding 0.9, fuzzy buyer/title), contract (buyer + signing date + contractor
+ old planned end + scope, with score and features; always a review item, BZP has no contract numbers). Validates NIP/REGON
checksums, the KPO `IW.nn` rule (12 + voivodeship TERYT / 2) and the existence of the project. Contract-level changes become
`contract_change` (kind `document_change`, proposed); grant-level ones (KPO schedule) become a project event
(`risk_event` EV_PROJECT_TERM_CHANGE). Causes and effects become `risk_event`s with evidence (document page + verified quote).
Nothing is fixed silently: mismatches are `review_item` rows. Idempotent by keys (`doc:<id>:...`).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from rapidfuzz import fuzz
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.auth import ApiError
from riskminer.ingest.ids import kpo_check
from riskminer.review.common import audit, jdump
from riskminer.validators import nip_valid, regon_valid

ACTOR = "system:doc_link"
EVT_CAUSE, EVT_TERM, EVT_EFFECT = "EV_DOC_CAUSE", "EV_PROJECT_TERM_CHANGE", "EV_LINKED_INVESTMENT_DELAY"
VERIF = {"exact": "exact", "fuzzy": "fuzzy", "unverified": "unverified", "structured_field": "structured_field"}


async def _rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def _scalar(db: AsyncSession, sql: str, **p) -> Any:
    return (await db.execute(text(sql), p)).scalar()


def _d(x: Any) -> date | None:
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10]) if x else None
    except ValueError:
        return None


def pl_date(d: Any) -> str:
    d = _d(d)
    return d.strftime("%d.%m.%Y") if d else ""


_FORMS = re.compile(r"\b(sp\.?\s*z\s*o\.?\s*o\.?|sp\.?\s*k\.?|s\.?\s*a\.?|spółka|spolka|z ograniczon\w+|odpowiedzialno\w+|komandytow\w+|akcyjn\w+|jawn\w+|przedsi[eę]biorstwo|firma|zak[łl]ad)\b", re.I)


def company_core(name: str | None) -> str:
    """Company name without legal-form words ('WIMAX Sp. z o.o.' -> 'wimax')."""
    return re.sub(r"\s+", " ", _FORMS.sub(" ", re.sub(r"[.,;()\"]", " ", name or ""))).strip().lower()


def _sim(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a.lower(), b.lower()) / 100


# ------------------------------------------------------------------------------------------------------------ validation

def _digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def nearest_registry_nip(bad: str, candidates: list[str]) -> str | None:
    """A valid NIP in the registry that differs from `bad` by one digit (typo) or one transposition."""
    b = _digits(bad)
    for c in candidates:
        c = _digits(c)
        if len(c) == len(b) == 10 and c != b:
            diff = [i for i in range(10) if c[i] != b[i]]
            if len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and c[diff[0]] == b[diff[1]] and c[diff[1]] == b[diff[0]]):
                if nip_valid(c):
                    return c
    return None


def nearest_registry_regon(bad: str, candidates: list[str]) -> str | None:
    """A valid REGON in the registry that differs from `bad` by one digit (typo)."""
    b = _digits(bad)
    for c in candidates:
        c = _digits(c)
        if len(c) == len(b) and c != b and sum(x != y for x, y in zip(c, b)) == 1 and regon_valid(c):
            return c
    return None


def validate_identifiers(facts: dict, project: dict | None, registry_nips: list[str], registry_regons: list[str] | None = None) -> list[dict]:
    """[{kind, ok, value, detail, expected?}] for every identifier we can check. Pure."""
    ids = facts.get("identifiers") or {}
    out: list[dict] = []
    for n in ids.get("nip") or []:
        v = n.get("value") if isinstance(n, dict) else n
        ok = nip_valid(v)
        row = {"kind": "nip", "value": _digits(v), "ok": ok, "detail": "suma kontrolna poprawna" if ok else "suma kontrolna niepoprawna"}
        if not ok:
            row["expected"] = nearest_registry_nip(v, registry_nips)
        elif project and project.get("beneficiary_nip") and _digits(v) != _digits(project["beneficiary_nip"]) and _digits(v) not in {_digits(x) for x in registry_nips}:
            row.update(ok=False, detail="NIP poprawny, ale inny niż w projekcie", expected=_digits(project["beneficiary_nip"]))
        out.append(row)
    for r in ids.get("regon") or []:
        v = r.get("value") if isinstance(r, dict) else r
        ok = regon_valid(v)
        row = {"kind": "regon", "value": _digits(v), "ok": ok, "detail": "suma kontrolna poprawna" if ok else "suma kontrolna niepoprawna"}
        if not ok:
            row["expected"] = nearest_registry_regon(v, registry_regons or [])
        out.append(row)
    for k in ids.get("kpo") or []:
        woj = (project or {}).get("province", "")[2:] if (project or {}).get("province") else None
        c = kpo_check(k, woj)
        ok = c.get("valid_format", False) and c.get("iw_matches_woj", True)
        detail = "zły format numeru KPO" if not c.get("valid_format") else (
            "numer KPO zgodny z województwem projektu" if ok else f"IW.{c['iw']} nie pasuje do województwa projektu (oczekiwano IW.{c['iw_expected']})")
        out.append({"kind": "kpo", "value": k, "ok": ok, "detail": detail, "expected": c.get("iw_expected")})
    return out


# ---------------------------------------------------------------------------------------------------------------- linking

async def resolve_project(db: AsyncSession, doc: dict, facts: dict) -> dict:
    """-> {project|None, method, score, features, candidates}."""
    ids = facts.get("identifiers") or {}
    feats: dict[str, float] = {}
    for k in ids.get("kpo") or []:
        p = await _rows(db, "SELECT * FROM project WHERE public_id = :k OR external_ids->>'kpo' = :k", k=k)
        if p:
            return {"project": p[0], "method": "exact_id", "score": 1.0, "features": {"kpo_exact": 1.0}}
    if doc.get("project_id"):
        p = await _rows(db, "SELECT * FROM project WHERE id = :i", i=doc["project_id"])
        if p:
            return {"project": p[0], "method": "user_bound", "score": 0.9, "features": {"upload_bound": 1.0}}
    best, best_s, best_f = None, 0.0, {}
    for p in await _rows(db, "SELECT * FROM project WHERE is_pilot"):
        f = {"buyer": _sim(ids.get("buyer"), p.get("beneficiary_name")), "title": _sim(ids.get("task_title"), p.get("title"))}
        s = (0.5 * f["buyer"] + 0.5 * f["title"]) if ids.get("task_title") else f["buyer"] * 0.6
        if s > best_s:
            best, best_s, best_f = p, s, f
    if best and best_s >= 0.6:
        return {"project": best, "method": "fuzzy", "score": round(best_s, 3), "features": best_f}
    return {"project": None, "method": None, "score": 0.0, "features": feats}


def _old_end(change: dict, contract_date: date | None) -> date | None:
    old = _d(change.get("old_end"))
    if old:
        return old
    new, dm = _d(change.get("planned_end_calc") or change.get("new_end")), change.get("delta_months")
    return new - relativedelta(months=int(dm)) if new and dm else None


def score_contract(c: dict, proc: dict, facts: dict) -> tuple[float, dict]:
    """Weighted features over those present on both sides (coverage-normalised, like the case similarity)."""
    ids = facts.get("identifiers") or {}
    change = facts.get("change") or {}
    cdate = _d((ids.get("contract") or {}).get("date"))
    parts: dict[str, tuple[float, float]] = {}  # feature -> (weight, value)
    if cdate and c.get("signed_on"):
        parts["signed_on"] = (0.30, 1.0 if cdate == c["signed_on"] else (0.4 if abs((cdate - c["signed_on"]).days) <= 31 else 0.0))
    if ids.get("contractor") and c.get("contractor_name"):
        ca, cb = company_core(ids["contractor"]), company_core(c["contractor_name"])
        parts["contractor"] = (0.25, max(_sim(ids["contractor"], c["contractor_name"]), fuzz.ratio(ca, cb) / 100 if ca and cb else 0.0))
    old = _old_end(change, cdate)
    if old and c.get("planned_end_on"):
        parts["planned_end"] = (0.25, 1.0 if old == c["planned_end_on"] else (0.5 if abs((old - c["planned_end_on"]).days) <= 7 else 0.0))
    if ids.get("task_title") and proc.get("title"):
        parts["scope"] = (0.10, _sim(ids["task_title"], proc["title"]))
    if ids.get("buyer") and proc.get("buyer_name"):
        parts["buyer"] = (0.10, _sim(ids["buyer"], proc["buyer_name"]))
    w = sum(x[0] for x in parts.values())
    if not w:
        return 0.0, {}
    feats = {k: round(v, 3) for k, (_, v) in parts.items()}
    feats["coverage"] = round(w, 2)
    return round(sum(a * b for a, b in parts.values()) / w, 3), feats


async def match_contracts(db: AsyncSession, project: dict | None, facts: dict) -> list[dict]:
    if not project:
        return []
    cs = await _rows(db, """SELECT c.*, pr.title AS proc_title, pr.buyer_name, pr.ocid, pr.id AS proc_id FROM contract c
                            JOIN project_procedure pp ON pp.procedure_id = c.procedure_id JOIN procedure pr ON pr.id = c.procedure_id
                            WHERE pp.project_id = :p AND pp.review_status <> 'rejected'""", p=project["id"])
    out = []
    for c in cs:
        s, f = score_contract(c, {"title": c["proc_title"], "buyer_name": c["buyer_name"]}, facts)
        out.append({"contract": c, "score": s, "features": f})
    out.sort(key=lambda x: -x["score"])
    return out


# -------------------------------------------------------------------------------------------------------------- writers

async def _insert_event(db: AsyncSession, key: str, **f) -> int | None:
    cols = ["key"] + list(f)
    vals = ", ".join(f":{c}" for c in cols)
    r = await db.execute(text(f"INSERT INTO risk_event ({', '.join(cols)}) VALUES ({vals}) ON CONFLICT (key) DO NOTHING RETURNING id"), {"key": key, **f})
    got = r.scalar()
    return got if got is not None else await _scalar(db, "SELECT id FROM risk_event WHERE key = :k", k=key)


async def _evidence(db: AsyncSession, table: str, claim_id: int, doc_id: int, field: str | None, page: int | None, quote: str | None,
                    verification: str | None, state: str | None = None, note: str | None = None) -> None:
    if not quote and not state:
        return
    if await _scalar(db, "SELECT count(*) FROM evidence WHERE claim_table=:t AND claim_id=:c AND document_id=:d AND coalesce(claim_field,'')=coalesce(:f,'') "
                         "AND coalesce(quote,'')=coalesce(:q,'')", t=table, c=claim_id, d=doc_id, f=field, q=quote):
        return
    await db.execute(text("""INSERT INTO evidence (claim_table, claim_id, claim_field, document_id, page_no, quote, verification, evidence_state, note)
                             VALUES (:t, :c, :f, :d, :p, :q, :v, :s, :n)"""),
                     {"t": table, "c": claim_id, "f": field, "d": doc_id, "p": page, "q": quote, "v": VERIF.get(verification or "", "unverified"), "s": state, "n": note})


async def _item(db: AsyncSession, key: str, *, kind: str, code: str, title: str, question: str, project_id: int | None, target_table: str | None = None,
                target_id: int | None = None, target_field: str | None = None, detail: dict | None = None, severity: str = "medium",
                model_pick: str | None = None, confidence: float | None = None, source_id: int | None = None) -> int | None:
    r = await db.execute(text("""INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, detail, severity, key, created_by,
                                                          model_pick, confidence, target_field, source_id)
        VALUES (:k, :c, :tt, :ti, :p, :t, :q, CAST(:d AS jsonb), :sev, :key, :by, :mp, :cf, :tf, :sid)
        ON CONFLICT (key) DO NOTHING RETURNING id"""),
                         {"k": kind, "c": code, "tt": target_table, "ti": target_id, "p": project_id, "t": title[:500], "q": question, "d": jdump(detail or {}),
                          "sev": severity, "key": key, "by": ACTOR, "mp": model_pick, "cf": confidence, "tf": target_field, "sid": source_id})
    got = r.scalar()
    return got if got is not None else await _scalar(db, "SELECT id FROM review_item WHERE key = :k", k=key)


async def _link_candidate(db: AsyncSession, doc_id: int, right_table: str, right_id: int | None, right_ref: str, method: str, score: float,
                          features: dict, explanation: str, decision: str, status: str) -> int:
    r = await db.execute(text("""INSERT INTO link_candidate (left_table, left_id, right_table, right_id, right_ref, method, features, score, rank, explanation,
                                                             decision, review_status)
        VALUES ('document', :d, :rt, :ri, :rr, :m, CAST(:f AS jsonb), :s, 1, :e, :dec, :st)
        ON CONFLICT (left_table, left_id, right_table, right_ref, method) DO UPDATE SET score = EXCLUDED.score, features = EXCLUDED.features
        RETURNING id"""), {"d": doc_id, "rt": right_table, "ri": right_id, "rr": right_ref, "m": method, "f": jdump(features), "s": score, "e": explanation,
                           "dec": decision, "st": status})
    return r.scalar_one()


def _origin(facts: dict) -> str:
    fl = facts.get("facts") or []
    return "AI" if any(f.get("origin") == "AI" for f in fl) or any(c.get("origin") == "AI" for c in facts.get("causes") or []) else "CALC"


def _delta_days(change: dict) -> float | None:
    if change.get("delta_days") is not None:
        return float(change["delta_days"])
    old, new = _old_end(change, None), _d(change.get("new_end") or change.get("planned_end_calc"))
    if old and new:
        return float((new - old).days)
    if change.get("delta_months"):
        return float(change["delta_months"]) * 30.4
    return None


def _kinds_pl(kinds: list[str]) -> str:
    names = {"termin": "terminu", "wynagrodzenie": "wynagrodzenia", "zakres": "zakresu"}
    return ", ".join(names.get(k, k) for k in kinds)


# ------------------------------------------------------------------------------------------------------------- main

async def link_document(db: AsyncSession, document_id: int, *, actor: str = ACTOR, request_id: str | None = None) -> dict:
    docs = await _rows(db, "SELECT * FROM document WHERE id = :i", i=document_id)
    if not docs:
        raise ApiError(404, "Nie ma takiego dokumentu.", "not_found")
    doc = docs[0]
    facts = (doc.get("data") or {}).get("facts")
    if not facts:
        raise ApiError(409, "Z dokumentu nie wyczytano jeszcze faktów. Uruchom odczyt.", "no_facts")
    if facts.get("kind") == "tender_scan" or facts.get("doc_kind") == "tender_scan":
        # Red Pen scan of a tender document: its signals are already risk_event rows written by the scanner, nothing to link or duplicate
        return {"document_id": document_id, "skipped": "tender_scan", "created": {}, "review_items": [], "checks": [], "warnings": [], "project": None}
    ids = facts.get("identifiers") or {}
    change = facts.get("change") or {}
    level = facts.get("level") or "contract"
    doc_date = _d(facts.get("doc_date"))
    label = facts.get("doc_kind_label") or doc.get("title") or "Dokument"
    sid = doc.get("source_id")
    res: dict[str, Any] = {"document_id": document_id, "level": level, "created": {}, "review_items": [], "checks": [], "warnings": []}
    created = res["created"]

    # --- project
    pr = await resolve_project(db, doc, facts)
    project = pr["project"]
    res["project"] = {"rm_id": project["rm_id"], "method": pr["method"], "score": pr["score"], "features": pr["features"]} if project else None
    if project:
        await _link_candidate(db, document_id, "project", project["id"], project["rm_id"], pr["method"], pr["score"], pr["features"],
                              f"Dokument powiązany z projektem {project['rm_id']} (metoda {pr['method']}).",
                              "accept" if pr["score"] >= 0.99 else "review", "auto" if pr["score"] >= 0.99 else "proposed")
        if pr["score"] >= 0.99 and not doc.get("project_id"):
            await db.execute(text("UPDATE document SET project_id = :p WHERE id = :d AND project_id IS NULL"), {"p": project["id"], "d": document_id})
    else:
        it = await _item(db, f"doc:{document_id}:no_project", kind="discrepancy", code="document_no_project", project_id=None, source_id=sid,
                         title=f"Nie powiązano dokumentu „{label}” z żadnym projektem",
                         question="Do którego projektu należy ten dokument?",
                         detail={"sub": "Numer KPO, zamawiający i tytuł zadania nie wskazują jednoznacznie projektu.", "document_id": document_id})
        res["review_items"].append(it)

    # --- identifiers
    registry = [project["beneficiary_nip"]] if project and project.get("beneficiary_nip") else []
    registry += [r["buyer_nip"] for r in await _rows(db, "SELECT DISTINCT buyer_nip FROM procedure pr JOIN project_procedure pp ON pp.procedure_id=pr.id "
                                                          "WHERE pp.project_id = :p AND buyer_nip IS NOT NULL", p=project["id"])] if project else []
    registry_regons = [r["regon"] for r in await _rows(db, "SELECT DISTINCT regon FROM organization WHERE regon IS NOT NULL AND nip = ANY(:n)",
                                                       n=[_digits(x) for x in registry] or [""])]
    checks = validate_identifiers(facts, project, registry, registry_regons)
    res["checks"] = checks
    for c in checks:
        if c["ok"]:
            continue
        sub = f"{c['kind'].upper()} {c['value']}: {c['detail']}."
        if c["kind"] == "nip" and c.get("expected"):
            title = f"NIP w dokumencie niepoprawny (suma kontrolna); w rejestrze {c['expected']}"
            sub += f" W zestawie i rejestrze VAT jest {c['expected']}. Niczego nie poprawiamy samodzielnie."
        elif c["kind"] == "regon" and c.get("expected"):
            title = f"REGON w dokumencie niepoprawny (suma kontrolna); w rejestrze {c['expected']}"
            sub += f" W rejestrze jest {c['expected']}. Niczego nie poprawiamy samodzielnie."
        elif c["kind"] == "kpo":
            title = f"Numer KPO {c['value']} niezgodny z województwem projektu"
        else:
            title = f"{c['kind'].upper()} w dokumencie: {c['detail']}"
        it = await _item(db, f"doc:{document_id}:chk:{c['kind']}:{c['value']}", kind="discrepancy", code=f"document_{c['kind']}_invalid",
                         project_id=project["id"] if project else None, source_id=sid, title=title, severity="high" if c["kind"] == "nip" else "medium",
                         question=f"Co zrobić z identyfikatorem {c['kind'].upper()} {c['value']} w dokumencie „{label}”?",
                         detail={"sub": sub, "document_id": document_id, "value": c["value"], "expected": c.get("expected"), "check": c})
        res["review_items"].append(it)

    # --- contract match
    matches = await match_contracts(db, project, facts) if level == "contract" else []
    best = matches[0] if matches else None
    proc_id = best["contract"]["proc_id"] if best else None
    contract_id = best["contract"]["id"] if best else None
    if best:
        c = best["contract"]
        lc = await _link_candidate(db, document_id, "contract", c["id"], f"contract:{c['id']}", "buyer+date+contractor+term", best["score"], best["features"],
                                   f"Umowa z {pl_date(c['signed_on'])}, wykonawca {c['contractor_name']}.", "review", "proposed")
        created["link_candidate"] = lc
        cnum = (ids.get("contract") or {}).get("number")
        it = await _item(db, f"doc:{document_id}:contract:{c['id']}", kind="link", code="document_contract", target_table="link_candidate", target_id=lc,
                         project_id=project["id"], source_id=sid, model_pick=f"contract:{c['id']}", confidence=best["score"],
                         title=f"Dokument „{label}” dotyczy umowy {cnum or ''} z {pl_date(c['signed_on'])}?".replace("  ", " "),
                         question=f"Czy {label.lower()} z {pl_date(doc_date)} dotyczy umowy {cnum or ''} z wykonawcą {c['contractor_name']}?".replace("  ", " "),
                         detail={"sub": "W BZP nie ma numeru umowy, więc dopasowanie opiera się na dacie, wykonawcy i terminie.", "features": best["features"],
                                 "document_id": document_id, "contract_id": c["id"]})
        res["review_items"].append(it)
        res["contract"] = {"contract_id": c["id"], "ocid": c["ocid"], "score": best["score"], "features": best["features"], "contractor": c["contractor_name"]}
        if best["score"] < 0.6:
            res["warnings"].append("Słabe dopasowanie umowy, sprawdź w Przeglądzie.")
    elif level == "contract" and project:
        it = await _item(db, f"doc:{document_id}:no_contract", kind="discrepancy", code="document_no_contract", project_id=project["id"], source_id=sid,
                         title=f"Nie znaleziono umowy w BZP dla dokumentu „{label}”", question="Której umowy dotyczy ta zmiana?",
                         detail={"sub": "Projekt nie ma powiązanej umowy z ogłoszenia o wyniku.", "document_id": document_id})
        res["review_items"].append(it)

    pid = project["id"] if project else None
    origin = _origin(facts)
    cause_text = " ".join(c.get("quote") or c.get("why") or "" for c in (facts.get("causes") or [])[:2]).strip() or None

    # --- the change itself
    change_id = None
    dd = _delta_days(change)
    has_change = bool(change and (change.get("kinds") or change.get("new_end") or change.get("requested_end") or change.get("value") or change.get("planned_end_calc")))
    if level == "contract" and has_change and proc_id:
        v = change.get("value") or {}
        lb = change.get("legal_basis") or []
        r = await db.execute(text("""INSERT INTO contract_change (key, contract_id, procedure_id, document_id, kind, change_no, changed_on, legal_basis, legal_basis_raw,
                change_types, delta_days, delta_value_amount, delta_value_currency, delta_value_vat, cause_text, description_text, origin, review_status, source_id)
            VALUES (:key, :c, :p, :d, 'document_change', :no, :on, :lb, :lbr, :ct, :dd, :va, :vc, :vv, :cause, :desc, :o, 'proposed', :sid)
            ON CONFLICT (key) DO NOTHING RETURNING id"""),
                             {"key": f"doc:{document_id}:change", "c": contract_id, "p": proc_id, "d": document_id, "no": f"dok-{document_id}",
                              "on": doc_date, "lb": lb, "lbr": ", ".join(lb) if lb else None, "ct": change.get("kinds") or [], "dd": dd,
                              "va": v.get("amount"), "vc": v.get("currency"), "vv": v.get("vat_basis"), "cause": cause_text,
                              "desc": f"{label}: zmiana {_kinds_pl(change.get('kinds') or [])}", "o": origin, "sid": sid})
        change_id = r.scalar() or await _scalar(db, "SELECT id FROM contract_change WHERE key = :k", k=f"doc:{document_id}:change")
        created["contract_change"] = change_id
        for f in facts.get("facts") or []:
            if f.get("field") in ("legal_basis", "delta_value", "value", "new_end", "delta_months", "delta_days", "old_end", "planned_end_calc") or f.get("field", "").startswith("change"):
                await _evidence(db, "contract_change", change_id, document_id, f.get("field"), f.get("page"), f.get("quote"), f.get("verification"))
        if change.get("legal_basis_state") == "DOKUMENT_NIE_WSPOMINA" or not lb:
            await _evidence(db, "contract_change", change_id, document_id, "legal_basis", 1, None, None, "DOKUMENT_NIE_WSPOMINA", "Dokument nie podaje podstawy prawnej zmiany.")
        old = _old_end(change, None)
        new = _d(change.get("planned_end_calc") or change.get("new_end"))
        bits = []
        if "termin" in (change.get("kinds") or []):
            bits.append(f"termin {('o ' + str(change['delta_months']) + ' mies.') if change.get('delta_months') else ('o ' + str(int(dd)) + ' dni' if dd else '')}".strip()
                        + (f" do {pl_date(new)}" if new else ""))
        if v.get("amount"):
            bits.append(f"wynagrodzenie o {float(v['amount']):,.2f} zł {'brutto' if v.get('vat_basis') == 'gross' else ''}".replace(",", " ").replace(".", ",").strip())
        question = f"Czy zmiana ({'; '.join(bits) or _kinds_pl(change.get('kinds') or [])}) z dokumentu z {pl_date(doc_date)} dotyczy umowy {(ids.get('contract') or {}).get('number') or ''} ?".replace(" ?", "?").replace("  ", " ")
        it = await _item(db, f"doc:{document_id}:change_item", kind="fact", code="document_change", target_table="contract_change", target_id=change_id,
                         target_field="delta_days", project_id=pid, source_id=sid, confidence=best["score"] if best else None,
                         title=f"Zmiana umowy z dokumentu „{label}”: {', '.join(bits) or 'szczegóły w dokumencie'}", question=question,
                         detail={"sub": "Wniosek powstał z dokumentu, w BZP nie ma jeszcze ogłoszenia o tej zmianie.", "document_id": document_id,
                                 "old_end": str(old) if old else None, "new_end": str(new) if new else None})
        res["review_items"].append(it)
    elif level == "grant" and project:
        req = _d(change.get("requested_end") or change.get("new_end"))
        eid = await _insert_event(db, f"doc:{document_id}:term", project_id=pid, event_type=EVT_TERM, catalogue_code="R13",
                                  summary=f"Wniosek o wydłużenie terminu realizacji projektu KPO{(' do ' + pl_date(req)) if req else ''}",
                                  cause=cause_text, occurred_on=doc_date, origin=origin, review_status="proposed", source_id=sid,
                                  phase="realizacja")
        created["project_term_event"] = eid
        res["project_term"] = {"kind": "termin_projektu", "requested_end": str(req) if req else None, "event_id": eid}
        await _evidence(db, "risk_event", eid, document_id, "requested_end", 1, next((f.get("quote") for f in facts.get("facts") or []
                                                                                          if f.get("field") in ("requested_end", "new_end")), None), "exact")
        it = await _item(db, f"doc:{document_id}:term_item", kind="event", code="document_grant_term", target_table="risk_event", target_id=eid, project_id=pid,
                         source_id=sid, model_pick="R13", confidence=pr["score"], title=f"Wniosek o zmianę terminu projektu KPO{(' do ' + pl_date(req)) if req else ''}",
                         question=f"Czy pismo z {pl_date(doc_date)} zmienia termin realizacji projektu {project['rm_id']}{(' na ' + pl_date(req)) if req else ''}?",
                         detail={"sub": "To zmiana harmonogramu umowy o dofinansowanie, nie zmiana umowy z wykonawcą.", "document_id": document_id})
        res["review_items"].append(it)

    # --- causes, effects
    events = []
    for n, c in enumerate(facts.get("causes") or []):
        code = c.get("code")
        if not code or not (pid or proc_id):
            continue
        eid = await _insert_event(db, f"doc:{document_id}:cause:{code}:{n}", project_id=pid, procedure_id=proc_id, contract_id=contract_id, change_id=change_id,
                                  event_type=EVT_CAUSE, catalogue_code=code, summary=(c.get("why") or c.get("quote") or f"Przyczyna {code}")[:300],
                                  cause=c.get("quote"), occurred_on=doc_date, origin="AI" if c.get("origin") == "AI" else "CALC", review_status="proposed",
                                  source_id=sid, phase="realizacja", conf_data_quality=c.get("confidence") or (0.9 if c.get("verification") == "exact" else 0.6))
        await _evidence(db, "risk_event", eid, document_id, "cause", c.get("page"), c.get("quote"), c.get("verification"))
        names = await _scalar(db, "SELECT name FROM catalogue_risk WHERE sector='wod-kan' AND code = :c AND status IN ('approved','proposed') ORDER BY version DESC LIMIT 1", c=code)
        it = await _item(db, f"doc:{document_id}:evt:{eid}", kind="event", code="document_cause", target_table="risk_event", target_id=eid, project_id=pid, source_id=sid,
                         model_pick=code, confidence=c.get("confidence") or (0.9 if c.get("verification") == "exact" else 0.6),
                         title=f"Przyczyna {code} w dokumencie „{label}”: {(c.get('why') or c.get('quote') or '')[:120]}",
                         question=f"Czy przyczyną zmiany jest: {(c.get('why') or c.get('quote') or '')[:160]} ({code}{(' ' + names) if names else ''})?",
                         detail={"sub": "Cytat z dokumentu jest sprawdzony na stronie źródłowej." if c.get("verification") == "exact" else "Cytat nie został w pełni sprawdzony.",
                                 "document_id": document_id})
        events.append(eid)
        res["review_items"].append(it)
    for n, e in enumerate(facts.get("effects") or []):
        if not (pid or proc_id):
            continue
        months = e.get("months")
        eid = await _insert_event(db, f"doc:{document_id}:effect:{e.get('code')}:{n}", project_id=pid, procedure_id=proc_id, contract_id=contract_id, change_id=change_id,
                                  event_type=EVT_EFFECT, catalogue_code=e.get("code") or "R18", impact_days=(float(months) * 30.4 if months else None),
                                  summary=f"Efekt użytkowy opóźniony{(' o ok. ' + str(months) + ' mies.') if months else ''} przez inwestycję powiązaną: {e.get('linked_investment') or 'brak nazwy'}"[:300],
                                  cause=e.get("quote"), occurred_on=doc_date, origin="AI" if e.get("origin") == "AI" else "CALC", review_status="proposed", source_id=sid,
                                  phase="realizacja", conf_data_quality=0.7)
        await _evidence(db, "risk_event", eid, document_id, "effect", e.get("page"), e.get("quote"), e.get("verification"))
        it = await _item(db, f"doc:{document_id}:evt:{eid}", kind="event", code="document_effect", target_table="risk_event", target_id=eid, project_id=pid, source_id=sid,
                         model_pick=e.get("code") or "R18", confidence=0.7,
                         title=f"Zależność od inwestycji powiązanej: {e.get('linked_investment') or ''}".strip(),
                         question=f"Czy efekt użytkowy projektu jest opóźniony przez inwestycję powiązaną ({e.get('linked_investment') or 'bez nazwy'})?",
                         detail={"sub": "Tego ryzyka (R18) nie ma jeszcze w zatwierdzonym katalogu.", "document_id": document_id})
        events.append(eid)
        res["review_items"].append(it)
    created["risk_events"] = events

    # --- flags from the extraction (mixed legal basis ...), R18 catalogue proposal
    for fl in facts.get("flags") or []:
        if fl.get("code") in ("nip_checksum",):  # already handled by our own validation
            continue
        it = await _item(db, f"doc:{document_id}:flag:{fl.get('code')}", kind="discrepancy", code=f"document_{fl.get('code')}", project_id=pid, source_id=sid,
                         title=fl.get("text") or fl.get("code"), question=f"{fl.get('text')} Czy to wymaga uwagi?",
                         detail={"sub": fl.get("text"), "document_id": document_id}, severity="low")
        res["review_items"].append(it)
    for cp in facts.get("catalogue_proposals") or []:
        cid = await _scalar(db, "SELECT id FROM catalogue_risk WHERE sector='wod-kan' AND code = :c AND status = 'proposed' ORDER BY version DESC LIMIT 1", c=cp.get("code"))
        if cid:
            it = await _item(db, f"cat:risk:{cid}", kind="catalogue", code="catalogue_proposal", target_table="catalogue_risk", target_id=cid, severity="low",
                             title=f"Propozycja ryzyka: {cp.get('name') or cp.get('code')}", question="Czy dodać to ryzyko do katalogu?", project_id=None,
                             detail={"merge_suggestion": None, "document_id": document_id})
            res["review_items"].append(it)

    res["review_items"] = [i for i in res["review_items"] if i]
    if has_change and (contract_id or pid):
        from riskminer.monitoring import alerts as AL
        bits = []
        if dd:
            bits.append({"summary": f"termin {'+' if dd > 0 else ''}{int(dd)} dni" + (f" (do {pl_date(change.get('planned_end_calc') or change.get('new_end'))})" if (change.get("planned_end_calc") or change.get("new_end")) else ""),
                         "kind": "termin", "delta_days": dd})
        if (change.get("value") or {}).get("amount"):
            bits.append({"summary": f"{(change['value'] or {}).get('amount')} zł", "kind": "wynagrodzenie", "delta_value_amount": float(change["value"]["amount"])})
        if level == "grant" and change.get("requested_end"):
            bits.append({"summary": f"wniosek o termin projektu do {pl_date(change['requested_end'])}", "kind": "termin_projektu"})
        al = await AL.raise_for_document(db, document_id=document_id, contract_id=contract_id if level == "contract" else None,
                                         project_id=pid if level == "grant" else None, doc_date=doc_date, changes=bits,
                                         kind="grant_term_change" if level == "grant" else "document_change", created_by=actor)
        res["alert"] = al
        if al.get("alert_id"):
            created["alert"] = al["alert_id"]
    link = {"at": datetime.now().astimezone().isoformat(), "project": res["project"], "contract": res.get("contract"), "checks": checks,
            "created": created, "review_items": res["review_items"], "warnings": res["warnings"]}
    await db.execute(text("UPDATE document SET data = data || CAST(:l AS jsonb), updated_at = now() WHERE id = :i"), {"i": document_id, "l": jdump({"link": link})})
    await audit(db, actor, "document.link", "document", document_id, None,
                {"project": res["project"], "contract": res.get("contract"), "review_items": res["review_items"], "created": created}, request_id,
                f"powiązanie dokumentu: {label}")
    return res


# ------------------------------------------------------------------------------------------------------ G4: what changed

def _zl(x: Any) -> str:
    try:
        return f"{float(x):,.2f}".replace(",", " ").replace(".", ",") + " zł"
    except (TypeError, ValueError):
        return str(x)


async def changes_since(db: AsyncSession, rm_id: str, document_id: int) -> dict:
    """"Co się zmieniło" after a document: potwierdzone (also in BZP / registry), zmienione (planned end, value, delay), nowe (changes, risks,
    dependency) and zamknięte (gaps and queue items settled by the document). A preview: nothing here changes BZP data."""
    prj = await _rows(db, "SELECT * FROM project WHERE rm_id = :r", r=rm_id)
    if not prj:
        raise ApiError(404, "Nie ma takiego projektu.", "not_found")
    project = prj[0]
    docs = await _rows(db, "SELECT * FROM document WHERE id = :i", i=document_id)
    if not docs:
        raise ApiError(404, "Nie ma takiego dokumentu.", "not_found")
    doc = docs[0]
    data = doc.get("data") or {}
    facts, link = data.get("facts") or {}, data.get("link") or {}
    if not facts:
        raise ApiError(409, "Z dokumentu nie wyczytano jeszcze faktów.", "no_facts")
    change = facts.get("change") or {}
    ids = facts.get("identifiers") or {}
    label = facts.get("doc_kind_label") or doc.get("title") or "Dokument"
    doc_date = _d(facts.get("doc_date"))
    ev_doc = {"kind": "document", "id": str(document_id), "label": f"{label}, {pl_date(doc_date)}"}
    conf: list[dict] = []
    chg: list[dict] = []
    new: list[dict] = []
    closed: list[dict] = []
    agg: dict[str, Any] = {}

    # potwierdzone ---------------------------------------------------------------------------------------------
    pm = link.get("project") or {}
    if pm.get("method") == "exact_id":
        conf.append({"key": "kpo", "label": "Numer KPO z dokumentu", "value": (ids.get("kpo") or [""])[0], "where": "zgodny z projektem w zestawie organizatora", "refs": [ev_doc]})
    for c in link.get("checks") or []:
        if c["kind"] == "nip" and c["ok"]:
            conf.append({"key": "nip", "label": "NIP w dokumencie", "value": c["value"], "where": "suma kontrolna poprawna, zgodny z rejestrem", "refs": [ev_doc]})
    contract = None
    if (link.get("contract") or {}).get("contract_id"):
        contract = (await _rows(db, "SELECT * FROM contract WHERE id = :i", i=link["contract"]["contract_id"]) or [None])[0]
    cdate = _d((ids.get("contract") or {}).get("date"))
    if contract:
        feats = link["contract"].get("features") or {}
        if feats.get("signed_on") == 1.0:
            conf.append({"key": "signed_on", "label": "Data zawarcia umowy", "value": pl_date(cdate), "where": "zgodna z ogłoszeniem o wyniku w BZP", "refs": [ev_doc]})
        if feats.get("planned_end") == 1.0:
            conf.append({"key": "old_end", "label": "Dotychczasowy termin umowy", "value": pl_date(contract["planned_end_on"]),
                         "where": "zgodny z BZP (ogłoszenie o wyniku)", "refs": [ev_doc]})
        # a change already notified in BZP?
        for bz in await _rows(db, "SELECT ch.*, n.notice_number FROM contract_change ch LEFT JOIN notice n ON n.id = ch.notice_id WHERE ch.contract_id = :c AND ch.kind = 'change_notice'",
                              c=contract["id"]):
            same_days = change.get("delta_days") is not None and bz.get("delta_days") is not None and abs(float(bz["delta_days"]) - float(change["delta_days"])) <= 3
            v = (change.get("value") or {}).get("amount")
            same_val = v and bz.get("delta_value_amount") and abs(float(bz["delta_value_amount"]) - float(v)) <= 0.01 * float(v)
            if same_days or same_val:
                conf.append({"key": f"bzp:{bz['id']}", "label": "Zmiana jest już w BZP", "value": bz.get("notice_number") or "ogłoszenie o zmianie",
                             "where": "ta sama zmiana w ogłoszeniu o zmianie umowy", "refs": [ev_doc]})

    # zmienione + aggregates -----------------------------------------------------------------------------------
    new_end = _d(change.get("planned_end_calc") or change.get("new_end"))
    if contract and new_end and "termin" in (change.get("kinds") or []):
        before_end = contract["planned_end_on"]
        chg.append({"key": "planned_end", "label": "Planowany koniec umowy", "before": pl_date(before_end), "after": pl_date(new_end),
                    "why": f"{label} z {pl_date(doc_date)}", "refs": [ev_doc]})
        perf = (await _rows(db, "SELECT completed_on, delay_days FROM contract_performance WHERE contract_id = :c AND NOT is_duplicate ORDER BY id DESC LIMIT 1", c=contract["id"]) or [None])[0]
        agg["planned_end"] = {"before": pl_date(before_end), "after": pl_date(new_end)}
        if perf and perf.get("completed_on"):
            after_delay = (perf["completed_on"] - new_end).days
            agg["delay_days"] = {"before": perf["delay_days"], "after": after_delay,
                                 "display_before": f"{perf['delay_days']:+d} dni", "display_after": f"{after_delay:+d} dni"}
            chg.append({"key": "delay", "label": "Opóźnienie względem terminu", "before": f"{perf['delay_days']:+d} dni", "after": f"{after_delay:+d} dni",
                        "why": "po uwzględnieniu nowego terminu z dokumentu", "refs": [ev_doc]})
        else:
            overdue = (date.today() - new_end).days
            agg["days_overdue"] = {"before": max((date.today() - before_end).days, 0), "after": max(overdue, 0)}
    v = (change.get("value") or {}).get("amount")
    if contract and v and "wynagrodzenie" in (change.get("kinds") or []):
        after_val = float(contract["value_amount"]) + float(v)
        chg.append({"key": "value", "label": "Wartość umowy", "before": _zl(contract["value_amount"]) + " brutto", "after": _zl(after_val) + " brutto",
                    "why": f"zmiana o {_zl(v)} brutto", "refs": [ev_doc]})
        agg["contract_value"] = {"before": _zl(contract["value_amount"]), "after": _zl(after_val)}
    req = _d(change.get("requested_end"))
    if (facts.get("level") == "grant") and req:
        chg.append({"key": "project_end", "label": "Termin realizacji projektu KPO", "before": "brak w bazie", "after": f"{pl_date(req)} (wniosek)",
                    "why": "wniosek do instytucji pośredniczącej, nie zmiana umowy z wykonawcą", "refs": [ev_doc]})
        agg["project_end"] = {"before": None, "after": pl_date(req)}

    # nowe -----------------------------------------------------------------------------------------------------
    cid = (link.get("created") or {}).get("contract_change")
    if cid:
        new.append({"key": "contract_change", "label": f"Proponowana zmiana umowy: {_kinds_pl(change.get('kinds') or [])}", "value": "do zatwierdzenia", "refs": [ev_doc]})
    for e in await _rows(db, "SELECT id, catalogue_code, summary, review_status FROM risk_event WHERE key LIKE :k ORDER BY id", k=f"doc:{document_id}:%"):
        new.append({"key": f"event:{e['id']}", "label": e["summary"], "value": f"{e['catalogue_code']}, {'zatwierdzone' if e['review_status'] in ('approved', 'edited') else 'do przeglądu'}",
                    "refs": [ev_doc]})
    for fl in facts.get("flags") or []:
        if fl.get("code") != "nip_checksum":
            new.append({"key": f"flag:{fl.get('code')}", "label": fl.get("text"), "value": "uwaga dla eksperta", "refs": [ev_doc]})
    for c in link.get("checks") or []:
        if not c["ok"]:
            new.append({"key": f"check:{c['kind']}", "label": f"{c['kind'].upper()} {c['value']}: {c['detail']}", "value": f"w rejestrze {c['expected']}" if c.get("expected") else "do wyjaśnienia",
                        "refs": [ev_doc]})

    # zamknięte ------------------------------------------------------------------------------------------------
    for it in await _rows(db, "SELECT id, title, status, detail->'resolution'->>'option' AS option FROM review_item WHERE key LIKE :k AND status <> 'open' ORDER BY id", k=f"doc:{document_id}:%"):
        closed.append({"key": f"item:{it['id']}", "label": it["title"], "value": "rozstrzygnięte", "refs": [ev_doc]})
    kind = (facts.get("doc_kind") or "")
    if kind.startswith("protokol"):
        closed.append({"key": "gap:protokol", "label": "Brakujący dokument z budowy: protokół konieczności lub odbioru", "value": "mamy dokument", "refs": [ev_doc]})
    items = await _rows(db, "SELECT id, title, status, kind FROM review_item WHERE key LIKE :k ORDER BY id", k=f"doc:{document_id}:%")
    # every line says it came from this document; records that were decided carry who decided and when (audit)
    for lines in (conf, chg, new, closed):
        for l in lines:
            l["from_document"] = True if lines is not conf else False
    for l in new:
        if l["key"].startswith("event:"):
            l["decision"] = await decision_of(db, "risk_event", int(l["key"].split(":")[1]))
        elif l["key"] == "contract_change" and cid:
            l["decision"] = await decision_of(db, "contract_change", cid)
    gr = await growth(db, document_id)
    rerun = [r["code"] for r in await _rows(db, """SELECT a.code FROM analysis a WHERE a.code IS NOT NULL AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(coalesce(a.results->'stale_cases', '[]'::jsonb)) e WHERE (e->>'document_id')::bigint = :d) ORDER BY a.code""", d=document_id)]
    return {"growth": gr, "analyses_to_rerun": rerun, "document": {"id": document_id, "title": doc.get("title"), "kind_label": label, "date": str(doc_date) if doc_date else None},
            "project": rm_id, "groups": {"potwierdzone": conf, "zmienione": chg, "nowe": new, "zamkniete": closed},
            "counts": {"potwierdzone": len(conf), "zmienione": len(chg), "nowe": len(new), "zamkniete": len(closed)},
            "aggregates": agg, "review_items": [{"id": i["id"], "title": i["title"], "status": i["status"], "kind": i["kind"], "href": f"/przeglad?sprawa={i['id']}"} for i in items]}


# ------------------------------------------------------------------------------------------- growth and decisions

def _plw(n: int, one: str, few: str, many: str) -> str:
    return one if n == 1 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


async def growth(db: AsyncSession, document_id: int) -> dict:
    """What this document added to the case base: "+1 zmiana umowy, +2 zdarzenia ryzyka, 1 propozycja do katalogu (R18)"."""
    n_ch = await _scalar(db, "SELECT count(*) FROM contract_change WHERE document_id = :d AND review_status <> 'rejected'", d=document_id) or 0
    ev = await _rows(db, "SELECT catalogue_code FROM risk_event WHERE key LIKE :k AND review_status <> 'rejected'", k=f"doc:{document_id}:%")
    cats = await _rows(db, """SELECT DISTINCT c.code FROM review_item r JOIN catalogue_risk c ON c.id = r.target_id
                              WHERE r.kind = 'catalogue' AND r.target_table = 'catalogue_risk' AND (r.detail->>'document_id')::bigint = :d""", d=document_id)
    n_ev = len(ev)
    parts = []
    if n_ch:
        parts.append(f"+{n_ch} {_plw(n_ch, 'zmiana umowy', 'zmiany umowy', 'zmian umowy')}")
    if n_ev:
        parts.append(f"+{n_ev} {_plw(n_ev, 'zdarzenie ryzyka', 'zdarzenia ryzyka', 'zdarzeń ryzyka')}")
    if cats:
        parts.append(f"{len(cats)} {_plw(len(cats), 'propozycja', 'propozycje', 'propozycji')} do katalogu ({', '.join(c['code'] for c in cats)})")
    return {"contract_changes": n_ch, "risk_events": n_ev, "catalogue_proposals": [c["code"] for c in cats],
            "sentence": ("Nowe w bazie dzięki temu dokumentowi: " + ", ".join(parts)) if parts else None, "short": ", ".join(parts) or None}


async def decision_of(db: AsyncSession, table: str, row_id: int) -> dict | None:
    """Latest expert decision on a row (approve | edit | reject, not undone): who and when, for the audit trail in the diff."""
    rs = await _rows(db, """SELECT r.id, r.action, r.reviewer, r.created_at FROM review r
                            WHERE r.target_table = :t AND r.target_id = :i AND r.action IN ('approve','edit','reject') AND r.undo_of IS NULL
                              AND coalesce(r.option_key,'') NOT IN ('undo','demo_reset') AND NOT EXISTS (SELECT 1 FROM review u WHERE u.undo_of = r.id)
                            ORDER BY r.id DESC LIMIT 1""", t=table, i=row_id)
    if not rs:
        return None
    r = rs[0]
    name = r["reviewer"].split(":", 1)[-1]
    return {"action": r["action"], "by": r["reviewer"], "by_label": f"Ekspert {name}" if r["reviewer"].startswith("user:") else name, "at": r["created_at"].isoformat(),
            "action_label": {"approve": "zatwierdzone", "edit": "poprawione", "reject": "odrzucone"}[r["action"]]}
