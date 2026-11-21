"""Baza Konkurencyjności 2021 (bazakonkurencyjnosci.funduszeeuropejskie.gov.pl): per-buyer check (docs/scrape.md §2 P3).

Undocumented JSON behind the SPA (research/sources/examples.sh `bk`):
  GET /api/announcements/search?page=1&limit=50&sort=default&advertiserIdentificationNumber=<NIP>
      &status[0]=PUBLISHED&status[1]=RESOLVED&status[2]=CANCELLED&status[3]=CLOSED
  GET /api/announcements/<id>   (detail, only for hits)
Expected ~0 hits: KPO B3.1.1 gminas procure under Pzp (BZP), BK2021 covers EU-funded orders outside Pzp.
RODO: contact persons (name, phone, e-mail) are dropped from parsed records.
Records: SourceCheck per pilot buyer NIP; ExternalRecord kind="bk_announcement" per hit.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.bk2021")

SOURCE = "bk2021"
DEFAULTS = {"min_interval": 1.0, "headers": {"Content-type": "application/json; charset=utf-8"}}

BASE = "https://bazakonkurencyjnosci.funduszeeuropejskie.gov.pl"
SEARCH = f"{BASE}/api/announcements/search"
CITE = f"{BASE}/ogloszenia/{{id}}"
_PERSON = re.compile(r"contact|person|phone|email|e-mail|mail|telefon|imie|nazwisk|firstName|lastName|forename|"
                     r"surname|name_of_person|created_by|modified_by|pesel", re.IGNORECASE)
WODKAN_CPV = re.compile(r"^(45231[3-4]|452324|4523241|4523242|452321|452524|452521|452522|4525|9040|9041|6510|6511)")
WODKAN_KW = re.compile(r"kanaliz|wodociąg|oczyszczal|ściek|uzdatnian|wodno-?\s*ściek", re.IGNORECASE)


def _cpvs(o: Any) -> list[str]:
    out: list[str] = []
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "code" and isinstance(v, str) and re.match(r"^\d{8}-\d$", v):
                out.append(v)
            else:
                out.extend(_cpvs(v))
    elif isinstance(o, list):
        for x in o:
            out.extend(_cpvs(x))
    return out


def _params(nip: str, page: int) -> dict[str, str]:
    return {"page": str(page), "limit": "50", "sort": "default", "advertiserIdentificationNumber": nip,
            "status[0]": "PUBLISHED", "status[1]": "RESOLVED", "status[2]": "CANCELLED", "status[3]": "CLOSED"}


def pilot_buyers() -> list[tuple[str, str]]:
    p = settings().ref_dir / "pilot_projects.json"
    out: dict[str, str] = {}
    if p.exists():
        for proj in json.loads(p.read_text(encoding="utf-8")):
            if proj.get("buyer_nip"):
                out.setdefault(proj["buyer_nip"], proj.get("buyer_name") or "")
    return sorted(out.items())


def _items(body: Any) -> tuple[list[dict], int | None]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)], None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        d = body["data"]
        for k in ("advertisements", "announcements", "items", "results"):
            if isinstance(d.get(k), list):
                return [x for x in d[k] if isinstance(x, dict)], (d.get("meta") or {}).get("total")
    if isinstance(body, dict):
        for k in ("data", "items", "results", "announcements", "content"):
            v = body.get(k)
            if isinstance(v, list):
                total = body.get("total") or body.get("totalCount") or body.get("count") or (body.get("meta") or {}).get("total")
                return [x for x in v if isinstance(x, dict)], total
    return [], None


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        **opts: Any) -> dict:
    buyers = [(re.sub(r"\D", "", n), "") for n in only] if only else pilot_buyers()
    if limit:
        buyers = buyers[:limit]
    hits = 0
    for nip, _name in buyers:
        page = 1
        while page <= 10:
            r = ctx.fetch(SEARCH, params=_params(nip, page), rel_path=f"search/{nip}_p{page}.json", ttl=None,
                          note=f"buyer nip={nip} page={page}")
            if not r.ok:
                break
            try:
                items, _total = _items(r.json())
            except json.JSONDecodeError:
                break
            for it in items:
                aid = it.get("id")
                if aid:
                    hits += 1
                    ctx.fetch(f"{BASE}/api/announcements/{aid}", rel_path=f"detail/{aid}.json", ttl=None,
                              note=f"detail id={aid} nip={nip}")
            if len(items) < 50:
                break
            page += 1
    return {"buyers": len(buyers), "hits": hits}


# ---------------------------------------------------------------------------------------------
def _scrub(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items() if not _PERSON.search(k)}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    return o


def parse(store: RawStore) -> Iterable[ExternalRecord | SourceCheck]:
    searches: dict[str, list[dict]] = {}
    details: dict[str, dict] = {}
    for e in store.entries():
        note = e.get("note") or ""
        m = re.match(r"buyer nip=(\d+) page=(\d+)", note)
        if m:
            searches.setdefault(m.group(1), []).append(e)
        m = re.match(r"detail id=(\S+)", note)
        if m and e.get("status") == "ok":
            details[m.group(1)] = e
    names = dict(pilot_buyers())
    for nip in sorted(searches):
        es = searches[nip]
        ok = [e for e in es if e.get("status") in ("ok", "empty")]
        checked = datetime.strptime(es[-1]["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if not ok:
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip,
                              query={"advertiserIdentificationNumber": nip}, checked_at=checked,
                              result="blocked" if es[-1].get("status") == "blocked" else "error",
                              note=f"HTTP {es[-1].get('http_status')} {es[-1].get('note', '')}")
            continue
        ids: list[str] = []
        n_wodkan = 0
        for e in ok:
            try:
                items, _ = _items(json.loads(store.abs(e["path"]).read_bytes() or b"null"))
            except (OSError, json.JSONDecodeError):
                items = []
            for it in items:
                aid = str(it.get("id") or "")
                if not aid or aid in ids:
                    continue
                ids.append(aid)
                de = details.get(aid)
                det = {}
                if de:
                    try:
                        det = json.loads(store.abs(de["path"]).read_bytes() or b"null") or {}
                    except (OSError, json.JSONDecodeError):
                        det = {}
                title = it.get("title") or ((det.get("data") or {}).get("advertisement") or {}).get("title")
                cpvs = sorted(set(_cpvs(det)))
                wodkan = bool([c for c in cpvs if WODKAN_CPV.match(c)]) or bool(WODKAN_KW.search(title or ""))
                if wodkan:
                    n_wodkan += 1
                yield ExternalRecord(
                    source=SOURCE, kind="bk_announcement", external_id=aid, title=title, buyer_nip=nip,
                    buyer_name=names.get(nip) or None, url=CITE.format(id=aid),
                    raw_path=(de or e)["path"], raw_sha256=(de or e).get("sha256"),
                    data={"search_item": _scrub(it), "detail": _scrub(det) if det else None, "cpv_codes": cpvs,
                          "wodkan_related": wodkan, "rodo": "contact persons dropped"})
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip,
                          query={"advertiserIdentificationNumber": nip, "status": "PUBLISHED,RESOLVED,CANCELLED,CLOSED"},
                          n_hits=len(ids), n_relevant=n_wodkan, result="found" if ids else "not_found",
                          matched_ids=ids, checked_at=checked,
                          note=(f"{len(ids)} BK2021 announcement(s) by this advertiser NIP, {n_wodkan} water/sewage-"
                                "related (CPV/keyword); link to the pilot project not assessed" if ids
                                else "no BK2021 announcement with this advertiser NIP"))
