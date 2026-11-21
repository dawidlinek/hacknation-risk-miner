"""Sector lessons digest (W17): top risk categories by frequency and impact, with recurring causes and mitigations.

Only publishable rows are aggregated: risk events that are approved or edited by an expert, or deterministic CALC rows
(review_status auto, origin not AI). AI proposals and rejected rows never enter the digest (invariant 2). Every figure is a
calc Num with n and method (api/prov.py); below `MIN_N` events the figure is "za mało danych".
Mitigations: measured ones come from events that record a mitigation; the catalogue proposals are shown separately and
labelled as expert assumptions (not measured effectiveness).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analytics import catalogue as CAT
from riskminer.api.prov import fmt_num, num_calc, q_ref

MIN_N = 5
PUBLISHABLE = ("(e.review_status IN ('approved', 'edited') OR (e.review_status = 'auto' AND e.origin <> 'AI'))")
CASE_KEY = "coalesce(e.project_id::text, 'p' || e.procedure_id::text)"
NORM = "lower(regexp_replace(btrim(%s), '[.;,\\s]+$', ''))"


def _n(value, display, unit, n, method, ref_id, label) -> dict:
    return num_calc(value, display, unit, n=n, method=method, refs=[q_ref(ref_id, label)], min_n=MIN_N).model_dump(mode="json")


async def _all(db: AsyncSession, sql: str, **p) -> list[dict[str, Any]]:
    return [dict(r) for r in (await db.execute(text(sql), p)).mappings().all()]


def _source(r: dict) -> dict:
    case = r.get("rm_id") or r.get("ocid")
    return {"case_id": case, "title": r.get("case_title"), "href": f"/projekty/{case}" if case else None,
            "event_id": r["id"], "text": r.get("text"), "quote": r.get("quote") or r.get("text"), "url": r.get("url"),
            "field_code": r.get("field_code"), "review_status": r["review_status"], "origin": r["origin"]}


async def sector_lessons(db: AsyncSession, sector: str = "wod-kan", limit: int = 8, per: int = 3) -> dict:
    base = f"""
        FROM risk_event e
        LEFT JOIN procedure pr ON pr.id = e.procedure_id
        LEFT JOIN project pj ON pj.id = e.project_id
        WHERE e.catalogue_code ~ '^R[0-9]' AND {PUBLISHABLE} AND coalesce(pj.sector, pr.sector) = :sector"""
    tot = (await _all(db, f"SELECT count(*) AS n, count(*) FILTER (WHERE e.review_status IN ('approved','edited')) AS approved, "
                          f"count(DISTINCT {CASE_KEY}) AS cases {base}", sector=sector))[0]
    excluded = (await _all(db, "SELECT count(*) AS n FROM risk_event e LEFT JOIN procedure pr ON pr.id = e.procedure_id "
                               "LEFT JOIN project pj ON pj.id = e.project_id WHERE e.catalogue_code ~ '^R[0-9]' "
                               f"AND NOT {PUBLISHABLE} AND coalesce(pj.sector, pr.sector) = :sector", sector=sector))[0]["n"]
    cats = await _all(db, f"""
        SELECT split_part(e.catalogue_code, '.', 1) AS code, count(*) AS n, count(DISTINCT {CASE_KEY}) AS cases,
               count(*) FILTER (WHERE e.review_status IN ('approved','edited')) AS approved,
               count(*) FILTER (WHERE e.impact_days > 0) AS d_n,
               coalesce(sum(e.impact_days) FILTER (WHERE e.impact_days > 0), 0) AS d_sum,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY e.impact_days) FILTER (WHERE e.impact_days > 0) AS d_med,
               count(*) FILTER (WHERE e.impact_value_amount > 0 AND e.impact_value_vat = 'gross') AS v_n,
               coalesce(sum(e.impact_value_amount) FILTER (WHERE e.impact_value_amount > 0 AND e.impact_value_vat = 'gross'), 0) AS v_sum,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY e.impact_value_amount)
                   FILTER (WHERE e.impact_value_amount > 0 AND e.impact_value_vat = 'gross') AS v_med
        {base} GROUP BY 1 ORDER BY n DESC, code LIMIT :lim""", sector=sector, lim=limit)
    codes = [c["code"] for c in cats]
    cat = await CAT.load(db)
    names = cat.get("risk_names") or {}

    exj = """
        LEFT JOIN LATERAL (SELECT quote, url, field_code, notice_id FROM evidence x WHERE x.claim_table = 'risk_event'
                           AND x.claim_id = e.id ORDER BY x.id LIMIT 1) ev ON true
        LEFT JOIN notice nt ON nt.id = ev.notice_id"""
    causes = await _all(db, f"""
        WITH g AS (
          SELECT split_part(e.catalogue_code, '.', 1) AS code, {NORM % 'e.cause'} AS norm, count(*) AS n,
                 count(DISTINCT {CASE_KEY}) AS cases,
                 (array_agg(e.id ORDER BY (e.review_status IN ('approved','edited')) DESC, e.id))[1] AS ex_id
          {base} AND e.cause IS NOT NULL AND btrim(e.cause) <> '' AND split_part(e.catalogue_code, '.', 1) = ANY(:codes)
          GROUP BY 1, 2),
        r AS (SELECT *, row_number() OVER (PARTITION BY code ORDER BY n DESC, norm) AS rk FROM g)
        SELECT r.code, r.n, r.cases, r.rk, e.id, e.review_status, e.origin, e.cause AS text, pj.rm_id, pr.ocid,
               coalesce(pj.title, pr.title) AS case_title, ev.quote, coalesce(ev.url, nt.url) AS url, ev.field_code
        FROM r JOIN risk_event e ON e.id = r.ex_id LEFT JOIN procedure pr ON pr.id = e.procedure_id
        LEFT JOIN project pj ON pj.id = e.project_id {exj}
        WHERE r.rk <= :per ORDER BY r.code, r.rk""", sector=sector, codes=codes, per=per)
    measured = await _all(db, f"""
        WITH g AS (
          SELECT split_part(e.catalogue_code, '.', 1) AS code, {NORM % 'e.mitigation'} AS norm, count(*) AS n,
                 count(DISTINCT {CASE_KEY}) AS cases,
                 (array_agg(e.id ORDER BY (e.review_status IN ('approved','edited')) DESC, e.id))[1] AS ex_id
          {base} AND e.mitigation IS NOT NULL AND btrim(e.mitigation) <> '' AND split_part(e.catalogue_code, '.', 1) = ANY(:codes)
          GROUP BY 1, 2),
        r AS (SELECT *, row_number() OVER (PARTITION BY code ORDER BY n DESC, norm) AS rk FROM g)
        SELECT r.code, r.n, r.cases, e.id, e.review_status, e.origin, e.mitigation AS text, e.mitigation_effectiveness AS effect,
               pj.rm_id, pr.ocid, coalesce(pj.title, pr.title) AS case_title, ev.quote, coalesce(ev.url, nt.url) AS url, ev.field_code
        FROM r JOIN risk_event e ON e.id = r.ex_id LEFT JOIN procedure pr ON pr.id = e.procedure_id
        LEFT JOIN project pj ON pj.id = e.project_id {exj}
        WHERE r.rk <= :per ORDER BY r.code, r.rk""", sector=sector, codes=codes, per=per)

    proposals: dict[str, list[dict]] = {}
    for m in (cat.get("mitigations") or {}).get("items", []):
        for eff in m.get("effects") or []:
            proposals.setdefault(str(eff.get("risk")), []).append(
                {"code": m.get("code"), "label": m.get("label") or m.get("short"), "rationale": m.get("rationale"),
                 "status": m.get("status") or "proposed", "assumption": True})

    out_cats = []
    for c in cats:
        code, n = c["code"], int(c["n"])
        ref = f"lessons:{sector}:{code}"
        lab = f"zdarzenia ryzyka {code} z wniosków i ogłoszeń ({sector})"
        out_cats.append({
            "code": code, "name": names.get(code) or code,
            "events": _n(n, fmt_num(n), "count", n, "count(zdarzenia ryzyka, zatwierdzone lub obliczone)", ref, lab),
            "cases": _n(int(c["cases"]), fmt_num(int(c["cases"])), "count", int(c["cases"]), "count(distinct przypadki)", ref, lab),
            "approved_events": int(c["approved"]),
            "delay_median_days": _n(c["d_med"], f"{fmt_num(c['d_med'])} dni" if c["d_med"] is not None else "", "days",
                                    int(c["d_n"]), "median(impact_days | zdarzenia z opóźnieniem)", ref, lab),
            "delay_total_days": _n(c["d_sum"], f"{fmt_num(c['d_sum'])} dni", "days", int(c["d_n"]),
                                   "sum(impact_days | zdarzenia z opóźnieniem)", ref, lab),
            "cost_median": _n(float(c["v_med"]) if c["v_med"] is not None else None,
                              f"{fmt_num(float(c['v_med']))} zł brutto" if c["v_med"] is not None else "", "pln", int(c["v_n"]),
                              "median(impact_value | zdarzenia z kosztem, brutto)", ref, lab),
            "cost_total": _n(float(c["v_sum"]), f"{fmt_num(float(c['v_sum']) / 1e6, 1)} mln zł brutto", "pln", int(c["v_n"]),
                             "sum(impact_value | zdarzenia z kosztem, brutto)", ref, lab),
            "causes": [{"count": int(r["n"]), "cases": int(r["cases"]), **_source(r)} for r in causes if r["code"] == code],
            "mitigations_measured": [{"count": int(r["n"]), "cases": int(r["cases"]), "effect": r["effect"], **_source(r)}
                                     for r in measured if r["code"] == code],
            "mitigations_proposed": proposals.get(code, []),
        })
    return {
        "sector": sector,
        "scope": "Zatwierdzone lub edytowane przez eksperta zdarzenia oraz zdarzenia obliczone z ogłoszeń; bez propozycji AI i odrzuconych.",
        "totals": {"events": _n(int(tot["n"]), fmt_num(int(tot["n"])), "count", int(tot["n"]), "count(opublikowane zdarzenia ryzyka)",
                                f"lessons:{sector}", "zdarzenia ryzyka"),
                   "cases": _n(int(tot["cases"]), fmt_num(int(tot["cases"])), "count", int(tot["cases"]), "count(distinct przypadki)",
                               f"lessons:{sector}", "zdarzenia ryzyka"),
                   "approved_events": int(tot["approved"]), "excluded_events": int(excluded)},
        "min_n": MIN_N, "categories": out_cats,
    }
