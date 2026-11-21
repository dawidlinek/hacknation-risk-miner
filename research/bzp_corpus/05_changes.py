"""
05_changes.py - contract change analysis.

Sources
  AU = AgreementUpdateNotice (published only for art. 455 ust. 1 pkt 3/4 changes)
  CP = change blocks 5.4.2-5.4.8 embedded in ContractPerformingNotice (all bases, incl. pkt 1, ust. 2)

Outputs (out/)
  change_bases.csv            legal-basis distribution by source and population (wod-kan core / other)
  change_value_stats.csv      value change % of contract value by source/basis/price-increase
  change_extension_stats.csv  extension of deadline (days) parsed from AU descriptions
  change_keyword_freq.csv     keyword pre-classifier frequencies by source x basis (wod-kan core)
  change_what.csv             what was changed (time / price / scope) by source x basis
  data/change_reasons_sample.csv  stratified sample of ~150 reasons for hand labelling
Run: uv run --with pandas --with numpy python -I 05_changes.py
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bzp_parse as bp  # noqa: E402
import change_keywords as ck  # noqa: E402
import wodkan_classify as wk  # noqa: E402

D = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")


def tag(df, title_col, desc_col, cpv_col):
    tags = [wk.classify(t, d, c, None, "Works") for t, d, c in zip(df[title_col], df[desc_col], df[cpv_col].astype(str).str[:8])]
    df["relevance"] = [t.relevance for t in tags]
    df["subsector"] = [t.primary for t in tags]
    df["wodkan"] = df.relevance.isin(["core", "cpv_only"]) & np.array([t.scope_kind == "works" for t in tags])
    return df


_NEWDATE_RX = re.compile(r"(?:do\s+dnia|do|na\s+dzień|termin\w*[^.;]{0,80}?)\s*(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})", re.I)


def new_deadline(text: str | None):
    if not isinstance(text, str):
        return None
    m = _NEWDATE_RX.search(text)
    return bp.iso_date(m.group(1)) if m else None


def qstats(s: pd.Series) -> dict:
    s = s.dropna()
    if not len(s):
        return {"n": 0}
    return {"n": len(s), "p10": s.quantile(.1), "p25": s.quantile(.25), "p50": s.quantile(.5), "p75": s.quantile(.75),
            "p90": s.quantile(.9), "mean": s.mean()}


def main():
    os.makedirs(OUT, exist_ok=True)
    au = pd.read_csv(os.path.join(D, "changes.csv.gz"), low_memory=False)
    au["_v"] = pd.to_numeric(au.noticeVersion, errors="coerce").fillna(1)
    au = au.sort_values(["bzpNumber", "_v"]).drop_duplicates("bzpNumber", keep="last")
    au = tag(au, "title", "description", "cpvMain")
    perf = pd.read_csv(os.path.join(D, "contracts_reference.csv.gz"), low_memory=False,
                       usecols=["objectId", "relevance", "scope", "subsector", "contractDate", "plannedEnd", "contract_year", "contractValue"])
    perf["wodkan"] = perf.relevance.isin(["core", "cpv_only"]) & (perf.scope == "works")
    pc = pd.read_csv(os.path.join(D, "perf_changes.csv.gz"), low_memory=False)
    pc = pc.merge(perf[["objectId", "wodkan", "subsector", "contract_year"]], on="objectId", how="inner")  # dedup'd perf only

    # ---------------- legal bases -----------------------------------------------------------
    rows = []
    for src, df, bcol in (("AU", au, "basis"), ("CP", pc, "basis")):
        for popname, sub in (("wod-kan core", df[df.wodkan]), ("pozostałe", df[~df.wodkan]), ("wszystkie", df)):
            vc = sub[bcol].fillna("brak/inna").replace("", "brak/inna").value_counts()
            for b, n in vc.items():
                rows.append({"source": src, "population": popname, "basis": b, "n": int(n), "pct": round(100 * n / len(sub), 2)})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "change_bases.csv"), index=False)

    # ---------------- value change % ----------------------------------------------------------
    au["value_pct"] = au.valueChange / au.contractValue * 100
    pc["value_pct"] = pc.value_change / pc.contractValue * 100
    vrows = []
    for src, df, pcol, inc in (("AU", au, "value_pct", "priceIncrease"), ("CP", pc, "value_pct", "price_increase")):
        d = df[df.wodkan]
        for b, g in d.groupby(d.basis.fillna("brak")):
            vrows.append({"source": src, "basis": b, "n_changes": len(g), "price_increase_share": round(g[inc].mean(), 3),
                          "value_given_share": round(g[pcol].notna().mean(), 3),
                          **{f"inc_{k}": v for k, v in qstats(g.loc[g[inc] == True, pcol].clip(upper=500)).items()},  # noqa: E712
                          **{f"noinc_{k}": v for k, v in qstats(g.loc[g[inc] == False, pcol].clip(upper=500)).items()}})  # noqa: E712
        g = d
        vrows.append({"source": src, "basis": "ALL", "n_changes": len(g), "price_increase_share": round(g[inc].mean(), 3),
                      "value_given_share": round(g[pcol].notna().mean(), 3),
                      **{f"inc_{k}": v for k, v in qstats(g.loc[g[inc] == True, pcol].clip(upper=500)).items()},  # noqa: E712
                      **{f"noinc_{k}": v for k, v in qstats(g.loc[g[inc] == False, pcol].clip(upper=500)).items()}})  # noqa: E712
    pd.DataFrame(vrows).round(2).to_csv(os.path.join(OUT, "change_value_stats.csv"), index=False)

    # ---------------- extension days (AU) --------------------------------------------------------
    au["ext_days_text"] = [bp.extension_days(f"{d} {r}") for d, r in zip(au.changeDescription, au.reason)]
    au["new_deadline"] = [new_deadline(d) or new_deadline(r) for d, r in zip(au.changeDescription, au.reason)]
    pe = pd.to_datetime(au.plannedEnd, errors="coerce")
    nd = pd.to_datetime(au.new_deadline, errors="coerce")
    au["ext_days_date"] = (nd - pe).dt.days
    au.loc[(au.ext_days_date <= 0) | (au.ext_days_date > 1500), "ext_days_date"] = np.nan
    au["ext_days"] = au.ext_days_text.fillna(au.ext_days_date)
    au["time_change"] = [("time" in ck.what_changed(r, d)) for r, d in zip(au.reason, au.changeDescription)]
    erows = []
    for b, g in au[au.wodkan].groupby("basis"):
        erows.append({"basis": b, "n": len(g), "time_change_share": round(g.time_change.mean(), 3),
                      "ext_parsed_share": round(g.ext_days.notna().mean(), 3),
                      "from_text_n": int(g.ext_days_text.notna().sum()), "from_new_date_n": int(g.ext_days_date.notna().sum()),
                      **qstats(g.ext_days)})
    g = au[au.wodkan]
    erows.append({"basis": "ALL", "n": len(g), "time_change_share": round(g.time_change.mean(), 3),
                  "ext_parsed_share": round(g.ext_days.notna().mean(), 3),
                  "from_text_n": int(g.ext_days_text.notna().sum()), "from_new_date_n": int(g.ext_days_date.notna().sum()), **qstats(g.ext_days)})
    pd.DataFrame(erows).round(1).to_csv(os.path.join(OUT, "change_extension_stats.csv"), index=False)

    # ---------------- keyword pre-classifier ---------------------------------------------------------
    au["kw"] = [ck.keyword_categories(r, d) for r, d in zip(au.reason, au.changeDescription)]
    pc["kw"] = [ck.keyword_categories(r, d) for r, d in zip(pc.reason, pc.description)]
    au["what"] = [ck.what_changed(r, d) for r, d in zip(au.reason, au.changeDescription)]
    pc["what"] = [ck.what_changed(r, d) for r, d in zip(pc.reason, pc.description)]
    krows, wrows = [], []
    for src, df in (("AU", au), ("CP", pc)):
        d = df[df.wodkan]
        for b, g in list(d.groupby(d.basis.fillna("brak"))) + [("ALL", d)]:
            n = len(g)
            ex = g.kw.explode()
            cnt = ex.value_counts()
            krows.append({"source": src, "basis": b, "n": n, "no_category": round((g.kw.str.len() == 0).mean() * 100, 1),
                          **{c: round(100 * cnt.get(c, 0) / n, 1) for c in ck.CATEGORY_NAMES}})
            wx = g.what.explode().value_counts()
            wrows.append({"source": src, "basis": b, "n": n, **{c: round(100 * wx.get(c, 0) / n, 1) for c in ck.WHAT}})
    pd.DataFrame(krows).to_csv(os.path.join(OUT, "change_keyword_freq.csv"), index=False)
    pd.DataFrame(wrows).to_csv(os.path.join(OUT, "change_what.csv"), index=False)
    # price-increase-related reasons by contract year (inflation shock signal)
    pc["price_kw"] = pc.kw.apply(lambda k: "N-PRICE" in k)
    au["price_kw"] = au.kw.apply(lambda k: "N-PRICE" in k)
    au["year"] = pd.to_datetime(au.contractDate, errors="coerce").dt.year
    infl = pd.concat([
        pc[pc.wodkan].groupby("contract_year").agg(n=("price_kw", "size"), price_kw_share=("price_kw", "mean")).assign(source="CP"),
        au[au.wodkan].groupby("year").agg(n=("price_kw", "size"), price_kw_share=("price_kw", "mean")).assign(source="AU"),
    ])
    infl.round(3).to_csv(os.path.join(OUT, "change_price_reasons_by_year.csv"))

    # ---------------- stratified sample for hand labelling -------------------------------------------
    rng = 20261121
    strata = [("AU", "455.1.4", 45), ("AU", "455.1.3", 30), ("CP", "455.1.1", 30), ("CP", "455.2", 20), ("CP", "455.1.4", 15),
              ("CP", "455.1.3", 10)]
    samp = []
    for src, b, n in strata:
        df = au if src == "AU" else pc
        rc, dc = ("reason", "changeDescription") if src == "AU" else ("reason", "description")
        g = df[df.wodkan & (df.basis == b) & (df[rc].fillna("").str.len() >= 25)]
        s = g.sample(n=min(n, len(g)), random_state=rng)
        for _, r in s.iterrows():
            samp.append({"sample_id": f"{src}-{b}-{len(samp)+1:03d}", "source": src, "basis": b,
                         "noticeNumber": r.noticeNumber, "objectId": r.objectId, "subsector": r.subsector,
                         "reason": str(r[rc]).replace("\n", " ")[:1200], "description": str(r[dc]).replace("\n", " ")[:600],
                         "kw_categories": " ".join(r.kw)})
    pd.DataFrame(samp).to_csv(os.path.join(D, "change_reasons_sample.csv"), index=False)
    # short / uninformative reasons share
    for src, df in (("AU", au), ("CP", pc)):
        d = df[df.wodkan]
        print(src, "short(<25 chars) reasons share:", round((d.reason.fillna("").str.len() < 25).mean() * 100, 1))
    au[["objectId", "noticeNumber", "tenderId", "wodkan", "subsector", "basis", "priceIncrease", "valueChange", "contractValue", "value_pct",
        "ext_days", "ext_days_text", "ext_days_date", "time_change", "kw", "what"]].to_csv(os.path.join(D, "changes_enriched.csv.gz"), index=False)
    print(pd.read_csv(os.path.join(OUT, "change_bases.csv")).to_string())
    print(pd.read_csv(os.path.join(OUT, "change_value_stats.csv")).to_string())
    print(pd.read_csv(os.path.join(OUT, "change_extension_stats.csv")).to_string())
    print(pd.read_csv(os.path.join(OUT, "change_keyword_freq.csv")).T.to_string())
    print(pd.read_csv(os.path.join(OUT, "change_what.csv")).to_string())
    print(infl.round(3).to_string())


if __name__ == "__main__":
    main()
