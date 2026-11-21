"""docs_sample: procurement documents for the national sample (docs/scrape.md §4, data/ref/doc_sample.csv).

Same pipeline, document set, evidence states and size caps as docs_22 (riskminer.connectors.docs_22 +
platforms.py); differences:
  * subject_type="procedure", subject_key=OCID; every record carries stratum / reason / metric in `data`
  * the CSV gives the buyer's platform profile (e.g. https://<buyer>.ezamawiajacy.pl) - the procedure is
    found there by its reference number (from e-Zamówienia GetTender) or, failing that, by title
  * breadth first: default download scope is "priority" (SWZ/PFU/PPU/OPZ/Q&A, then kwota/otwarcie/wybor/
    changes; no archives). A second run with `--opt download="all"` fetches the rest up to the size cap.
  * procedures are processed by a few worker threads, one worker per platform host (Marketplanet download
    tokens are bound to the HTTP session, so one host is never driven by two threads at once).

run:   uv run riskminer scrape docs_sample --no-db [--only <ocid,...>] [--limit N] [--opt download="all"]
parse: uv run riskminer parse docs_sample
"""
from __future__ import annotations

import csv
import logging
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from riskminer.config import settings
from riskminer.connectors import docs_22 as D
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import DocumentRecord, SourceCheck

log = logging.getLogger("riskminer.docs_sample")

SOURCE = "docs_sample"
DEFAULTS = {"min_interval": 1.0, "timeout": 300.0}
EXTRA_FIELDS = ("stratum", "reason", "metric", "subsector_main", "province", "buyer_nip", "platform_rank")


def _rows() -> list[dict]:
    with (settings().ref_dir / "doc_sample.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _clean_title(t: str) -> str:
    t = re.sub(r'^[\s"„”“]+|[\s"„”“]+$', "", t or "")
    return re.sub(r"\s+", " ", t.replace('""', '"'))


def _subject(row: dict) -> dict:
    """doc_sample row -> the pilot-project-shaped dict the docs_22 pipeline expects."""
    cn = (row.get("contract_notice_no") or "").strip()
    return {
        "rm_id": row["ocid"], "tender_id": row["ocid"], "title": _clean_title(row.get("title", "")),
        "platform_urls": [u for u in [(row.get("platform_url") or "").strip()] if u],
        "buyer_name": row.get("buyer_name"),
        "notices": [{"type": "ContractNotice", "number": cn}] if cn else [],
    }


def _extra(row: dict) -> dict:
    d: dict[str, Any] = {k: row.get(k) for k in EXTRA_FIELDS}
    try:
        d["metric"] = float(d["metric"]) if d.get("metric") not in (None, "") else None
    except ValueError:
        pass
    d["sample_design_build"] = (row.get("design_build") or "").strip().lower() == "true"
    return d


def run(ctx: ScrapeContext, *, since: str | None = None, until: str | None = None, limit: int | None = None,
        only: list[str] | None = None, **opts: Any) -> dict:
    rows = _rows()
    if only:
        want = {x.strip() for x in only}
        rows = [r for r in rows if r["ocid"] in want or r.get("stratum") in want]
    if limit:
        rows = rows[: int(limit)]
    popts = {"download": opts.get("download", "priority"), "size_cap": int(opts.get("size_cap", D.SIZE_CAP))}
    workers = max(1, int(opts.get("workers", 3)))
    idx = D._Index(ctx.store.entries())
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[urllib.parse.urlsplit(r.get("platform_url") or "").netloc or "-"].append(r)
    out: dict[str, Any] = {"procedures": len(rows), "hosts": len(groups), "download": popts["download"],
                           "per_procedure": {}}

    def work(group: list[dict]) -> dict:
        res = {}
        for r in group:
            subj = _subject(r)
            try:
                res[r["ocid"]] = D._process(ctx, subj, idx, popts)
            except Exception as e:  # noqa: BLE001 - one procedure must not stop the run
                log.exception("docs_sample %s failed", r["ocid"])
                ctx.record(f"sample:{r['ocid']}", "error", note=D._note(rm=r["ocid"], role="project") +
                           f" {type(e).__name__}: {e}"[:400])
                res[r["ocid"]] = {"error": f"{type(e).__name__}: {e}"[:300]}
        return res

    # biggest groups first so the run is not dominated by one long tail
    ordered = sorted(groups.values(), key=len, reverse=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, g) for g in ordered]
        for f in as_completed(futs):
            out["per_procedure"].update(f.result())
    agg: dict[str, int] = defaultdict(int)
    for st in out["per_procedure"].values():
        for k in ("listed", "downloaded", "blocked", "errors"):
            agg[k] += int(st.get(k) or 0)
        agg[f"platform:{st.get('platform')}"] += 1
        if st.get("page_status"):
            agg[f"page:{st['page_status']}"] += 1
    out["totals"] = dict(agg)
    if not opts.get("verbose"):
        out.pop("per_procedure")
    return out


def parse(store: RawStore) -> Iterable[DocumentRecord | SourceCheck]:
    idx = D._Index(store.entries())
    for row in _rows():
        yield from D._parse_project(_subject(row), idx, source=SOURCE, subject_type="procedure",
                                    extra_data=_extra(row), design_build_hint=_extra(row)["sample_design_build"])
