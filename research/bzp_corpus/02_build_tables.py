"""
02_build_tables.py - one streaming pass over notices.jsonl -> normalised tables (gzipped CSV).

  data/notice_index.csv.gz       every notice: ids, type, version, tenderId, date, org, CPV, title,
                                 n parts, refs to other notices (for chaining)
  data/perf.csv.gz               ContractPerformingNotice -> 1 row per notice (= per contract)
  data/perf_changes.csv.gz       change blocks 5.4.2-5.4.8 embedded in performance notices
  data/changes.csv.gz            AgreementUpdateNotice -> 1 row per notice
  data/results.csv.gz            TenderResultNotice -> 1 row per lot
  data/contract_notices.csv.gz   ContractNotice -> 1 row per lot (long texts trimmed)

Run: python3 -I 02_build_tables.py [notices.jsonl]   (~1 min with 10 processes)
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import sys
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bzp_parse as bp  # noqa: E402

DEFAULT = os.path.join(HERE, "../../materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl")
DATA = os.path.join(HERE, "data")

TRIM = 1500  # trim long free-text fields in CSV


def _trim(v, n=TRIM):
    if isinstance(v, str) and len(v) > n:
        return v[:n] + " […]"
    return v


def work(line: str):
    rec = json.loads(line)
    t = rec["noticeType"]
    pn = bp.parse_html(rec.get("htmlBody", ""))
    f = pn.as_dict()
    out = {"type": t}
    # ---- index row (all types) -------------------------------------------------------
    idx = bp._common(rec)
    refs = {}
    if t == "ContractPerformingNotice":
        refs = {"refContractNotice": f.get("3.2.1"), "refResultNotice": f.get("4.5")}
    elif t == "AgreementUpdateNotice":
        refs = {"refContractNotice": f.get("3.1.1"), "refResultNotice": f.get("4.5"), "refEarlierChange": f.get("5.7")}
    elif t == "TenderResultNotice":
        refs = {"refContractNotice": f.get("2.14"), "refPreviousProcedure": f.get("3.1.2")}
    idx.update({
        "templateVersion": pn.template_version,
        "nEntries": len(pn.entries),
        "partMarkers": " ".join(map(str, pn.part_markers)),
        "n_4_1": sum(1 for e in pn.entries if e.code == "4.1"),
        "n_5_5": sum(1 for e in pn.entries if e.code == "5.5"),
        "n_8_1": sum(1 for e in pn.entries if e.code == "8.1"),
        "nContractors": len(rec.get("contractors") or []),
        **{k: (bp.notice_no(v).get("bzp") or bp.notice_no(v).get("ted") or (v or "")[:60] or None) for k, v in refs.items()},
    })
    out["index"] = {k: _trim(v, 300) for k, v in idx.items()}
    # ---- typed rows ------------------------------------------------------------------
    if t == "ContractPerformingNotice":
        r = bp.extract_performance(rec, pn)
        ch = r.pop("changes")
        r["partMarkers"] = idx["partMarkers"]
        r["n_4_1"] = idx["n_4_1"]
        r["changeBases"] = " ".join(c["basis"] or "?" for c in ch)
        r["changeValueSum"] = sum(c["value_change"] or 0 for c in ch) if ch else None
        r["anyPriceIncrease"] = any(c["price_increase"] for c in ch) if ch else None
        out["perf"] = {k: _trim(v) for k, v in r.items()}
        out["perf_changes"] = [{"objectId": r["objectId"], "tenderId": r["tenderId"], "noticeNumber": r["noticeNumber"],
                                "contractValue": r["contractValue"], "idx": i + 1,
                                **{k: _trim(v) for k, v in c.items()}} for i, c in enumerate(ch)]
    elif t == "AgreementUpdateNotice":
        r = bp.extract_change(rec, pn)
        r["partMarkers"] = idx["partMarkers"]
        out["changes"] = {k: _trim(v, 4000) for k, v in r.items()}
    elif t == "TenderResultNotice":
        out["results"] = [{k: _trim(v, 600) for k, v in r.items()} for r in bp.extract_result(rec, pn)]
    elif t == "ContractNotice":
        out["contract_notices"] = [{k: _trim(v, 600) for k, v in r.items()} for r in bp.extract_contract_notice(rec, pn)]
    return out


class GzCsv:
    def __init__(self, path):
        self.fh = gzip.open(path, "wt", encoding="utf-8", newline="")
        self.w = None

    def write(self, row: dict):
        if self.w is None:
            self.w = csv.DictWriter(self.fh, fieldnames=list(row.keys()), extrasaction="ignore")
            self.w.writeheader()
        self.w.writerow(row)

    def close(self):
        self.fh.close()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    os.makedirs(DATA, exist_ok=True)
    names = ["index", "perf", "perf_changes", "changes", "results", "contract_notices"]
    files = {n: GzCsv(os.path.join(DATA, ("notice_index" if n == "index" else n) + ".csv.gz")) for n in names}
    counts = {n: 0 for n in names}
    with open(path, encoding="utf-8") as fh, Pool(max(1, os.cpu_count() - 2)) as pool:
        for out in pool.imap(work, fh, chunksize=32):
            for n in names:
                v = out.get(n)
                if v is None:
                    continue
                rows = v if isinstance(v, list) else [v]
                for row in rows:
                    files[n].write(row)
                    counts[n] += 1
    for f in files.values():
        f.close()
    print(counts)


if __name__ == "__main__":
    main()
