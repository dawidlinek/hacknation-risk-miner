"""
07_wow_features.py - quick feasibility numbers for "wow" features.

 1. unit-cost benchmark (PLN per km of network) from lengths in title/description
 2. competition signal (offers, spread, discount vs estimate) vs later delay/overrun/changes
 3. ongoing contracts / early-warning radar (awarded, no performance notice, past planned end)
 4. backtest of reference-class bands (train: completed < 2024-01-01, test: completed 2024-2026)
 5. pitch headline numbers by year and province
Outputs: out/wow_*.csv, printed summary.
Run: uv run --with pandas --with numpy python -I 07_wow_features.py
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wodkan_classify as wk  # noqa: E402

D, OUT = os.path.join(HERE, "data"), os.path.join(HERE, "out")
CORPUS_END = pd.Timestamp("2026-11-12")
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

# ---------------------------------------------------------------------------------------------
# 1. lengths
# ---------------------------------------------------------------------------------------------
_LEN_RX = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[,.](\d+))?\s*(km|mb|m\.?\s?b\.?|mtr|metr\w*|m)(?![\w²³2-3])(?!\s*n\.?\s*p\.?\s*m)",
    re.I)
_CONN_RX = re.compile(r"przyłącz|podłącz|przykanalik|odgałęzie|sięgacz", re.I)
_SKIP_RX = re.compile(r"głęboko|zagłębie|wysokoś|szerokoś|średnic|grubo|odległoś|promie|wysięg|nad\s+poziom|poniżej|powyżej", re.I)
_TOTAL_RX = re.compile(r"łączn\w*\s+długoś|o\s+długości\s+całkowitej|długość\s+całkowita|razem", re.I)


def lengths(text: str | None) -> dict:
    """Return network length (km) and connection length (km) mentioned in text.
    - unit m/mb/km; ignores mm, m2/m3, 'm n.p.m.'; values < 5 m or > 200 km dropped
    - a mention is a 'connection' if 'przyłącz/przykanalik' occurs in the 60 chars before it
    - if a 'łączna długość' style total is present, it is used instead of summing segments"""
    if not isinstance(text, str):
        return {"net_km": None, "conn_km": None, "n_mentions": 0, "used_total": False}
    net, conn, n, total = [], [], 0, None
    for m in _LEN_RX.finditer(text):
        num = float(re.sub(r"[  ]", "", m.group(1)) + ("." + m.group(2) if m.group(2) else ""))
        unit = m.group(3).lower()
        km = num if unit == "km" else num / 1000
        if km < 0.005 or km > 200:
            continue
        ctx = text[max(0, m.start() - 60): m.start()]
        if _SKIP_RX.search(text[max(0, m.start() - 35): m.start()]):
            continue
        n += 1
        if _CONN_RX.search(ctx):
            conn.append(km)
        else:
            net.append(km)
            if total is None and _TOTAL_RX.search(ctx):
                total = km
    net_km = total if total is not None else (sum(net) if net else None)
    return {"net_km": net_km, "conn_km": sum(conn) if conn else None, "n_mentions": n, "used_total": total is not None}


def unit_costs(c: pd.DataFrame) -> pd.DataFrame:
    perf = pd.read_csv(os.path.join(D, "perf.csv.gz"), usecols=["objectId", "description", "orderObject"], low_memory=False)
    w = c[c.wodkan].merge(perf, on="objectId", how="left")
    text = w.title.fillna("") + " \n " + w.description.fillna("")
    L = pd.DataFrame([lengths(t) for t in text], index=w.index)
    w = pd.concat([w, L], axis=1)
    cov = w.groupby("subsector_name").agg(n=("objectId", "size"), any_length=("n_mentions", lambda s: (s > 0).mean()),
                                         net_length=("net_km", lambda s: s.notna().mean()),
                                         conn_only=("conn_km", lambda s: s.notna().mean()))
    cov.loc["ALL"] = [len(w), (w.n_mentions > 0).mean(), w.net_km.notna().mean(), w.conn_km.notna().mean()]
    cov.round(3).to_csv(os.path.join(OUT, "wow_length_coverage.csv"))
    x = w[w.subsector.isin(["SAN", "WOD"]) & w.net_km.between(0.1, 100) & w.contractValue.gt(50e3)].copy()
    x["pln_per_km"] = x.contractValue / x.net_km
    x["paid_per_km"] = x.paid / x.net_km
    x = x[x.pln_per_km.between(5e4, 2e7)]  # drop absurd ratios (length mis-parse)
    rows = []
    for (s, y), g in x.groupby(["subsector_name", "contract_year"]):
        rows.append({"subsector": s, "contract_year": y, "n": len(g), "p25": g.pln_per_km.quantile(.25), "p50": g.pln_per_km.median(),
                     "p75": g.pln_per_km.quantile(.75), "p90": g.pln_per_km.quantile(.9)})
    for s, g in x.groupby("subsector_name"):
        rows.append({"subsector": s, "contract_year": "ALL", "n": len(g), "p25": g.pln_per_km.quantile(.25), "p50": g.pln_per_km.median(),
                     "p75": g.pln_per_km.quantile(.75), "p90": g.pln_per_km.quantile(.9)})
    uc = pd.DataFrame(rows)
    uc.round(0).to_csv(os.path.join(OUT, "wow_unit_cost_pln_per_km.csv"), index=False)
    x[["objectId", "noticeNumber", "title", "subsector", "contract_year", "contractValue", "net_km", "conn_km", "used_total", "pln_per_km"]].to_csv(
        os.path.join(D, "unit_cost_contracts.csv.gz"), index=False)
    print("\n[1] length coverage\n", cov.round(3).to_string())
    print(uc.round(0).to_string())
    return x


# ---------------------------------------------------------------------------------------------
# 2. competition
# ---------------------------------------------------------------------------------------------
def competition(c: pd.DataFrame) -> pd.DataFrame:
    r = pd.read_csv(os.path.join(D, "results.csv.gz"), low_memory=False)
    r["_v"] = pd.to_numeric(r.noticeVersion, errors="coerce").fillna(1)
    r = r.sort_values(["bzpNumber", "part", "_v"]).drop_duplicates(["bzpNumber", "part"], keep="last")
    aw = r[r.contractDate.notna()].copy()
    w = c[c.wodkan & c.resultNoticeRef.notna()].copy()
    # match perf -> TR row: same TR number and (NIP or value within 1%), else TR with one awarded row
    m1 = w.merge(aw, left_on=["resultNoticeRef", "contractorNip"], right_on=["bzpNumber", "contractorNip"], how="inner", suffixes=("", "_tr"))
    m1 = m1.drop_duplicates("objectId")
    rest = w[~w.objectId.isin(m1.objectId)]
    m2 = rest.merge(aw, left_on="resultNoticeRef", right_on="bzpNumber", how="inner", suffixes=("", "_tr"))
    m2 = m2[(m2.contractValue / m2.contractValue_tr - 1).abs() < 0.01].drop_duplicates("objectId")
    rest = rest[~rest.objectId.isin(m2.objectId)]
    single = aw.groupby("bzpNumber").filter(lambda g: len(g) == 1)
    m3 = rest.merge(single, left_on="resultNoticeRef", right_on="bzpNumber", how="inner", suffixes=("", "_tr"))
    m = pd.concat([m1, m2, m3], ignore_index=True)
    print(f"\n[2] perf (wod-kan) with TR ref: {len(w)}, matched to TR row: {len(m)} (nip {len(m1)}, value {len(m2)}, single {len(m3)})")
    m["n_offers_b"] = pd.cut(m.nOffers, [0, 1, 2, 4, 7, 1000], labels=["1", "2", "3-4", "5-7", "8+"])
    m["budget_gross"] = m.estimatedValueNet * 1.23
    m["award_vs_budget"] = m.contractValue_tr / m.budget_gross
    ok = (m.nParts == 1) & m.award_vs_budget.between(0.2, 3)
    m.loc[~ok, "award_vs_budget"] = np.nan
    m["discount_b"] = pd.cut(m.award_vs_budget, [0, 0.6, 0.8, 0.95, 1.05, 10], labels=["<60% kosztorysu", "60-80%", "80-95%", "95-105%", ">105%"])
    m["spread"] = m.maxOffer / m.minOffer
    m["spread_b"] = pd.cut(m.spread, [0.99, 1.0001, 1.25, 1.5, 2, 1000], labels=["1 oferta/identyczne", "<1.25", "1.25-1.5", "1.5-2", ">2"])
    m["win_vs_2nd_proxy"] = m.minOffer / m.maxOffer
    rows = []
    for dim in ["n_offers_b", "discount_b", "spread_b"]:
        for gname, g in m.groupby(dim, observed=True):
            rows.append({"dimension": dim, "group": str(gname), "n": len(g), "late_share": g.late.mean(),
                         "change_share": (g.nChanges > 0).mean(), "cost_overrun_share": (g.cost_dev_pct > 0.5).mean(),
                         "cost_dev_p90": g.cost_dev_pct.quantile(.9), "delay_days_p90": g.delay_days_rec.quantile(.9),
                         "median_value_mln": g.contractValue.median() / 1e6})
    out = pd.DataFrame(rows)
    # control for size: within value bucket 1-5 mln
    sub = m[m.contractValue.between(1e6, 5e6)]
    for dim in ["n_offers_b", "discount_b"]:
        for gname, g in sub.groupby(dim, observed=True):
            rows.append({"dimension": dim + " | 1-5 mln", "group": str(gname), "n": len(g), "late_share": g.late.mean(),
                         "change_share": (g.nChanges > 0).mean(), "cost_overrun_share": (g.cost_dev_pct > 0.5).mean(),
                         "cost_dev_p90": g.cost_dev_pct.quantile(.9), "delay_days_p90": g.delay_days_rec.quantile(.9),
                         "median_value_mln": g.contractValue.median() / 1e6})
    out = pd.DataFrame(rows)
    out.round(3).to_csv(os.path.join(OUT, "wow_competition_vs_outcomes.csv"), index=False)
    fill = pd.Series({"nOffers": r.nOffers.notna().mean(), "minOffer": r.minOffer.notna().mean(), "maxOffer": r.maxOffer.notna().mean(),
                      "winningOffer": r.winningOffer.notna().mean(), "estimatedValueNet": r.estimatedValueNet.notna().mean(),
                      "contractValue": r.contractValue.notna().mean()})
    fill.round(3).to_csv(os.path.join(OUT, "wow_tr_field_fill.csv"))
    print(fill.round(3).to_string())
    print(out.round(3).to_string())
    # cancellations (art. 255 pkt 3 = offers above budget) by year - inflation shock signal
    r["year"] = r.publicationDate.str[:4]
    r["art255"] = r.cancelBasis255.astype("Int64").astype(str)
    tags = [wk.classify(t, d, cc, None, "Works") for t, d, cc in zip(r.orderObject, r.shortDescription, r.cpvMainForm.astype(str))]
    r["wodkan"] = [t.relevance in ("core", "cpv_only") and t.scope_kind == "works" for t in tags]
    canc = r[r.wodkan].groupby("year").agg(n_parts=("bzpNumber", "size"), cancelled_share=("cancelled", "mean"),
                                           cancel_255_3_share=("art255", lambda s: (s == "3").mean()),
                                           cancel_255_1_no_offers_share=("art255", lambda s: (s == "1").mean()),
                                           single_offer_share=("nOffers", lambda s: (s == 1).mean()),
                                           offers_median=("nOffers", "median"))
    canc.round(3).to_csv(os.path.join(OUT, "wow_cancellations_by_year.csv"))
    print(canc.round(3).to_string())
    return m


# ---------------------------------------------------------------------------------------------
# 3. ongoing contracts
# ---------------------------------------------------------------------------------------------
def ongoing(c_all: pd.DataFrame) -> pd.DataFrame:
    r = pd.read_csv(os.path.join(D, "results.csv.gz"), low_memory=False)
    r["_v"] = pd.to_numeric(r.noticeVersion, errors="coerce").fillna(1)
    r = r.sort_values(["bzpNumber", "part", "_v"]).drop_duplicates(["bzpNumber", "part"], keep="last")
    aw = r[r.contractDate.notna()].copy()
    tags = [wk.classify(t, d, cc, None, "Works") for t, d, cc in zip(aw.orderObject, aw.shortDescription, aw.cpvMainForm.astype(str))]
    aw["wodkan"] = [t.relevance in ("core", "cpv_only") and t.scope_kind == "works" for t in tags]
    aw["subsector"] = [t.primary for t in tags]
    perf = pd.read_csv(os.path.join(D, "perf.csv.gz"), usecols=["resultNoticeRef", "contractorNip", "contractValue", "tenderId"], low_memory=False)
    k_nip = set(zip(perf.resultNoticeRef, perf.contractorNip))
    k_val = set(zip(perf.resultNoticeRef, perf.contractValue.round(0)))
    refs = perf.resultNoticeRef.value_counts()
    nrows = aw.groupby("bzpNumber").size()
    aw["has_perf"] = [((b, n) in k_nip) or ((b, round(v, 0) if v == v else None) in k_val) or (nrows.get(b, 0) == 1 and refs.get(b, 0) > 0)
                      for b, n, v in zip(aw.bzpNumber, aw.contractorNip, aw.contractValue)]
    au = pd.read_csv(os.path.join(D, "changes.csv.gz"), usecols=["tenderId", "resultNoticeRef", "basis", "priceIncrease"], low_memory=False)
    au_by_tr = au.groupby("resultNoticeRef").size()
    aw["n_change_notices"] = aw.bzpNumber.map(au_by_tr).fillna(0).astype(int)
    aw["has_perf_in_tender"] = aw.tenderId.isin(set(perf.tenderId))
    aw["plannedEnd"] = pd.to_datetime(aw.plannedEnd, errors="coerce")
    aw["days_past_planned_end"] = (CORPUS_END - aw.plannedEnd).dt.days
    rows = []
    for pop, g in (("wod-kan core", aw[aw.wodkan]), ("wszystkie", aw)):
        op = g[~g.has_perf]
        rows.append({"population": pop, "awarded_contracts(TR rows)": len(g), "with_perf_notice": int(g.has_perf.sum()),
                     "without_perf_notice": len(op),
                     "without_any_perf_in_same_tender": int((~g.has_perf_in_tender).sum()),
                     "without_perf_planned_end_future": int((op.days_past_planned_end < 0).sum()),
                     "without_perf_past_end_0_90d": int(op.days_past_planned_end.between(0, 90).sum()),
                     "without_perf_past_end_90_365d": int(op.days_past_planned_end.between(91, 365).sum()),
                     "without_perf_past_end_gt_365d": int((op.days_past_planned_end > 365).sum()),
                     "without_perf_with_change_notice": int((op.n_change_notices > 0).sum()),
                     "without_perf_past_end_and_change_notice": int(((op.days_past_planned_end > 0) & (op.n_change_notices > 0)).sum()),
                     "value_without_perf_mln": op.contractValue.sum() / 1e6})
    out = pd.DataFrame(rows)
    out.round(1).to_csv(os.path.join(OUT, "wow_ongoing_radar.csv"), index=False)
    # by contract year for wod-kan
    g = aw[aw.wodkan].copy()
    g["cy"] = pd.to_datetime(g.contractDate).dt.year
    by = g.groupby("cy").agg(awarded=("has_perf", "size"), perf_share=("has_perf", "mean"),
                             open_past_end=("days_past_planned_end", lambda s: ((s > 30) & ~g.loc[s.index, "has_perf"]).sum()))
    by.round(3).to_csv(os.path.join(OUT, "wow_ongoing_by_contract_year.csv"))
    radar = g[~g.has_perf & (g.days_past_planned_end > -90)].sort_values("days_past_planned_end", ascending=False)
    radar[["bzpNumber", "part", "tenderId", "orgName", "orgProvince", "orderObject", "subsector", "contractDate", "contractValue",
           "durationRaw", "plannedEnd", "days_past_planned_end", "n_change_notices"]].to_csv(os.path.join(D, "radar_open_contracts.csv.gz"), index=False)
    print("\n[3] ongoing radar\n", out.round(1).T.to_string())
    print(by.round(3).to_string())
    return out


# ---------------------------------------------------------------------------------------------
# 4. backtest
# ---------------------------------------------------------------------------------------------
def backtest(c: pd.DataFrame) -> pd.DataFrame:
    w = c[c.wodkan & (c.executed == True)].copy()  # noqa: E712
    w["execDate"] = pd.to_datetime(w.execDate, errors="coerce")
    train = w[w.execDate < "2024-01-01"]
    test = w[w.execDate >= "2024-01-01"]
    rows = []
    for metric in ["delay_days_rec", "delay_pct_rec", "cost_dev_pct"]:
        for level in ["subsector+value", "subsector", "global"]:
            keys = {"subsector+value": ["subsector", "value_bucket"], "subsector": ["subsector"], "global": []}[level]
            tr = train.dropna(subset=[metric])
            te = test.dropna(subset=[metric]).copy()
            if keys:
                q = tr.groupby(keys, observed=True)[metric].agg(n="size", p10=lambda s: s.quantile(.1), p50="median",
                                                                p80=lambda s: s.quantile(.8), p90=lambda s: s.quantile(.9)).reset_index()
                te = te.merge(q, on=keys, how="left")
                # fallback when class too small
                small = te.n.fillna(0) < 30
                te.loc[small, ["p10", "p50", "p80", "p90"]] = [tr[metric].quantile(.1), tr[metric].median(), tr[metric].quantile(.8), tr[metric].quantile(.9)]
            else:
                te["p10"], te["p50"], te["p80"], te["p90"], te["n"] = tr[metric].quantile(.1), tr[metric].median(), tr[metric].quantile(.8), tr[metric].quantile(.9), len(tr)
            y = te[metric]
            inside = (y >= te.p10) & (y <= te.p90)
            pin90 = np.mean(np.maximum(0.9 * (y - te.p90), (0.9 - 1) * (y - te.p90)))
            rows.append({"metric": metric, "reference_class": level, "n_train": len(tr), "n_test": len(te),
                         "share_in_P10_P90": inside.mean(), "share_le_P80": (y <= te.p80).mean(), "share_le_P90": (y <= te.p90).mean(),
                         "share_above_P90": (y > te.p90).mean(), "pinball_loss_P90": pin90})
    # late-share calibration
    for level in ["subsector+value", "subsector", "global"]:
        keys = {"subsector+value": ["subsector", "value_bucket"], "subsector": ["subsector"], "global": []}[level]
        tr = train.dropna(subset=["late"]); te = test.dropna(subset=["late"]).copy()
        te["late"] = te.late.astype(float); tr = tr.assign(late=tr.late.astype(float))
        if keys:
            q = tr.groupby(keys, observed=True).late.agg(p_late="mean", n="size").reset_index()
            te = te.merge(q, on=keys, how="left")
            te.loc[te.n.fillna(0) < 30, "p_late"] = tr.late.mean()
        else:
            te["p_late"] = tr.late.mean()
        brier = np.mean((te.p_late - te.late) ** 2)
        rows.append({"metric": "late (prob.)", "reference_class": level, "n_train": len(tr), "n_test": len(te),
                     "brier": brier, "pred_mean": te.p_late.mean(), "obs_mean": te.late.mean()})
        if level == "subsector+value":
            te["bin"] = pd.cut(te.p_late, [0, .2, .3, .4, .5, 1])
            cal = te.groupby("bin", observed=True).agg(n=("late", "size"), pred=("p_late", "mean"), obs=("late", "mean"))
            cal.round(3).to_csv(os.path.join(OUT, "wow_backtest_late_calibration.csv"))
            print(cal.round(3).to_string())
    out = pd.DataFrame(rows)
    out.round(3).to_csv(os.path.join(OUT, "wow_backtest.csv"), index=False)
    print("\n[4] backtest\n", out.round(3).to_string())
    return out


# ---------------------------------------------------------------------------------------------
# 5. pitch numbers
# ---------------------------------------------------------------------------------------------
def pitch(c: pd.DataFrame):
    w = c[c.wodkan & (c.executed == True)].copy()  # noqa: E712
    w["exec_year"] = pd.to_datetime(w.execDate, errors="coerce").dt.year.where(w.time_ok)
    w["over"] = (w.paid - w.contractValue).where(w.cost_ok)
    def agg(g):
        return pd.Series({"n_contracts": len(g), "contract_value_mln": g.contractValue.where(g.cost_ok).sum() / 1e6, "paid_mln": g.paid.where(g.cost_ok).sum() / 1e6,
                          "paid_above_value_mln (sum of overruns)": g.over.clip(lower=0).sum() / 1e6,
                          "net_paid_minus_value_mln": g.over.sum() / 1e6,
                          "late_share": g.late.mean(), "delay_days_sum": g.delay_days_rec.sum(), "delay_days_median_if_late": g.loc[g.late == True, "delay_days_rec"].median(),  # noqa: E712
                          "change_share": (g.nChanges > 0).mean(), "cost_overrun_share": (g.cost_dev_pct > 0.5).mean(),
                          "improper_share": (g.properlyPerformed == False).mean()})  # noqa: E712
    tot = agg(w)
    by_cy = w.groupby("contract_year").apply(agg)
    by_ey = w.groupby("exec_year").apply(agg)
    by_pr = w.groupby(["orgProvince", "region"]).apply(agg)
    allc = c[c.executed == True]  # noqa: E712
    allc = allc.assign(over=(allc.paid - allc.contractValue).where(allc.cost_ok))
    tot_all = agg(allc)
    pd.concat({"wod-kan core": tot, "cały korpus (wszystkie roboty)": tot_all}, axis=1).round(2).to_csv(os.path.join(OUT, "wow_pitch_totals.csv"))
    by_cy.round(3).to_csv(os.path.join(OUT, "wow_pitch_by_contract_year.csv"))
    by_ey.round(3).to_csv(os.path.join(OUT, "wow_pitch_by_exec_year.csv"))
    by_pr.round(3).to_csv(os.path.join(OUT, "wow_pitch_by_province.csv"))
    print("\n[5] pitch\n", pd.concat({"wodkan": tot, "all": tot_all}, axis=1).round(2).to_string())
    print(by_cy.round(3).to_string()); print(by_ey.round(3).to_string()); print(by_pr.round(3).to_string())


def main():
    c = pd.read_csv(os.path.join(D, "contracts_reference.csv.gz"), low_memory=False)
    c["wodkan"] = c.relevance.isin(["core", "cpv_only"]) & (c.scope == "works")
    unit_costs(c)
    competition(c)
    ongoing(c)
    backtest(c)
    pitch(c)


if __name__ == "__main__":
    main()
