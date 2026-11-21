"""BZP live API slice for ROADS (CPV 45233*) 2024-2026, for the W9 "sector pack in 60 s" demo (docs/scrape.md §2 P3).

Same e-Zamówienia notice API and helpers as `bzp_api` (imported, not copied): production
`https://ezamowienia.gov.pl` (<=25 req/min -> min_interval 2.6 s, HTTP 403/429 back-off in bzp_api._get).
Notice types: ContractPerformingNotice + AgreementUpdateNotice by default (see TYPES for the volume
measurement), `--opt types=all` adds ContractNotice + TenderResultNotice; CpvCode=45233 (substring filter:
any notice listing a 45233xxx-x road-works code), monthly windows, keyset paging by SearchAfter.
NoticeUpdateNotice carries an empty cpvCode on production, so a CPV filter returns nothing; a national sweep
(~300/day) is out of scope for this slice -> `--opt nun=true` sweeps them anyway (expensive), default off.

Every manifest note starts with "sector=drogi". `iter_notices(store)` yields (record, raw_path, sha256), one per
objectId (latest fetch wins), records tagged `_sector="drogi"`; parse() yields only SourceCheck records
(one per pilot buyer: road notices of that buyer NIP in the slice).
Options: --since/--until (default 2024-01-01 .. today), --opt window_days=31, --opt types=..., --opt cpv=45233,
--opt base=mirror (mirror holds only the wod-kan copy, so production is the default), --limit N (pages per stream).
"""
from __future__ import annotations

import logging
import urllib.parse
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from riskminer.connectors import bzp_api
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import SourceCheck

log = logging.getLogger("riskminer.connectors.bzp_roads")

SOURCE = "bzp_roads"
DEFAULTS = {"min_interval": 2.6}

SECTOR = "drogi"
ROAD_CPV = ["45233"]
ALL_TYPES = ["ContractNotice", "TenderResultNotice", "AgreementUpdateNotice", "ContractPerformingNotice"]
# Default = the outcome/change notices only. Measured 2026-11-21: CPV 45233* is far larger than expected
# (per month ~1,600 CN / 60 MB, ~1,700 TRN / 28 MB, ~1,300 CPN / 17 MB, ~160 AUN), i.e. ~170k notices / ~4 GB
# for all 4 types 2024-2026. CPN (final value, dates, changes) + AUN (modifications) ~ 50k notices / ~0.6 GB.
# `--opt types=all` (or an explicit list) fetches the rest.
TYPES = ["ContractPerformingNotice", "AgreementUpdateNotice"]
DEFAULT_SINCE = date(2024, 1, 1)


def run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts: Any) -> dict:
    base = bzp_api._norm_base(opts.get("base") or bzp_api.PROD_BASE)
    tag = bzp_api._host_tag(base)
    today = datetime.now(UTC).date()
    d_since = bzp_api._to_date(since, DEFAULT_SINCE)
    d_until = bzp_api._to_date(until, today)
    types = (ALL_TYPES if str(opts.get("types", "")).lower() == "all"
             else bzp_api._list(opts.get("types"), TYPES))
    if bzp_api._bool(opts.get("nun"), False):
        types = [*types, "NoticeUpdateNotice"]
    cpvs = bzp_api._list(opts.get("cpv"), ROAD_CPV)
    window = int(opts.get("window_days", 31))
    page_size = int(opts.get("page_size", 500 if today < date(2027, 1, 11) else 100))
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    pages = 0
    w_start = d_since
    while w_start <= d_until:
        w_end = min(w_start + timedelta(days=window - 1), d_until)
        ttl: Any = timedelta(hours=1) if w_end >= today - timedelta(days=1) else "default"
        for ntype in types:
            for cpv in ([""] if ntype in bzp_api.NO_CPV_TYPES else cpvs):
                after: str | None = None
                n = 0
                while True:
                    n += 1
                    params: dict[str, Any] = {"NoticeType": ntype, **({"CpvCode": cpv} if cpv else {}),
                                              **bzp_api._date_params(base, w_start, w_end), "PageSize": page_size}
                    if after:
                        params["SearchAfter"] = after
                    rel = f"{tag}/{ntype}_cpv{cpv or 'all'}_{w_start}_{w_end}_p{n}.json"
                    r = bzp_api._get(ctx, base, bzp_api.NOTICE_PATH, params, rel=rel, ttl=ttl,
                                     note=f"sector={SECTOR} job=roads type={ntype} cpv={cpv or 'all'}")
                    pages += 1
                    items = bzp_api._json_list(r)
                    for it in items:
                        oid = it.get("objectId")
                        if oid and oid not in seen:
                            seen.add(oid)
                            counts[ntype] += 1
                    if r.status != "ok" or len(items) < page_size:
                        break
                    last = items[-1].get("objectId")
                    if not last or last == after or (limit and n >= int(limit)):
                        break
                    after = last
        w_start = w_end + timedelta(days=1)
    return {"pages": pages, "unique_notices": len(seen), "by_type": dict(counts), "since": str(d_since),
            "until": str(d_until), "sector": SECTOR}


# ---------------------------------------------------------------------------------------------
def iter_notices(store: RawStore) -> Iterator[tuple[dict, str, str]]:
    """Every unique objectId in the raw road pages -> (record, raw_path, raw_sha256); latest fetch wins."""
    entries = sorted(bzp_api._notice_entries(store), key=lambda e: e.get("fetched_at", ""))
    best: dict[str, tuple[dict, str, str]] = {}
    for e in entries:
        u = urllib.parse.urlsplit(e.get("url", ""))
        for rec in bzp_api._load_entry(store, e):
            oid = rec.get("objectId")
            if not oid:
                continue
            rec = dict(rec)
            rec["_cite_url"] = bzp_api.CITE_URL.format(oid)
            rec["_api_base"] = f"{u.scheme}://{u.netloc}"
            rec["_job"] = "roads"
            rec["_sector"] = SECTOR
            rec["_road_cpv"] = [c for c in bzp_api.CPV_RE.findall(rec.get("cpvCode") or "") if c.startswith("45233")]
            best[oid] = (rec, e["path"], e.get("sha256") or "")
    yield from best.values()


def parse(store: RawStore) -> Iterable[SourceCheck]:
    by_nip: dict[str, list[str]] = {}
    n = 0
    last_fetch = None
    for rec, _path, _sha in iter_notices(store):
        n += 1
        nip = bzp_api._digits(rec.get("organizationNationalId"))
        by_nip.setdefault(nip, []).append(rec["objectId"])
    for e in bzp_api._notice_entries(store):
        last_fetch = max(last_fetch or "", e.get("fetched_at", ""))
    checked = datetime.strptime(last_fetch, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if last_fetch else None
    seen: set[str] = set()
    for p in bzp_api.load_pilot():
        nip = p.get("buyer_nip")
        if not nip or nip in seen:
            continue
        seen.add(nip)
        hits = by_nip.get(nip, [])
        yield SourceCheck(
            source=SOURCE, subject_type="organization", subject_key=nip,
            query={"sector": SECTOR, "cpv": "45233*", "types": TYPES, "from": str(DEFAULT_SINCE)},
            n_hits=len(hits), n_relevant=len(hits), result="found" if hits else "not_found",
            matched_ids=hits[:200], checked_at=checked,
            note=f"{len(hits)} road (CPV 45233*) notices of this buyer among {n} in the BZP roads slice")
