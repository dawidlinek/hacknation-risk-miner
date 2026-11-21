"""National list for Projekty: every wod-kan procedure (relevance core, optionally component) from the `procedure_national`
materialized view (migration 0016). Status, planned and actual end, delay, value and changes are the same facts the automatic
card shows (contract + contract_performance). Reads only. Delay: for completed procedures the performance-notice delay (CALC
over the notice fields), for ongoing ones days past the contract end as of today (CALC, no performance notice yet)."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.prov import Num, Ref, fmt_num, num_calc, num_source, q_ref
from riskminer.api.schemas import Money

DELAY = ("CASE WHEN n.status = 'completed' THEN n.delay_days "
         "WHEN n.status = 'ongoing' AND n.planned_end_on < current_date THEN (current_date - n.planned_end_on) END")
SORTS = {"delay": f"{DELAY} DESC NULLS LAST", "-delay": f"{DELAY} DESC NULLS LAST", "delay_asc": f"{DELAY} ASC NULLS LAST",
         "value": "n.value_amount DESC NULLS LAST", "-value": "n.value_amount DESC NULLS LAST",
         "value_asc": "n.value_amount ASC NULLS LAST",
         "signed": "n.signed_on DESC NULLS LAST", "-signed": "n.signed_on DESC NULLS LAST", "signed_asc": "n.signed_on ASC NULLS LAST"}
STATUS = {"completed": "completed", "zakonczone": "completed", "ongoing": "ongoing", "w_toku": "ongoing", "none": "none"}


def _where(q, woj, status, year_from, year_to, relevance, params) -> str:
    w = ["n.relevance = ANY(:rel)"]
    params["rel"] = ["core", "component"] if relevance == "all" else [relevance]
    if q:
        for i, tok in enumerate(q.lower().split()[:6]):
            w.append(f"n.search_text LIKE :q{i}")
            params[f"q{i}"] = f"%{tok}%"
    if woj:
        w.append("n.woj = :woj")
        params["woj"] = woj
    if status and status != "all":
        w.append("n.status = :status")
        params["status"] = STATUS.get(status, status)
    if year_from:
        w.append("n.year >= :yfrom")
        params["yfrom"] = year_from
    if year_to:
        w.append("n.year <= :yto")
        params["yto"] = year_to
    return " AND ".join(w)


def _row(r: dict) -> dict:
    refs: list[Ref] = []
    if r["result_notice_no"]:
        refs.append(Ref(kind="notice", id=r["result_notice_no"], label="ogł. o wyniku", field_code="8.3"))
    perf_refs = [Ref(kind="notice", id=r["perf_notice_no"], label="ogł. o wykonaniu", url=r["perf_notice_url"], field_code="5.2")] \
        if r["perf_notice_no"] else []
    qref = [q_ref(f"procedure:{r['ocid']}", "umowy i ogłoszenia procedury")]
    completed, ongoing = r["status"] == "completed", r["status"] == "ongoing"
    days = r["delay_days"] if completed else (r["overdue_days"] if ongoing and r["overdue_days"] and r["overdue_days"] > 0 else None)
    if days is not None:
        sign = "+" if days > 0 else ""
        delay = num_calc(days, f"{sign}{fmt_num(days)} dni", "days", n=1, min_n=1, refs=perf_refs or refs or qref,
                         method="performance_notice.delay_days" if completed else "current_date - planned_end_on")
    else:
        delay = num_calc(None, "brak danych" if completed else "-", "days", n=1, min_n=1, refs=qref, method="no delay data")
    changes = num_calc(r["changes"], fmt_num(r["changes"]), "count", n=1, min_n=1, refs=perf_refs or refs or qref,
                       method="sum(changes_count) or change notices")
    value = Money(amount=r["value_amount"], currency=r["value_currency"] if r["value_amount"] is not None else None,
                  vat_basis=(r["value_vat"] if r["value_vat"] in ("net", "gross") else "unknown") if r["value_amount"] is not None else None)
    value_prov = num_source(float(r["value_amount"]), fmt_num(r["value_amount"]) + " zł", "pln", refs or qref) \
        if r["value_amount"] is not None else None
    return {
        "id": r["ocid"], "ocid": r["ocid"], "href": f"/projekty/{r['ocid']}", "title": r["title"], "buyer": r["buyer_name"],
        "gmina": r["gmina"], "powiat": r["powiat"], "woj": r["woj"], "terc": r["gmi"] or r["pow"] or r["woj"],
        "relevance": r["relevance"], "status": r["status"],
        "status_label": {"completed": "zakończone", "ongoing": "w toku", "none": "bez umowy"}[r["status"]],
        "value": value.model_dump(mode="json"), "value_num": value_prov.model_dump(mode="json") if value_prov else None,
        "signed_on": str(r["signed_on"]) if r["signed_on"] else None,
        "planned_end_on": str(r["planned_end_on"]) if r["planned_end_on"] else None,
        "actual_end_on": str(r["completed_on"]) if completed and r["completed_on"] else None,
        "actual_end_label": str(r["completed_on"]) if completed and r["completed_on"] else ("w toku" if ongoing else None),
        "delay_days": delay.model_dump(mode="json"), "changes": changes.model_dump(mode="json"),
        "n_contracts": r["n_contracts"] or 0,
    }


async def list_national(db: AsyncSession, *, q: str | None, woj: str | None, status: str | None, year_from: int | None,
                        year_to: int | None, relevance: str, sort: str, page: int, page_size: int) -> dict:
    params: dict[str, Any] = {}
    where = _where(q, woj, status, year_from, year_to, relevance, params)
    order = SORTS[sort]
    total = (await db.execute(text(f"SELECT count(*) FROM procedure_national n WHERE {where}"), params)).scalar() or 0
    rs = (await db.execute(text(f"""SELECT n.*, (current_date - n.planned_end_on) AS overdue_days FROM procedure_national n
        WHERE {where} ORDER BY {order}, n.ocid LIMIT :limit OFFSET :offset"""),
                           {**params, "limit": page_size, "offset": (page - 1) * page_size})).mappings().all()
    return {"total": total, "page": page, "page_size": page_size, "as_of": str(date.today()), "items": [_row(dict(r)) for r in rs]}
