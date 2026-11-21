"""Biała lista VAT (wl-api.mf.gov.pl): NIP -> name, REGON, KRS, statusVat, address (docs/scrape.md §3.2).

`GET https://wl-api.mf.gov.pl/api/search/nips/{nip1,...,nip30}?date=YYYY-MM-DD`

* HARD CAP: 100 search requests/day/IP (blocked until midnight after that). This connector batches
  30 NIPs per request, never re-asks for a NIP that already has an ok answer in the raw store
  (cache forever, across days), and refuses to go over `daily_cap` (default 90) search requests
  counted from today's manifest lines, nor over `max_requests` (default 10) per run.
* NIP checksum is validated locally first (weights 6,5,7,2,3,4,5,6,7, mod 11); an invalid NIP in a
  batch would fail the whole request.
* A missing VAT status is NOT an invalid NIP (e.g. Gmina Zagrodno `Niezarejestrowany`, still returned).
* RODO: parse() drops representatives, authorizedClerks, partners (person names), pesel and bank
  account numbers. Company/business addresses are kept.

Default scope: the distinct buyer NIPs + every valid contractor NIP from data/ref/pilot_projects.json.
`--only nip1,nip2` restricts to given NIPs; `--opt nips_file=path` adds a backlog file (any text/CSV:
every 10-digit NIP-like token with a valid checksum is taken).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext, utcnow
from riskminer.connectors.records import ExternalRecord, SourceCheck
from riskminer.validators import nip_valid as _nip_valid

log = logging.getLogger("riskminer.connectors.vat_whitelist")

SOURCE = "vat_whitelist"
DEFAULTS = {"min_interval": 1.0}

BASE = "https://wl-api.mf.gov.pl/api/search/nips/"
BATCH = 30
DAILY_CAP = 90          # leave headroom under the 100/day/IP hard cap
MAX_REQUESTS_PER_RUN = 10

# 10 digits written plain or with the usual 3-3-2-2 / 3-2-2-3 separators, optionally after "PL"
_NIP_TOKEN = re.compile(r"(?<!\d)(\d{3}[- ]?\d{3}[- ]?\d{2}[- ]?\d{2}|\d{3}[- ]?\d{2}[- ]?\d{2}[- ]?\d{3})(?!\d)")

# fields dropped from parsed records (personal data / bank accounts)
_DROP = {"representatives", "authorizedClerks", "partners", "accountNumbers", "pesel"}


def nip_valid(nip: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", nip or "")) and _nip_valid(nip)    # shared rule: riskminer/validators.py


def extract_nips(text: str | None) -> list[str]:
    """Every checksum-valid NIP in a messy id string ("946 210 51 81", "NIP:PL 6690503086", ...).
    9-digit REGONs (e.g. "369467516, 320468735") are ignored."""
    out: list[str] = []
    if not text:
        return out
    for m in _NIP_TOKEN.finditer(str(text)):
        n = re.sub(r"\D", "", m.group(1))
        if nip_valid(n) and n not in out:
            out.append(n)
    return out


def pilot_path() -> Path:
    return settings().ref_dir / "pilot_projects.json"


def pilot_nips() -> dict[str, list[dict]]:
    """NIP -> [{rm_id, role, name}] for the 22 pilot projects (buyers + contractors)."""
    out: dict[str, list[dict]] = {}
    p = pilot_path()
    if not p.exists():
        return out
    for proj in json.loads(p.read_text(encoding="utf-8")):
        for n in extract_nips(proj.get("buyer_nip")):
            out.setdefault(n, []).append({"rm_id": proj["rm_id"], "role": "buyer"})
        for c in proj.get("contractors") or []:
            for n in extract_nips(c.get("nip")) + extract_nips(c.get("id_raw")):
                roles = out.setdefault(n, [])
                r = {"rm_id": proj["rm_id"], "role": "contractor"}
                if r not in roles:
                    roles.append(r)
    return out


def _nips_in_url(url: str) -> list[str]:
    if "/search/nips/" not in url:
        return []
    tail = url.split("/search/nips/", 1)[1].split("?", 1)[0]
    return [x for x in tail.split(",") if x]


def done_nips(store: RawStore) -> set[str]:
    done: set[str] = set()
    for e in store.entries():
        if e.get("status") == "ok" and e.get("method") == "GET":
            done.update(_nips_in_url(e.get("url", "")))
    return done


def used_today(store: RawStore) -> int:
    today = utcnow().date().isoformat()
    return sum(1 for e in store.entries()
               if e.get("method") == "GET" and "/api/search/" in e.get("url", "")
               and str(e.get("fetched_at", "")).startswith(today) and e.get("http_status") is not None)


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        nips_file: str | None = None, refresh: bool = False, max_requests: int = MAX_REQUESTS_PER_RUN,
        daily_cap: int = DAILY_CAP, on_date: str | None = None, **opts: Any) -> dict:
    wanted: list[str] = []
    invalid: list[str] = []
    if only:
        for x in only:
            n = re.sub(r"\D", "", str(x))
            (wanted if nip_valid(n) else invalid).append(n)
    else:
        wanted.extend(sorted(pilot_nips()))
    if nips_file:
        txt = Path(nips_file).read_text(encoding="utf-8", errors="replace")
        for n in extract_nips(txt):
            if n not in wanted:
                wanted.append(n)
    wanted = list(dict.fromkeys(wanted))
    skip = set() if refresh else done_nips(ctx.store)
    todo = [n for n in wanted if n not in skip]
    if limit:
        todo = todo[:limit]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    used = used_today(ctx.store)
    budget = max(0, min(max_requests, daily_cap - used))
    if len(batches) > budget:
        log.warning("daily budget: %s batches needed, %s allowed (used today %s); rest stays queued",
                    len(batches), budget, used)
    day = on_date or date.today().isoformat()
    sent = 0
    for i, b in enumerate(batches[:budget]):
        url = BASE + ",".join(b)
        r = ctx.fetch(url, params={"date": day}, rel_path=f"search_nips_{day}_{i + 1:02d}_{b[0]}.json",
                      ttl=None, note=f"{len(b)} NIPs")
        sent += 1
        if r.status != "ok":
            log.warning("batch %s: %s %s", i + 1, r.status, (r.content or b"")[:300])
    return {"nips_wanted": len(wanted), "nips_already_done": len(set(wanted) & skip), "invalid_nips": invalid,
            "batches_sent": sent, "batches_queued": max(0, len(batches) - sent), "used_today_before": used}


# ---------------------------------------------------------------------------------------------
def _clean_subject(s: dict) -> dict:
    d = {k: v for k, v in s.items() if k not in _DROP}
    d["n_bank_accounts"] = len(s.get("accountNumbers") or [])
    return d


def _status_note(s: dict) -> str:
    st = s.get("statusVat") or "brak statusu"
    note = f"statusVat {st}"
    if s.get("removalDate"):
        note += f" (removed {s['removalDate']}{'; ' + s['removalBasis'] if s.get('removalBasis') else ''})"
    return note


def parse(store: RawStore) -> Iterable[ExternalRecord | SourceCheck]:
    roles = pilot_nips()
    latest: dict[str, tuple[str, dict | None, dict]] = {}    # nip -> (fetched_at, subject|None, manifest entry)
    failed: dict[str, dict] = {}
    for e in store.entries():
        nips = _nips_in_url(e.get("url", ""))
        if not nips:
            continue
        if e.get("status") != "ok" or not e.get("path"):
            for n in nips:
                failed[n] = e
            continue
        p = store.abs(e["path"])
        if not p.exists():
            continue
        try:
            body = json.loads(p.read_bytes())
        except json.JSONDecodeError:
            continue
        res = body.get("result") or {}
        found: dict[str, dict | None] = dict.fromkeys(nips)
        for ent in res.get("entries") or []:
            ident = str(ent.get("identifier") or "")
            subs = ent.get("subjects") or []
            if ident:
                found[ident] = subs[0] if subs else None
        for s in res.get("subjects") or []:      # older response shape
            if s and s.get("nip"):
                found[s["nip"]] = s
        for n, s in found.items():
            prev = latest.get(n)
            if prev is None or e["fetched_at"] >= prev[0]:
                latest[n] = (e["fetched_at"], s, {**e, "_request": res.get("requestId"),
                                                   "_req_time": res.get("requestDateTime")})
    for n, (fetched_at, s, e) in sorted(latest.items()):
        checked_at = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        pr = roles.get(n, [])
        if s:
            d = _clean_subject(s)
            d["request_id"] = e.get("_request")
            d["request_date_time"] = e.get("_req_time")
            d["query_date"] = (e.get("params") or {}).get("date")
            if pr:
                d["pilot_roles"] = pr
            yield ExternalRecord(
                source=SOURCE, kind="vat_entity", external_id=n, title=s.get("name"),
                buyer_nip=n, buyer_regon=s.get("regon") or None, buyer_name=s.get("name"),
                url=f"{e['url']}?date={d['query_date']}",   # the request actually made (batch of NIPs)
                raw_path=e.get("path"), raw_sha256=e.get("sha256"), data=d)
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=n,
                              query={"nip": n, "date": d["query_date"]}, n_hits=1, n_relevant=1,
                              result="found", matched_ids=[n], note=_status_note(s),
                              checked_at=checked_at, raw_path=e.get("path"))
        else:
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=n,
                              query={"nip": n, "date": (e.get("params") or {}).get("date")}, n_hits=0,
                              result="not_found",
                              note="no subject in the VAT register for this NIP on the query date "
                                   "(not proof of an invalid NIP: e.g. VAT-centralised budgetary unit; use REGON/BIR)",
                              checked_at=checked_at, raw_path=e.get("path"))
    for n, e in sorted(failed.items()):
        if n in latest:
            continue
        st = e.get("status")
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=n, query={"nip": n},
                          result="blocked" if st == "blocked" else "error",
                          note=f"HTTP {e.get('http_status')} {e.get('note', '')}".strip(),
                          checked_at=datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
                          raw_path=e.get("path"))
