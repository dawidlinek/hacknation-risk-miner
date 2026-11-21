"""e-Zamówienia / BZP notice API client (scrape.md §2 P0, §3.1; docs/research/01_bzp_api.md).

One client, two base URLs: production `https://ezamowienia.gov.pl` (default, ≤25 req/min, HTTP 403 =
rate-limited -> back off) or the HackNation mirror of the organisers' copy `https://bzp.cytr.us`
(unlimited). Select with `--opt base=https://bzp.cytr.us` (or `--opt base=mirror`).

Jobs (`--opt jobs=delta,pilot,stats[,pdf]`, default `delta,pilot,stats`):

* delta  - live delta since `--since` (default 2026-11-12, the end of the copy) to `--until` (today)
           for ContractNotice, TenderResultNotice, AgreementUpdateNotice, ContractPerformingNotice and
           NoticeUpdateNotice, for water/sewage CPV fragments. CpvCode is a substring filter, so the
           broad fragments 45231/45232/45252 are a superset of the narrow wod-kan list (452313, 452324,
           4523241, 4523242, 452321, 452524, 452521, 452522); the narrow hits are tagged client-side.
           Keyset paging with SearchAfter=<objectId of last item>; dedupe by objectId.
* pilot  - re-fetch every notice of the 22 pilot chains (data/ref/pilot_projects.json) by
           NoticeNumber (without version, so later corrections /02 show up too) from the selected base,
           plus the same notices from the mirror for comparison (`--opt compare_mirror=false` to skip),
           plus NoticeUpdateNotice (tender modifications, not in the copy) per pilot buyer (name
           substring query, NIP + tenderId filtered client-side).
* stats  - one call to /mo-board/api/v1/notice/stats per run.
* pdf    - official notice PDFs for the 22 pilot chains (GetNoticePdfById, production only).

`--only RM-2026-001,...` restricts the pilot/pdf jobs to these projects. `--limit N` caps the pages per
delta stream and the number of pilot projects. `--opt refresh=true` forces live re-fetch of cached
pilot queries (integration test).

Date params: production wants date-only (whole days, inclusive); the mirror compares strings, so it
needs a time part or the end day is excluded. `_date_params` normalises this per base.

The lead session loads notices into the `notice` table via `iter_notices(store)`; `parse()` yields
only SourceCheck records (one per pilot project per base). `iter_pdfs(store)` lists fetched PDFs.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import FetchResult, RawStore, ScrapeContext, safe_name
from riskminer.connectors.records import SourceCheck

log = logging.getLogger("riskminer.connectors.bzp_api")

SOURCE = "bzp_api"
# production: ≤25 req/min -> 2.6 s between requests; the mirror gets a per-call override.
DEFAULTS: dict[str, Any] = {"min_interval": 2.6, "timeout": 120.0}

PROD_BASE = "https://ezamowienia.gov.pl"
MIRROR_BASE = "https://bzp.cytr.us"
NOTICE_PATH = "/mo-board/api/v1/notice"
STATS_PATH = "/mo-board/api/v1/notice/stats"
PDF_PATH = "/mo-board/api/v1/Board/GetNoticePdfById"
CITE_URL = "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{}"

DELTA_TYPES = ["ContractNotice", "TenderResultNotice", "AgreementUpdateNotice", "ContractPerformingNotice",
               "NoticeUpdateNotice"]
# Narrow water/sewage CPV fragments (scrape.md §3.1) and broad ones that contain them as prefixes.
WODKAN_CPV = ["452313", "452324", "4523241", "4523242", "452321", "452524", "452521", "452522"]
BROAD_CPV = ["45231", "45232", "45252"]
NO_CPV_TYPES = {"NoticeUpdateNotice"}       # cpvCode is empty for these on production
DEFAULT_SINCE = date(2026, 11, 12)
API_2027 = date(2027, 1, 11)          # PageSize cap drops to 100, unknown params -> 404
CPV_RE = re.compile(r"\d{8}-\d")

PILOT_PATH = Path(settings().ref_dir) / "pilot_projects.json"


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def _norm_base(base: str | None) -> str:
    b = (base or settings().bzp_api_base or PROD_BASE).strip()
    if b in ("prod", "production"):
        b = PROD_BASE
    elif b in ("mirror", "copy"):
        b = settings().bzp_mirror_base or MIRROR_BASE
    if not b.startswith("http"):
        b = "https://" + b
    return b.rstrip("/")


def _is_prod(base: str) -> bool:
    return urllib.parse.urlsplit(base).netloc.endswith("ezamowienia.gov.pl")


def _host_tag(base: str) -> str:
    host = urllib.parse.urlsplit(base).netloc
    if host.endswith("ezamowienia.gov.pl"):
        return "prod" if host in ("ezamowienia.gov.pl", "www.ezamowienia.gov.pl") else safe_name(host)
    if host == urllib.parse.urlsplit(MIRROR_BASE).netloc:
        return "mirror"
    return safe_name(host)


def _to_date(v: Any, default: date) -> date:
    if v is None or v == "":
        return default
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _date_params(base: str, d_from: date, d_to: date, mode: str | None = None) -> dict[str, str]:
    """Production: date-only, whole days inclusive. Mirror/local copy: string compare -> add time part."""
    mode = mode or ("date" if _is_prod(base) else "datetime")
    if mode == "date":
        return {"PublicationDateFrom": d_from.isoformat(), "PublicationDateTo": d_to.isoformat()}
    return {"PublicationDateFrom": f"{d_from.isoformat()}T00:00:00",
            "PublicationDateTo": f"{d_to.isoformat()}T23:59:59"}


def _is_empty_list(b: bytes) -> bool:
    s = b.strip()
    return s in (b"", b"[]", b"null")


def _bool(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _list(v: Any, default: list[str]) -> list[str]:
    if v is None or v == "":
        return list(default)
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [x.strip() for x in str(v).split(",") if x.strip()]


def _get(ctx: ScrapeContext, base: str, path: str, params: dict, *, rel: str, note: str,
         ttl: Any = "default", ext: str = ".json") -> FetchResult:
    """ctx.fetch with production 403/429 back-off (403 = rate limit on prod, scrape.md §3.1)."""
    url = base + path
    mi = None if _is_prod(base) else float(ctx.opts.get("mirror_interval", 0.05))
    r: FetchResult | None = None
    for attempt in range(5):
        r = ctx.fetch(url, params=params, rel_path=rel, ext=ext, note=note, ttl=ttl, min_interval=mi,
                      empty_if=_is_empty_list if ext == ".json" else None)
        if r.cached or r.status not in ("blocked", "error") or r.http_status not in (403, 429):
            return r
        wait = 30 * (attempt + 1)
        log.warning("bzp_api: HTTP %s from %s, backing off %ss (attempt %s)", r.http_status, url, wait, attempt + 1)
        time.sleep(wait)
    assert r is not None
    return r


def _json_list(r: FetchResult) -> list[dict]:
    if r.status not in ("ok", "empty") or not r.content:
        return []
    try:
        data = json.loads(r.content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def load_pilot() -> list[dict]:
    if not PILOT_PATH.exists():
        return []
    return json.loads(PILOT_PATH.read_text(encoding="utf-8"))


def _bzp_number(number: str) -> str:
    """'2022/BZP 00058537/01' -> '2022/BZP 00058537' (query all versions)."""
    m = re.match(r"^(\d{4}/BZP \d+)", number.strip())
    return m.group(1) if m else number.strip()


def _name_stem(buyer_name: str) -> str:
    """Substring for OrganizationName (case-insensitive substring on the API); NIP filtered client-side."""
    name = re.split(r"\s[–-]\s", buyer_name)[0]
    words = [w for w in re.findall(r"[\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+", name)
             if w.lower() not in ("gmina", "miasto", "miejska", "wiejska", "i", "w", "urząd", "miejski")]
    if not words:
        return buyer_name
    if not buyer_name.lower().startswith("gmina"):
        return " ".join(words[:3])           # e.g. Wielkopolski Zarząd Dróg
    w = words[0]
    return w[:-1] if len(w) > 5 else w


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------
def run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts) -> dict:
    ctx.opts.update(opts)
    base = _norm_base(opts.get("base"))
    today = datetime.now(UTC).date()
    d_since = _to_date(since, DEFAULT_SINCE)
    d_until = _to_date(until, today)
    jobs = _list(opts.get("jobs"), ["delta", "pilot", "stats"])
    out: dict[str, Any] = {"base": base, "since": d_since.isoformat(), "until": d_until.isoformat(), "jobs": jobs}
    only_ids = set(only or [])
    if "stats" in jobs:
        if _is_prod(base) or _bool(opts.get("force_stats"), False):
            out["stats"] = _job_stats(ctx, base, d_since, d_until)
        else:
            out["stats"] = {"status": "skipped", "note": "the mirror serves only /notice (stats -> 404)"}
    if "pilot" in jobs:
        out["pilot"] = _job_pilot(ctx, base, d_until, only_ids, limit, opts)
    if "delta" in jobs:
        out["delta"] = _job_delta(ctx, base, d_since, d_until, limit, opts)
    if "pdf" in jobs:
        out["pdf"] = _job_pdf(ctx, base, only_ids, limit)
    return out


def _job_stats(ctx: ScrapeContext, base: str, d_from: date, d_to: date) -> dict:
    tag = _host_tag(base)
    params = _date_params(base, d_from, d_to)
    r = _get(ctx, base, STATS_PATH, params, rel=f"{tag}/stats_{d_from}_{d_to}.json", note="job=stats",
             ttl=timedelta(hours=1))
    res: dict[str, Any] = {"status": r.status, "http_status": r.http_status}
    if r.status == "ok":
        try:
            res["counts"] = {x.get("noticeType"): x.get("numberOfNotices") for x in r.json()}
        except (ValueError, AttributeError):
            pass
    return res


def _job_delta(ctx: ScrapeContext, base: str, d_since: date, d_until: date, limit, opts) -> dict:
    tag = _host_tag(base)
    types = _list(opts.get("types"), DELTA_TYPES)
    cpvs = _list(opts.get("cpv"), BROAD_CPV)
    window = int(opts.get("window_days", 7))
    page_size = int(opts.get("page_size", 500 if datetime.now(UTC).date() < API_2027 else 100))
    today = datetime.now(UTC).date()
    seen: set[str] = set()
    counts: dict[str, int] = {}
    pages = 0
    w_start = d_since
    while w_start <= d_until:
        w_end = min(w_start + timedelta(days=window - 1), d_until)
        # closed windows are cached forever; a window touching today is refreshed hourly
        ttl: Any = timedelta(hours=1) if w_end >= today - timedelta(days=1) else "default"
        for ntype in types:
            # NoticeUpdateNotice carries an empty cpvCode, so a CpvCode filter returns nothing: sweep all
            # of them in the window (~300/day nationally) and join to wod-kan tenders by tenderId later.
            type_cpvs = [""] if ntype in NO_CPV_TYPES and _bool(opts.get("nun_all"), True) else cpvs
            for cpv in type_cpvs:
                after: str | None = None
                n = 0
                while True:
                    n += 1
                    params: dict[str, Any] = {"NoticeType": ntype, **({"CpvCode": cpv} if cpv else {}),
                                              **_date_params(base, w_start, w_end), "PageSize": page_size}
                    if after:
                        params["SearchAfter"] = after
                    rel = f"{tag}/delta/{ntype}_cpv{cpv or 'all'}_{w_start}_{w_end}_p{n}.json"
                    r = _get(ctx, base, NOTICE_PATH, params, rel=rel,
                             note=f"job=delta type={ntype} cpv={cpv or 'all'}", ttl=ttl)
                    pages += 1
                    items = _json_list(r)
                    for it in items:
                        oid = it.get("objectId")
                        if oid and oid not in seen:
                            seen.add(oid)
                            counts[ntype] = counts.get(ntype, 0) + 1
                    if r.status not in ("ok",) or len(items) < page_size:
                        break
                    last = items[-1].get("objectId")
                    if not last or last == after:
                        break
                    after = last
                    if limit and n >= int(limit):
                        break
        w_start = w_end + timedelta(days=1)
    return {"pages": pages, "unique_notices": len(seen), "by_type": counts}


def _pilot_queries(base: str, p: dict, d_until: date) -> list[tuple[dict, dict]]:
    """(notice, params) for every notice of a pilot project."""
    out = []
    for nt in p.get("notices", []):
        d = _to_date(nt.get("date"), d_until)
        params = {"NoticeType": nt["type"], "NoticeNumber": _bzp_number(nt["number"]),
                  **_date_params(base, d - timedelta(days=2), d_until), "PageSize": 50}
        out.append((nt, params))
    return out


def _job_pilot(ctx: ScrapeContext, base: str, d_until: date, only_ids: set[str], limit, opts) -> dict:
    projects = [p for p in load_pilot() if not only_ids or p["rm_id"] in only_ids]
    if limit:
        projects = projects[: int(limit)]
    refresh = _bool(opts.get("refresh"), False)
    ttl: Any = timedelta(0) if refresh else "default"
    bases = [base]
    mirror = _norm_base("mirror")
    if _bool(opts.get("compare_mirror"), True) and base != mirror:
        bases.append(mirror)
    found = missing = 0
    for b in bases:
        tag = _host_tag(b)
        for p in projects:
            for nt, params in _pilot_queries(b, p, d_until):
                rel = f"{tag}/pilot/{p['rm_id']}/{nt['type']}_{safe_name(params['NoticeNumber'])}.json"
                r = _get(ctx, b, NOTICE_PATH, params, rel=rel, note=f"job=pilot rm_id={p['rm_id']}",
                         ttl=ttl if b == base else "default")
                hit = any(x.get("objectId") == nt.get("objectId") for x in _json_list(r))
                if b == base:
                    found += hit
                    missing += not hit
    # NoticeUpdateNotice (tender modifications) per pilot buyer, on the selected base only
    nun = 0
    if _bool(opts.get("pilot_nun"), _is_prod(base)):   # the mirror has no NoticeUpdateNotice
        tag = _host_tag(base)
        by_buyer: dict[str, list[dict]] = {}
        for p in projects:
            by_buyer.setdefault(p["buyer_nip"], []).append(p)
        for nip, ps in by_buyer.items():
            stem = _name_stem(ps[0]["buyer_name"])
            d0 = min(_to_date(n.get("date"), d_until) for p in ps for n in p.get("notices", [])) - timedelta(days=365)
            after = None
            n = 0
            while True:
                n += 1
                params: dict[str, Any] = {"NoticeType": "NoticeUpdateNotice", "OrganizationName": stem,
                                          **_date_params(base, d0, d_until), "PageSize": 500}
                if after:
                    params["SearchAfter"] = after
                rel = f"{tag}/pilot_nun/{nip}_{safe_name(stem)}_p{n}.json"
                r = _get(ctx, base, NOTICE_PATH, params, rel=rel, note=f"job=pilot_nun nip={nip}", ttl=ttl)
                items = _json_list(r)
                nun += sum(1 for x in items if _digits(x.get("organizationNationalId")) == nip)
                if r.status != "ok" or len(items) < 500 or n >= 10:
                    break
                after = items[-1].get("objectId")
    return {"projects": len(projects), "bases": bases, "notices_found": found, "notices_missing": missing,
            "nun_for_buyer_nips": nun}


def _job_pdf(ctx: ScrapeContext, base: str, only_ids: set[str], limit) -> dict:
    if not _is_prod(base):
        base = PROD_BASE          # the mirror has no PDF endpoint
    projects = [p for p in load_pilot() if not only_ids or p["rm_id"] in only_ids]
    if limit:
        projects = projects[: int(limit)]
    ok = bad = 0
    for p in projects:
        for nt in p.get("notices", []):
            oid = nt.get("objectId")
            if not oid:
                continue
            r = _get(ctx, base, PDF_PATH, {"noticeId": oid}, rel=f"prod/pdf/{p['rm_id']}/{oid}.pdf",
                     note=f"job=pdf rm_id={p['rm_id']} number={nt.get('number')}", ext=".pdf")
            if r.status == "ok":
                ok += 1
            else:
                bad += 1
    return {"pdf_ok": ok, "pdf_not_ok": bad}


def _digits(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


# ---------------------------------------------------------------------------------------------
# raw -> records (no network)
# ---------------------------------------------------------------------------------------------
def _notice_entries(store: RawStore) -> list[dict]:
    out = []
    for e in store.entries():
        if e.get("status") not in ("ok", "empty") or not e.get("path"):
            continue
        if not str(e.get("url", "")).endswith(NOTICE_PATH):
            continue
        out.append(e)
    return out


def _load_entry(store: RawStore, e: dict) -> list[dict]:
    p = store.abs(e["path"])
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_bytes() or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _entry_is_prod(e: dict) -> bool:
    return urllib.parse.urlsplit(e.get("url", "")).netloc.endswith("ezamowienia.gov.pl")


_COPY_TENDERS: set[str] | None = None


def copy_tender_ids() -> set[str]:
    """tenderIds of the organisers' offline copy (wod-kan works only); empty set if the file is absent."""
    global _COPY_TENDERS
    if _COPY_TENDERS is None:
        ids: set[str] = set()
        p = Path(settings().bzp_copy_path)
        if p.exists():
            rx = re.compile(rb'"tenderId":\s*"([^"]+)"')
            with p.open("rb") as fh:
                for line in fh:
                    m = rx.search(line, 0, 4000)
                    if m:
                        ids.add(m.group(1).decode())
        _COPY_TENDERS = ids
    return _COPY_TENDERS


def iter_notices(store: RawStore, *, wodkan_only: bool = True) -> Iterator[tuple[dict, str, str]]:
    """Every unique objectId in the raw notice pages -> (record, raw_path, raw_sha256).

    Latest fetch wins; production fetches win over mirror fetches of the same objectId.
    Added fields (prefixed '_', not API fields): `_cite_url` (SPA link), `_api_base`, `_job`
    (delta|pilot|pilot_nun), `_wodkan_cpv` (narrow wod-kan CPV fragments found in cpvCode).

    With wodkan_only (default) two kinds of over-broad pages are filtered client-side:
    * pilot_nun pages (buyer-name substring query) -> only records of the 20 pilot buyer NIPs;
    * NoticeUpdateNotice pages (delta sweep without CPV filter, pilot_nun) -> only records whose tenderId
      belongs to a wod-kan tender: one seen in the other raw pages or in the offline copy (bzp_copy_path).
    """
    entries = sorted(_notice_entries(store), key=lambda e: (_entry_is_prod(e), e.get("fetched_at", "")))
    pilot_nips = {p["buyer_nip"] for p in load_pilot()}
    best: dict[str, tuple[dict, str, str]] = {}
    nun_all: list[tuple[dict, str, str]] = []
    for e in entries:
        u = urllib.parse.urlsplit(e.get("url", ""))
        note = e.get("note") or ""
        job = note.split()[0][4:] if note.startswith("job=") else ""
        sweep = (job == "delta" and "cpv=all" in note) or job == "pilot_nun"
        for rec in _load_entry(store, e):
            oid = rec.get("objectId")
            if not oid:
                continue
            if wodkan_only and job == "pilot_nun" and _digits(rec.get("organizationNationalId")) not in pilot_nips:
                continue
            rec = dict(rec)
            rec["_cite_url"] = CITE_URL.format(oid)
            rec["_api_base"] = f"{u.scheme}://{u.netloc}"
            rec["_job"] = job
            rec["_wodkan_cpv"] = wodkan_cpv_hits(rec.get("cpvCode"))
            item = (rec, e["path"], e.get("sha256") or "")
            if wodkan_only and sweep:
                nun_all.append(item)
            else:
                best[oid] = item
    if nun_all:
        tenders = {r.get("tenderId") for r, _, _ in best.values()} | copy_tender_ids()
        for item in nun_all:
            oid = item[0]["objectId"]
            if item[0].get("tenderId") in tenders and oid not in best:
                best[oid] = item
    yield from best.values()


def iter_pdfs(store: RawStore) -> Iterator[dict]:
    """Fetched official notice PDFs: {objectId, rm_id, raw_path, raw_sha256, url, cite_url}."""
    seen: dict[str, dict] = {}
    for e in store.entries():
        if e.get("status") != "ok" or not str(e.get("url", "")).endswith(PDF_PATH):
            continue
        oid = (e.get("params") or {}).get("noticeId")
        m = re.search(r"rm_id=(\S+)", e.get("note") or "")
        seen[oid] = {"objectId": oid, "rm_id": m.group(1) if m else None, "raw_path": e.get("path"),
                     "raw_sha256": e.get("sha256"), "url": e.get("url") + "?noticeId=" + str(oid),
                     "cite_url": CITE_URL.format(oid)}
    yield from seen.values()


def wodkan_cpv_hits(cpv_string: str | None) -> list[str]:
    """Narrow wod-kan fragments that prefix any CPV code in the notice's cpvCode string."""
    codes = CPV_RE.findall(cpv_string or "")
    return sorted({f for f in WODKAN_CPV for c in codes if c.startswith(f)})


def _norm_html(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


COMPARE_FIELDS = ["noticeType", "noticeNumber", "bzpNumber", "tenderId", "publicationDate", "orderObject",
                  "organizationNationalId", "organizationName", "cpvCode", "procedureResult"]


def _diff(a: dict, b: dict) -> list[str]:
    d = [f for f in COMPARE_FIELDS if (a.get(f) or None) != (b.get(f) or None)]
    if _norm_html(a.get("htmlBody")) != _norm_html(b.get("htmlBody")):
        d.append("htmlBody")
    return d


def parse(store: RawStore) -> Iterable[SourceCheck]:
    """One SourceCheck per pilot project per API base (production = integration test)."""
    projects = load_pilot()
    if not projects:
        return
    # (host_tag, rm_id) -> {objectId: (record, entry)}; plus list of entries per (tag, rm_id)
    pilot: dict[tuple[str, str], dict[str, tuple[dict, dict]]] = {}
    status: dict[tuple[str, str], list[dict]] = {}
    nun_by_tag: dict[str, list[tuple[dict, dict]]] = {}
    any_by_tag: dict[str, dict[str, tuple[dict, dict]]] = {}
    for e in store.entries():
        note = e.get("note") or ""
        if not str(e.get("url", "")).endswith(NOTICE_PATH):
            continue
        u = urllib.parse.urlsplit(e["url"])
        tag = _host_tag(f"{u.scheme}://{u.netloc}")
        if note.startswith("job=pilot rm_id="):
            rm = note.split("rm_id=", 1)[1].split()[0]
            status.setdefault((tag, rm), []).append(e)
            if e.get("status") in ("ok", "empty") and e.get("path"):
                slot = pilot.setdefault((tag, rm), {})
                for rec in _load_entry(store, e):
                    if rec.get("objectId"):
                        slot[rec["objectId"]] = (rec, e)
        elif note.startswith("job=pilot_nun") and e.get("status") == "ok" and e.get("path"):
            for rec in _load_entry(store, e):
                nun_by_tag.setdefault(tag, []).append((rec, e))
                any_by_tag.setdefault(tag, {})[rec.get("objectId")] = (rec, e)
    tags = sorted({t for t, _ in status})
    for tag in tags:
        other = "mirror" if tag != "mirror" else None
        for p in projects:
            rm = p["rm_id"]
            entries = status.get((tag, rm))
            if not entries:
                continue
            got = pilot.get((tag, rm), {})
            exp_all = p.get("notices", [])
            # the mirror (offline copy) holds only the 4 copy types: other types are not applicable there
            exp = [n for n in exp_all if tag != "mirror" or n.get("type") not in NO_CPV_TYPES]
            if len(exp) < len(exp_all):
                notes_na = f"{len(exp_all) - len(exp)} NoticeUpdateNotice not applicable (not in the copy)"
            else:
                notes_na = ""
            found_ids, missing, notes = [], [], []
            last_path = None
            for nt in exp:
                oid = nt.get("objectId")
                hit = got.get(oid) or any_by_tag.get(tag, {}).get(oid)
                if hit:
                    found_ids.append(oid)
                    rec, e = hit
                    last_path = e.get("path")
                    if rec.get("noticeNumber") != nt.get("number"):
                        notes.append(f"{nt['number']}: API number {rec.get('noticeNumber')}")
                    if other and (other, rm) in pilot and oid in pilot[(other, rm)]:
                        dif = _diff(rec, pilot[(other, rm)][oid][0])
                        if dif:
                            notes.append(f"{nt['number']} differs from {other} in: {','.join(dif)}")
                else:
                    missing.append(nt.get("number"))
            # other versions / notices returned for the same numbers (corrections)
            exp_ids = {n.get("objectId") for n in exp}
            extra = sorted({r.get("noticeNumber") for oid, (r, _) in got.items()
                            if oid not in exp_ids and r.get("tenderId") == p.get("tender_id")})
            if extra:
                notes.append("additional versions/notices for the same numbers: " + ", ".join(extra))
            nun = sorted({r.get("noticeNumber") for r, _ in nun_by_tag.get(tag, [])
                          if r.get("tenderId") == p.get("tender_id")})
            nun_ids = sorted({r.get("objectId") for r, _ in nun_by_tag.get(tag, [])
                              if r.get("tenderId") == p.get("tender_id")})
            if tag in nun_by_tag:
                notes.append(f"NoticeUpdateNotice for tenderId: {len(nun)}" + (f" ({', '.join(nun)})" if nun else ""))
            if missing:
                notes.append("not returned by API: " + ", ".join(missing))
            if notes_na:
                notes.append(notes_na)
            sts = {e.get("status") for e in entries}
            if found_ids and not missing:
                result = "found"
            elif found_ids:
                result = "partial"
            elif sts & {"blocked"} and not sts & {"ok", "empty"}:
                result = "blocked"
            elif sts <= {"error"}:
                result = "error"
            else:
                result = "not_found"
            checked = max((e.get("fetched_at") for e in entries), default=None)
            base_url = {"prod": PROD_BASE, "mirror": MIRROR_BASE}.get(tag, tag)
            yield SourceCheck(
                source=SOURCE, subject_type="project", subject_key=rm,
                query={"base": base_url, "tender_id": p.get("tender_id"),
                       "notice_numbers": [n.get("number") for n in exp]},
                n_hits=len(got), n_relevant=len(found_ids), result=result,
                matched_ids=found_ids + nun_ids,
                note=(f"{tag}: {len(found_ids)}/{len(exp)} chain notices re-fetched by NoticeNumber"
                      + ("; identical to mirror copy" if other and (other, rm) in pilot and not any(
                          'differs' in x for x in notes) and found_ids else "")
                      + ("; " + "; ".join(notes) if notes else "")),
                checked_at=datetime.strptime(checked, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) if checked else None,
                raw_path=last_path,
            )
