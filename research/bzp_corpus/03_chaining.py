"""
03_chaining.py - procedure chains (tenderId / OCID) across the 4 notice types.

Outputs (out/):
  chain_patterns.csv        tender-level type patterns (CN/TR/AU/CP present) with counts
  chain_summary.json        headline coverage numbers
  perf_ref_resolution.csv   how ContractPerformingNotice fields 3.2.1 / 4.5 resolve
Run: uv run --with pandas python -I 03_chaining.py
"""
from __future__ import annotations

import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "out")
ABBR = {"ContractNotice": "CN", "TenderResultNotice": "TR", "AgreementUpdateNotice": "AU", "ContractPerformingNotice": "CP"}


def latest_versions(ix: pd.DataFrame) -> pd.DataFrame:
    ix = ix.copy()
    ix["_v"] = pd.to_numeric(ix["noticeVersion"], errors="coerce").fillna(1)
    ix = ix.sort_values(["noticeType", "bzpNumber", "_v"])
    return ix.drop_duplicates(["noticeType", "bzpNumber"], keep="last").drop(columns="_v")


def main():
    os.makedirs(OUT, exist_ok=True)
    ix = pd.read_csv(os.path.join(D, "notice_index.csv.gz"), dtype=str)
    s: dict = {"notices_total": len(ix)}
    s["tenderId_missing"] = int(ix.tenderId.isna().sum())
    s["versions_gt1_by_type"] = ix[ix.noticeVersion.fillna("01") != "01"].groupby("noticeType").size().to_dict()
    s["same_bzpNumber_multiple_versions_rows"] = int(ix.duplicated(["noticeType", "bzpNumber"], keep=False).sum())
    lx = latest_versions(ix)
    s["after_dedup"] = len(lx)
    lx["t"] = lx.noticeType.map(ABBR)

    # ---- tender-level patterns --------------------------------------------------------
    cnt = lx.pivot_table(index="tenderId", columns="t", values="objectId", aggfunc="count", fill_value=0)
    for c in ["CN", "TR", "AU", "CP"]:
        if c not in cnt:
            cnt[c] = 0
    pat = cnt.apply(lambda r: "+".join(c for c in ["CN", "TR", "AU", "CP"] if r[c] > 0), axis=1)
    pc = pat.value_counts().rename_axis("pattern").reset_index(name="n_tenders")
    pc["pct"] = (100 * pc.n_tenders / pc.n_tenders.sum()).round(2)
    pc.to_csv(os.path.join(OUT, "chain_patterns.csv"), index=False)
    s["tenders"] = int(len(cnt))
    s["tenders_with"] = {c: int((cnt[c] > 0).sum()) for c in ["CN", "TR", "AU", "CP"]}
    has = {c: cnt[c] > 0 for c in ["CN", "TR", "AU", "CP"]}
    s["full_chain_CN_TR_CP"] = int((has["CN"] & has["TR"] & has["CP"]).sum())
    s["full_chain_CN_TR_AU_CP"] = int((has["CN"] & has["TR"] & has["AU"] & has["CP"]).sum())
    s["CP_tenders_with_CN_and_TR_pct"] = round(100 * (has["CN"] & has["TR"] & has["CP"]).sum() / has["CP"].sum(), 2)
    s["CP_tenders_with_TR_pct"] = round(100 * (has["TR"] & has["CP"]).sum() / has["CP"].sum(), 2)
    s["CP_tenders_with_CN_pct"] = round(100 * (has["CN"] & has["CP"]).sum() / has["CP"].sum(), 2)
    s["AU_tenders_with_CP_pct"] = round(100 * (has["AU"] & has["CP"]).sum() / has["AU"].sum(), 2)
    s["CN_tenders_with_TR_pct"] = round(100 * (has["CN"] & has["TR"]).sum() / has["CN"].sum(), 2)
    s["CN_tenders_with_CP_pct"] = round(100 * (has["CN"] & has["CP"]).sum() / has["CN"].sum(), 2)
    # completion by CN year (right-censoring of the performance notice)
    cn_year = lx[lx.t == "CN"].groupby("tenderId").publicationDate.min().str[:4]
    tr_awarded = None
    try:
        res = pd.read_csv(os.path.join(D, "results.csv.gz"), dtype=str, usecols=["tenderId", "noticeNumber", "cancelled", "contractDate", "part"])
        aw = res[res.cancelled == "False"].groupby("tenderId").size()
        tr_awarded = aw
    except Exception:  # pragma: no cover
        pass
    yr = pd.DataFrame({"year": cn_year})
    yr["has_CP"] = cnt.reindex(yr.index)["CP"] > 0
    yr["has_TR"] = cnt.reindex(yr.index)["TR"] > 0
    if tr_awarded is not None:
        yr["awarded"] = yr.index.isin(tr_awarded.index)
    s["CN_year_coverage"] = yr.groupby("year").agg(n=("has_CP", "size"), pct_TR=("has_TR", "mean"),
                                                   pct_awarded=("awarded", "mean"), pct_CP=("has_CP", "mean")).round(3).to_dict(orient="index")
    # multiplicity
    s["CP_per_tender_dist"] = cnt.loc[cnt.CP > 0, "CP"].value_counts().sort_index().head(10).to_dict()
    s["TR_per_tender_dist"] = cnt.loc[cnt.TR > 0, "TR"].value_counts().sort_index().head(10).to_dict()
    s["AU_per_tender_dist"] = cnt.loc[cnt.AU > 0, "AU"].value_counts().sort_index().head(10).to_dict()

    # ---- performance notice references ------------------------------------------------
    perf = pd.read_csv(os.path.join(D, "perf.csv.gz"), dtype=str)
    perf = perf.sort_values("noticeVersion").drop_duplicates("bzpNumber", keep="last")
    bzp_by_type = {t: set(g.bzpNumber) for t, g in lx.groupby("t")}
    tid_of = dict(zip(lx.bzpNumber + "|" + lx.t, lx.tenderId))

    def kind(raw):
        if not isinstance(raw, str) or not raw.strip():
            return "missing"
        if "BZP" in raw.upper():
            return "BZP"
        if "/S" in raw.upper() or "-20" in raw or "TED" in raw.upper():
            return "TED"
        return "other"

    rows = []
    for fld, typ in (("contractNoticeRef", "CN"), ("resultNoticeRef", "TR")):
        raw = perf[fld + "Raw"]
        k = raw.map(kind)
        ref = perf[fld]
        in_corpus = ref.isin(bzp_by_type[typ])
        same_tid = [(tid_of.get(f"{r}|{typ}") == t) if isinstance(r, str) else False for r, t in zip(ref, perf.tenderId)]
        for kk in ["BZP", "TED", "other", "missing"]:
            m = k == kk
            rows.append({"field": "3.2.1" if typ == "CN" else "4.5", "points_to": typ, "kind": kk, "n": int(m.sum()),
                         "pct": round(100 * m.mean(), 2),
                         "resolves_in_corpus": int((in_corpus & m).sum()),
                         "resolves_same_tenderId": int((pd.Series(same_tid, index=perf.index) & m).sum())})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "perf_ref_resolution.csv"), index=False)
    # BZP refs that don't resolve: is the referenced notice maybe another type (e.g. CN number in 4.5)?
    all_bzp = set(lx.bzpNumber)
    r45 = perf.resultNoticeRef
    s["perf_4.5_BZP_not_TR_but_other_type"] = int((r45.isin(all_bzp) & ~r45.isin(bzp_by_type["TR"])).sum())
    r321 = perf.contractNoticeRef
    s["perf_3.2.1_points_to_TR_instead_of_CN"] = int(r321.isin(bzp_by_type["TR"]).sum())
    s["perf_not_preceded_by_notice(3.2=Nie)"] = int((perf.precededByNotice == "False").sum())
    s["perf_aboveEU(belowEU=False)"] = int((perf.belowEU == "False").sum())
    # perf notices per tender vs lots
    perf_per_t = perf.groupby("tenderId").size()
    s["perf_notices_tenders_with_gt1_perf"] = int((perf_per_t > 1).sum())
    s["perf_notices_in_tenders_with_gt1_perf"] = int(perf_per_t[perf_per_t > 1].sum())
    s["perf_with_part_markers"] = int(perf.partMarkers.notna().sum())
    pm = perf.partMarkers.dropna().str.split().str.len()
    s["perf_part_markers_count_dist"] = pm.value_counts().sort_index().head(8).to_dict()
    s["perf_n_4_1_dist"] = perf.n_4_1.value_counts().to_dict()
    # does the same contract get >1 perf notice? (same tenderId + contractor NIP + value)
    key = perf.tenderId + "|" + perf.contractorNip.fillna(perf.contractorName.fillna("")) + "|" + perf.contractValue.fillna("")
    s["perf_duplicate_contract_key_rows"] = int(key.duplicated(keep=False).sum())
    s["perf_duplicate_contract_key_extra"] = int(key.duplicated().sum())
    # AU -> which contract? AU references 4.5 result notice; check resolvable
    au = pd.read_csv(os.path.join(D, "changes.csv.gz"), dtype=str)
    s["AU_4.5_resolves_TR"] = round(100 * au.resultNoticeRef.isin(bzp_by_type["TR"]).mean(), 2)
    s["AU_tender_has_CP_pct"] = round(100 * au.tenderId.isin(perf.tenderId).mean(), 2)
    with open(os.path.join(OUT, "chain_summary.json"), "w", encoding="utf-8") as fo:
        json.dump(s, fo, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(s, ensure_ascii=False, indent=1, default=str))
    print(pc.head(20).to_string())
    print(pd.read_csv(os.path.join(OUT, "perf_ref_resolution.csv")).to_string())


if __name__ == "__main__":
    main()
