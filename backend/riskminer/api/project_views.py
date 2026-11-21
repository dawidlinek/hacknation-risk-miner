"""Project card (J7), documents view (2.5), notice facts, history (2.6). Reads only (session B).
Every number is a Num with provenance; public callers see no unverified AI rows (counted in `unverified_hidden`)."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import audit_read as AR
from riskminer.api import auth as A
from riskminer.api.prov import Prov, Ref, fmt_num, q_ref
from riskminer.api.projects_read import PERF_CTE, metrics_for


async def rows(db: AsyncSession, sql: str, **p) -> list[dict]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


def pl_date(d: Any) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.strftime("%d.%m.%Y") if d else ""


def zl(x: Any) -> str:
    return f"{fmt_num(float(x), 2)} zł" if x is not None else ""


def role(origin: str | None) -> str:
    return {"SOURCE": "source", "CALC": "calc", "AI": "ai"}.get(origin or "SOURCE", "source")


def num(value, display, unit, prov: Prov) -> dict:
    return {"value": value, "display": display, "unit": unit, "prov": prov.model_dump(mode="json", exclude_none=True)}


def notice_ref(notice_number: str | None, url: str | None, label: str, field: str | None = None) -> Ref | None:
    return Ref(kind="notice", id=notice_number, label=label, url=url, field_code=field) if notice_number else None


def is_ocid(x: str) -> bool:
    return x.startswith("ocds-")


async def load_chain(db: AsyncSession, rm_id: str, user: A.User | None) -> dict | None:
    """Pilot project (RM-*) or, for an OCID, an automatic card built from the national BZP procedure (`kind: bzp_procedure`)."""
    if is_ocid(rm_id):
        pr = await rows(db, """SELECT pr.id, pr.ocid, pr.title, pr.contract_notice_no, pr.design_build, pr.buyer_nip, pr.buyer_name, pr.subsector_main
                               FROM procedure pr WHERE pr.ocid = :o""", o=rm_id)
        if not pr:
            return None
        pr = pr[0]
        org = await rows(db, "SELECT id, name, nip, nip_valid FROM organization WHERE nip = :n LIMIT 1", n=pr["buyer_nip"]) if pr["buyer_nip"] else []
        p = {"id": None, "rm_id": rm_id, "title": pr["title"], "beneficiary_nip": pr["buyer_nip"], "beneficiary_name": pr["buyer_name"],
             "beneficiary_org_id": org[0]["id"] if org else None, "is_pilot": False, "kind": "bzp_procedure",
             "delivery_model": "zaprojektuj i wybuduj" if pr["design_build"] else None, "subsector_main": pr["subsector_main"]}
        procs = [{"id": pr["id"], "ocid": pr["ocid"], "title": pr["title"], "contract_notice_no": pr["contract_notice_no"],
                  "design_build": pr["design_build"], "method": "bzp", "link_status": "auto", "lots": []}]
    else:
        p = await rows(db, "SELECT * FROM project WHERE rm_id = :r", r=rm_id)
        if not p:
            return None
        p = {**p[0], "kind": "pilot_project"}
        org = await rows(db, "SELECT name, nip, nip_valid FROM organization WHERE id = :i", i=p.get("beneficiary_org_id")) if p.get("beneficiary_org_id") else []
        procs = await rows(db, """SELECT pr.id, pr.ocid, pr.title, pr.contract_notice_no, pr.design_build, pp.method, pp.review_status AS link_status, pp.lots
                              FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
                              WHERE pp.project_id = :p AND pp.review_status <> 'rejected' ORDER BY pp.score DESC NULLS LAST""", p=p["id"])
    pid = p["id"]
    pids = [x["id"] for x in procs] or [0]
    contracts = await rows(db, "SELECT * FROM contract WHERE procedure_id = ANY(:p) ORDER BY signed_on, id", p=pids)
    perf = await rows(db, """SELECT DISTINCT ON (pf.contract_id) pf.*, n.notice_number, n.url AS notice_url FROM contract_performance pf
                             LEFT JOIN notice n ON n.id = pf.notice_id WHERE pf.procedure_id = ANY(:p) AND NOT pf.is_duplicate
                             ORDER BY pf.contract_id, pf.id DESC""", p=pids)
    changes = await rows(db, """SELECT ch.*, n.notice_number, n.url AS notice_url FROM contract_change ch LEFT JOIN notice n ON n.id = ch.notice_id
                                WHERE ch.procedure_id = ANY(:p) AND ch.kind = 'change_notice' ORDER BY ch.changed_on NULLS LAST, ch.id""", p=pids)
    doc_changes = await rows(db, """SELECT ch.*, d.title AS doc_title, d.filename FROM contract_change ch JOIN document d ON d.id = ch.document_id
                                    WHERE ch.procedure_id = ANY(:p) AND ch.kind = 'document_change' AND ch.review_status <> 'rejected' ORDER BY ch.changed_on, ch.id""", p=pids)
    notices = await rows(db, """SELECT object_id, notice_type, notice_number, url, published_at FROM notice
                                WHERE ocid = ANY(:o) AND is_latest ORDER BY published_at""", o=[x["ocid"] for x in procs] or [""])
    events = await rows(db, f"""SELECT e.*, n.notice_number AS change_notice, n.url AS change_url FROM risk_event e
                               LEFT JOIN contract_change ch ON ch.id = e.change_id LEFT JOIN notice n ON n.id = ch.notice_id
                               WHERE {'e.procedure_id = ANY(:pids)' if pid is None else 'e.project_id = :p'} AND {A.public_filter(user, 'e')}
                               ORDER BY e.occurred_on NULLS LAST, e.id""", **({"pids": pids} if pid is None else {"p": pid}))
    hidden = (await db.execute(text(f"""SELECT count(*) FROM risk_event e WHERE {'e.procedure_id = ANY(:pids)' if pid is None else 'e.project_id = :p'}
                                        AND origin='AI' AND review_status NOT IN ('approved','edited')"""),
                               {"pids": pids} if pid is None else {"p": pid})).scalar() if user is None else 0
    if pid is None:  # national procedure: metrics straight from its performance notices (one row per contract)
        value = sum(float(x["contract_value_amount"]) for x in perf if x.get("contract_value_amount") is not None) or None
        paid = sum(float(x["total_paid_amount"]) for x in perf if x.get("total_paid_amount") is not None) or None
        delays = [x["delay_days"] for x in perf if x.get("delay_days") is not None]
        metric = {"rm_id": rm_id, "n_contracts": len(perf), "value": value, "paid": paid, "delay_days": max(delays) if delays else None,
                  "changes": sum(x.get("changes_count") or 0 for x in perf) if perf else None,
                  "proper": (all(x.get("properly_performed") for x in perf) if perf else None),
                  "cost_dev_pct": ((paid / value - 1) * 100) if value and paid else None, "open_n": 0, "disc_n": 0, "disc_code": None}
    else:
        metric = (await rows(db, f"WITH {PERF_CTE} SELECT p.id, p.rm_id, pm.*, oi.open_n, oi.disc_n, oi.disc_code FROM project p LEFT JOIN pm ON pm.project_id = p.id "
                                 "LEFT JOIN oi ON oi.project_id = p.id WHERE p.id = :p", p=pid))[0]
    metric["pm_value"] = metric.get("value")
    return {"project": p, "org": org[0] if org else None, "procs": procs, "contracts": contracts, "perf": perf, "changes": changes,
            "notices": notices, "events": events, "hidden": hidden or 0, "metric": metric,
            "doc_changes": [c for c in doc_changes if user is not None or c["review_status"] in ("approved", "edited")]}


def main_perf(perf: list[dict]) -> dict | None:
    return max(perf, key=lambda r: (r.get("delay_days") if r.get("delay_days") is not None else -10**9)) if perf else None


def summary_sentence(m: dict, perf: list[dict], contracts: list[dict] | None = None) -> str:
    if not perf:
        ends = [c["planned_end_on"] for c in contracts or [] if c.get("planned_end_on")]
        if ends and max(ends) < date.today():
            days = (date.today() - max(ends)).days
            return f"Termin z umowy minął {fmt_num(days)} dni temu, a w BZP nie ma ogłoszenia o wykonaniu umowy."
        return "W BZP nie ma ogłoszenia o wykonaniu umowy, więc nie wiemy jeszcze, jak skończyła się ta inwestycja."
    delay, cost = m.get("delay_days"), m.get("cost_dev_pct")
    a = (f"Skończono {fmt_num(delay)} dni po terminie" if delay and delay > 0 else
         (f"Skończono {fmt_num(-delay)} dni przed terminem" if delay and delay < 0 else "Skończono w terminie"))
    if cost is None:
        return a + "."
    b = (f"zapłacono o {fmt_num(cost, 1)}% więcej niż w umowie" if cost > 0.5 else
         (f"zapłacono o {fmt_num(-cost, 1)}% mniej niż w umowie" if cost < -0.5 else "zapłacono tyle, ile w umowie"))
    return f"{a} i {b}."


def plan_vs_actual(ch: dict) -> list[dict]:
    perf, m = ch["perf"], ch["metric"]
    mp = main_perf(perf)
    out = []
    if mp:
        nref = notice_ref(mp.get("notice_number"), mp.get("notice_url"), "ogł. o wykonaniu", "5.2")
        res_no = next((c["result_notice_no"] for c in ch["contracts"] if c["id"] == mp.get("contract_id")), None)
        planned_ref = [Ref(kind="notice", id=res_no, label="ogł. o wyniku", field_code="4.2")] if res_no else [q_ref(f"project:{m['rm_id']}", "termin z umowy")]
        pl, ac, dl = mp.get("planned_days"), mp.get("actual_days"), mp.get("delay_days")
        out.append({
            "key": "time", "label": "Termin",
            "planned": num(pl, f"{fmt_num(pl)} dni" if pl is not None else "brak", "days", Prov(role="source", review_status="auto", refs=planned_ref)),
            "actual": num(ac, f"{fmt_num(ac)} dni" if ac is not None else "brak", "days",
                          Prov(role="calc", review_status="auto", n=1, method="completed_on - signed_on", refs=[nref] if nref else [])),
            "delta": num(dl, f"{'+' if dl and dl > 0 else ''}{fmt_num(dl)} dni" if dl is not None else "brak", "days",
                         Prov(role="calc", review_status="auto", n=1, method="actual - planned", refs=[])),
            "note": f"plan {fmt_num(pl)} dni, faktycznie {fmt_num(ac)}" if pl is not None and ac is not None else None})
    value, paid, cost = m.get("value"), m.get("paid"), m.get("cost_dev_pct")
    if value is not None and paid is not None:
        refs = [r for r in (notice_ref(p.get("notice_number"), p.get("notice_url"), "ogł. o wykonaniu", "5.5") for p in perf) if r]
        out.append({
            "key": "cost", "label": "Koszt",
            "planned_money": {"amount": str(value), "currency": "PLN", "vat_basis": "gross"},
            "actual_money": {"amount": str(paid), "currency": "PLN", "vat_basis": "gross"},
            "delta": num(round(cost, 1) if cost is not None else None, f"{'+' if cost and cost > 0 else ''}{fmt_num(cost, 1)}%" if cost is not None else "brak", "pct",
                         Prov(role="calc", review_status="auto", n=m.get("n_contracts") or 1, method="paid/contract - 1", refs=refs)),
            "note": f"{zl(value)} → {zl(paid)} brutto"})
    return out


def steps(ch: dict) -> list[dict]:
    out: list[dict] = []
    for n in ch["notices"]:
        if n["notice_type"] == "ContractNotice":
            out.append({"date": n["published_at"], "state": "done", "title": "Ogłoszenie o zamówieniu", "text": ch["procs"][0]["title"] if ch["procs"] else "",
                        "ref": {"kind": "notice", "id": n["notice_number"], "label": "ogł. o zamówieniu", "url": n["url"]}, "review_status": "auto"})
    for c in ch["contracts"]:
        out.append({"date": c["signed_on"], "state": "done", "title": "Podpisano umowę",
                    "text": ", ".join(x for x in (c.get("contractor_name"), zl(c.get("value_amount")) + " brutto" if c.get("value_amount") else None,
                                                  f"termin {fmt_num(c['planned_duration_days'])} dni" if c.get("planned_duration_days") else None) if x),
                    "ref": {"kind": "notice", "id": c.get("result_notice_no") or "", "label": "ogł. o wyniku"} if c.get("result_notice_no") else None,
                    "review_status": c["review_status"]})
    for ch_ in ch["changes"]:
        dv = ch_.get("delta_value_amount")
        title = f"Dopłata {zl(dv)}" if dv and dv > 0 else (f"Zmiana wartości {zl(dv)}" if dv else (f"Zmiana terminu o {fmt_num(ch_['delta_days'])} dni" if ch_.get("delta_days") else "Zmiana umowy"))
        basis = ", ".join(ch_["legal_basis"] or [])
        cause = (ch_.get("cause_text") or "").strip()
        out.append({"date": ch_["changed_on"], "state": "done", "title": title,
                    "text": (cause[:220] + ("…" if len(cause) > 220 else "")) + (f" Podstawa: {basis}." if basis else ""),
                    "ref": {"kind": "notice", "id": ch_["notice_number"], "label": "ogł. o zmianie", "url": ch_.get("notice_url")} if ch_.get("notice_number") else None,
                    "review_status": ch_["review_status"]})
    for dc in ch.get("doc_changes", []):
        bits = []
        if dc.get("delta_days"):
            bits.append(f"termin {'+' if dc['delta_days'] > 0 else ''}{fmt_num(dc['delta_days'])} dni")
        if dc.get("delta_value_amount"):
            bits.append(f"wartość {'+' if dc['delta_value_amount'] > 0 else ''}{zl(dc['delta_value_amount'])}")
        approved = dc["review_status"] in ("approved", "edited")
        out.append({"date": dc.get("changed_on"), "state": "done" if approved else "now", "title": "Zmiana z dokumentu: " + (", ".join(bits) or "szczegóły w dokumencie"),
                    "text": ((dc.get("cause_text") or "")[:200]) + ("" if approved else " Czeka na decyzję eksperta."),
                    "ref": {"kind": "document", "id": str(dc["document_id"]), "label": dc.get("doc_title") or "dokument"}, "review_status": dc["review_status"]})
    for p in ch["perf"]:
        out.append({"date": p.get("completed_on"), "state": "done", "title": "Zakończono wykonanie umowy",
                    "text": f"Zapłacono {zl(p.get('total_paid_amount'))} brutto; wykonano " + ("należycie." if p.get("properly_performed") else "nienależycie." if p.get("properly_performed") is False else "(brak oceny).") ,
                    "ref": {"kind": "notice", "id": p["notice_number"], "label": "ogł. o wykonaniu", "url": p.get("notice_url")} if p.get("notice_number") else None,
                    "review_status": p["review_status"]})
    if not ch["perf"] and ch["contracts"]:
        out.append({"date": None, "state": "missing", "title": "Brak ogłoszenia o wykonaniu umowy", "text": "Nie wiemy jeszcze, jak zakończyła się umowa.",
                    "ref": None, "review_status": "auto"})
    out.sort(key=lambda s: (s["date"] is None, str(s["date"] or "")))
    for s in out:
        s["date_label"] = pl_date(s["date"]) if s["date"] else "po ostatnim ogłoszeniu"
        s["date"] = str(s["date"])[:10] if s["date"] else None
    return out


def event_out(e: dict) -> dict:
    refs = [Ref(kind="notice", id=e["change_notice"], label="pole 5.3", url=e.get("change_url"), field_code="5.3").model_dump(mode="json", exclude_none=True)] if e.get("change_notice") else []
    return {"id": e["id"], "title": e["summary"], "text": e.get("cause"), "risk_code": e.get("catalogue_code"),
            "event_type": e.get("event_type"), "review_status": e["review_status"], "origin": e["origin"],
            "prov": {"role": role(e["origin"]), "review_status": e["review_status"], "refs": refs,
                     **({"llm": {"llm_call_id": e["llm_call_id"]}} if e.get("llm_call_id") else {})}}


# ---------------------------------------------------------------------------------------------------- documents view

EXPECTED = [  # (doc_type, label, ext, unlocks, where, only_for_design_build, limits_when_missing)
    ("pfu", "Program funkcjonalno-użytkowy (PFU)", "PDF", "Potwierdzi, czy roboty dodatkowe wynikały z niepełnego opisu zakresu (R01).", "Załączniki do ogłoszenia o zamówieniu, BIP zamawiającego.", True,
     "Nie potwierdzimy, czego w nim brakowało."),
    ("swz", "Specyfikacja warunków zamówienia (SWZ)", "PDF", "Pozwoli sprawdzić podział ryzyk i terminy w postępowaniu.", "Platforma zakupowa zamawiającego, załączniki do ogłoszenia.", False,
     "Nie sprawdzimy podziału ryzyk w postępowaniu."),
    ("ppu", "Projektowane postanowienia umowy", "PDF", "Pokaże klauzule waloryzacyjne i zasady zmian umowy (R08).", "Załączniki do SWZ na platformie zakupowej.", False,
     "Nie ocenimy klauzul waloryzacyjnych i zasad zmian umowy."),
    ("geotech", "Dokumentacja geotechniczna", "PDF", "Potwierdzi rozpoznanie gruntu przed przetargiem (R02).", "Dokumentacja projektowa, załączniki do SWZ.", False,
     "Ogranicza ocenę ryzyka R02 (grunt)."),
    ("protokol", "Protokół konieczności lub odbioru", "PDF", "Pokaże zmiany zakresu i terminu oraz faktyczną datę zakończenia.", "Dokumentacja realizacji u zamawiającego.", False,
     "Nie sprawdzimy, z czego wynikały zmiany w trakcie realizacji."),
    ("projekt", "Dokumentacja projektowa", "PDF", "Pozwoli porównać zakres projektu z zakresem robót.", "Załączniki do SWZ.", False,
     "Nie porównamy zakresu projektu z zakresem robót."),
]
STATE_LABEL = {"BRAK_W_PACZCE": "nie ma w paczce", "POTWIERDZONO": "mamy dokument", "NIECZYTELNY": "dokument nieczytelny"}


async def documents_view(db: AsyncSession, rm_id: str, user: A.User | None) -> dict | None:
    ch = await load_chain(db, rm_id, user)
    if ch is None:
        return None
    p = ch["project"]
    scope = "d.procedure_id = ANY(:p)" if p["id"] is None else "d.project_id = :p"
    docs = await rows(db, f"SELECT d.id, d.doc_type, d.title, d.filename, d.fetch_state, d.url, d.sha256, d.mime, d.data->'facts'->>'doc_kind' AS doc_kind FROM document d WHERE {scope} "
                          f"AND {A.public_doc_filter(user)} AND {A.public_filter(user, 'd')} ORDER BY d.id",
                      p=[x["id"] for x in ch["procs"]] if p["id"] is None else p["id"])
    have_types = {d["doc_type"] for d in docs if d["fetch_state"] == "found"}
    if any((d.get("doc_kind") or "").startswith("protokol") or (d.get("doc_type") or "").startswith("protok") for d in docs):
        have_types.add("protokol")
    design_build = bool(p.get("delivery_model") and "projektuj" in str(p["delivery_model"]).lower()) or any(x.get("design_build") for x in ch["procs"])
    expected = []
    for dt, label, ext, unlocks, where, only_db, limits in EXPECTED:
        if only_db and not design_build:
            continue
        have = dt in have_types
        state = "POTWIERDZONO" if have else "BRAK_W_PACZCE"
        expected.append({"doc_type": dt.upper(), "key": dt, "label": label, "title": label, "ext": ext, "evidence_state": state, "state": state,
                         "state_label": STATE_LABEL[state], "limits": limits, "unlocks": unlocks, "where_to_find": where, "where": where, "have": have,
                         "checklist": f"{label}: {'jest w paczce' if have else 'brak w paczce'}"})
    codes_by_change: dict[int, str] = {}
    for e in ch["events"]:
        if e.get("change_id") and e.get("catalogue_code"):
            codes_by_change[e["change_id"]] = e["catalogue_code"]
    public = []
    for n in ch["notices"]:
        nid = (await db.execute(text("SELECT id FROM notice WHERE object_id = :o"), {"o": n["object_id"]})).scalar()
        facts = (await db.execute(text("SELECT count(*) FROM evidence WHERE notice_id = :n"), {"n": nid})).scalar() or 0
        ch_codes = sorted({codes_by_change[c["id"]] for c in ch["changes"] if c.get("notice_number") == n["notice_number"] and c["id"] in codes_by_change})
        public.append({"kind": "notice", "key": n["object_id"], "object_id": n["object_id"], "ref": n["notice_number"], "title": _notice_title(n["notice_type"]),
                       "ext": "BZP", "date": str(n["published_at"])[:10], "facts": facts, "facts_label": f"{facts} faktów", "risk_codes": ch_codes,
                       "review_status": "auto", "status_label": "z ogłoszenia BZP", "url": n["url"]})
    from riskminer.review import doclink
    for d in docs:
        gr = await doclink.growth(db, d["id"]) if d.get("doc_kind") else {"short": None, "sentence": None}
        public.append({"kind": "document", "key": f"doc:{d['id']}", "object_id": str(d["id"]), "ref": d.get("filename") or d.get("title"), "title": d.get("title") or d.get("filename"),
                       "growth": gr.get("sentence"), "ext": (d.get("mime") or "pdf").split("/")[-1].upper()[:4], "date": None, "facts": 0,
                       "facts_label": gr.get("short") or "bez faktów", "risk_codes": [],
                       "review_status": "auto", "status_label": "dokument z postępowania", "url": d.get("url")})
    have = sum(1 for x in expected if x["have"])
    return {"expected": expected, "public": public, "public_docs": public, "have": have, "expected_total": len(expected),
            "summary": f"Mamy {_pl(len(ch['notices']), 'ogłoszenie', 'ogłoszenia', 'ogłoszeń')} z BZP. " + (
                f"Brakuje {_pl(len(expected) - have, 'dokumentu', 'dokumentów', 'dokumentów')} z budowy, ich brak ogranicza ocenę przyczyn zmian."
                if len(expected) - have else "Mamy komplet dokumentów z budowy.")}


def _pl(n: int, one: str, few: str, many: str) -> str:
    """'1 ogłoszenie', '3 ogłoszenia', '5 ogłoszeń' (Polish plural)."""
    word = one if n == 1 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many
    return f"{n} {word}"


def _notice_title(t: str | None) -> str:
    return {"ContractNotice": "Ogłoszenie o zamówieniu", "TenderResultNotice": "Ogłoszenie o wyniku postępowania",
            "ContractPerformingNotice": "Ogłoszenie o wykonaniu umowy", "ContractAmendmentNotice": "Ogłoszenie o zmianie umowy",
            "AgreementUpdateNotice": "Ogłoszenie o zmianie umowy", "ContractPerformanceNotice": "Ogłoszenie o wykonaniu umowy"}.get(t or "", t or "Ogłoszenie")


FIELD_LABEL = {
    ("contract", "planned_end_on"): "planowany termin zakończenia", ("contract", "signed_on"): "data zawarcia umowy",
    ("contract", "value"): "wartość umowy",
    ("contract_performance", "properly_performed"): "wykonanie należyte", ("contract_performance", "changes_count"): "liczba zmian umowy",
    ("contract_performance", "completed_on"): "data zakończenia", ("contract_performance", "executed"): "umowa wykonana",
    ("contract_performance", "on_time_declared"): "wykonana w terminie (deklaracja)", ("contract_performance", "total_paid"): "kwota zapłacona",
    ("contract_change", "cause_text"): "uzasadnienie zmiany", ("risk_event", "event"): "zdarzenie ryzyka",
}
TAG_STATUS = {"approved": "zatwierdzone", "edited": "poprawione", "proposed": "do przeglądu", "rejected": "odrzucone"}


def _fmt_value(table: str, field: str, row: dict) -> str:
    def yn(v):
        return "tak" if v else "nie"
    if field in ("planned_end_on", "signed_on", "completed_on"):
        return pl_date(row.get(field))
    if field == "value":
        return f"{zl(row.get('value_amount'))} {'brutto' if row.get('value_vat') == 'gross' else ''}".strip()
    if field == "total_paid":
        return f"{zl(row.get('total_paid_amount'))} brutto"
    if field in ("properly_performed", "executed", "on_time_declared"):
        v = row.get(field)
        return "brak danych" if v is None else yn(v)
    if field == "changes_count":
        return str(row.get("changes_count") if row.get("changes_count") is not None else "brak danych")
    return str(row.get(field) or "")


async def notice_facts(db: AsyncSession, object_id: str, user: A.User | None = None) -> dict | None:
    n = await rows(db, """SELECT n.id, n.notice_number, n.url, n.notice_type, n.source_id, s.retrieved_at, s.sha256, s.licence
                          FROM notice n LEFT JOIN source s ON s.id = n.source_id WHERE n.object_id = :o""", o=object_id)
    if not n:
        return None
    n = n[0]
    ev = await rows(db, """SELECT DISTINCT ON (e.field_code, e.claim_table, e.claim_id, e.claim_field) e.field_code, e.claim_table, e.claim_id, e.claim_field,
                                  e.quote, e.verification FROM evidence e WHERE e.notice_id = :n AND e.claim_table IN ('contract','contract_change','contract_performance','risk_event')
                           ORDER BY e.field_code, e.claim_table, e.claim_id, e.claim_field, e.id""", n=n["id"])
    claims: dict[str, dict[int, dict]] = {}
    for t in {e["claim_table"] for e in ev}:
        ids = [e["claim_id"] for e in ev if e["claim_table"] == t]
        claims[t] = {r["id"]: r for r in await rows(db, f"SELECT * FROM {t} WHERE id = ANY(:i)", i=ids)}
    out = []
    for e in ev:
        t, f = e["claim_table"], e["claim_field"]
        row = claims.get(t, {}).get(e["claim_id"], {})
        if t == "risk_event":
            if not e["quote"] or f != "event":
                continue  # structured duplicates of the same notice field carry no extra information
            if user is None and row.get("origin") == "AI" and row.get("review_status") not in ("approved", "edited"):
                continue
            code = row.get("catalogue_code")
            st = row.get("review_status")
            tag = ", ".join(x for x in (code, TAG_STATUS.get(st)) if x) or "zdarzenie"
            out.append({"field_code": e["field_code"], "label": FIELD_LABEL.get((t, f), f), "value": e["quote"], "tag": tag,
                        "tag_role": role(row.get("origin")), "review_status": st, "claim": {"table": t, "id": e["claim_id"], "field": f}})
            continue
        value = e["quote"] or _fmt_value(t, f, row)
        out.append({"field_code": e["field_code"], "label": FIELD_LABEL.get((t, f), f), "value": value,
                    "tag": "źródło" if t != "contract_performance" or f not in ("changes_count",) else "źródło", "tag_role": "source",
                    "review_status": row.get("review_status") or "auto", "claim": {"table": t, "id": e["claim_id"], "field": f}})
    for r in out:
        r["prov"] = {"role": r["tag_role"], "review_status": r["review_status"],
                     "refs": [{"kind": "notice", "id": n["notice_number"], "label": f"pole {r['field_code']}", "field_code": r["field_code"], "url": n["url"]}]}
    lic = n["licence"] or ""
    return {"rows": out, "meta": {"url": n["url"], "retrieved_at": n["retrieved_at"].isoformat() if n["retrieved_at"] else None,
                                  "sha256": n["sha256"], "licence": lic,
                                  "licence_label": "informacja publiczna" if (not lic or lic.startswith("public information")) else lic,
                                  "notice_number": n["notice_number"]}}


# ------------------------------------------------------------------------------------------------------------ history

PROJECT_AUDIT_SQL = """
SELECT a.* FROM audit_log a
WHERE (a.table_name = 'project' AND a.row_id = :pid)
   OR (a.table_name = 'project_procedure' AND a.row_id IN (SELECT id FROM project_procedure WHERE project_id = :pid))
   OR (a.table_name = 'risk_event' AND a.row_id IN (SELECT id FROM risk_event WHERE project_id = :pid))
   OR (a.table_name = 'review_item' AND a.row_id IN (SELECT id FROM review_item WHERE project_id = :pid))
   OR (a.table_name = 'link_candidate' AND a.row_id IN (SELECT id FROM link_candidate WHERE left_table = 'project' AND left_id = :pid))
"""


def _pl_events(n: int) -> str:
    return f"{n} {'zdarzenie' if n == 1 else 'zdarzenia' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'zdarzeń'} ryzyka"


async def _derived(db: AsyncSession, pid: int) -> list[dict]:
    """History entries for facts that were written by the pipeline without an audit row: the organiser import, the notice
    match, deterministic events and the model's proposals. They look like audit rows (negative ids, never restorable)."""
    out: list[dict] = []
    n = -1

    def add(at, actor, label, after, why, table, row_id):
        nonlocal n
        out.append({"id": n, "at": at, "actor": actor, "action": "derived", "_label": label, "table_name": table, "row_id": row_id,
                    "before": "brak", "after": after, "note": why, "request_id": None})
        n -= 1
    p = (await rows(db, "SELECT rm_id, created_at, beneficiary_nip FROM project WHERE id = :p", p=pid))[0]
    add(p["created_at"], "system:xlsx_import", "zaimportował rekord z zestawu organizatora", p["rm_id"],
        "Wiersz zestawu organizatora" + (", NIP przeszedł sumę kontrolną." if p["beneficiary_nip"] else "."), "project", pid)
    for l in await rows(db, """SELECT pp.id, pp.created_at, pp.method, pp.score, pr.ocid FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
                               WHERE pp.project_id = :p AND pp.review_status <> 'rejected'""", p=pid):
        why = f"Metoda dopasowania: {l['method']}" + (f", wynik {fmt_num(l['score'], 2)}." if l["score"] is not None else ".")
        add(l["created_at"], "system:linker", "dopasował postępowanie BZP do projektu", l["ocid"], why, "project_procedure", l["id"])
    calc = await rows(db, "SELECT count(*) AS n, min(created_at) AS at FROM risk_event WHERE project_id = :p AND origin <> 'AI'", p=pid)
    if calc[0]["n"]:
        add(calc[0]["at"], "system:derive", "wyliczył zdarzenia ryzyka z pól ogłoszeń", _pl_events(calc[0]["n"]), "Reguły na polach ogłoszeń BZP, bez modelu.",
            "risk_event", None)
    for e in await rows(db, """SELECT e.id, e.created_at, e.catalogue_code, e.summary, e.conf_data_quality, e.cause, c.provider, c.model
                               FROM risk_event e LEFT JOIN llm_call c ON c.id = e.llm_call_id WHERE e.project_id = :p AND e.origin = 'AI' ORDER BY e.id""", p=pid):
        actor = f"model:{e['provider']}/{e['model']}" if e.get("model") else "model:AI"
        conf = f", pewność {fmt_num(e['conf_data_quality'], 2)}" if e.get("conf_data_quality") is not None else ""
        add(e["created_at"], actor, f"zaproponował zdarzenie {e['catalogue_code'] or ''}".strip(), f"{e['catalogue_code'] or 'bez kodu'}{conf}",
            (e.get("cause") or e["summary"] or "")[:160], "risk_event", e["id"])
    return out


async def _timeline(db: AsyncSession, pid: int) -> list[dict]:
    """Ascending list of entries (audit rows + derived ones); position + 1 = record version."""
    audit_rows = await rows(db, f"SELECT * FROM ({PROJECT_AUDIT_SQL}) x", pid=pid)
    allr = audit_rows + await _derived(db, pid)
    allr.sort(key=lambda r: (r["at"], 0 if r["id"] < 0 else 1, abs(r["id"])))
    for i, r in enumerate(allr, 1):
        r["seq"] = i
    return allr


async def history(db: AsyncSession, rm_id: str, actor_kind: str | None) -> dict | None:
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id = :r"), {"r": rm_id})).scalar()
    if pid is None:
        return None
    tl = await _timeline(db, pid)
    items = []
    for r in reversed(tl):
        e = AR.entry(r, version=f"v{r['seq']}")
        if actor_kind and e["actor_kind"] != actor_kind:
            continue
        items.append(e)
    return {"record_version": f"v{len(tl)}", "versions": [{"version": f"v{i}", "label": f"v{i}"} for i in range(1, len(tl) + 1)], "items": items}


async def history_compare(db: AsyncSession, rm_id: str, v_from: str, v_to: str) -> dict | None:
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id = :r"), {"r": rm_id})).scalar()
    if pid is None:
        return None
    try:
        a, b = int(v_from.lstrip("v")), int(v_to.lstrip("v"))
    except ValueError:
        return {"changes": []}
    rs = [r for r in await _timeline(db, pid) if min(a, b) < r["seq"] <= max(a, b)]
    merged: dict[tuple, dict] = {}
    for r in rs:
        if r["action"] == "derived":  # a fact that appeared: before "brak", after the new value
            k = (r["table_name"], r["row_id"], r["_label"])
            merged[k] = {"table": r["table_name"], "row_id": r["row_id"], "field": r["_label"], "before": "brak", "after": r["after"]}
            continue
        chs = (r["before"] or {}).get("changes") if isinstance(r.get("before"), dict) and "changes" in r["before"] else None
        afs = {(c["table"], c["id"]): c.get("fields") or {} for c in ((r["after"] or {}).get("changes") or [])} if isinstance(r.get("after"), dict) else {}
        for c in chs or []:
            for f, before in (c.get("fields") or {}).items():
                k = (c["table"], c["id"], f)
                after = afs.get((c["table"], c["id"]), {}).get(f)
                merged[k] = {"table": c["table"], "row_id": c["id"], "field": f, "before": merged[k]["before"] if k in merged else before, "after": after}
    return {"from": v_from, "to": v_to, "changes": [{**v, "before": AR.short(v["before"]), "after": AR.short(v["after"])} for v in merged.values()]}


# --------------------------------------------------------------------------------------------------------------- card

async def similar_cases(db: AsyncSession, rm_id: str, k: int = 5) -> list[dict]:
    """Simple similarity over rc_contract (same subsector, close contract value, same formula), with per-feature contributions.
    Method `similarity_simple`; the analysis engine (analytics/similarity.py) is the richer version used for reports."""
    if is_ocid(rm_id):
        me = await rows(db, """SELECT NULL::bigint AS id, pr.subsector_main, pr.design_build, coalesce((SELECT sum(contract_value_amount) FROM contract_performance cp
                               WHERE cp.procedure_id = pr.id AND NOT cp.is_duplicate), 0) AS value, pr.ocid FROM procedure pr WHERE pr.ocid = :r""", r=rm_id)
    else:
        me = await rows(db, """SELECT p.id, p.subsector_main, pr.design_build, COALESCE(m.value, 0) AS value, pr.ocid FROM project p
        LEFT JOIN LATERAL (SELECT pr.* FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id WHERE pp.project_id = p.id
                           AND pp.review_status <> 'rejected' ORDER BY pp.score DESC NULLS LAST LIMIT 1) pr ON true
        LEFT JOIN LATERAL (SELECT sum(contract_value_amount) AS value FROM contract_performance cp JOIN project_procedure pp2 ON pp2.procedure_id = cp.procedure_id
                           WHERE pp2.project_id = p.id AND NOT cp.is_duplicate) m ON true WHERE p.rm_id = :r""", r=rm_id)
    if not me:
        return []
    me = me[0]
    val = float(me["value"] or 0) or None
    rs = await rows(db, """
        SELECT rc.*, pr.title, pj.rm_id, pn.notice_number, pn.url
        FROM rc_contract rc JOIN procedure pr ON pr.id = rc.procedure_id
        LEFT JOIN project_procedure pp ON pp.procedure_id = rc.procedure_id AND pp.review_status <> 'rejected'
        LEFT JOIN project pj ON pj.id = pp.project_id LEFT JOIN notice pn ON pn.id = (SELECT notice_id FROM contract_performance WHERE id = rc.performance_id)
        WHERE rc.relevance = 'core' AND rc.subsector_main = :sub AND rc.value_gross IS NOT NULL AND rc.delay_days IS NOT NULL
          AND (pj.rm_id IS NULL OR pj.rm_id <> :rm) AND pr.ocid <> :ocid
          AND (CAST(:val AS numeric) IS NULL OR rc.value_gross BETWEEN CAST(:val AS numeric) / 3 AND CAST(:val AS numeric) * 3)
        ORDER BY abs(ln(rc.value_gross / COALESCE(CAST(:val AS numeric), rc.value_gross))), rc.performance_id LIMIT :k""",
                  sub=me["subsector_main"], rm=rm_id, ocid=me["ocid"] or "", val=val, k=k)
    import math
    pool = (await db.execute(text("SELECT count(*) FROM rc_contract WHERE relevance='core' AND subsector_main = :s AND delay_days IS NOT NULL"),
                             {"s": me["subsector_main"]})).scalar() or 0
    out = []
    for i, r in enumerate(rs, 1):
        dv = abs(math.log(float(r["value_gross"]) / val)) if val else 1.0
        c_sub = 0.5
        c_val = round(0.35 * max(0.0, 1 - dv / math.log(3)), 3)
        c_form = 0.15 if (me["design_build"] is not None and r["design_build"] == me["design_build"]) else 0.0
        score = round(c_sub + c_val + c_form, 2)
        ref_perf = [Ref(kind="notice", id=r["notice_number"], label="ogł. o wykonaniu", url=r["url"], field_code="5.2").model_dump(mode="json", exclude_none=True)] if r.get("notice_number") else \
                   [Ref(kind="procedure", id=r["ocid"], label="postępowanie").model_dump(mode="json", exclude_none=True)]
        out.append({
            "rank": i, "rm_id": r.get("rm_id"), "ocid": r["ocid"], "title": r["title"],
            "score": num(score, fmt_num(score, 2), "score", Prov(role="calc", review_status="auto", n=int(pool), method="similarity_simple",
                                                                refs=[q_ref("similarity:simple", "podsektor, wartość, formuła")])),
            "why": "ten sam podsektor" + (", podobna wartość" if c_val > 0.2 else "") + (", ta sama formuła" if c_form else ""),
            "contributions": [{"feature": "subsector_main", "label": "podsektor", "value": c_sub}, {"feature": "value", "label": "wartość", "value": c_val},
                              {"feature": "formula", "label": "formuła", "value": c_form}],
            "outcome": {"delay_days": num(r["delay_days"], f"{'+' if r['delay_days'] > 0 else ''}{fmt_num(r['delay_days'])} dni", "days",
                                          Prov(role="case", review_status="auto", refs=[Ref(**x) for x in ref_perf])),
                        "cost_dev_pct": num(round(r["cost_dev_pct"], 1) if r["cost_dev_pct"] is not None else None,
                                            f"{'+' if (r['cost_dev_pct'] or 0) > 0 else ''}{fmt_num(r['cost_dev_pct'], 1)}%" if r["cost_dev_pct"] is not None else "brak",
                                            "pct", Prov(role="case", review_status="auto", refs=[Ref(**x) for x in ref_perf]))},
            "href": f"/projekty/{r['rm_id']}" if r.get("rm_id") else f"/umowy/{r['contract_id']}"})
    return out


async def _from_documents(db: AsyncSession, ch: dict) -> list[dict]:
    """"Nowe w bazie dzięki temu dokumentowi" for every document of the project that was read and linked."""
    from riskminer.review import doclink
    p = ch["project"]
    if p["id"] is None:
        return []
    rs = await rows(db, "SELECT id, title, filename, data->'facts'->>'doc_kind_label' AS kind_label FROM document WHERE project_id = :p AND data ? 'link' ORDER BY id", p=p["id"])
    out = []
    for d in rs:
        gr = await doclink.growth(db, d["id"])
        if gr["sentence"]:
            out.append({"document_id": d["id"], "title": d["title"] or d["filename"], "kind_label": d["kind_label"], "sentence": gr["sentence"], "href": f"/projekty/{p['rm_id']}/dokumenty?dok=doc:{d['id']}"})
    return out


async def card(db: AsyncSession, rm_id: str, user: A.User | None) -> dict | None:
    ch = await load_chain(db, rm_id, user)
    if ch is None:
        return None
    p, m = ch["project"], ch["metric"]
    docs = await documents_view(db, rm_id, user)
    metrics = metrics_for(m, user)
    ev_out = [event_out(e) for e in ch["events"]]
    # lessons shown on the card: events with their review status (public mode: no unverified AI, see unverified_hidden)
    open_by_event = {r["target_id"]: r["id"] for r in await rows(
        db, "SELECT id, target_id FROM review_item WHERE status='open' AND target_table='risk_event' AND target_id = ANY(:ids)",
        ids=[e["id"] for e in ch["events"]] or [0])} if user else {}
    for e in ev_out:
        e["review_item_id"] = open_by_event.get(e["id"])
    st = steps(ch)
    org = ch["org"]
    ident = [{"k": "Rekord", "v": rm_id}] if p["kind"] == "pilot_project" else []
    for pr in ch["procs"]:
        if pr.get("contract_notice_no"):
            ident.append({"k": "BZP", "v": pr["contract_notice_no"]})
        ident.append({"k": "OCID", "v": pr["ocid"]})
    if p.get("beneficiary_nip"):
        ident.append({"k": "NIP", "v": p["beneficiary_nip"], "verified": bool(org and org.get("nip_valid")), "check": "ok" if org and org.get("nip_valid") else None})
    for s in st:
        s["href"] = None
    return {
        "rm_id": rm_id, "id": rm_id, "kind": p["kind"], "title": p["title"], "auto_card": not p.get("is_pilot"),  # pilot RM-* cards are curated records; only cards built from OCIDs alone are automatic
        "buyer": {"name": (org or {}).get("name") or p.get("beneficiary_name"), "nip": p.get("beneficiary_nip"), "nip_valid": (org or {}).get("nip_valid")},
        "summary": {"sentence": summary_sentence(m, ch["perf"], ch["contracts"]),
                    "prov": {"role": "calc", "review_status": "auto", "method": "template:card_v1", "n": m.get("n_contracts") or 0,
                             "refs": [q_ref(f"project:{rm_id}", "dane z ogłoszeń o wykonaniu")]}},
        "metrics": metrics,
        "plan_vs_actual": plan_vs_actual(ch),
        "steps": st, "timeline": st,
        "events": ev_out, "lessons": ev_out,
        "gaps": [{"doc_type": x["doc_type"], "evidence_state": x["evidence_state"], "state_label": x["state_label"], "limits": x["limits"]}
                 for x in (docs or {}).get("expected", []) if not x["have"]],
        "doc_counts": {"have": (docs or {}).get("have", 0), "expected": (docs or {}).get("expected_total", 0)},
        "identifiers": ident,
        "similar": await similar_cases(db, rm_id, 5),
        "unverified_hidden": ch["hidden"],
        "from_documents": await _from_documents(db, ch),
        "chat": {"suggestions": ["Dlaczego umowa skończyła się po terminie?", "Co zmieniło wartość umowy?"]},
    }
