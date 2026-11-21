"""Monitoring 4.1-4.1c (public start page): region aggregates from rc_contract, signals from monitor_signals(as_of).

Population (both modes): water/sewage (sector wod-kan) procedures classified relevance=core, scope_kind=works.
- mode done: completed contracts in rc_contract (rows with impossible dates have late/delay NULL, see 0010).
- mode open: signals = contracts past their planned end with no performance notice as of `as_of`.
Region key: buyer TERYT (organization.teryt, see ingest/geo.py) at woj (2) / pow (4) / gmi (7) level; woj falls back
to the procedure province. Every value is a calc Num with n and a query ref (api/prov.py rules).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.prov import Money, Num, Ref, Signal, fmt_num, num_calc, num_source, q_ref

CORE = "r.sector = 'wod-kan' AND r.relevance = 'core' AND r.scope_kind = 'works'"
NOTICE_URL = "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{}"

METRICS: dict[str, dict[str, str]] = {
    "late": {"label": "Po terminie", "description": "odsetek umów zakończonych po terminie z umowy", "unit": "pct"},
    "delay": {"label": "Opóźnienie", "description": "mediana opóźnienia umów zakończonych po terminie (dni)", "unit": "days"},
    "over": {"label": "Ponad wartość umowy", "description": "odsetek umów, w których wypłacono o ponad 0,5% więcej niż wartość umowy",
             "unit": "pct"},
    "chg": {"label": "Zmiany umów", "description": "odsetek umów z co najmniej jedną zmianą", "unit": "pct"},
    "imp": {"label": "Nienależyte wykonanie", "description": "odsetek umów wykonanych nienależycie", "unit": "pct"},
    "sig": {"label": "Sygnały", "description": "umowy po terminie bez ogłoszenia o wykonaniu", "unit": "count"},
}
LEVEL_LEN = {"woj": 2, "pow": 4, "gmi": 7}
CHILD = {"woj": "pow", "pow": "gmi"}


@dataclass
class Filters:
    subsector: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    year_from: int | None = None
    year_to: int | None = None
    q: str | None = None
    as_of: date | None = None
    sector: str = "wod-kan"     # other sector packs (drogi, budynki, cieplo): all their completed works, by region


def _population(f: Filters, params: dict) -> str:
    if f.sector == "wod-kan":
        return CORE
    params["sector"] = f.sector
    return "r.sector = :sector AND r.scope_kind = 'works'"


def level_of(terc: str) -> str:
    return {2: "woj", 4: "pow", 7: "gmi"}.get(len(terc), "gmi")


def _key(level: str, alias: str = "r") -> str:
    if level == "woj":
        return f"{alias}.buyer_woj"
    if level == "pow":
        return f"CASE WHEN length({alias}.buyer_terc) >= 4 THEN left({alias}.buyer_terc, 4) END"
    return f"CASE WHEN length({alias}.buyer_terc) = 7 THEN {alias}.buyer_terc END"


def _sig_key(level: str) -> str:
    return {"woj": "s.woj", "pow": "s.pow", "gmi": "s.gmi"}[level]


def _rc_where(f: Filters, params: dict, parent: str | None, level: str) -> str:
    w = [_population(f, params)]
    if parent:
        w.append(f"{_key(level)} LIKE :parent")
        params["parent"] = parent + "%"
    if f.subsector:
        w.append("(r.subsector_main = :sub OR :sub = ANY(r.subsectors))")
        params["sub"] = f.subsector
    if f.value_min is not None:
        w.append("r.value_gross >= :vmin")
        params["vmin"] = f.value_min
    if f.value_max is not None:
        w.append("r.value_gross <= :vmax")
        params["vmax"] = f.value_max
    if f.year_from:
        w.append("r.completion_year >= :yfrom")
        params["yfrom"] = f.year_from
    if f.year_to:
        w.append("r.completion_year <= :yto")
        params["yto"] = f.year_to
    if f.as_of:
        w.append("r.completed_on <= :as_of")
        params["as_of"] = f.as_of
    if f.q:
        w.append("EXISTS (SELECT 1 FROM procedure p WHERE p.id = r.procedure_id AND (p.title ILIKE :q OR p.buyer_name ILIKE :q))")
        params["q"] = f"%{f.q}%"
    return " AND ".join(w)


def _sig_where(f: Filters, params: dict) -> str:
    if f.sector != "wod-kan":
        return "false"          # monitor_signals(as_of) covers core water/sewage works only (frozen schema)
    w = ["true"]
    if f.subsector:
        w.append("s.subsector_main = :sub")
        params["sub"] = f.subsector
    if f.value_min is not None:
        w.append("s.value_amount >= :vmin")
        params["vmin"] = f.value_min
    if f.value_max is not None:
        w.append("s.value_amount <= :vmax")
        params["vmax"] = f.value_max
    if f.year_from:
        w.append("extract(year FROM s.signed_on) >= :yfrom")
        params["yfrom"] = f.year_from
    if f.year_to:
        w.append("extract(year FROM s.signed_on) <= :yto")
        params["yto"] = f.year_to
    if f.q:
        w.append("(s.title ILIKE :q OR s.buyer_name ILIKE :q)")
        params["q"] = f"%{f.q}%"
    return " AND ".join(w)


def _signals_src(f: Filters, params: dict) -> str:
    params["sig_as_of"] = f.as_of or date.today()
    return "monitor_signals(:sig_as_of)"


async def rc_by_region(db: AsyncSession, level: str, parent: str | None, f: Filters) -> dict[str, dict]:
    params: dict[str, Any] = {}
    where = _rc_where(f, params, parent, level)
    key = _key(level)
    rows = (await db.execute(text(f"""
        SELECT {key} AS terc, count(*) n,
               count(*) FILTER (WHERE r.late IS NOT NULL) n_late_known, count(*) FILTER (WHERE r.late) n_late,
               avg(r.late::int) FILTER (WHERE r.late IS NOT NULL) late_share,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY r.delay_days) FILTER (WHERE r.late) median_delay,
               count(*) FILTER (WHERE r.paid_gross IS NOT NULL AND r.value_gross > 0) n_cost,
               count(*) FILTER (WHERE r.paid_gross > r.value_gross * 1.005) n_over,
               sum(r.paid_gross - r.value_gross) FILTER (WHERE r.paid_gross > r.value_gross * 1.005) overpaid,
               sum(r.value_gross) value_sum,
               count(*) FILTER (WHERE r.changes_count IS NOT NULL) n_chg_known, count(*) FILTER (WHERE r.changes_count > 0) n_chg,
               count(*) FILTER (WHERE r.properly_performed IS NOT NULL) n_imp_known,
               count(*) FILTER (WHERE r.properly_performed IS FALSE) n_imp
        FROM rc_contract r WHERE {where} AND {key} IS NOT NULL GROUP BY 1"""), params)).mappings().all()
    return {r["terc"]: dict(r) for r in rows}


async def rc_total(db: AsyncSession, parent: str | None, level: str, f: Filters) -> dict:
    params: dict[str, Any] = {}
    where = _rc_where(f, params, parent, level)
    r = (await db.execute(text(f"""SELECT count(*) n, count(*) FILTER (WHERE r.late IS NOT NULL) n_late_known,
                                   avg(r.late::int) FILTER (WHERE r.late IS NOT NULL) late_share
                                   FROM rc_contract r WHERE {where}"""), params)).mappings().one()
    return dict(r)


async def signals_by_region(db: AsyncSession, level: str, parent: str | None, f: Filters) -> dict[str, dict]:
    params: dict[str, Any] = {}
    src = _signals_src(f, params)
    where = _sig_where(f, params)
    key = _sig_key(level)
    if parent:
        where += f" AND {key} LIKE :sparent"
        params["sparent"] = parent + "%"
    rows = (await db.execute(text(f"""
        SELECT {key} AS terc, count(*) n, count(*) FILTER (WHERE s.lon IS NOT NULL) on_map,
               (array_agg(DISTINCT s.buyer_name))[1:3] AS buyers
        FROM {src} s WHERE {where} AND {key} IS NOT NULL GROUP BY 1"""), params)).mappings().all()
    return {r["terc"]: dict(r) for r in rows}


async def names(db: AsyncSession, level: str, parent: str | None) -> dict[str, str]:
    params: dict[str, Any] = {"level": level}
    w = "level = :level"
    if parent:
        w += " AND terc LIKE :p"
        params["p"] = parent + "%"
    rows = (await db.execute(text(f"SELECT terc, name FROM ref_geo_centroid WHERE {w} ORDER BY terc"), params)).all()
    return {r[0]: r[1] for r in rows}


def _pct(x: float | None) -> str:
    return f"{fmt_num(x, 1)}%" if x is not None else ""


def metric_num(metric: str, m: dict | None, sig: dict | None, terc: str, level: str) -> Num:
    ref = [q_ref(f"rc:core|{level}:{terc}", "ogłoszenia o wykonaniu umowy, BZP (umowy zakończone)")]
    m = m or {}
    if metric == "late":
        v = m.get("late_share")
        return num_calc(round(v * 100, 1) if v is not None else None, _pct(v * 100 if v is not None else None), "pct",
                        n=int(m.get("n_late_known") or 0), method=f"rc_share(late) by {level}", refs=ref)
    if metric == "delay":
        v = m.get("median_delay")
        return num_calc(round(v) if v is not None else None, f"{fmt_num(v)} dni" if v is not None else "", "days",
                        n=int(m.get("n_late") or 0), method="median(delay_days) where late", refs=ref)
    if metric == "over":
        n = int(m.get("n_cost") or 0)
        v = (m.get("n_over") or 0) / n * 100 if n else None
        return num_calc(round(v, 1) if v is not None else None, _pct(v), "pct", n=n,
                        method="rc_share(paid > value * 1.005)", refs=ref)
    if metric == "chg":
        n = int(m.get("n_chg_known") or 0)
        v = (m.get("n_chg") or 0) / n * 100 if n else None
        return num_calc(round(v, 1) if v is not None else None, _pct(v), "pct", n=n, method="rc_share(changes_count > 0)", refs=ref)
    if metric == "imp":
        n = int(m.get("n_imp_known") or 0)
        v = (m.get("n_imp") or 0) / n * 100 if n else None
        return num_calc(round(v, 1) if v is not None else None, _pct(v), "pct", n=n,
                        method="rc_share(properly_performed = false)", refs=ref)
    n = int((sig or {}).get("n") or 0)
    return num_calc(n, fmt_num(n), "count", n=n, method="count(monitor_signals) by region", min_n=0,
                    refs=[q_ref(f"signals:{level}:{terc}", "umowy po terminie bez ogłoszenia o wykonaniu (BZP)")])


def compact(m: dict | None, sig: dict | None) -> dict:
    m = m or {}
    def share(a, b):
        return round((m.get(a) or 0) / m[b] * 100, 1) if m.get(b) else None
    return {"n_completed": int(m.get("n") or 0),
            "late_pct": round(m["late_share"] * 100, 1) if m.get("late_share") is not None else None,
            "median_delay_days_late": round(m["median_delay"]) if m.get("median_delay") is not None else None,
            "overpaid_pln": str(round(Decimal(m["overpaid"]), 2)) if m.get("overpaid") is not None else None,
            "value_pln": str(round(Decimal(m["value_sum"]), 2)) if m.get("value_sum") is not None else None,
            "over_pct": share("n_over", "n_cost"), "changes_pct": share("n_chg", "n_chg_known"),
            "improper_pct": share("n_imp", "n_imp_known"), "signals": int((sig or {}).get("n") or 0)}


async def regions(db: AsyncSession, level: str, parent: str | None, mode: str, metric: str, f: Filters) -> dict:
    if mode == "open":
        metric = "sig"
    rc = await rc_by_region(db, level, parent, f)
    sig = await signals_by_region(db, level, parent, f)
    nm = await names(db, level, parent)
    out = []
    for terc in sorted(set(nm) | set(rc) | set(sig)):
        if parent and not terc.startswith(parent):
            continue
        out.append({"terc": terc, "name": nm.get(terc, terc),
                    "value": metric_num(metric, rc.get(terc), sig.get(terc), terc, level).model_dump(),
                    "metrics": compact(rc.get(terc), sig.get(terc))})
    vals = [r["value"]["value"] for r in out if r["value"]["value"] is not None]
    unit = METRICS[metric]["unit"]
    fmt = (lambda v: _pct(v)) if unit == "pct" else (lambda v: f"{fmt_num(v)} dni" if unit == "days" else fmt_num(v))
    tot = await rc_total(db, parent, level, f)
    n_sig = sum(int(s.get("n") or 0) for s in sig.values())
    if mode == "open":
        label = f"{fmt_num(n_sig)} umów po terminie bez ogłoszenia o wykonaniu"
        n_total = n_sig
    else:
        ls = tot.get("late_share")
        label = f"{fmt_num(tot['n'])} umów zakończonych, {fmt_num(ls * 100) if ls is not None else '?'}% po terminie"
        n_total = int(tot["n"])
    return {"level": level, "parent": parent, "mode": mode, "metric": {"key": metric, **METRICS[metric]},
            "sector": f.sector, "signals_available": f.sector == "wod-kan",
            "total": {"label": label, "n": n_total},
            "legend": {"min": {"value": min(vals), "display": fmt(min(vals))} if vals else None,
                       "max": {"value": max(vals), "display": fmt(max(vals))} if vals else None},
            "regions": out}


# ---- signals --------------------------------------------------------------------------------------------------------

SORTS = {"-days_overdue": "s.days_overdue DESC", "days_overdue": "s.days_overdue", "-value": "s.value_amount DESC NULLS LAST",
         "value": "s.value_amount NULLS LAST", "-signed_on": "s.signed_on DESC", "signed_on": "s.signed_on",
         "planned_end_on": "s.planned_end_on", "-n_change_notices": "s.n_change_notices DESC, s.days_overdue DESC"}


def signal_from_row(r: dict, as_of: date | None = None) -> Signal:
    days = r.get("days_overdue")
    refs = [Ref(kind="notice", id=r["bzp_number"] or r["ocid"], label="ogł. o wyniku", field_code="8.3",
                url=r.get("result_notice_url"))]
    method = f"{'as_of' if as_of else 'current_date'} - planned_end_on"
    dnum = num_calc(days, f"{fmt_num(days)} dni" if days is not None else "", "days", n=1, min_n=1, method=method, refs=refs) \
        if days is not None else num_source(None, "brak", "days", refs)
    return Signal(contract_id=r["contract_id"], ocid=r["ocid"], bzp_number=r.get("bzp_number"), lot_no=r.get("lot_no"),
                  n_parts=r.get("n_parts"), buyer_name=r.get("buyer_name"), title=r.get("title"),
                  value=Money(amount=r.get("value_amount"), currency=r.get("value_currency"), vat_basis=r.get("value_vat")),
                  signed_on=str(r["signed_on"]) if r.get("signed_on") else None,
                  planned_end_on=str(r["planned_end_on"]) if r.get("planned_end_on") else None,
                  days_overdue=dnum, n_change_notices=int(r.get("n_change_notices") or 0),
                  has_performance=bool(r.get("has_performance")), woj=r.get("woj"), pow=r.get("pow"), gmi=r.get("gmi"),
                  lon=r.get("lon"), lat=r.get("lat"), location_method=r.get("location_method"), watched=bool(r.get("watched")))


async def signals(db: AsyncSession, terc: str | None, level: str | None, f: Filters, limit: int, offset: int,
                  sort: str, geo: bool) -> dict:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    src = _signals_src(f, params)
    where = _sig_where(f, params)
    if terc:
        lvl = level or level_of(terc)
        where += f" AND {_sig_key(lvl)} LIKE :terc"
        params["terc"] = terc + "%"
    if geo:
        where += " AND s.lon IS NOT NULL"
    order = SORTS.get(sort, SORTS["-days_overdue"])
    total = (await db.execute(text(f"SELECT count(*) FROM {src} s WHERE {where}"), params)).scalar()
    rows = (await db.execute(text(f"SELECT s.* FROM {src} s WHERE {where} ORDER BY {order}, s.contract_id "
                                  "LIMIT :limit OFFSET :offset"), params)).mappings().all()
    return {"total": total, "limit": limit, "offset": offset, "items": [signal_from_row(dict(r), f.as_of) for r in rows]}


async def region(db: AsyncSession, terc: str, mode: str, metric: str, f: Filters) -> dict | None:
    level = level_of(terc)
    nm_all = await names(db, level, terc)
    if terc not in nm_all:
        return None
    crumbs = [{"terc": None, "name": "Polska"}]
    for lvl, ln in (("woj", 2), ("pow", 4), ("gmi", 7)):
        if len(terc) >= ln:
            nm = await names(db, lvl, terc[:ln])
            crumbs.append({"terc": terc[:ln], "name": nm.get(terc[:ln], terc[:ln])})
    rc = (await rc_by_region(db, level, terc, f)).get(terc)
    sig = (await signals_by_region(db, level, terc, f)).get(terc)
    m = rc or {}
    kpis = [{"key": "late_pct", "label": "PO TERMINIE", "value": metric_num("late", rc, sig, terc, level)},
            {"key": "median_delay", "label": "MEDIANA OPÓŹNIENIA", "value": metric_num("delay", rc, sig, terc, level)},
            {"key": "over_pct", "label": "PONAD WARTOŚĆ UMOWY", "value": metric_num("over", rc, sig, terc, level)},
            {"key": "changes_pct", "label": "UMOWY ZE ZMIANAMI", "value": metric_num("chg", rc, sig, terc, level)}]
    if m.get("overpaid") is not None:
        op = float(m["overpaid"])
        kpis.append({"key": "overpaid", "label": "WYPŁACONO PONAD UMOWY",
                     "value": num_calc(round(op, 2), f"{fmt_num(op / 1e6, 1)} mln zł", "pln", n=int(m.get("n_over") or 0),
                                       min_n=1, method="sum(paid - value) where paid > value * 1.005",
                                       refs=[q_ref(f"rc:core|{level}:{terc}", "ogłoszenia o wykonaniu umowy, BZP")])})
    kpis.append({"key": "signals", "label": "SYGNAŁY TERAZ", "attention": True, "value": metric_num("sig", rc, sig, terc, level)})
    for k in kpis:
        k["value"] = k["value"].model_dump() if hasattr(k["value"], "model_dump") else k["value"]
    children = []
    if level in CHILD:
        cl = CHILD[level]
        c_rc = await rc_by_region(db, cl, terc, f)
        c_sig = await signals_by_region(db, cl, terc, f)
        c_nm = await names(db, cl, terc)
        for ct in sorted(c_nm):
            children.append({"terc": ct, "name": c_nm[ct], "signals": int((c_sig.get(ct) or {}).get("n") or 0),
                             "buyers": list((c_sig.get(ct) or {}).get("buyers") or []),
                             "value": metric_num("sig" if mode == "open" else metric, c_rc.get(ct), c_sig.get(ct), ct, cl).model_dump(),
                             "metrics": compact(c_rc.get(ct), c_sig.get(ct))})
    page = await signals(db, terc, level, f, 20, 0, "-days_overdue", False)
    on_map = int((sig or {}).get("on_map") or 0)
    total = int((sig or {}).get("n") or 0)
    lvl_q = f"terc={terc}&level={level}"
    return {"terc": terc, "name": nm_all[terc], "level": level, "sector": f.sector, "signals_available": f.sector == "wod-kan",
            "breadcrumb": crumbs, "kpis": kpis, "children": children,
            "signals": {"total": total, "on_map": on_map, "items": [s.model_dump() for s in page["items"]],
                        "csv_href": f"/api/export/signals.csv?{lvl_q}",
                        "note": (f"Na mapie {fmt_num(on_map)} z {fmt_num(total)} sygnałów: te, które da się przypisać do gminy "
                                 "po nazwie lub siedzibie zamawiającego. Plik CSV ma wszystkie.")},
            "list_href": f"/projekty?province={terc[:2]}"}


async def contract_detail(db: AsyncSession, contract_id: int, can_write: bool) -> dict | None:
    r = (await db.execute(text("""
        SELECT c.id contract_id, p.id procedure_id, p.ocid, c.result_notice_no bzp_number, rn.url result_notice_url,
               coalesce(c.lot_no, 0) lot_no, coalesce(p.n_lots, 1) n_parts, coalesce(o.name, p.buyer_name) buyer_name,
               p.title, p.subsector_main, c.value_amount, c.value_currency, c.value_vat, c.contractor_name, c.signed_on,
               c.planned_end_on, c.planned_duration_days, c.duration_raw, c.planned_end_computed,
               coalesce(left(o.teryt, 2), substr(p.province, 3, 2)) woj,
               CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END pow, CASE WHEN length(o.teryt) = 7 THEN o.teryt END gmi,
               coalesce(gc.lon, pc.lon) lon, coalesce(gc.lat, pc.lat) lat,
               CASE WHEN gc.lon IS NOT NULL THEN coalesce(o.data->>'teryt_method', 'teryt') || '|gmina'
                    WHEN pc.lon IS NOT NULL THEN coalesce(o.data->>'teryt_method', 'teryt') || '|powiat' END location_method,
               EXISTS (SELECT 1 FROM monitor_watch w WHERE w.contract_id = c.id AND w.active) watched,
               (SELECT pf.id FROM contract_performance pf WHERE pf.contract_id = c.id AND NOT pf.is_duplicate LIMIT 1) perf_id,
               (SELECT n.notice_number FROM contract_performance pf JOIN notice n ON n.id = pf.notice_id
                 WHERE pf.contract_id = c.id AND NOT pf.is_duplicate LIMIT 1) perf_no,
               (SELECT n.url FROM contract_performance pf JOIN notice n ON n.id = pf.notice_id
                 WHERE pf.contract_id = c.id AND NOT pf.is_duplicate LIMIT 1) perf_url
        FROM contract c JOIN procedure p ON p.id = c.procedure_id
        LEFT JOIN notice rn ON rn.id = c.result_notice_id
        LEFT JOIN organization o ON o.id = p.buyer_org_id
        LEFT JOIN ref_geo_centroid gc ON gc.terc = CASE WHEN length(o.teryt) = 7 THEN o.teryt END
        LEFT JOIN ref_geo_centroid pc ON pc.terc = CASE WHEN length(o.teryt) >= 4 THEN left(o.teryt, 4) END
        WHERE c.id = :id"""), {"id": contract_id})).mappings().first()
    if not r:
        return None
    r = dict(r)
    chg = (await db.execute(text("""SELECT n.notice_number, n.url, ch.changed_on FROM contract_change ch
                                    JOIN notice n ON n.id = ch.notice_id WHERE ch.contract_id = :id AND ch.kind = 'change_notice'
                                    ORDER BY ch.changed_on NULLS LAST"""), {"id": contract_id})).mappings().all()
    today = date.today()
    has_perf = r["perf_id"] is not None
    r["has_performance"] = has_perf
    r["n_change_notices"] = len(chg)
    r["days_overdue"] = (today - r["planned_end_on"]).days if (r["planned_end_on"] and not has_perf
                                                                 and r["planned_end_on"] < today) else None
    sig = signal_from_row(r)
    ref = Ref(kind="notice", id=r["bzp_number"] or r["ocid"], label="ogł. o wyniku", field_code="8.3", url=r["result_notice_url"])
    pdays = r["planned_duration_days"]
    plan = {"planned_days": num_source(round(pdays) if pdays is not None else None,
                                       f"{fmt_num(pdays)} dni" if pdays is not None else "brak", "days", [ref]),
            "overdue_days": sig.days_overdue.model_dump()}
    plan["planned_days"] = plan["planned_days"].model_dump()
    woj = r["woj"]
    f = Filters()
    rc = (await rc_by_region(db, "woj", woj, f)).get(woj) if woj else None
    woj_name = (await names(db, "woj", woj)).get(woj, woj) if woj else None
    late = metric_num("late", rc, None, woj or "", "woj")
    med = metric_num("delay", rc, None, woj or "", "woj")
    if r["days_overdue"] is not None and med.value is not None:
        loc = re.sub(r"kie$", "kim", woj_name or "")          # 'śląskie' -> 'w śląskim' (all 16 names end in -kie)
        sentence = (f"Ta umowa jest już {fmt_num(r['days_overdue'])} dni po terminie; połowa spóźnionych umów w "
                    f"{loc} kończyła się do {med.display} po terminie.")
    elif has_perf:
        sentence = "Dla tej umowy opublikowano ogłoszenie o wykonaniu."
    else:
        sentence = "Termin tej umowy jeszcze nie minął." if r["planned_end_on"] and r["planned_end_on"] >= today \
            else "Brak danych o terminie umowy."
    sources = [{"k": "ogłoszenie o wyniku", "v": r["bzp_number"] or "brak", "url": r["result_notice_url"],
                "missing": r["bzp_number"] is None},
               {"k": "ogłoszenia o zmianie", "v": str(len(chg)), "items": [{"v": c["notice_number"], "url": c["url"]} for c in chg]},
               {"k": "ogłoszenie o wykonaniu", "v": r["perf_no"] or "brak", "url": r["perf_url"], "missing": not has_perf}]
    return {"signal": sig.model_dump(), "plan": plan,
            "compare": {"region_late_pct": late.model_dump(), "region_median_delay": med.model_dump(), "sentence": sentence},
            "sources": sources,
            "actions": {"card_href": f"/projekty/{r['ocid']}", "can_watch": can_write, "can_report": can_write}}


async def warm(db: AsyncSession, *, step_months: int = 3, start: date = date(2021, 1, 1)) -> dict:
    """Pull the pages monitor_signals(as_of) reads (notice, procedure, lot, contract, performance) into the cache, so the
    first time-slider step is as fast as the next ones (~4 s cold vs ~0.1 s warm). Read-only; run at API startup."""
    import time
    t0, n, d = time.time(), 0, start
    today = date.today()
    while d <= today:
        await db.execute(text("SELECT count(*) FROM monitor_signals(:d)"), {"d": d})
        n += 1
        m = d.month - 1 + step_months
        d = date(d.year + m // 12, m % 12 + 1, 1)
    await db.execute(text("SELECT count(*) FROM monitor_signals(current_date)"))
    await db.execute(text("SELECT count(*) FROM rc_contract WHERE dq_ok"))
    return {"dates": n + 1, "seconds": round(time.time() - t0, 2)}
