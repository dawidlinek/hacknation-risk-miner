"""National headline numbers for Pulpit and the pitch (analytics.md §3.10.1), from the in-memory case base.

Usage (B's dashboard router): `from riskminer.analytics.headline import headline; h = headline(await get_casebase(db))`.
"""
from __future__ import annotations

import numpy as np

from riskminer.analytics import templates as T
from riskminer.analytics.base import CaseBase


def headline(cb: CaseBase) -> dict:
    late = cb["late"]
    m_late = late >= 0
    n = cb.n
    late_share = float((late[m_late] == 1).mean())
    ch = cb["changes_count"]
    change_share = float((ch[np.isfinite(ch)] > 0).mean())
    t_ok = cb["time_ok"]
    d = cb["delay_days"]
    delay_sum = float(np.nansum(np.where(t_ok & np.isfinite(d) & (d > 0) & (late == 1), d, 0)))
    li = t_ok & (late == 1) & np.isfinite(d) & (d > 0)
    p50, p90 = (float(x) for x in np.percentile(d[li], [50, 90]))
    c_ok = cb["cost_ok"]
    c = cb["cost_dev_pct"][c_ok]
    v = cb["value_gross"][c_ok]
    p = cb["paid_gross"][c_ok]
    overpaid = float(np.maximum(p - v, 0).sum())
    ref = {"kind": "query", "id": "an_contract:all", "label": f"{T.pl_num(n)} wykonanych umów wod-kan (BZP)"}

    def num(value, display, unit, nn, method):
        return {"value": value, "display": display, "unit": unit,
                "prov": {"role": "calc", "review_status": "auto", "n": int(nn), "method": method, "refs": [ref]}}

    sentence = (f"Od 2021 r. {T.pct(late_share)} z {T.pl_num(n)} wykonanych umów wodno-kanalizacyjnych skończyło się "
                f"po terminie, łącznie {T.pl_num(delay_sum / 1000)} tys. dni opóźnień. Ponad wartość umów zapłacono "
                f"{T.pl_num(overpaid / 1e6)} mln zł.")
    return {
        "sentence": sentence,
        "completed": num(n, T.pl_num(n), "count", n, "count"),
        "late_share": num(round(late_share, 4), T.pct(late_share, 1), "share", int(m_late.sum()), "share(late)"),
        "change_share": num(round(change_share, 4), T.pct(change_share, 1), "share", n, "share(changes_count>0)"),
        "delay_days_total": num(delay_sum, f"{T.pl_num(delay_sum / 1000)} tys. dni", "days", int(li.sum()),
                                "sum(delay_days | late, time_ok)"),
        "delay_if_late_p50": num(p50, f"{T.pl_num(p50)} dni", "days", int(li.sum()), "median(delay_days | late)"),
        "delay_if_late_p90": num(p90, f"{T.pl_num(p90)} dni", "days", int(li.sum()), "p90(delay_days | late)"),
        "cost_p90_pct": num(float(np.percentile(c, 90)), f"+{T.pl_num(float(np.percentile(c, 90)), 1)}%", "pct",
                            int(c.size), "p90(cost_dev_pct | cost_ok)"),
        "paid_above_share": num(float((c > 0.5).mean()), T.pct(float((c > 0.5).mean()), 1), "share", int(c.size),
                                "share(cost_dev_pct > 0,5)"),
        "overpaid": {"money": {"amount": f"{overpaid:.2f}", "currency": "PLN", "vat_basis": "gross"},
                     "prov": {"role": "calc", "review_status": "auto", "n": int(c.size),
                              "method": "sum(max(paid - value, 0) | cost_ok)", "refs": [ref]}},
        "value_sum": {"amount": f"{float(v.sum()):.2f}", "currency": "PLN", "vat_basis": "gross"},
        "paid_sum": {"amount": f"{float(p.sum()):.2f}", "currency": "PLN", "vat_basis": "gross"},
        "data_as_of": cb.data_as_of.isoformat() if cb.data_as_of else None,
        "data_version": cb.data_version,
        "chips": _chips(cb),
    }


def _chips(cb: CaseBase) -> dict:
    late = cb["late"]
    db = cb["design_build"]
    out = {}
    for k, val in (("design_build", 1), ("build_only", 0)):
        m = (db == val) & (late >= 0)
        out[k] = {"late_share": round(float((late[m] == 1).mean()), 4), "n": int(m.sum())}
    return out
