"""Projects list metrics, stats and project card building blocks (api_contract §2.4). Reads only (session B).

Per project the metrics come from the project's linked contract_performance notices (one row per contract, newest notice):
delay = max delay, cost deviation = paid / contract value - 1 over the contracts, changes = sum of changes_count.
Single-project metrics are calculations over the project's own facts (n = number of contracts, refs to the notices)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api.prov import Num, Prov, Ref, fmt_num, num_calc, q_ref
from riskminer.api.schemas import Money

PERF_ONLY = """perf AS (
  SELECT DISTINCT ON (pp.project_id, pf.contract_id) pp.project_id, pf.*
  FROM project_procedure pp JOIN contract_performance pf ON pf.procedure_id = pp.procedure_id AND NOT pf.is_duplicate
  WHERE pp.review_status <> 'rejected'
  ORDER BY pp.project_id, pf.contract_id, pf.id DESC
)"""
PERF_CTE = PERF_ONLY + """,
pm AS (
  SELECT project_id, count(*) AS n_contracts, sum(contract_value_amount) AS value, sum(total_paid_amount) AS paid,
         max(delay_days) AS delay_days, sum(changes_count) AS changes, bool_and(properly_performed) AS proper,
         (sum(total_paid_amount) / NULLIF(sum(contract_value_amount), 0) - 1) * 100 AS cost_dev_pct,
         bool_or(properly_performed IS FALSE) AS improper_any
  FROM perf GROUP BY project_id
),
oi AS (
  SELECT project_id, count(*) AS open_n, count(*) FILTER (WHERE kind = 'discrepancy') AS disc_n,
         (array_agg(code ORDER BY id) FILTER (WHERE kind = 'discrepancy'))[1] AS disc_code
  FROM review_item WHERE status = 'open' GROUP BY project_id
)
"""

DISC_LABEL = {"value_deviation": "rozbieżność wartości", "part_mismatch": "rozbieżność części", "part_scope_wider": "rozbieżność zakresu",
              "contract_notice_missing": "brak ogłoszenia w BZP"}
# "-x" = descending, "x" = ascending
SORTS = {"delay_days": "pm.delay_days ASC NULLS LAST", "-delay_days": "pm.delay_days DESC NULLS LAST",
         "cost_dev_pct": "pm.cost_dev_pct ASC NULLS LAST", "-cost_dev_pct": "pm.cost_dev_pct DESC NULLS LAST",
         "value": "pm.value ASC NULLS LAST", "-value": "pm.value DESC NULLS LAST", "rm_id": "p.rm_id", "-rm_id": "p.rm_id DESC"}


def _pl_int(n: Any) -> str:
    return fmt_num(n)


def _signed(x: float, unit: str) -> str:
    return f"{'+' if x > 0 else ''}{fmt_num(x, 0 if unit == 'dni' else 1)}{' dni' if unit == 'dni' else '%'}"


def state_of(r: dict, user: A.User | None) -> dict:
    open_n, disc_n = r.get("open_n") or 0, r.get("disc_n") or 0
    if disc_n:
        return {"code": "discrepancy", "label": DISC_LABEL.get(r.get("disc_code"), "rozbieżność w danych")}
    if open_n:
        return {"code": "to_review", "label": f"{open_n} do przeglądu" if user else "niezweryfikowane"}
    if (r.get("paid") is not None and r.get("pm_value") is not None and float(r["paid"]) < float(r["pm_value"]) * 0.99):
        return {"code": "partial_payment", "label": "wypłacono mniej niż w umowie"}
    return {"code": "auto", "label": "z ogłoszeń BZP"}


def metrics_for(r: dict, user: A.User | None, notice_refs: list[Ref] | None = None) -> dict:
    refs = notice_refs or []
    n = r.get("n_contracts") or 0
    own = Prov(role="calc", review_status="auto", n=n, method="project_contracts", refs=refs or [q_ref(f"project:{r['rm_id']}", "ogłoszenia o wykonaniu umowy")])
    delay = r.get("delay_days")
    cost = r.get("cost_dev_pct")
    return {
        "contract_value": Money(amount=r.get("pm_value"), currency="PLN" if r.get("pm_value") is not None else None,
                                vat_basis="gross" if r.get("pm_value") is not None else None).model_dump(mode="json"),
        "delay_days": Num(value=delay, display=_signed(delay, "dni") if delay is not None else "brak danych", unit="days", prov=own).model_dump(mode="json"),
        "cost_dev_pct": Num(value=round(cost, 1) if cost is not None else None, display=_signed(cost, "pct") if cost is not None else "brak danych",
                            unit="pct", prov=own).model_dump(mode="json"),
        "changes": Num(value=r.get("changes"), display=_pl_int(r.get("changes")) if r.get("changes") is not None else "brak danych",
                       unit="count", prov=own).model_dump(mode="json"),
        "properly_performed": r.get("proper"),
        "state": state_of(r, user),
    }


def _filters(user, q, province, subsector, pilot, late, has_discrepancy, to_review, contractor_nip, rm_ids):
    where, params = ["true"], {}
    if q:
        where.append("(p.title ILIKE :q OR p.beneficiary_name ILIKE :q OR p.rm_id ILIKE :q OR p.public_id ILIKE :q OR p.beneficiary_nip = :qraw "
                     "OR EXISTS (SELECT 1 FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id WHERE pp.project_id=p.id "
                     "AND (pr.contract_notice_no ILIKE :q OR pr.ocid ILIKE :q)))")
        params["q"], params["qraw"] = f"%{q}%", q.replace(" ", "").replace("-", "")
    if province:
        where.append("p.province = :province")
        params["province"] = province
    if subsector:
        where.append("(p.subsector_main = :sub OR :sub = ANY(p.subsectors_extra))")
        params["sub"] = subsector
    if pilot is not None:
        where.append("p.is_pilot = :pilot")
        params["pilot"] = pilot
    if late is True:
        where.append("pm.delay_days > 0")
    if has_discrepancy is True:
        where.append("coalesce(oi.disc_n, 0) > 0")
    if to_review is True:
        if user is None:
            where.append("false")
        else:
            where.append("coalesce(oi.open_n, 0) > 0")
    if contractor_nip:
        where.append("EXISTS (SELECT 1 FROM perf f JOIN contract c ON c.id = f.contract_id WHERE f.project_id = p.id AND c.contractor_nip = :cnip)")
        params["cnip"] = contractor_nip.replace("-", "").replace(" ", "")
    if rm_ids:
        where.append("p.rm_id = ANY(:rm_ids)")
        params["rm_ids"] = [x.strip() for x in rm_ids.split(",") if x.strip()]
    return " AND ".join(where), params


async def notice_refs(db: AsyncSession, project_ids: list[int]) -> dict[int, list[Ref]]:
    if not project_ids:
        return {}
    rs = (await db.execute(text(f"""WITH {PERF_ONLY}
        SELECT perf.project_id, n.notice_number, n.url FROM perf JOIN notice n ON n.id = perf.notice_id
        WHERE perf.project_id = ANY(:ids) ORDER BY perf.project_id, n.notice_number"""), {"ids": project_ids})).mappings().all()
    out: dict[int, list[Ref]] = {}
    for r in rs:
        out.setdefault(r["project_id"], []).append(Ref(kind="notice", id=r["notice_number"], label="ogł. o wykonaniu", url=r["url"], field_code="5.2"))
    return out


def _with_metrics(base_sql: str) -> str:
    cols = "pm.n_contracts, pm.value AS pm_value, pm.paid, pm.delay_days, pm.changes, pm.proper, pm.cost_dev_pct, oi.open_n, oi.disc_n, oi.disc_code,"
    sql = base_sql.replace("SELECT p.*,", f"SELECT p.*, {cols}", 1)
    return sql.replace("FROM project p", "FROM project p LEFT JOIN pm ON pm.project_id = p.id LEFT JOIN oi ON oi.project_id = p.id", 1)


async def list_page(db: AsyncSession, user: A.User | None, *, base_sql: str, q=None, province=None, subsector=None, pilot=None, late=None,
                    has_discrepancy=None, to_review=None, contractor_nip=None, sort=None, rm_ids=None, limit=100, offset=0) -> dict:
    w, params = _filters(user, q, province, subsector, pilot, late, has_discrepancy, to_review, contractor_nip, rm_ids)
    order = SORTS.get(sort or "rm_id", "p.rm_id") + ", p.rm_id"
    join = "LEFT JOIN pm ON pm.project_id = p.id LEFT JOIN oi ON oi.project_id = p.id"
    total = (await db.execute(text(f"WITH {PERF_CTE} SELECT count(*) FROM project p {join} WHERE {w}"), params)).scalar() or 0
    ids = (await db.execute(text(f"WITH {PERF_CTE} SELECT p.id FROM project p {join} WHERE {w} ORDER BY {order} LIMIT :limit OFFSET :offset"),
                            {**params, "limit": limit, "offset": offset})).scalars().all()
    if not ids:
        return {"total": total, "limit": limit, "offset": offset, "items": [], "facets": await facets(db, user)}
    rs = (await db.execute(text(f"""WITH {PERF_CTE} {_with_metrics(base_sql)}
        WHERE p.id = ANY(:ids)"""), {"ids": list(ids)})).mappings().all()
    return {"rows": {r["id"]: dict(r) for r in rs}, "ids": list(ids), "total": total, "limit": limit, "offset": offset,
            "refs": await notice_refs(db, list(ids)), "facets": await facets(db, user)}


async def facets(db: AsyncSession, user: A.User | None) -> dict:
    r = (await db.execute(text(f"""WITH {PERF_CTE} SELECT count(*) AS n_all, count(*) FILTER (WHERE pm.delay_days > 0) AS n_late,
        count(*) FILTER (WHERE coalesce(oi.disc_n,0) > 0) AS n_disc, count(*) FILTER (WHERE coalesce(oi.open_n,0) > 0) AS n_review
        FROM project p LEFT JOIN pm ON pm.project_id = p.id LEFT JOIN oi ON oi.project_id = p.id WHERE p.is_pilot"""))).mappings().one()
    subs = (await db.execute(text("""SELECT coalesce(s.code, p.subsector_main) AS key, coalesce(s.name, p.subsector_main) AS label, count(*) AS n
        FROM project p LEFT JOIN catalogue_subsector s ON s.code = p.subsector_main AND s.status='approved' AND s.sector='wod-kan'
        WHERE p.is_pilot AND p.subsector_main IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC"""))).mappings().all()
    return {"all": r["n_all"], "late": r["n_late"], "discrepancy": r["n_disc"], "review": r["n_review"] if user else None,
            "subsectors": [dict(s) for s in subs]}


async def stats(db: AsyncSession, user: A.User | None, **filters) -> dict:
    w, params = _filters(user, filters.get("q"), filters.get("province"), filters.get("subsector"), None, filters.get("late"),
                         filters.get("has_discrepancy"), filters.get("to_review"), filters.get("contractor_nip"), filters.get("rm_ids"))
    r = (await db.execute(text(f"""WITH {PERF_CTE}
        SELECT count(*) AS n, count(*) FILTER (WHERE f.delay_days > 0) AS late, count(*) FILTER (WHERE f.cost_dev_pct > 0.5) AS over,
               count(*) FILTER (WHERE f.properly_performed IS FALSE) AS improper, coalesce(sum(f.changes_count), 0) AS changes,
               count(*) FILTER (WHERE f.changes_count > 0) AS with_changes,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY f.cost_dev_pct) FILTER (WHERE f.cost_dev_pct > 0.5) AS median_over,
               max(f.cost_dev_pct) AS max_over, count(DISTINCT f.project_id) AS n_projects
        FROM perf f JOIN project p ON p.id = f.project_id LEFT JOIN pm ON pm.project_id = p.id LEFT JOIN oi ON oi.project_id = p.id
        WHERE {w}"""), params)).mappings().one()
    n = r["n"] or 0
    refs = [q_ref("projects:filtered", "umowy z projektów po filtrach")]

    def count(label_key: str, k: int, method: str, extra: str = "") -> dict:
        num = num_calc(k, f"{k} z {n}", "count", n=n, method=method, refs=refs)
        return {"label": label_key, "value": num.model_dump(mode="json"), "note": extra or None}

    med = f"mediana +{fmt_num(r['median_over'], 1)}%, najwięcej +{fmt_num(r['max_over'], 1)}%" if r["median_over"] is not None else None
    return {"late": count("Umowy po terminie", r["late"], "count(delay_days > 0)"),
            "overpaid": count("Zapłacono ponad umowę", r["over"], "count(cost_dev_pct > 0,5)", med or ""),
            "improper": count("Wykonane nienależycie", r["improper"], "count(properly_performed = false)"),
            "changes": count("Zmiany umów", r["with_changes"], "count(changes_count > 0)", f"{r['changes']} zmian w sumie"),
            "n_contracts": n, "n_projects": r["n_projects"]}
