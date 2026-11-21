"""docs_22: procurement documents for the 22 pilot projects (docs/scrape.md §2 row docs_22, §4).

run():   per pilot project (data/ref/pilot_projects.json)
           1. e-Zamówienia public read API: GetTender + GetTenderDocuments for the OCID (evidence of where
              the procedure is run: `isProceedingOnPlatform`, referenceNumber used for profile searches)
           2. the procedure page on its platform (URL from ContractNotice 3.1/3.5; buyer-profile URLs are
              searched for the procedure by its reference number / title)
           3. every listed attachment: downloaded when robots.txt allows it, otherwise a `blocked`
              manifest line with the robots rule; ZIPs are stored, listed, and their text documents
              extracted (cap SIZE_CAP bytes per procedure); text via pdftotext / docx-xml / openpyxl / soffice
parse(): re-derives DocumentRecords + one SourceCheck per project from data/raw/docs_22 only.

Manifest `note` convention (machine-readable, space separated): "docs_22 rm=<rm_id> role=<role> key=<k> ..."
roles: ezgov_tender, ezgov_docs, robots, page, folder, profile, file, text, ziplist, member.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import urllib.parse
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors import platforms as P
from riskminer.connectors.base import RawStore, ScrapeContext, safe_name
from riskminer.connectors.records import DocumentRecord, SourceCheck

log = logging.getLogger("riskminer.docs_22")

SOURCE = "docs_22"
DEFAULTS = {"min_interval": 1.0, "timeout": 300.0}

HOST_INTERVAL = {"platformazakupowa.pl": 1.5, "www.platformazakupowa.pl": 1.5, "ezamowienia.gov.pl": 2.5}
SIZE_CAP = 200_000_000          # downloaded bytes per procedure
MEMBER_CAP = 60_000_000         # max size of one archive member we extract
MAX_MEMBERS = 400               # text members extracted per archive
EZ_TENDER = "https://ezamowienia.gov.pl/mp-readmodels/api/Search/GetTender"
EZ_DOCS = "https://ezamowienia.gov.pl/mp-readmodels/api/Search/GetTenderDocuments"

# Extra platform URLs found by hand when the pilot list has none (provenance in the note).
HINTS: dict[str, list[tuple[str, str]]] = {
    "RM-2026-022": [(
        "https://gminawolin.ezamawiajacy.pl",
        "buyer platform of Gmina Wolin per BZP ContractNotice 2023/BZP 00181538/01 and TenderResultNotice "
        "2023/BZP 00232972/01 of the same buyer; the ContractNotice of this procedure is not in the BZP copy",
    )],
}

EXPECTED_ALL = ["swz", "pfu", "projekt", "przedmiar", "stwiorb", "ppu", "qa", "kwota", "otwarcie", "wybor"]


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def _note(**kw: Any) -> str:
    parts = ["docs_22"]
    for k, v in kw.items():
        if v is None or v == "":
            continue
        parts.append(k + "=" + re.sub(r"\s+", "_", str(v)))
    return " ".join(parts)


def _pnote(note: str | None) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", note or ""))


def _pilot() -> list[dict]:
    return json.loads((settings().ref_dir / "pilot_projects.json").read_text(encoding="utf-8"))


def _cn(p: dict) -> dict:
    for n in p.get("notices") or []:
        if n.get("type") == "ContractNotice":
            return n
    return {}


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc.lower()


def _interval(url: str) -> float | None:
    return HOST_INTERVAL.get(_host(url))


def _abs_path(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else settings().raw_dir.parent.parent / p


class _Index:
    """Manifest lines of this source grouped by (rm, role, key) and by URL (last line wins)."""

    def __init__(self, entries: list[dict]):
        self.by_key: dict[tuple[str, str, str], dict] = {}
        self.by_rm: dict[str, list[dict]] = defaultdict(list)
        self.robots: dict[str, dict] = {}
        for e in entries:
            n = _pnote(e.get("note"))
            e["_n"] = n
            rm = n.get("rm")
            if n.get("role") == "robots" and e.get("status") == "ok":
                self.robots[n.get("host", "")] = e
            if not rm:
                continue
            self.by_rm[rm].append(e)
            if n.get("key"):
                self.by_key[(rm, n.get("role", ""), n["key"])] = e

    def add(self, e: dict) -> None:
        n = _pnote(e.get("note"))
        e["_n"] = n
        rm = n.get("rm")
        if rm:
            self.by_rm[rm].append(e)
            if n.get("key"):
                self.by_key[(rm, n.get("role", ""), n["key"])] = e

    def get(self, rm: str, role: str, key: str, ok_only: bool = True) -> dict | None:
        e = self.by_key.get((rm, role, key))
        if e is None:
            return None
        if ok_only:
            if e.get("status") != "ok":
                return None
            p = _abs_path(e.get("path"))
            if p is None or not p.exists():
                return None
        return e


# ---------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------

_ROBOTS: dict[str, list[tuple[bool, str]]] = {}


def _robots(ctx: ScrapeContext, url: str) -> list[tuple[bool, str]]:
    if ctx.override_for(url):     # operator-approved host: robots.txt not applied (still rate-limited, tagged)
        return []
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin in _ROBOTS:
        return _ROBOTS[origin]
    r = ctx.fetch(origin + "/robots.txt", rel_path=f"_robots/{safe_name(parts.netloc)}.txt",
                  note=_note(role="robots", host=parts.netloc), check_blocked=False, min_interval=_interval(url),
                  ttl=timedelta(hours=12), accept_status=(200, 404, 410))
    txt = ""
    if r.ok and r.http_status == 200 and r.content and "html" not in (r.content_type or "") \
            and len(r.content) < 500_000:
        txt = r.text()
    _ROBOTS[origin] = P.robots_rules(txt)
    return _ROBOTS[origin]


def run(ctx: ScrapeContext, *, since: str | None = None, until: str | None = None, limit: int | None = None,
        only: list[str] | None = None, **opts: Any) -> dict:
    projects = _pilot()
    if only:
        want = {x.strip() for x in only}
        projects = [p for p in projects if p["rm_id"] in want]
    if since or until:
        projects = [p for p in projects if (not since or (_cn(p).get("date") or "9999") >= since)
                    and (not until or (_cn(p).get("date") or "0000") <= until)]
    if limit:
        projects = projects[: int(limit)]
    idx = _Index(ctx.store.entries())
    out: dict[str, Any] = {"projects": len(projects), "per_project": {}}
    for p in projects:
        try:
            out["per_project"][p["rm_id"]] = _process(ctx, p, idx, opts)
        except Exception as e:  # noqa: BLE001 - one project must not stop the run
            log.exception("docs_22 %s failed", p["rm_id"])
            ctx.record(f"pilot:{p['rm_id']}", "error", note=_note(rm=p["rm_id"], role="project") +
                       f" {type(e).__name__}: {e}"[:400])
            out["per_project"][p["rm_id"]] = {"error": f"{type(e).__name__}: {e}"[:300]}
    return out


def _process(ctx: ScrapeContext, p: dict, idx: _Index, opts: dict) -> dict:
    rm, ocid = p["rm_id"], p.get("tender_id")
    st: dict[str, Any] = {"platform": None, "listed": 0, "downloaded": 0, "blocked": 0, "errors": 0}
    log.info("docs_22 %s %s", rm, (p.get("title") or "")[:60])

    # 1. e-Zamówienia read API (public)
    tender: dict = {}
    if ocid:
        r = ctx.fetch(EZ_TENDER, params={"id": ocid}, rel_path=f"{rm}/ezamowienia_GetTender.json",
                      note=_note(rm=rm, role="ezgov_tender", platform="ezamowienia"), min_interval=2.5)
        if r.ok:
            try:
                tender = P.parse_ezamowienia_tender(r.json())
            except ValueError:
                tender = {}
        # documents list only when the procedure may run on e-Zamówienia (opts ezgov_docs="always" forces it)
        want_docs = opts.get("ezgov_docs") == "always" or not tender or tender.get("isProceedingOnPlatform")
        r2 = ctx.fetch(EZ_DOCS, params={"tenderId": ocid}, rel_path=f"{rm}/ezamowienia_GetTenderDocuments.json",
                       note=_note(rm=rm, role="ezgov_docs", platform="ezamowienia"), min_interval=2.5) \
            if want_docs else None
        if r2 is not None and r2.ok:
            try:
                ez_files = P.parse_ezamowienia_documents(r2.json(), ocid)
            except ValueError:
                ez_files = []
            if ez_files:
                st["platform"] = "ezamowienia"
                lst = P.Listing("ezamowienia", f"https://ezamowienia.gov.pl/mp-client/search/list/{ocid}",
                                proc_id=ocid, files=ez_files)
                _download_all(ctx, rm, lst, idx, st, opts)

    # 2. platform page(s)
    urls = list(dict.fromkeys(p.get("platform_urls") or []))
    hint_urls = [u for u, _ in HINTS.get(rm, [])]
    proc_urls = [u for u in urls if P.is_procedure_url(u)]
    profile_urls = [u for u in urls + hint_urls if not P.is_procedure_url(u)]
    if not proc_urls and profile_urls:
        found = _search_profiles(ctx, rm, p, tender, profile_urls)
        proc_urls = found
    if not proc_urls:
        if st["platform"] is None:
            ctx.record(f"pilot:{rm}", "empty", note=_note(rm=rm, role="noplatform") +
                       " no procedure URL in ContractNotice and none found on buyer profiles")
        return st
    for url in proc_urls:
        plat = P.detect_platform(url)
        st["platform"] = plat
        lst = _fetch_listing(ctx, rm, url, fresh=False)
        if lst.status != "ok":
            st["page_status"] = lst.status
            continue
        if plat == "ezamawiajacy" and lst.meta.get("_cached"):
            missing = [f for f in lst.files if f.method == "POST" and not idx.get(rm, "file", f.key)
                       and _in_scope(f, opts)
                       and (idx.get(rm, "file", f.key, ok_only=False) or {}).get("status") != "blocked"]
            if missing:   # download tokens are bound to the HTTP session -> reload the page(s) fresh
                lst = _fetch_listing(ctx, rm, url, fresh=True)
        st["listed"] += len(lst.files)
        _download_all(ctx, rm, lst, idx, st, opts)
    return st


def _in_scope(f: P.ListedFile, opts: dict | None) -> bool:
    mode = (opts or {}).get("download", "all")
    if mode == "none":
        return False
    if mode == "priority":
        return _rank(f) <= 1 and (f.size_bytes or 0) <= PRIORITY_MAX_BYTES
    return True


def _search_profiles(ctx: ScrapeContext, rm: str, p: dict, tender: dict, profile_urls: list[str]) -> list[str]:
    """Find the procedure on the buyer's platform profile (ref number from e-Zamówienia, else title)."""
    ref = tender.get("referenceNumber")
    title = (p.get("title") or tender.get("title") or "").lower()
    out: list[str] = []
    for prof in profile_urls:
        plat = P.detect_platform(prof)
        if plat == "ezamawiajacy":
            host = _host(prof).removeprefix("www.")
            buyer = P.ezam_buyer(prof.replace("://www.", "://"))
            opts_pages = 8
            for state in ("expired", "during", "current"):
                lurl = f"https://{host}/pn/{buyer}/demand/notice/publicpzp/{state}/list"
                if not P.robots_allows(_robots(ctx, lurl), lurl)[0]:
                    continue
                queries = []
                if ref:
                    queries.append(("ref", {"demandNumber": ref, "demandName": ""}))
                if title:
                    queries.append(("title", {"demandNumber": "", "demandName": _title_query(title)}))
                for qk, q in queries:
                    data = {**q, "isFiredBySearchButton": "true", "GD_pagestart": "0"}
                    rel = f"{rm}/profile_search_{state}.html" if qk == "ref" else f"{rm}/profile_search_{state}_title.html"
                    r = ctx.fetch(lurl, method="POST", data=data, rel_path=rel,
                                  note=_note(rm=rm, role="profile", platform=plat), min_interval=_interval(lurl))
                    if not r.ok:
                        continue
                    rows = P.ezamawiajacy_search_rows(r.text(), lurl)
                    for row in rows:
                        if (ref and _norm_ref(row["number"]) == _norm_ref(ref)) or (
                                title and _title_match(title, row["title"])):
                            out.append(row["url"])
                    if out:
                        return list(dict.fromkeys(out))
            # fallback: page through the public lists (search form matches exact numbers only)
            for state in ("expired", "during", "current"):
                lurl = f"https://{host}/pn/{buyer}/demand/notice/publicpzp/{state}/list"
                for page in range(int(opts_pages)):
                    data = {"demandNumber": "", "demandName": "", "isFiredBySearchButton": "false",
                            "GD_pagestart": str(page * 25)}
                    r = ctx.fetch(lurl, method="POST", data=data, rel_path=f"{rm}/profile_list_{state}_{page}.html",
                                  note=_note(rm=rm, role="profile", platform=plat), min_interval=_interval(lurl))
                    if not r.ok:
                        break
                    rows = P.ezamawiajacy_search_rows(r.text(), lurl)
                    for row in rows:
                        nr, nref = _norm_ref(row["number"]), _norm_ref(ref or "")
                        if (nref and (nr.startswith(nref) or nref.startswith(nr) and len(nr) > 6)) or (
                                title and _title_match(title, row["title"])):
                            out.append(row["url"])
                    if out:
                        return list(dict.fromkeys(out))
                    if len(rows) < 25:
                        break
        elif plat == "platformazakupowa":
            if not P.robots_allows(_robots(ctx, prof), prof)[0]:
                continue
            r = ctx.fetch(prof, rel_path=f"{rm}/profile_{safe_name(_host(prof))}.html",
                          note=_note(rm=rm, role="profile", platform=plat), min_interval=_interval(prof))
            if not r.ok:
                continue
            for u, txt in P.platformazakupowa_profile_links(r.text(), prof):
                t = txt.lower()
                if (ref and ref.lower() in t) or (title and title[:40] in t):
                    out.append(u)
            if out:
                return out
    if not out:
        ctx.record(f"pilot:{rm}", "empty", note=_note(rm=rm, role="profile_search", ref=ref) +
                   f" procedure not found on profiles {profile_urls}")
    return out


def _norm_ref(s: str) -> str:
    return re.sub(r"[\s.\-_/]+", "", (s or "").lower())


def _clean_title(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"„”“'«»]", " ", s or "")).strip().lower()


def _title_query(title: str) -> str:
    """A distinctive chunk of the title for the platform's substring search."""
    t = _clean_title(title)
    return t[:60].rsplit(" ", 1)[0] if len(t) > 60 else t


def _title_match(a: str, b: str) -> bool:
    from rapidfuzz import fuzz
    a, b = _clean_title(a), _clean_title(b)
    return bool(a and b) and (fuzz.token_set_ratio(a, b) >= 90 or (len(a) > 30 and a[:40] in b))


def _alias(ctx: ScrapeContext, r, rm: str, role: str, key: str | None = None, platform: str | None = None):
    """A cached response fetched earlier for ANOTHER subject (two OCIDs resolving to the same platform procedure,
    same session token URL): add a manifest line for this subject pointing at the same raw file."""
    if not getattr(r, "cached", False) or not r.ok:
        return r
    owner = _pnote(r.manifest.get("note")).get("rm")
    if owner == rm:
        return r
    akey = hashlib.sha1(f"alias {rm} {role} {key or ''} {r.manifest.get('key')}".encode()).hexdigest()
    if akey in ctx.store.index():
        return r
    m = r.manifest
    rr = ctx.record(m.get("url") or r.url, "ok", method=m.get("method") or "GET", params=m.get("params") or None,
                    note=_note(rm=rm, role=role, key=key, platform=platform) + f" alias_of={owner}",
                    key=akey, http_status=m.get("http_status"), path=m.get("path"),
                    extra={"sha256": m.get("sha256"), "bytes": m.get("bytes"), "content_type": m.get("content_type"),
                           "alias_of_key": m.get("key")})
    r.manifest = rr.manifest
    return r


def _fetch_page(ctx: ScrapeContext, rm: str, url: str, role: str, fresh: bool, method: str = "GET"):
    rules = _robots(ctx, url)
    ok, rule = P.robots_allows(rules, url)
    plat = P.detect_platform(url)
    if not ok:
        return ctx.record(url, "blocked", note=_note(rm=rm, role=role, platform=plat) + f" robots.txt {rule}")
    suffix = f"__{ctx.run_id[:8]}" if fresh else ""
    sub = hashlib.sha1(url.encode()).hexdigest()[:8]
    r = ctx.fetch(url, method=method, rel_path=f"{rm}/{role}_{plat}_{sub}{suffix}.html",
                  note=_note(rm=rm, role=role, platform=plat), min_interval=_interval(url),
                  ttl=timedelta(0) if fresh else "default")
    return _alias(ctx, r, rm, role, platform=plat)


def _page_state(r) -> tuple[str, str]:
    if r.status == "blocked":
        return "blocked", (r.manifest.get("note") or "")[:300]
    if r.status == "error":
        hs = r.http_status
        note = r.manifest.get("note") or ""
        if hs in (404, 410) or re.search(r"ConnectError|Name or service|nodename|getaddrinfo|SSL", note):
            return "link_dead", f"HTTP {hs} {note}"[:300]
        return "error", f"HTTP {hs} {note}"[:300]
    if r.status == "empty":
        return "link_dead", "empty response"
    return "ok", ""


def _parse_page(plat: str, html: str, url: str, folder_title: str | None = None) -> P.Listing:
    if plat == "platformazakupowa":
        return P.parse_platformazakupowa(html, url)
    if plat == "ezamawiajacy":
        return P.parse_ezamawiajacy(html, url, folder_title)
    if plat == "logintrade":
        return P.parse_logintrade(html, url)
    lst, _ = P.parse_generic(html, url)
    return lst


def _fetch_listing(ctx: ScrapeContext, rm: str, url: str, fresh: bool) -> P.Listing:
    plat = P.detect_platform(url)
    if plat == "uzp_miniportal":
        r = _fetch_page(ctx, rm, url, "page", fresh)
        state, note = _page_state(r)
        return P.Listing(plat, url, status="link_dead" if state != "ok" else "ok",
                         note=note or "old miniPortal (retired)")
    r = _fetch_page(ctx, rm, url, "page", fresh)
    state, note = _page_state(r)
    if state != "ok":
        return P.Listing(plat, url, status=state, note=note)
    cached = r.cached
    html = r.text()
    lst = _parse_page(plat, html, r.url or url)
    if plat == "generic":
        # depth 2: follow same-host HTML links that look procedure-related
        _, follow = P.parse_generic(html, url)
        for u in follow[:15]:
            if not re.search(r"przetarg|zamowien|zamówien|postepowan|ogloszen|swz|dokument", u, re.I):
                continue
            r2 = _fetch_page(ctx, rm, u, "page2", fresh)
            if r2.ok and "html" in (r2.content_type or ""):
                l2, _ = P.parse_generic(r2.text(), u)
                keys = {f.key for f in lst.files}
                lst.files += [f for f in l2.files if f.key not in keys]
    if plat == "ezamawiajacy":
        keys = {f.key: f for f in lst.files}
        for sub_url, sub_title in list(lst.subpages):
            r2 = _fetch_page(ctx, rm, sub_url, "folder", fresh)
            cached = cached and r2.cached
            if not r2.ok:
                continue
            l2 = P.parse_ezamawiajacy(r2.text(), sub_url, sub_title)
            for f in l2.files:
                if f.key in keys:
                    if f.section != "Postępowanie":
                        keys[f.key].section, keys[f.key].context = f.section, f.context
                    if fresh:
                        keys[f.key].url = f.url
                else:
                    keys[f.key] = f
                    lst.files.append(f)
    lst.meta["_cached"] = cached
    if lst.status != "ok":
        # own key: must not shadow the cached page fetch (same URL) in the manifest index
        pkey = hashlib.sha1(f"page_parse {url}".encode()).hexdigest()
        if pkey not in ctx.store.index():
            ctx.record(url, "blocked" if lst.status == "blocked" else "empty",
                       note=_note(rm=rm, role="page_parse", platform=plat) + f" {lst.note}", key=pkey)
    return lst


_PRIORITY = {"swz": 0, "pfu": 0, "ppu": 0, "opz": 0, "qa": 0, "kwota": 1, "otwarcie": 1, "wybor": 1,
             "modyfikacja": 1, "uniewaznienie": 1, "umowa": 1, "aneks": 1, "stwiorb": 2, "przedmiar": 2,
             "kosztorys": 2, "inne": 3, "projekt": 4}
PRIORITY_MAX_BYTES = 40_000_000


def _rank(f: P.ListedFile) -> int:
    t = P.classify(f.name, f.context or "", "", f.size_bytes)[0]
    r = _PRIORITY.get(t, 3)
    if re.search(r"\.(zip|7z|rar)$", f.name, re.I) and r < 4:
        r += 1
    return r


def _sort_key(f: P.ListedFile) -> tuple:
    is_arch = bool(re.search(r"\.(zip|7z|rar)$", f.name, re.I))
    return (_rank(f), is_arch, f.size_bytes or 0)


def _download_all(ctx: ScrapeContext, rm: str, lst: P.Listing, idx: _Index, st: dict,
                  opts: dict | None = None) -> None:
    """opts: download="all" (default) | "priority" (SWZ/PFU/PPU/OPZ/Q&A + kwota/otwarcie/wybor/changes only,
    no archives, <= PRIORITY_MAX_BYTES each) | "none"; size_cap = bytes per procedure."""
    opts = opts or {}
    mode = opts.get("download", "all")
    if mode == "none":
        return
    used = 0
    for e in idx.by_rm.get(rm, []):
        if e["_n"].get("role") == "file" and e.get("status") == "ok":
            used += int(e.get("bytes") or 0)
    budget = int(opts.get("size_cap", SIZE_CAP)) - used
    for f in sorted(lst.files, key=_sort_key):
        if not _in_scope(f, opts):
            continue
        done = idx.get(rm, "file", f.key)
        if done:
            p = _abs_path(done.get("path"))
            if p and not idx.get(rm, "text", f.key) and not idx.get(rm, "ziplist", f.key):
                _post_process(ctx, rm, f, p.read_bytes(), done.get("sha256") or "", idx)
            continue
        rules = _robots(ctx, f.url)
        ok, rule = P.robots_allows(rules, f.url)
        if not ok:
            prev = idx.get(rm, "file", f.key, ok_only=False)
            if not (prev and prev.get("status") == "blocked"):
                r = ctx.record(f.url, "blocked", method=f.method,
                               note=_note(rm=rm, role="file", key=f.key, platform=lst.platform) + f" robots.txt {rule}")
                idx.add(r.manifest)
            st["blocked"] += 1
            continue
        if f.size_bytes and f.size_bytes > budget:
            prev = idx.get(rm, "file", f.key, ok_only=False)
            if prev and prev.get("status") == "blocked":
                st["blocked"] += 1
                continue
            r = ctx.record(f.url, "blocked", method=f.method,
                           note=_note(rm=rm, role="file", key=f.key, platform=lst.platform) +
                           f" size_cap: {f.size_bytes} B exceeds remaining per-procedure budget {budget} B")
            idx.add(r.manifest)
            st["blocked"] += 1
            continue
        name_ext = P.sniff_ext(b"", f.name)
        rel = f"{rm}/files/{f.key}_{safe_name(f.name, 90)}"
        if name_ext == ".bin":
            rel += ".html" if "preview" in f.url else ".bin"
        r = ctx.fetch(f.url, method=f.method, rel_path=rel, check_blocked=False,
                      note=_note(rm=rm, role="file", key=f.key, platform=lst.platform), min_interval=_interval(f.url))
        r = _alias(ctx, r, rm, "file", f.key, lst.platform)
        idx.add(r.manifest)
        if not r.ok:
            st["errors" if r.status == "error" else "blocked"] += 1
            continue
        content = r.content or b""
        if "html" in (r.content_type or "") and name_ext not in (".bin", ".html", ".htm"):
            rr = ctx.record(f.url, "error", method=f.method,
                            note=_note(rm=rm, role="file", key=f.key, platform=lst.platform) +
                            " got an HTML page instead of the file (expired session token / login page)")
            idx.add(rr.manifest)
            st["errors"] += 1
            continue
        budget -= len(content)
        st["downloaded"] += 1
        _post_process(ctx, rm, f, content, r.sha256 or "", idx)


def _post_process(ctx: ScrapeContext, rm: str, f: P.ListedFile, content: bytes, sha: str, idx: _Index) -> None:
    ext = P.sniff_ext(content, f.name)
    if ext == ".zip":
        _process_zip(ctx, rm, f.key, f.url, content, idx, depth=0)
    elif ext in (".7z", ".rar"):
        if not idx.get(rm, "ziplist", f.key):
            r = ctx.save_derived(f"{rm}/zip/{f.key}.json", json.dumps(
                {"archive": f.name, "error": f"{ext} archives not supported (no extractor installed)",
                 "members": []}, ensure_ascii=False).encode(), url=f.url,
                note=_note(rm=rm, role="ziplist", key=f.key))
            idx.add(r.manifest)
    elif ext in P.TEXT_EXTS:
        _extract(ctx, rm, f.key, f.url, content, ext, idx, sha)


def _extract(ctx: ScrapeContext, rm: str, key: str, url: str, content: bytes, ext: str, idx: _Index,
             sha: str = "") -> None:
    if idx.get(rm, "text", key):
        return
    text, pages, method = P.extract_text(content, ext)
    r = ctx.save_derived(f"{rm}/text/{key}.txt", text.encode("utf-8"), url=url,
                         note=_note(rm=rm, role="text", key=key, pages=pages, method=method.split(":")[0]),
                         extra={"pages": pages, "method": method, "of_sha256": sha or hashlib.sha256(content).hexdigest(),
                                "chars": len(text)})
    idx.add(r.manifest)


def _process_zip(ctx: ScrapeContext, rm: str, key: str, url: str, content: bytes, idx: _Index, depth: int,
                 prefix: str = "", root_key: str | None = None) -> None:
    root_key = root_key or key
    if depth == 0 and idx.get(rm, "ziplist", key):
        return
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        r = ctx.save_derived(f"{rm}/zip/{key}.json", json.dumps({"error": f"BadZipFile: {e}", "members": []}).encode(),
                             url=url, note=_note(rm=rm, role="ziplist", key=key))
        idx.add(r.manifest)
        return
    members = []
    for info in z.infolist():
        if info.is_dir():
            continue
        members.append({"name": P.zip_member_name(info), "size": info.file_size, "compressed": info.compress_size})
    r = ctx.save_derived(f"{rm}/zip/{key}.json", json.dumps({"prefix": prefix, "members": members},
                                                            ensure_ascii=False, indent=0).encode(),
                         url=url, note=_note(rm=rm, role="ziplist", key=key, depth=depth))
    idx.add(r.manifest)
    n = 0
    for info in z.infolist():
        if info.is_dir() or info.file_size > MEMBER_CAP or n >= MAX_MEMBERS:
            continue
        name = P.zip_member_name(info)
        lname = name.lower()
        is_zip = lname.endswith(".zip")
        if not (lname.endswith(P.TEXT_EXTS) or is_zip) or lname.endswith((".html", ".htm", ".xml")):
            continue
        if "__macosx" in lname:
            continue
        mkey = hashlib.sha1(f"{key}/{name}".encode()).hexdigest()[:16]
        try:
            data = z.read(info)
        except Exception as e:  # noqa: BLE001 - encrypted / broken member
            log.warning("zip member %s: %s", name, e)
            continue
        if is_zip:
            if depth < 2:
                _process_zip(ctx, rm, mkey, url, data, idx, depth + 1, prefix=f"{prefix}{name}/", root_key=root_key)
            continue
        n += 1
        mext = P.sniff_ext(data, name)
        if not idx.get(rm, "member", mkey):
            r = ctx.save_derived(f"{rm}/members/{mkey}{mext}", data, url=url,
                                 note=_note(rm=rm, role="member", key=mkey, parent=key),
                                 extra={"member_name": f"{prefix}{name}", "archive_key": root_key})
            idx.add(r.manifest)
        _extract(ctx, rm, mkey, url, data, mext, idx)


# ---------------------------------------------------------------------------------------------
# parse (raw -> records, no network)
# ---------------------------------------------------------------------------------------------

def _needs_ocr(txt: dict | None) -> bool | None:
    """PDF without a text layer (scan): pdftotext yields ~1 form feed per page."""
    if not txt or txt.get("method") != "pdftotext":
        return None
    chars, pages = int(txt.get("chars") or 0), int(txt.get("pages") or 0)
    return chars < 100 * max(pages, 1) if pages else chars < 100


def _read(rel: str | None) -> bytes | None:
    p = _abs_path(rel)
    if p is None or not p.exists():
        return None
    return p.read_bytes()


def _text_head(rel: str | None, n: int = 4000) -> str:
    b = _read(rel)
    return b[:n * 2].decode("utf-8", "replace")[:n] if b else ""


def _listings_from_raw(rm: str, entries: list[dict]) -> tuple[list[P.Listing], list[dict]]:
    """Re-parse the newest raw page/folder of every URL of this project."""
    last: dict[tuple[str, str], dict] = {}
    for e in entries:          # newest ok line per URL; newest line of any status if never ok
        role = e["_n"].get("role")
        if role in ("page", "folder", "page2"):
            k = (role, e["url"])
            if e.get("status") == "ok" or k not in last or last[k].get("status") != "ok":
                last[k] = e
    listings: list[P.Listing] = []
    states: list[dict] = []
    pages = {u: e for (role, u), e in last.items() if role == "page"}
    folders = {u: e for (role, u), e in last.items() if role == "folder"}
    for url, e in pages.items():
        plat = P.detect_platform(url)
        if e.get("status") != "ok":
            st = "blocked" if e.get("status") == "blocked" else (
                "link_dead" if (e.get("http_status") in (404, 410) or "Connect" in (e.get("note") or "")
                                or plat == "uzp_miniportal") else "error")
            states.append({"url": url, "status": st, "note": e.get("note"), "platform": plat})
            continue
        b = _read(e.get("path"))
        if b is None:
            continue
        html = b.decode("utf-8", "replace")
        lst = _parse_page(plat, html, url)
        lst.meta["raw_path"] = e.get("path")
        lst.meta["raw_sha256"] = e.get("sha256")
        lst.meta["fetched_at"] = e.get("fetched_at")
        if plat == "ezamawiajacy":
            keys = {f.key: f for f in lst.files}
            titles = dict(lst.subpages)
            for fu, fe in folders.items():
                if fe.get("status") != "ok" or fu not in titles:
                    continue
                fb = _read(fe.get("path"))
                if fb is None:
                    continue
                l2 = P.parse_ezamawiajacy(fb.decode("utf-8", "replace"), fu, titles.get(fu))
                for f in l2.files:
                    if f.key in keys:
                        if f.section != "Postępowanie":
                            keys[f.key].section, keys[f.key].context = f.section, f.context
                    else:
                        keys[f.key] = f
                        lst.files.append(f)
        states.append({"url": url, "status": lst.status, "note": lst.note, "platform": plat})
        if lst.status == "ok":
            listings.append(lst)
    if any(x.files for x in listings):
        # a working procedure page supersedes login walls / dead ends hit on other URLs of the same procedure
        states = [x for x in states if x["status"] == "ok"]
    return listings, states


def parse(store: RawStore) -> Iterable[DocumentRecord | SourceCheck]:
    idx = _Index(store.entries())
    for p in _pilot():
        yield from _parse_project(p, idx)


def _parse_project(p: dict, idx: _Index, *, source: str = SOURCE, subject_type: str = "project",
                   extra_data: dict | None = None, design_build_hint: bool | None = None
                   ) -> Iterable[DocumentRecord | SourceCheck]:
    """p: pilot-project-shaped dict (rm_id = subject key, tender_id = OCID, title, platform_urls, notices)."""
    rm, ocid = p["rm_id"], p.get("tender_id")
    entries = idx.by_rm.get(rm, [])
    if not entries:
        return          # project not scraped yet: emit nothing rather than false "not_in_package" states
    cn = _cn(p)
    base_data = {"ocid": ocid, "bzp_contract_notice": cn.get("number"), "buyer": p.get("buyer_name"),
                 **(extra_data or {})}
    tender: dict = {}
    ez_docs_checked = False
    for e in entries:
        role = e["_n"].get("role")
        if role == "ezgov_tender" and e.get("status") == "ok":
            b = _read(e.get("path"))
            try:
                tender = P.parse_ezamowienia_tender(json.loads(b or b"null"))
            except ValueError:
                pass
        if role == "ezgov_docs" and e.get("status") == "ok":
            ez_docs_checked = True
    base_data["reference_number"] = tender.get("referenceNumber")
    base_data["ezamowienia_isProceedingOnPlatform"] = tender.get("isProceedingOnPlatform")

    listings, page_states = _listings_from_raw(rm, entries)
    # e-Zamówienia documents (when the procedure is run on the e-Zamówienia platform)
    for e in entries:
        if e["_n"].get("role") == "ezgov_docs" and e.get("status") == "ok" and ocid:
            try:
                ez_files = P.parse_ezamowienia_documents(json.loads(_read(e.get("path")) or b"null"), ocid)
            except ValueError:
                ez_files = []
            if ez_files:
                listings.append(P.Listing("ezamowienia", f"https://ezamowienia.gov.pl/mp-client/search/list/{ocid}",
                                          proc_id=ocid, files=ez_files,
                                          meta={"raw_path": e.get("path"), "raw_sha256": e.get("sha256")}))

    records: list[DocumentRecord] = []
    found_types: dict[str, list[str]] = defaultdict(list)
    blocked_types: dict[str, list[str]] = defaultdict(list)
    blocked_archives: list[str] = []
    seen_keys: set[str] = set()
    platform = listings[0].platform if listings else (page_states[0]["platform"] if page_states else None)
    titles = [p.get("title") or "", tender.get("title") or ""]

    for lst in listings:
        titles.append(lst.title or "")
        titles.extend(str(v) for k, v in lst.meta.items() if "opis" in k.lower() or "przedmiot" in k.lower())
        for f in lst.files:
            if f.key in seen_keys:
                continue
            seen_keys.add(f.key)
            dl = idx.get(rm, "file", f.key, ok_only=False)
            txt = idx.get(rm, "text", f.key)
            head = _text_head(txt.get("path")) if txt else ""
            zl = idx.get(rm, "ziplist", f.key)
            members_note = ""
            if zl:
                try:
                    zj = json.loads(_read(zl.get("path")) or b"{}")
                    mnames = [m["name"] for m in zj.get("members", [])]
                    members_note = " | ".join(mnames[:40])
                except ValueError:
                    mnames = []
            dtype, sub, basis = P.classify(f.name, f.context or (f.section or ""), head or members_note, f.size_bytes)
            if zl and members_note and dtype == "inne":
                mt = [P.classify(m)[0] for m in members_note.split(" | ")]
                for cand in ("projekt", "przedmiar", "stwiorb", "pfu", "kosztorys"):
                    if cand in mt:
                        dtype, sub, basis = "projekt", "archive", "members"
                        break
            state = "found" if (dl and dl.get("status") == "ok" and _abs_path(dl.get("path")) and
                                _abs_path(dl.get("path")).exists()) else None
            note = ""
            if state is None:
                if dl is None:
                    state, note = "blocked", ("listed on the platform page but not downloaded: outside this run's "
                                              "download scope (priority documents / size cap) or run interrupted")
                elif dl.get("status") == "blocked":
                    state = "blocked"
                    note = "listed on the platform page; " + re.sub(r"docs_\w+( \w+=\S+)*", "", dl.get("note") or "").strip()
                else:
                    state = "blocked"
                    note = "listed on the platform page; download failed: " + re.sub(
                        r"docs_\w+( \w+=\S+)*", "", dl.get("note") or "").strip()
            data = {**base_data, "kind": "file", "platform": lst.platform, "procedure_id": lst.proc_id,
                    "page_url": lst.url, "section": f.section, "published": f.published, "size": f.size_text,
                    "size_bytes": (dl.get("bytes") if state == "found" else f.size_bytes),
                    "classified_by": basis, "subtype": sub or None, "context": P.scrub(f.context)[:300] or None}
            if lst.platform == "ezamawiajacy":
                data["download_url"] = f.url
            if txt:
                data["text_chars"] = txt.get("chars")
                data["text_method"] = txt.get("method")
                data["needs_ocr"] = _needs_ocr(txt)
            if zl:
                data["archive_members"] = len(members_note.split(" | ")) if members_note else 0
            if dtype == "kwota" and txt:
                data["amount_pln"] = P.find_amount(_text_head(txt.get("path"), 6000))
            url = f.url if lst.platform != "ezamawiajacy" else lst.url
            rec = DocumentRecord(
                source=source, subject_type=subject_type, subject_key=rm, doc_type=dtype, title=f.name,
                filename=f.name, url=url,
                raw_path=dl.get("path") if state == "found" else lst.meta.get("raw_path"),
                raw_sha256=dl.get("sha256") if state == "found" else lst.meta.get("raw_sha256"),
                text_path=txt.get("path") if txt else None, pages=(txt or {}).get("pages"),
                fetch_state=state, note=note[:500], data=data)
            records.append(rec)
            if state == "found":
                found_types[dtype].append(f.name)
            else:
                blocked_types[dtype].append(f.name)
                if re.search(r"\.(zip|7z|rar)$", f.name, re.I):
                    blocked_archives.append(f.name)
            # archive members
            for me in idx.by_rm.get(rm, []):
                if me["_n"].get("role") != "member" or me.get("archive_key") != f.key or me.get("status") != "ok":
                    continue
                mkey = me["_n"].get("key")
                if mkey in seen_keys:
                    continue
                seen_keys.add(mkey)
                mtxt = idx.get(rm, "text", mkey)
                mname = me.get("member_name") or mkey
                mt, msub, mbasis = P.classify_member(mname, _text_head(mtxt.get("path")) if mtxt else "")
                records.append(DocumentRecord(
                    source=source, subject_type=subject_type, subject_key=rm, doc_type=mt, title=mname,
                    filename=mname.rsplit("/", 1)[-1], url=url, raw_path=me.get("path"), raw_sha256=me.get("sha256"),
                    text_path=mtxt.get("path") if mtxt else None, pages=(mtxt or {}).get("pages"),
                    fetch_state="found", note=f"extracted from archive {f.name}",
                    data={**base_data, "kind": "archive_member", "platform": lst.platform, "archive": f.name,
                          "archive_raw_path": dl.get("path") if dl else None, "member_path": mname,
                          "classified_by": mbasis, "subtype": msub or None,
                          "text_chars": (mtxt or {}).get("chars"), "needs_ocr": _needs_ocr(mtxt)}))
                found_types[mt].append(mname)
        # inline information on the page itself (public messages / fields)
        for i, msg in enumerate(lst.messages):
            if msg.file_urls:
                continue
            dtype, sub, basis = P.classify("", msg.text, "")
            if dtype not in ("kwota", "otwarcie", "wybor", "uniewaznienie", "modyfikacja", "qa"):
                continue
            if re.search(r"komunikat zosta[lł] wycofany", msg.text, re.I):
                continue
            amount = P.find_amount(msg.text) if dtype == "kwota" else None
            records.append(DocumentRecord(
                source=source, subject_type=subject_type, subject_key=rm, doc_type=dtype,
                title=f"{lst.platform} page: {P.scrub(msg.text)[:120]}", filename=None, url=lst.url,
                raw_path=lst.meta.get("raw_path"), raw_sha256=lst.meta.get("raw_sha256"), text_path=None,
                fetch_state="found", note="published inline on the procedure page (public message / field), no file",
                data={**base_data, "kind": "inline", "platform": lst.platform, "procedure_id": lst.proc_id,
                      "date": msg.date, "text": P.scrub(msg.text)[:1500], "amount_pln": amount,
                      "amounts_pln": P.find_amounts(msg.text) if dtype == "kwota" else None}))
            found_types[dtype].append("inline")
    # e-Zamówienia kwota (amountToFinanced) when published there
    if tender.get("isAmountToFinancedPublished") and tender.get("amountToFinanced"):
        records.append(DocumentRecord(
            source=source, subject_type=subject_type, subject_key=rm, doc_type="kwota",
            title="e-Zamówienia: amountToFinanced", url=f"https://ezamowienia.gov.pl/mp-client/search/list/{ocid}",
            fetch_state="found", note="e-Zamówienia GetTender.amountToFinanced",
            data={**base_data, "kind": "inline", "platform": "ezamowienia", "amount_pln": tender.get("amountToFinanced")}))
        found_types["kwota"].append("ezamowienia")

    # expected document types -> evidence states
    design_build = bool(design_build_hint) or P.is_design_build(*titles) or \
        bool(found_types.get("pfu") or blocked_types.get("pfu"))
    expected = ["swz", "pfu"] if design_build else ["swz", "projekt", "przedmiar", "stwiorb"]
    expected += ["ppu", "qa", "kwota", "otwarcie", "wybor"]
    blocked_generic = [r.filename for r in records if r.fetch_state == "blocked" and r.data.get("kind") == "file"
                       and r.doc_type == "inne" and r.data.get("subtype") not in ("ogloszenie",)]
    page_ok = any(s["status"] == "ok" for s in page_states)
    page_blocked = [s for s in page_states if s["status"] == "blocked"]
    page_dead = [s for s in page_states if s["status"] == "link_dead"]
    page_url = listings[0].url if listings else (page_states[0]["url"] if page_states else None)
    n_listed = sum(len(lst.files) for lst in listings)
    for t in EXPECTED_ALL:
        if t in found_types:
            continue
        if t not in expected:
            state = "not_applicable"
            note = ("design-build procedure (zaprojektuj i wybuduj): the contractor prepares the design, "
                    "so no design documentation/BoQ in the tender package") if design_build else \
                   "build-only procedure: design documentation is supplied by the buyer, no PFU"
        elif t in blocked_types:
            state = "blocked"
            note = f"listed on the platform but not retrievable: {', '.join(blocked_types[t][:5])}"
            if any("robots" in (r.note or "") for r in records if r.doc_type == t):
                note += " (robots.txt disallows the attachment download path)"
        elif page_ok:
            if t in ("projekt", "przedmiar", "stwiorb") and blocked_archives:
                state = "blocked"
                note = (f"not listed as a separate file; probably inside archive(s) not retrievable: "
                        f"{', '.join(blocked_archives[:4])}")
            elif t in ("swz", "pfu", "ppu", "projekt", "przedmiar", "stwiorb") and blocked_generic:
                state = "blocked"
                note = (f"no file named as '{t}'; may be one of the unretrievable generic attachments: "
                        f"{', '.join(blocked_generic[:5])}")
            elif t == "qa":
                state = "not_in_package"
                note = (f"no Q&A (wyjaśnienia treści SWZ) among {n_listed} listed files/messages: "
                        "either no questions were asked or answers were not published there")
            else:
                state = "not_in_package"
                note = f"platform page reachable; none of {n_listed} listed files classified as '{t}'"
        elif page_blocked:
            state = "blocked"
            note = f"platform page blocked: {page_blocked[0]['note'] or ''}"[:300]
        elif page_dead:
            state = "link_dead"
            note = f"platform page does not resolve: {page_dead[0]['note'] or ''}"[:300]
        else:
            state = "not_in_package"
            note = ("no procedure page found (no URL in the ContractNotice, not found on buyer profiles); "
                    f"e-Zamówienia isProceedingOnPlatform={tender.get('isProceedingOnPlatform')}")
        records.append(DocumentRecord(
            source=source, subject_type=subject_type, subject_key=rm, doc_type=t, title=f"expected: {t}",
            url=page_url, fetch_state=state, note=note[:600],
            data={**base_data, "kind": "expected", "platform": platform, "design_build": design_build}))

    yield from records
    n_found = sum(1 for r in records if r.fetch_state == "found")
    n_blocked_files = sum(1 for r in records if r.fetch_state == "blocked" and r.data.get("kind") == "file")
    missing = [r.doc_type for r in records if r.data.get("kind") == "expected" and r.fetch_state != "not_applicable"]
    if n_found and not missing and not n_blocked_files:
        result = "found"
    elif n_found:
        result = "partial"
    elif page_blocked or n_blocked_files:
        result = "blocked"
    else:
        result = "not_found"
    checked = None
    ts = [e.get("fetched_at") for e in entries if e.get("fetched_at")]
    if ts:
        try:
            checked = datetime.strptime(max(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            checked = None
    yield SourceCheck(
        source=source, subject_type=subject_type, subject_key=rm,
        query={"ocid": ocid, "platform_urls": p.get("platform_urls"), "hints": [u for u, _ in HINTS.get(rm, [])],
               "ezamowienia_checked": ez_docs_checked},
        n_hits=sum(1 for r in records if r.fetch_state == "found" and r.data.get("kind") in ("file", "archive_member")),
        n_relevant=n_found, result=result,
        matched_ids=sorted({r.doc_type for r in records if r.fetch_state == "found" and r.doc_type}),
        note=(f"platform={platform}; listed={n_listed}; found={n_found}; blocked_files={n_blocked_files}; "
              f"design_build={design_build}; missing_expected={','.join(missing) or '-'}; "
              f"pages={[(s['platform'], s['status']) for s in page_states]}")[:1000],
        checked_at=checked, raw_path=listings[0].meta.get("raw_path") if listings else None)
