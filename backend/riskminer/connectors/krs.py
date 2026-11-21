"""KRS API (Ministry of Justice): odpis aktualny for contractors -> capacity signals (docs/scrape.md §2 P3).

`GET https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json` (no key).
Targets (KRS numbers come from local derived data, no extra lookups):
  1. pilot contractors: KRS from data/derived/vat_whitelist (data.krs) and data/derived/gus_bir
     (report praw_numerWRejestrzeEwidencji) for NIPs with a contractor role in data/ref/pilot_projects.json;
  2. top national contractors: data/ref/top_contractors.csv (nip, regon, krs?, name, n_contracts), KRS from the
     file or from the vat_whitelist record of that NIP.
Saturday maintenance: the API answers HTTP 200 with an HTML "Przerwa techniczna" page. The connector probes the
first target uncached; if it is the maintenance page it records `blocked` and stops (re-run later). Responses are
cached by the connector itself (a stored JSON odpis is never re-fetched unless --opt refresh=true).

parse(): ExternalRecord kind="krs_entity" (external_id = KRS) with company data (name, legal form, NIP/REGON,
registered seat, capital, PKD, registration dates) and data.capacity_flags from dział 6 (likwidacja, upadłość,
restrukturyzacja, rozwiązanie/unieważnienie, zawieszenie) + dział 4 (zaległości) = R12 capacity signal.
RODO: dział 2 (zarząd, prokurenci, organ nadzoru), shareholders (wspólnicy) and every person-name / PESEL field
are dropped. SourceCheck per target (subject = NIP, or KRS when the NIP is unknown).
"""
from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.krs")

SOURCE = "krs"
DEFAULTS = {"min_interval": 1.0, "timeout": 60.0}

API = "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}"
CITE = "https://wyszukiwarka-krs.ms.gov.pl/"
MAINT = re.compile(rb"Przerwa techniczna", re.IGNORECASE)
_PERSON = re.compile(r"imi[eo]|nazwisk|pesel|osob|sklad|czlonk|wspolni|prokur|reprezent|likwidator|nadzorc|"
                     r"zarzadca|kurator|syndyk|pelnomocn", re.IGNORECASE)
FLAG_RX = {
    "likwidacja": re.compile(r"likwidac", re.IGNORECASE),
    "upadlosc": re.compile(r"upad", re.IGNORECASE),
    "restrukturyzacja": re.compile(r"restruktur|uklad|sanac", re.IGNORECASE),
    "rozwiazanie_uniewaznienie": re.compile(r"rozwiaz|uniewaz", re.IGNORECASE),
    "zawieszenie": re.compile(r"zawiesz", re.IGNORECASE),
}


def _krs(v: Any) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d.zfill(10) if d and len(d) <= 10 and int(d) > 0 else None


def targets() -> list[dict]:
    """[{krs, nip, name, origin, n_contracts}] pilot contractors first, then top contractors."""
    ref = settings().ref_dir
    der = f"{settings().data_dir}/derived"
    pilot_roles: dict[str, str] = {}
    p = ref / "pilot_projects.json"
    if p.exists():
        for proj in json.loads(p.read_text(encoding="utf-8")):
            for c in proj.get("contractors") or []:
                for raw in (c.get("nip"), c.get("id_raw")):
                    for tok in re.findall(r"\d[\d\s-]{8,14}\d", str(raw or "")):
                        pilot_roles.setdefault(re.sub(r"\D", "", tok), proj["rm_id"])
    nip_krs: dict[str, tuple[str, str]] = {}
    for path, getk in ((f"{der}/vat_whitelist/records.jsonl", lambda d: d["data"].get("krs")),
                       (f"{der}/gus_bir/records.jsonl",
                        lambda d: (d["data"].get("report") or {}).get("praw_numerWRejestrzeEwidencji"))):
        fp = Path(path)
        if not fp.exists():
            continue
        with fp.open(encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("record_type") != "external_record":
                    continue
                nip = d.get("buyer_nip") or d.get("external_id")
                k = _krs(getk(d))
                if nip and k and nip not in nip_krs:
                    nip_krs[nip] = (k, d.get("title") or "")
    out: list[dict] = []
    seen: set[str] = set()
    for nip, rm in pilot_roles.items():
        if nip in nip_krs and nip_krs[nip][0] not in seen:
            k, name = nip_krs[nip]
            seen.add(k)
            out.append({"krs": k, "nip": nip, "name": name, "origin": f"pilot contractor {rm}", "n_contracts": None})
    tp = ref / "top_contractors.csv"
    if tp.exists():
        for r in csv.DictReader(tp.open(encoding="utf-8")):
            nip = re.sub(r"\D", "", r.get("nip") or "")
            k = _krs(r.get("krs")) or (nip_krs.get(nip) or (None, ""))[0]
            if k and k not in seen:
                seen.add(k)
                out.append({"krs": k, "nip": nip or None, "name": r.get("name"), "origin": "top_contractors.csv",
                            "n_contracts": r.get("n_contracts")})
    return out


def _stored(store: RawStore) -> dict[str, dict]:
    """KRS -> latest manifest entry holding a JSON odpis."""
    out: dict[str, dict] = {}
    for e in store.entries():
        m = re.search(r"/OdpisAktualny/(\d{10})", e.get("url", ""))
        if m and e.get("status") == "ok" and "json" in (e.get("content_type") or ""):
            out[m.group(1)] = e
    return out


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        refresh: bool = False, **opts: Any) -> dict:
    """only = KRS numbers (or NIPs of known targets)."""
    tg = targets()
    if only:
        want = {re.sub(r"\D", "", x) for x in only}
        tg = [t for t in tg if t["krs"] in {_krs(w) for w in want} or t["nip"] in want] or \
             [{"krs": _krs(w), "nip": None, "name": None, "origin": "only", "n_contracts": None} for w in want if _krs(w)]
    if limit:
        tg = tg[:limit]
    have = {} if refresh else _stored(ctx.store)
    todo = [t for t in tg if t["krs"] not in have]
    out = {"targets": len(tg), "cached": len(tg) - len(todo), "fetched": 0, "not_found": 0}
    for i, t in enumerate(todo):
        url = API.format(krs=t["krs"])
        r = ctx.fetch(url, params={"rejestr": "P", "format": "json"}, ttl=timedelta(seconds=0),
                      rel_path=f"odpis_{t['krs']}.json", accept_status=(200, 404), check_blocked=False,
                      note=f"krs={t['krs']} nip={t['nip'] or ''} origin={t['origin']}")
        body = r.content or b""
        if r.http_status == 200 and MAINT.search(body[:5000]):
            log.warning("KRS API maintenance page ('Przerwa techniczna'); stopping, re-run later")
            for t2 in todo[i:]:
                ctx.record(API.format(krs=t2["krs"]), "blocked", params={"rejestr": "P", "format": "json"},
                           note=f"krs={t2['krs']} nip={t2['nip'] or ''} KRS API maintenance (Przerwa techniczna)")
            return {**out, "stopped": "maintenance"}
        if r.http_status == 404:
            out["not_found"] += 1
        elif r.ok:
            out["fetched"] += 1
    return out


# ---------------------------------------------------------------------------------------------
_ROLE_NAME = re.compile(
    r"\b(NOTARIUSZ\w*|ZASTĘPC\w* NOTARIUSZA|SYNDYK\w*|NADZORC\w*|ZARZĄDC\w*|KURATOR\w*|LIKWIDATOR\w*|"
    r"PROKURENT\w*|PREZES\w*|SĘDZI\w*|REFERENDARZ\w*|ASESOR\w*)(\s+(?:SĄDOW\w+\s+)?)"
    r"((?:[A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻa-ząćęłńóśźż-]+\s*){2,3})", re.UNICODE)


def _mask(t: str) -> str:
    """RODO: names of natural persons after a role word in free-text registry entries are masked."""
    return _ROLE_NAME.sub(lambda m: f"{m.group(1)}{m.group(2)}[imię i nazwisko usunięte] ", t)


def _scrub(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items() if not _PERSON.search(k)}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    if isinstance(o, str):
        return _mask(o)
    return o


def _nonempty(o: Any) -> bool:
    if isinstance(o, dict):
        return any(_nonempty(v) for v in o.values())
    if isinstance(o, list):
        return any(_nonempty(x) for x in o)
    return o not in (None, "", False)


_DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def _closed(val: Any) -> bool:
    """A dział 6 section is historical when it records its end (zakończenie/uchylenie/umorzenie)."""
    txt = json.dumps(val, ensure_ascii=False).lower()
    return bool(re.search(r'"zakonczenie[^"]*": *(\{[^}]|"[^"]|\[[^\]])|uchylen|umorzen|dalszym istnieniu', txt))


def capacity_flags(dane: dict) -> dict:
    """R12 capacity signal. Each dział 6 flag says whether the proceeding is still open or closed (ended)."""
    d6 = dane.get("dzial6") or {}
    flags: dict[str, Any] = {}
    for key, val in d6.items():
        if not _nonempty(val):
            continue
        order = ["restrukturyzacja", "upadlosc", "likwidacja", "rozwiazanie_uniewaznienie", "zawieszenie"]
        flag = next((f for f in order if FLAG_RX[f].search(key)), None)
        if not flag:
            continue
        txt = json.dumps(val, ensure_ascii=False)
        dates = sorted({f"{y}-{m}-{d}" for d, m, y in _DATE.findall(txt)})
        closed = _closed(val)
        prev = flags.get(flag) or {}
        flags[flag] = {"present": True, "closed": bool(prev.get("closed", True) and closed),
                       "dates": sorted(set(prev.get("dates", [])) | set(dates)), "section": key}
    if flags.get("rozwiazanie_uniewaznienie") and flags.get("likwidacja", {}).get("closed"):
        flags["rozwiazanie_uniewaznienie"]["closed"] = True      # dissolution reversed with the liquidation
    d4 = dane.get("dzial4") or {}
    if _nonempty(d4):
        flags["dzial4_entries"] = sorted(k for k, v in d4.items() if _nonempty(v))
    name = json.dumps((dane.get("dzial1") or {}).get("danePodmiotu") or {}, ensure_ascii=False)
    if re.search(r"w likwidacji|w upadłości|w restrukturyzacji", name, re.IGNORECASE):
        flags["name_suffix_flag"] = True
    flags["any"] = any(flags.get(f) for f in FLAG_RX) or bool(flags.get("name_suffix_flag"))
    flags["any_open"] = any(flags.get(f) and not flags[f]["closed"] for f in FLAG_RX) or bool(flags.get("name_suffix_flag"))
    return flags


def parse(store: RawStore) -> Iterable[ExternalRecord | SourceCheck]:
    stored = _stored(store)
    last: dict[str, dict] = {}
    for e in store.entries():
        m = re.search(r"/OdpisAktualny/(\d{10})", e.get("url", ""))
        if m:
            last[m.group(1)] = e
    for t in targets():
        k = t["krs"]
        subj = t["nip"] or k
        e = stored.get(k)
        if e:
            try:
                odpis = (json.loads(store.abs(e["path"]).read_bytes()) or {}).get("odpis") or {}
            except (OSError, json.JSONDecodeError):
                odpis = {}
            dane = odpis.get("dane") or {}
            d1 = dane.get("dzial1") or {}
            dp = d1.get("danePodmiotu") or {}
            ids = dp.get("identyfikatory") or {}
            flags = capacity_flags(dane)
            data = {
                "krs": k, "naglowek": _scrub(odpis.get("naglowekA") or odpis.get("naglowekP") or {}),
                "dane_podmiotu": _scrub(dp), "siedziba_i_adres": _scrub(d1.get("siedzibaIAdres") or {}),
                "kapital": _scrub(d1.get("kapital") or {}),
                "przedmiot_dzialalnosci": _scrub((dane.get("dzial3") or {}).get("przedmiotDzialalnosci") or {}),
                "dzial4": _scrub(dane.get("dzial4") or {}), "dzial6": _scrub(dane.get("dzial6") or {}),
                "capacity_flags": flags, "origin": t["origin"], "n_contracts": t["n_contracts"],
                "rodo": "dział 2 (zarząd, prokurenci, nadzór), wspólnicy and person-name fields dropped",
            }
            checked = datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            yield ExternalRecord(
                source=SOURCE, kind="krs_entity", external_id=k, title=dp.get("nazwa") or t["name"],
                buyer_nip=ids.get("nip") or t["nip"], buyer_regon=ids.get("regon"), buyer_name=dp.get("nazwa"),
                url=CITE, raw_path=e["path"], raw_sha256=e.get("sha256"), data=data)
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=subj, query={"krs": k},
                              n_hits=1, n_relevant=1, result="found", matched_ids=[k], checked_at=checked,
                              raw_path=e["path"],
                              note="capacity flags: " + (", ".join(
                                  f"{f} ({'closed' if flags[f]['closed'] else 'OPEN'})" for f in FLAG_RX if flags.get(f))
                                  or "none") + ("; dział 4 entries" if flags.get("dzial4_entries") else ""))
            continue
        le = last.get(k)
        if le is None:
            continue
        checked = datetime.strptime(le["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if le.get("http_status") == 404:
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=subj, query={"krs": k},
                              result="not_found", checked_at=checked, note="KRS API 404 in rejestr P")
        else:
            yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=subj, query={"krs": k},
                              result="blocked" if le.get("status") in ("blocked", "ok", "empty") else "error",
                              checked_at=checked, note=le.get("note") or "")
