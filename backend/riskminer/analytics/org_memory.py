"""Authority and contractor memory (W10): a neutral history of one organisation (NIP) from the national BZP copy.

Roles: `contractor` (contract.contractor_nip) and `buyer` (procedure.buyer_nip of the contract's procedure). Every number is a
calc Num with n and method; below MEMORY_MIN_N contracts the value is "za mało danych" (api/prov.py rules). Read-only.

Definitions (stated in each Num.prov.method):
- completed: the contract has a (non-duplicate) performance notice with executed = true;
- ongoing: no performance notice, signed on or before as_of, planned end not older than 365 days before as_of;
- late: completed with delay_days > 0 (denominator: completed contracts with a known delay);
- load history (R12): month-end concurrent ongoing contracts over the last 24 months (signed, not yet completed or planned end).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analytics import flags as FL
from riskminer.analytics.base import as_of
from riskminer.api.prov import Money, Ref, fmt_num, num_calc, q_ref

MEMORY_MIN_N = 5
ROLES = ("contractor", "buyer")
CHANGE_LABEL = {"time": "zmiana terminu", "price": "zmiana ceny", "scope": "zmiana zakresu", "termin": "zmiana terminu"}
ONGOING = "pf.executed IS NULL AND c.signed_on <= :asof AND c.planned_end_on >= CAST(:asof AS date) - 365"

_FROM = {
    "contractor": "contract c",
    "buyer": "contract c JOIN procedure p0 ON p0.id = c.procedure_id",
}
_WHERE = {"contractor": "c.contractor_nip = :nip", "buyer": "p0.buyer_nip = :nip"}
_PERF = ("LEFT JOIN LATERAL (SELECT executed, completed_on, delay_days FROM contract_performance x "
         "WHERE x.contract_id = c.id AND NOT x.is_duplicate ORDER BY x.id LIMIT 1) pf ON true")


def _base(role: str) -> str:
    return f"FROM {_FROM[role]} {_PERF} WHERE {_WHERE[role]}"


def _ref(role: str, nip: str) -> list[Ref]:
    return [q_ref(f"organization:{nip}:{role}", "umowy z ogłoszeń BZP (kopia krajowa), NIP " + nip)]


def _n(value: float | None, display: str, unit: str, n: int, method: str, role: str, nip: str) -> dict:
    return num_calc(value, display, unit, n=n, method=method, refs=_ref(role, nip), min_n=MEMORY_MIN_N).model_dump(mode="json")


def _pct(x: float) -> str:
    return fmt_num(round(x * 100, 1), 1) + "%"


async def _one(db: AsyncSession, sql: str, **p) -> dict[str, Any]:
    return dict((await db.execute(text(sql), p)).mappings().one())


async def _all(db: AsyncSession, sql: str, **p) -> list[dict[str, Any]]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


async def _role_memory(db: AsyncSession, nip: str, role: str, asof: date) -> dict:
    b = _base(role)
    s = await _one(db, f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE pf.executed) AS completed,
               count(*) FILTER (WHERE {ONGOING}) AS ongoing,
               count(*) FILTER (WHERE pf.executed AND pf.delay_days IS NOT NULL) AS timed,
               count(*) FILTER (WHERE pf.executed AND pf.delay_days > 0) AS late,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY pf.delay_days) FILTER (WHERE pf.executed AND pf.delay_days > 0) AS med_delay,
               coalesce(sum(c.value_amount) FILTER (WHERE {ONGOING} AND c.value_vat = 'gross'), 0) AS ongoing_value,
               count(*) FILTER (WHERE {ONGOING} AND c.value_vat = 'gross') AS ongoing_value_n
        {b}""", nip=nip, asof=asof)
    total, completed, ongoing = int(s["total"]), int(s["completed"]), int(s["ongoing"])
    timed, late = int(s["timed"]), int(s["late"])
    ch = await _all(db, f"""
        SELECT cc.contract_id, cc.change_types FROM contract_change cc
        WHERE NOT cc.is_duplicate AND cc.contract_id IN (SELECT c.id {b})""", nip=nip, asof=asof)
    kinds: dict[str, int] = {}
    for r in ch:
        for k in set(r["change_types"] or []):
            kinds[k] = kinds.get(k, 0) + 1
    changed_contracts = len({r["contract_id"] for r in ch})
    ev = await _all(db, f"""
        SELECT split_part(e.catalogue_code, '.', 1) AS code, count(*) AS n, count(DISTINCT e.procedure_id) AS cases
        FROM risk_event e WHERE e.catalogue_code ~ '^R[0-9]' AND e.review_status <> 'rejected'
          AND e.procedure_id IN (SELECT c.procedure_id {b})
        GROUP BY 1 ORDER BY n DESC, code LIMIT 5""", nip=nip, asof=asof)
    names = {r["code"]: r["name"] for r in await _all(db, """
        SELECT DISTINCT ON (code) code, name FROM catalogue_risk WHERE level = 1 ORDER BY code, version DESC""")}
    recent = await _all(db, f"""
        SELECT c.id, c.signed_on, c.planned_end_on, c.value_amount, c.value_currency, c.value_vat, c.contractor_name,
               pr.ocid, pr.title, pr.buyer_name, pf.executed, pf.delay_days, pr.contract_notice_no,
               ({ONGOING}) AS is_ongoing
        FROM {_FROM[role]} JOIN procedure pr ON pr.id = c.procedure_id {_PERF}
        WHERE {_WHERE[role]} ORDER BY c.signed_on DESC NULLS LAST, c.id DESC LIMIT 5""", nip=nip, asof=asof)

    def m(label_n: int, method: str, value: float | None, disp: str, unit: str) -> dict:
        return _n(value, disp, unit, label_n, method, role, nip)

    kind_total = sum(kinds.values())
    out = {
        "role": role,
        "contracts_total": m(total, "count(umowy w roli)", total, fmt_num(total), "count"),
        "completed": m(total, "count(umowy z ogłoszeniem o wykonaniu, executed)", completed, fmt_num(completed), "count"),
        "ongoing": m(total, "count(bez ogłoszenia o wykonaniu, planowany koniec nie starszy niż 365 dni)", ongoing,
                     fmt_num(ongoing), "count"),
        "late_share": m(timed, "share(opóźnienie > 0 | umowy wykonane ze znanym opóźnieniem)",
                        (late / timed) if timed else None, _pct(late / timed) if timed else "", "share"),
        "median_delay_days": m(late, "median(delay_days | umowy wykonane po terminie)", s["med_delay"],
                               f"{fmt_num(s['med_delay'])} dni" if s["med_delay"] is not None else "", "days"),
        "annexes": m(total, "count(zmiany umów z ogłoszeń o zmianie, bez duplikatów)", len(ch), fmt_num(len(ch)), "count"),
        "contracts_with_change_share": m(total, "share(umowy z co najmniej jedną zmianą)",
                                         (changed_contracts / total) if total else None,
                                         _pct(changed_contracts / total) if total else "", "share"),
        "change_kinds": [
            {"kind": k, "label": CHANGE_LABEL.get(k, k), "count": v,
             "share": _n(v / kind_total, _pct(v / kind_total), "share", kind_total, "share(rodzaj zmiany | wszystkie rodzaje)", role, nip)}
            for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]) if kind_total
        ],
        "top_risks": [
            {"code": r["code"], "name": names.get(r["code"], r["code"]), "events": int(r["n"]), "cases": int(r["cases"]),
             "count": _n(int(r["n"]), fmt_num(int(r["n"])), "count", int(r["n"]), "count(zdarzenia ryzyka z postępowań roli)", role, nip),
             "href": f"/przeglad?ryzyko={r['code']}"}
            for r in ev
        ],
        "recent_contracts": [
            {"contract_id": r["id"], "title": r["title"], "ocid": r["ocid"], "href": f"/projekty/{r['ocid']}",
             "signed_on": r["signed_on"].isoformat() if r["signed_on"] else None,
             "planned_end_on": r["planned_end_on"].isoformat() if r["planned_end_on"] else None,
             "counterparty": r["buyer_name"] if role == "contractor" else r["contractor_name"],
             "value": Money(amount=r["value_amount"], currency=r["value_currency"], vat_basis=r["value_vat"] or "unknown").model_dump(mode="json"),
             "state": "completed" if r["executed"] else ("ongoing" if r["is_ongoing"] else "unknown"),
             "state_label": "zakończona" if r["executed"] else ("w toku" if r["is_ongoing"] else "brak ogłoszenia o wykonaniu"),
             "delay_days": r["delay_days"]}
            for r in recent
        ],
    }
    out["ongoing_value"] = {"money": Money(amount=Decimal(s["ongoing_value"]), currency="PLN", vat_basis="gross").model_dump(mode="json"),
                            "n": int(s["ongoing_value_n"]), "method": "sum(wartość brutto umów w toku)"}
    out["_raw"] = {"total": total, "ongoing": ongoing, "ongoing_value": float(s["ongoing_value"])}
    return out


async def _load_history(db: AsyncSession, nip: str, asof: date) -> dict:
    """Month-end concurrent contracts (and gross value) of the contractor over the previous 24 months."""
    rs = await _all(db, f"""
        WITH c AS (SELECT c.signed_on, c.value_amount, c.value_vat,
                          CASE WHEN pf.executed THEN coalesce(pf.completed_on, c.planned_end_on) ELSE c.planned_end_on + 365 END AS end_on
                   {_base('contractor')}),
        mo AS (SELECT (date_trunc('month', CAST(:asof AS date)) - make_interval(months => g))::date AS d FROM generate_series(1, 24) g)
        SELECT mo.d, count(c.*) FILTER (WHERE c.signed_on <= mo.d AND c.end_on >= mo.d) AS conc,
               coalesce(sum(c.value_amount) FILTER (WHERE c.signed_on <= mo.d AND c.end_on >= mo.d AND c.value_vat = 'gross'), 0) AS val
        FROM mo CROSS JOIN c GROUP BY mo.d ORDER BY mo.d""", nip=nip, asof=asof)
    conc = sorted(int(r["conc"]) for r in rs)
    val = sorted(float(r["val"]) for r in rs)

    def med(x):
        return (x[len(x) // 2] if len(x) % 2 else (x[len(x) // 2 - 1] + x[len(x) // 2]) / 2) if x else None

    return {"months": len(rs), "median_concurrent": med(conc), "max_concurrent": max(conc) if conc else None,
            "median_value": med(val)}


async def organization_memory(db: AsyncSession, nip: str) -> dict | None:
    org = (await db.execute(text("SELECT id, nip, name, roles, province, city, nip_valid FROM organization WHERE nip = :n"),
                            {"n": nip})).mappings().first()
    if org is None:
        return None
    asof = as_of()
    roles = {}
    for role in ROLES:
        roles[role] = await _role_memory(db, nip, role, asof)
    hist = await _load_history(db, nip, asof)
    c = roles["contractor"]
    raw = c.pop("_raw")
    roles["buyer"].pop("_raw")
    n = raw["total"]
    flags: list[dict] = []
    load = {
        "ongoing": _n(raw["ongoing"], fmt_num(raw["ongoing"]), "count", n, "count(umowy w toku wykonawcy)", "contractor", nip),
        "history_median": _n(hist["median_concurrent"], fmt_num(hist["median_concurrent"], 1) if hist["median_concurrent"] is not None else "",
                             "count", n, "median(miesięczna liczba równoległych umów, 24 mies.)", "contractor", nip),
        "ongoing_value": c["ongoing_value"],
        "history_median_value": {"money": Money(amount=Decimal(str(hist["median_value"] or 0)), currency="PLN", vat_basis="gross").model_dump(mode="json"),
                                 "n": n, "method": "median(miesięczna wartość brutto równoległych umów, 24 mies.)"},
        "months": hist["months"],
    }
    fl = FL.contractor_load_flag(raw["ongoing"], raw["ongoing_value"], hist["median_concurrent"], hist["median_value"], n,
                                 min_n=MEMORY_MIN_N)
    if fl is not None:
        flags.append({"code": fl.code, "rule": fl.rule, "title": fl.title, "text": fl.text, "risk_codes": fl.risk_codes,
                      "inputs": fl.inputs, "n": fl.n,
                      "prov": {"role": "calc", "review_status": "auto", "n": n, "method": fl.rule, "refs": [r.model_dump(mode="json") for r in _ref("contractor", nip)]}})
    return {
        "organization": {"nip": org["nip"], "name": org["name"], "roles": org["roles"] or [], "province": org["province"],
                        "city": org["city"], "nip_valid": org["nip_valid"]},
        "as_of": asof.isoformat(), "min_n": MEMORY_MIN_N,
        "contractor": c, "buyer": roles["buyer"], "load": load, "flags": flags,
        "note": "Neutralne fakty z ogłoszeń BZP; nie jest to ocena ani ranking organizacji.",
    }
