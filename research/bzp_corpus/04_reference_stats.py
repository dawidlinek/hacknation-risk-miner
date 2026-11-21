"""
04_reference_stats.py - reference-class statistics from ContractPerformingNotice.

Per contract: planned duration, actual duration, delay, on-time flag, paid vs contract value,
number of changes, properly-performed flag; relevance/subsector tagging; data-quality flags.

Outputs
  data/contracts_reference.csv.gz   one row per completed contract with features + flags
  out/quality_flags.csv             counts of every data-quality issue
  out/ref_stats_by_group.csv        distributions by dimension/group (long format)
  out/ref_class_sizes.csv           n per subsector x value bucket (reference-class sizes)
  out/min_n_bootstrap.csv           how stable p50/p80/p90 and share-late are vs sample size n
  out/censoring_by_year.csv         contract-year cohorts with/without follow-up restriction
Run: uv run --with pandas --with numpy python -I 04_reference_stats.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wodkan_classify as wk  # noqa: E402

D = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
CORPUS_END = pd.Timestamp("2026-11-12")
PROV = {"PL02": "dolnośląskie", "PL04": "kujawsko-pomorskie", "PL06": "lubelskie", "PL08": "lubuskie", "PL10": "łódzkie",
        "PL12": "małopolskie", "PL14": "mazowieckie", "PL16": "opolskie", "PL18": "podkarpackie", "PL20": "podlaskie",
        "PL22": "pomorskie", "PL24": "śląskie", "PL26": "świętokrzyskie", "PL28": "warmińsko-mazurskie",
        "PL30": "wielkopolskie", "PL32": "zachodniopomorskie"}
VALUE_BINS = [0, 500e3, 1e6, 2.5e6, 5e6, 10e6, np.inf]
VALUE_LABELS = ["<0.5 mln", "0.5-1 mln", "1-2.5 mln", "2.5-5 mln", "5-10 mln", ">10 mln"]


def load() -> tuple[pd.DataFrame, dict]:
    q: dict = {}
    p = pd.read_csv(os.path.join(D, "perf.csv.gz"), low_memory=False)
    q["raw_perf_notices"] = len(p)
    p["_v"] = pd.to_numeric(p.noticeVersion, errors="coerce").fillna(1)
    p = p.sort_values(["bzpNumber", "_v"]).drop_duplicates("bzpNumber", keep="last")
    q["dup_notice_versions_removed"] = q["raw_perf_notices"] - len(p)
    key = p.tenderId.astype(str) + "|" + p.contractorNip.fillna(p.contractorName.fillna("")).astype(str) + "|" + p.contractValue.round(2).astype(str) + "|" + p.partMarkers.fillna("").astype(str)
    p = p.assign(_key=key).sort_values("publicationDate")
    dup = p._key.duplicated(keep="last")
    q["dup_republished_same_contract_removed"] = int(dup.sum())
    p = p[~dup].drop(columns=["_v", "_key"])
    q["perf_after_dedup"] = len(p)
    return p, q


def features(p: pd.DataFrame) -> pd.DataFrame:
    tags = [wk.classify(t, d, c, None, o) for t, d, c, o in
            zip(p.title.fillna(p.orderObject), p.description, p.cpvMainForm.astype(str).str[:8], p.orderType)]
    p = p.assign(
        relevance=[t.relevance for t in tags],
        subsector=[t.primary for t in tags],
        subsectors_all=[" ".join(t.subsectors) for t in tags],
        scope=[t.scope_kind for t in tags],
        work_type=[t.work_type for t in tags],
        design_build=[t.design_build for t in tags],
        why=[t.why for t in tags],
    )
    p["subsector_name"] = p.subsector.map(wk.SUBSECTOR_NAMES)
    p["wodkan"] = p.relevance.isin(["core", "cpv_only"]) & (p.scope == "works")
    for c in ["contractDate", "execDate", "plannedEnd", "publicationDate"]:
        p[c] = pd.to_datetime(p[c], errors="coerce")
    p["contract_year"] = p.contractDate.dt.year.astype("Int64")
    p["cohort"] = np.where(p.contract_year <= 2022, "2021-2022 (szok inflacyjny)", "2023+")
    p.loc[p.contract_year.isna(), "cohort"] = None
    p["value_bucket"] = pd.cut(p.contractValue, VALUE_BINS, labels=VALUE_LABELS, right=False)
    p["region"] = p.orgProvince.map(PROV)
    p["eu"] = p.euFunded.map({True: "UE: tak", False: "UE: nie"})
    p["db"] = np.where(p.design_build, "zaprojektuj i wybuduj", "tylko wykonanie")
    # ratios
    p["paid_ratio"] = p.paid / p.contractValue
    return p


def quality(p: pd.DataFrame) -> pd.DataFrame:
    r = p.paid_ratio
    near = lambda x, v, tol: (x - v).abs() <= tol * v  # noqa: E731
    scale = pd.Series(False, index=p.index)
    for v in [10, 100, 1000, 0.1, 0.01, 0.001]:
        scale |= near(r, v, 0.03)
    vat = near(r, 1.23, 0.0015) | near(r, 1 / 1.23, 0.0015) | near(r, 1.08, 0.0015) | near(r, 1 / 1.08, 0.0015)
    f = pd.DataFrame(index=p.index)
    f["q_not_executed"] = p.executed == False  # noqa: E712
    f["q_no_exec_date"] = p.execDate.isna()
    f["q_exec_after_publication"] = p.execDate > p.publicationDate
    f["q_contract_after_publication"] = p.contractDate > p.publicationDate
    f["q_exec_before_contract"] = p.actualDays < 0
    f["q_exec_same_day"] = p.actualDays == 0
    f["q_planned_missing"] = p.plannedDays.isna()
    f["q_planned_nonpositive"] = p.plannedDays <= 0
    f["q_planned_gt_5y"] = p.plannedDays > 1826
    f["q_actual_gt_5y"] = p.actualDays > 1826
    f["q_delay_gt_2y"] = p.delayDays > 730
    f["q_early_gt_1y"] = p.delayDays < -365
    f["q_paid_zero"] = p.paid == 0
    f["q_paid_scale_error_x10"] = scale & (p.paid > 0)
    f["q_paid_vat_ratio"] = vat
    f["q_paid_lt_50pct"] = (r < 0.5) & (p.paid > 0) & ~scale
    f["q_paid_gt_200pct"] = (r > 2) & ~scale
    f["q_ontime_flag_missing"] = p.onTimeDeclared.isna()
    f["q_ontime_but_delay_gt_30d"] = (p.onTimeDeclared == True) & (p.delayDays > 30)  # noqa: E712
    f["q_late_but_delay_le_0"] = (p.onTimeDeclared == False) & (p.delayDays <= 0)  # noqa: E712
    f["q_changes0_but_paid_ne_value"] = (p.nChanges == 0) & ((r - 1).abs() > 0.005) & (p.paid > 0)
    f["q_nchanges_ne_blocks"] = (p.nChanges > 0) & (p.nChangeBlocks != p.nChanges)
    f["q_currency_not_pln"] = (p.contractCurrency.fillna("PLN") != "PLN") | (p.paidCurrency.fillna("PLN") != "PLN")
    return f


def derive(p: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
    time_ok = (~f.q_not_executed & ~f.q_no_exec_date & ~f.q_exec_after_publication & ~f.q_exec_before_contract
               & ~f.q_planned_missing & ~f.q_planned_nonpositive & ~f.q_planned_gt_5y & ~f.q_actual_gt_5y)
    cost_ok = (~f.q_not_executed & ~f.q_paid_zero & ~f.q_paid_scale_error_x10 & ~f.q_paid_lt_50pct & ~f.q_paid_gt_200pct
               & ~f.q_currency_not_pln & p.contractValue.gt(0))
    p["time_ok"], p["cost_ok"] = time_ok, cost_ok
    p["late"] = p.onTimeDeclared.map({False: True, True: False})
    # reconciled delay: declared on time -> 0; declared late & computed>0 -> computed; late & computed<=0 -> NaN
    d = p.delayDays.where(time_ok)
    rec = pd.Series(np.nan, index=p.index)
    rec[p.late == False] = 0  # noqa: E712
    m = (p.late == True) & (d > 0)  # noqa: E712
    rec[m] = d[m]
    p["delay_days_rec"] = rec.where(time_ok)
    p["delay_pct_rec"] = (p.delay_days_rec / p.plannedDays * 100).where(time_ok)
    p["delay_days_raw"] = d
    p["time_ratio"] = (p.actualDays / p.plannedDays).where(time_ok)
    p["cost_dev_pct"] = ((p.paid_ratio - 1) * 100).where(cost_ok)
    p["has_change"] = p.nChanges > 0
    p["improper"] = p.properlyPerformed == False  # noqa: E712
    return p


def summarize(g: pd.DataFrame) -> dict:
    def qs(s, prefix):
        s = s.dropna()
        if len(s) == 0:
            return {f"{prefix}_n": 0}
        return {f"{prefix}_n": len(s), f"{prefix}_p25": s.quantile(.25), f"{prefix}_p50": s.quantile(.5),
                f"{prefix}_p75": s.quantile(.75), f"{prefix}_p90": s.quantile(.9), f"{prefix}_mean": s.mean(),
                f"{prefix}_share_gt0": (s > 0).mean()}
    out = {"n": len(g),
           "late_share": g.late.mean(),
           "late_n": int(g.late.notna().sum()),
           "change_share": g.has_change.mean(),
           "changes_mean": g.nChanges.mean(),
           "improper_share": g.improper.mean(),
           "planned_days_p50": g.plannedDays.where(g.time_ok).median(),
           "actual_days_p50": g.actualDays.where(g.time_ok).median()}
    out.update(qs(g.delay_days_rec, "delay_days"))
    late = g[g.late == True]  # noqa: E712
    out.update({k.replace("delay_days", "delay_days_if_late"): v for k, v in qs(late.delay_days_rec, "delay_days").items() if not k.endswith("share_gt0")})
    out.update(qs(g.delay_pct_rec, "delay_pct"))
    out.update(qs(g.cost_dev_pct, "cost_dev_pct"))
    c = g.cost_dev_pct.dropna()
    out["cost_overrun_gt_0_5pct_share"] = (c > 0.5).mean() if len(c) else np.nan
    out["cost_underrun_lt_m0_5pct_share"] = (c < -0.5).mean() if len(c) else np.nan
    out["cost_exact_share"] = (c.abs() <= 0.5).mean() if len(c) else np.nan
    return out


def by_group(df: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
    rows = [{"dimension": "ALL", "group": "wszystkie", **summarize(df)}]
    for dname in dims:
        for gname, g in df.groupby(dname, observed=True, dropna=True):
            rows.append({"dimension": dname, "group": str(gname), **summarize(g)})
    return pd.DataFrame(rows)


def bootstrap_min_n(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for metric in ["delay_pct", "cost_dev_pct", "late"]:
        s = (df.delay_pct_rec if metric == "delay_pct" else df.cost_dev_pct if metric == "cost_dev_pct" else df.late.astype(float)).dropna().to_numpy()
        for n in [5, 10, 15, 20, 30, 50, 75, 100, 200]:
            draws = rng.choice(s, size=(2000, n), replace=True)
            if metric == "late":
                est = draws.mean(axis=1)
                rows.append({"metric": "late_share", "n": n, "stat": "share", "true": s.mean(),
                             "ci90_low": np.quantile(est, .05), "ci90_high": np.quantile(est, .95)})
            else:
                for qn in [.5, .8, .9]:
                    est = np.quantile(draws, qn, axis=1)
                    rows.append({"metric": metric, "n": n, "stat": f"p{int(qn*100)}", "true": np.quantile(s, qn),
                                 "ci90_low": np.quantile(est, .05), "ci90_high": np.quantile(est, .95)})
    out = pd.DataFrame(rows)
    out["ci90_width"] = out.ci90_high - out.ci90_low
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    p, qinfo = load()
    p = features(p)
    f = quality(p)
    p = derive(p, f)
    # ---- quality table ------------------------------------------------------------------
    rows = [{"flag": k, "n_all": v, "pct_all": None} for k, v in qinfo.items()]
    for c in f.columns:
        rows.append({"flag": c, "n_all": int(f[c].sum()), "pct_all": round(100 * f[c].mean(), 2),
                     "n_wodkan": int(f.loc[p.wodkan, c].sum()), "pct_wodkan": round(100 * f.loc[p.wodkan, c].mean(), 2)})
    rows.append({"flag": "time_ok (usable for time stats)", "n_all": int(p.time_ok.sum()), "pct_all": round(100 * p.time_ok.mean(), 2),
                 "n_wodkan": int(p.time_ok[p.wodkan].sum()), "pct_wodkan": round(100 * p.time_ok[p.wodkan].mean(), 2)})
    rows.append({"flag": "cost_ok (usable for cost stats)", "n_all": int(p.cost_ok.sum()), "pct_all": round(100 * p.cost_ok.mean(), 2),
                 "n_wodkan": int(p.cost_ok[p.wodkan].sum()), "pct_wodkan": round(100 * p.cost_ok[p.wodkan].mean(), 2)})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "quality_flags.csv"), index=False)
    # relevance table
    rel = pd.crosstab(p.relevance, p.scope, margins=True)
    rel.to_csv(os.path.join(OUT, "relevance_x_scope.csv"))
    # ---- stats --------------------------------------------------------------------------
    p["population"] = np.where(p.wodkan, "wod-kan (core, roboty)",
                               np.where(p.relevance == "component", "wod-kan jako element (np. droga+deszczówka)", "pozostałe (nie wod-kan)"))
    dims = ["subsector_name", "value_bucket", "contract_year", "cohort", "eu", "db", "region", "work_type", "durationKind"]
    w = p[p.wodkan & (p.executed == True)]  # noqa: E712  (reference set: wod-kan core works, executed)
    st = by_group(w, dims)
    pop = by_group(p[p.executed == True], ["population"])  # noqa: E712
    pop = pop[pop.dimension != "ALL"]
    allst = pd.concat([pop.assign(scope="all executed contracts"), st.assign(scope="wod-kan core works")], ignore_index=True)
    allst.round(3).to_csv(os.path.join(OUT, "ref_stats_by_group.csv"), index=False)
    # subsector x cohort and subsector x value bucket
    two = []
    for (a, b), g in w.groupby(["subsector_name", "cohort"], observed=True):
        two.append({"subsector": a, "cohort": b, **summarize(g)})
    pd.DataFrame(two).round(3).to_csv(os.path.join(OUT, "ref_stats_subsector_x_cohort.csv"), index=False)
    sizes = pd.crosstab(w.subsector_name, w.value_bucket, margins=True)
    sizes.to_csv(os.path.join(OUT, "ref_class_sizes.csv"))
    sizes2 = w.groupby(["subsector_name", "value_bucket", "work_type"], observed=True).size().rename("n").reset_index()
    sizes2.to_csv(os.path.join(OUT, "ref_class_sizes_detail.csv"), index=False)
    # ---- censoring -----------------------------------------------------------------------
    cen = []
    cut = pd.Timestamp("2025-06-30")
    for y, g in w.groupby("contract_year"):
        g2 = g[g.plannedEnd <= cut]
        cen.append({"contract_year": y, "n": len(g), "late_share": g.late.mean(), "delay_days_p90": g.delay_days_rec.quantile(.9),
                    "cost_dev_p50": g.cost_dev_pct.median(), "cost_dev_p90": g.cost_dev_pct.quantile(.9),
                    "planned_days_p50": g.plannedDays.median(),
                    "n_plannedEnd_le_2025_06_30": len(g2), "late_share_restricted": g2.late.mean(),
                    "delay_days_p90_restricted": g2.delay_days_rec.quantile(.9),
                    "cost_dev_p90_restricted": g2.cost_dev_pct.quantile(.9),
                    "planned_days_p50_restricted": g2.plannedDays.median()})
    pd.DataFrame(cen).round(3).to_csv(os.path.join(OUT, "censoring_by_year.csv"), index=False)
    # ---- min n bootstrap ------------------------------------------------------------------
    bootstrap_min_n(w, np.random.default_rng(42)).round(3).to_csv(os.path.join(OUT, "min_n_bootstrap.csv"), index=False)
    # ---- contract-level export ------------------------------------------------------------
    keep = ["objectId", "noticeNumber", "bzpNumber", "tenderId", "publicationDate", "orgName", "orgNip", "orgCity", "orgProvince", "region",
            "title", "cpvMainForm", "cpvAdditionalForm", "relevance", "subsector", "subsector_name", "subsectors_all", "scope",
            "work_type", "design_build", "why", "euFunded", "euProject", "procedure", "contractorName", "contractorNip",
            "contractNoticeRef", "resultNoticeRef", "partMarkers", "contractDate", "durationRaw", "durationKind", "plannedDays",
            "plannedEnd", "execDate", "actualDays", "delayDays", "delay_days_rec", "delay_pct_rec", "time_ratio", "onTimeDeclared",
            "late", "contractValue", "paid", "paid_ratio", "cost_dev_pct", "nChanges", "nChangeBlocks", "changeBases",
            "changeValueSum", "anyPriceIncrease", "executed", "properlyPerformed", "time_ok", "cost_ok", "value_bucket",
            "contract_year", "cohort"]
    out = pd.concat([p[keep], f], axis=1)
    out.to_csv(os.path.join(D, "contracts_reference.csv.gz"), index=False)
    s = {k: v for k, v in qinfo.items()}
    s["wodkan_core_works"] = int(p.wodkan.sum())
    s["wodkan_core_works_executed"] = int(len(w))
    s["relevance"] = p.relevance.value_counts().to_dict()
    s["scope"] = p.scope.value_counts().to_dict()
    s["subsector"] = w.subsector_name.value_counts().to_dict()
    with open(os.path.join(OUT, "reference_summary.json"), "w", encoding="utf-8") as fo:
        json.dump(s, fo, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(s, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
