"""Centralny Rejestr Umów (CRU, rejestrumow.gov.pl) - contracts of public-finance units concluded since
2026-07-01 (art. 34a u.f.p.), with annexes/terminations (scrape.md §2 P1, §3.7; docs/research/02 §6).

Public read API used by the portal SPA (no key):
* `POST /api-dp/v1/agreements/search?offset=&limit=` (limit is capped at 50 by the server) with body
  sections `menuGlowne` (nip, regon, nazwa, przedmiotUmowy, wartoscOd/Do, dataZawarciaOd/Do) and
  `zmianyUmowy` (rodzajZmiany TSU01..07, dataZmianyOd/Do). Dates: ISO `YYYY-MM-DD`.
* `GET /api-dp/v1/agreement/{idUmowy}` -> parties, period, value, `zmianyUmowy[]`.

Behind an Incapsula WAF: 1.5 s between requests, everything cached, a challenge page -> status=blocked
and the run stops. Five consecutive failures (maintenance window) also stop the run.

Jobs (`--opt jobs=national,changes,buyers,details`, all by default):
* national - subject fragments (kanaliz, wodoci, oczyszczal, uzdatn, ściek) -> summaries.
* changes  - the same fragments x change types TSU02 (aneks), TSU05 (rozwiązanie), TSU06
             (wypowiedzenie), TSU07 (odstąpienie) -> the monitoring signal.
* buyers   - every contract of the 20 pilot buyer NIPs.
* details  - detail for: change hits, pilot-buyer hits that are water/sewage-related or >= the value
             threshold, national hits >= `--opt detail_min_value` (default 100000), most valuable first.
             `--limit N` caps the number of detail requests.
`--since D` = dataZawarciaOd (national/buyers) and dataZmianyOd (changes): polling mode for monitoring.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext, safe_name
from riskminer.connectors.records import ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.cru")

SOURCE = "cru"
DEFAULTS: dict[str, Any] = {"min_interval": 1.5, "timeout": 90.0}

BASE = "https://rejestrumow.gov.pl"
SEARCH_URL = BASE + "/api-dp/v1/agreements/search"
DETAIL_URL = BASE + "/api-dp/v1/agreement/{}"
PORTAL_URL = DETAIL_URL                  # citation: the public read-API detail (SPA route not verified)
PAGE = 50
FRAGMENTS = ["kanaliz", "wodoci", "oczyszczal", "uzdatn", "ściek"]
CHANGE_TYPES = ["TSU02", "TSU05", "TSU06", "TSU07"]
CHANGE_LABELS = {  # label in detail -> code
    "korekt": "TSU01", "aneks": "TSU02", "jawno": "TSU03", "danych strony": "TSU04", "rozwiąz": "TSU05",
    "wypowiedz": "TSU06", "odstąp": "TSU07",
}
WATER_RX = re.compile(r"kanaliz|wodoci|wod\w* -? ?kanal|oczyszczal|ściek|uzdatn|sieci wod|stacj\w* uzdat|"
                      r"przepompown|SUW\b|deszczow|odwodn|hydrofor|studni", re.IGNORECASE)
PILOT_PATH = Path(settings().ref_dir) / "pilot_projects.json"
HDR = {"Accept": "application/json", "Content-Type": "application/json"}


class _Stop(Exception):
    pass


def _bool_opt(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on") if v is not None else False


_FOLD = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").translate(_FOLD).lower()).strip()


def _place(buyer_name: str) -> str:
    """'Gmina Kartuzy – Urząd Miejski w Kartuzach' -> 'Kartuzy'; non-gmina names unchanged."""
    n = re.split(r"\s[–-]\s", buyer_name)[0].strip()
    return re.sub(r"^gmina\s+", "", n, flags=re.IGNORECASE)


def _pilot() -> list[dict]:
    return json.loads(PILOT_PATH.read_text(encoding="utf-8")) if PILOT_PATH.exists() else []


def _iso(v: Any) -> str | None:
    if v in (None, ""):
        return None
    return str(v)[:10]


def _pl_date(s: Any) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


class _Runner:
    def __init__(self, ctx: ScrapeContext):
        self.ctx = ctx
        self.fails = 0
        self.blocked = False

    def _check(self, r) -> None:
        if r.status == "blocked":
            self.blocked = True
            raise _Stop(f"blocked by WAF at {r.url}")
        if r.status == "error":
            self.fails += 1
            if self.fails >= 5:
                raise _Stop("5 consecutive errors (maintenance window?)")
        else:
            self.fails = 0

    def search(self, body: dict, rel_stem: str, note: str, ttl: Any) -> list[dict]:
        offset, out = 0, []
        while True:
            params = {"offset": offset, "limit": PAGE}
            r = self.ctx.fetch(SEARCH_URL, method="POST", params=params, json_body=body, headers=HDR,
                               rel_path=f"{rel_stem}_o{offset}.json", note=note, ttl=ttl)
            self._check(r)
            if r.status != "ok":
                break
            try:
                d = r.json()
            except ValueError:
                break
            items = d.get("content") or []
            out.extend(items)
            total = int(d.get("totalElements") or 0)
            offset += PAGE
            if not items or offset >= total or offset >= 9950:
                break
        return out

    def detail(self, idu: str, ttl: Any) -> None:
        r = self.ctx.fetch(DETAIL_URL.format(idu), headers={"Accept": "application/json"},
                           rel_path=f"detail/{safe_name(idu)}.json", note=f"job=detail id={idu}", ttl=ttl)
        self._check(r)


def run(ctx: ScrapeContext, *, since=None, until=None, limit=None, only=None, **opts) -> dict:
    jobs = opts.get("jobs") or ["national", "changes", "buyers", "details"]
    if isinstance(jobs, str):
        jobs = [j.strip() for j in jobs.split(",") if j.strip()]
    frags = opts.get("fragments") or FRAGMENTS
    if isinstance(frags, str):
        frags = [f.strip() for f in frags.split(",") if f.strip()]
    d_since, d_until = _iso(since), _iso(until)
    min_value = float(opts.get("detail_min_value", 100000))
    ttl_search = timedelta(hours=float(opts.get("search_ttl_hours", 6)))
    ttl_detail = timedelta(hours=float(opts.get("detail_ttl_hours", 24)))
    if opts.get("interval"):
        ctx.min_interval = float(opts["interval"])
    # cool-down: do not come back within N minutes after the WAF challenged us
    cool = float(opts.get("cooldown_minutes", 30))
    last_block = max((e.get("fetched_at", "") for e in ctx.store.entries()
                      if e.get("status") == "blocked" and "run stopped" in (e.get("note") or "")), default="")
    if last_block and not _bool_opt(opts.get("force")):
        t = datetime.strptime(last_block, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if datetime.now(UTC) - t < timedelta(minutes=cool):
            msg = f"WAF challenged us at {last_block}; cooling down {cool:.0f} min (use --opt force=true to override)"
            log.warning("cru: %s", msg)
            return {"skipped": msg}
    run_ = _Runner(ctx)
    tag = f"{d_since or 'all'}_{d_until or 'now'}"
    national: dict[str, dict] = {}
    changed: dict[str, dict] = {}
    buyers: dict[str, dict] = {}
    out: dict[str, Any] = {}
    try:
        if "changes" in jobs:
            for f in frags:
                for t in CHANGE_TYPES:
                    zm: dict[str, Any] = {"rodzajZmiany": t}
                    if d_since:
                        zm["dataZmianyOd"] = d_since
                    if d_until:
                        zm["dataZmianyDo"] = d_until
                    for it in run_.search({"menuGlowne": {"przedmiotUmowy": f}, "zmianyUmowy": zm},
                                          f"changes/{safe_name(f)}_{t}_{tag}", f"job=changes frag={f} type={t}",
                                          ttl_search):
                        changed.setdefault(it["idUmowy"], it)
            out["changed_contracts"] = len(changed)
        if "buyers" in jobs:
            nips = sorted({p["buyer_nip"] for p in _pilot()})
            if only:
                nips = [n for n in nips if n in set(only)]
            for nip in nips:
                mg: dict[str, Any] = {"nip": nip}
                if d_since:
                    mg["dataZawarciaOd"] = d_since
                if d_until:
                    mg["dataZawarciaDo"] = d_until
                got = run_.search({"menuGlowne": mg}, f"buyer/{nip}_{tag}", f"job=buyer nip={nip}", ttl_search)
                for it in got:
                    buyers.setdefault(it["idUmowy"], it)
                if not got:
                    # no contract under this NIP (some gminas publish under another NIP/REGON):
                    # fall back to the place name, filtered client-side on the publisher name
                    place = _place(next(p["buyer_name"] for p in _pilot() if p["buyer_nip"] == nip))
                    mg2 = {**{k: v for k, v in mg.items() if k != "nip"}, "nazwa": place}
                    for it in run_.search({"menuGlowne": mg2}, f"buyer/{nip}_name_{safe_name(place)}_{tag}",
                                          f"job=buyer_name nip={nip} name={place}", ttl_search):
                        if _fold(place) in _fold(it.get("nazwa") or ""):
                            buyers.setdefault(it["idUmowy"], it)
            out["pilot_buyer_contracts"] = len(buyers)
        if "national" in jobs:
            for f in frags:
                mg = {"przedmiotUmowy": f}
                if d_since:
                    mg["dataZawarciaOd"] = d_since
                if d_until:
                    mg["dataZawarciaDo"] = d_until
                for it in run_.search({"menuGlowne": mg}, f"national/{safe_name(f)}_{tag}",
                                      f"job=national frag={f}", ttl_search):
                    national.setdefault(it["idUmowy"], it)
            out["national_contracts"] = len(national)
        if "details" in jobs:
            want: list[str] = list(changed)
            for idu, it in buyers.items():
                if WATER_RX.search(it.get("przedmiotUmowy") or "") or (it.get("wartoscPrzedmiotuUmowy") or 0) >= min_value:
                    want.append(idu)
            rest = sorted((it for idu, it in national.items() if (it.get("wartoscPrzedmiotuUmowy") or 0) >= min_value),
                          key=lambda x: -(x.get("wartoscPrzedmiotuUmowy") or 0))
            want.extend(it["idUmowy"] for it in rest)
            seen: set[str] = set()
            want = [x for x in want if not (x in seen or seen.add(x))]
            if limit:
                want = want[: int(limit)]
            out["details_wanted"] = len(want)
            for i, idu in enumerate(want):
                run_.detail(idu, ttl_detail)
                if i and i % 200 == 0:
                    log.info("cru: %s/%s details", i, len(want))
    except _Stop as e:
        log.warning("cru: stopped: %s", e)
        ctx.record(BASE, "blocked" if run_.blocked else "error", note=f"run stopped: {e}")
        out["stopped"] = str(e)
    return out


# ---------------------------------------------------------------------------------------------
# raw -> records
# ---------------------------------------------------------------------------------------------
def _read_json(store: RawStore, e: dict) -> Any:
    if not e.get("path"):
        return None
    p = store.abs(e["path"])
    if not p.exists():
        return None
    try:
        return json.loads(p.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _change_code(label: str | None) -> str | None:
    lab = (label or "").lower()
    for k, v in CHANGE_LABELS.items():
        if k in lab:
            return v
    return None


def _is_natural_person(s: dict) -> bool:
    rodzaj = (s.get("rodzaj") or "").lower()
    return "fizyczn" in rodzaj or rodzaj == "su02" or bool((s.get("imie") or s.get("nazwisko")) and not s.get("nip"))


def _party(s: dict) -> dict:
    if _is_natural_person(s):
        return {"kind": "osoba fizyczna"}          # RODO: drop name/address of natural persons
    adr = s.get("daneAdresowe") or {}
    return {"kind": s.get("rodzaj"), "name": s.get("nazwa"), "nip": s.get("nip"), "regon": s.get("regon"),
            "country": s.get("kraj"), "consortium": s.get("czyKonsorcjum"),
            "city": adr.get("miejscowosc"), "province": adr.get("wojewodztwo")}


def _vat_basis(desc: str | None) -> str:
    d = (desc or "").lower()
    if "brutto" in d and "netto" not in d:
        return "gross"
    if "netto" in d and "brutto" not in d:
        return "net"
    return "unknown"


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def parse(store: RawStore) -> Iterable[ExternalRecord | SourceCheck]:
    summaries: dict[str, tuple[dict, dict]] = {}
    details: dict[str, tuple[dict, dict]] = {}
    hit_jobs: dict[str, set[str]] = {}
    buyer_hits: dict[str, dict[str, dict]] = {}
    buyer_entries: dict[str, list[dict]] = {}
    name_hits: dict[str, dict[str, dict]] = {}
    for e in store.entries():
        note = e.get("note") or ""
        if not note.startswith("job="):
            continue
        job = note.split()[0][4:]
        if job == "detail":
            if e.get("status") == "ok":
                d = _read_json(store, e)
                if isinstance(d, dict) and d.get("idUmowy"):
                    details[d["idUmowy"]] = (d, e)
            continue
        if job in ("buyer", "buyer_name"):
            nip = re.search(r"nip=(\d+)", note)
            if nip:
                buyer_entries.setdefault(nip.group(1), []).append(e)
        if e.get("status") != "ok":
            continue
        d = _read_json(store, e)
        if not isinstance(d, dict):
            continue
        for it in d.get("content") or []:
            idu = it.get("idUmowy")
            if not idu:
                continue
            summaries[idu] = (it, e)
            hit_jobs.setdefault(idu, set()).add(note[4:])
            if job == "buyer" and nip:
                buyer_hits.setdefault(nip.group(1), {})[idu] = it
            elif job == "buyer_name" and nip:
                place = note.split("name=", 1)[-1]
                if _fold(place) in _fold(it.get("nazwa") or ""):
                    name_hits.setdefault(nip.group(1), {})[idu] = it

    nip_of: dict[str, str] = {idu: nip for nip, hs in buyer_hits.items() for idu in hs}
    for idu in sorted(set(summaries) | set(details)):
        s, se = summaries.get(idu, ({}, {}))
        d, de = details.get(idu, ({}, {}))
        pd = d.get("podstawoweDane") or {}
        sz = d.get("szczegolyUmowy") or {}
        parties = d.get("stronyUmowy") or []
        buyer = next((p for p in parties if (p.get("rodzaj") or "").upper() == "JSFP"), None)
        others = [_party(p) for p in parties if p is not buyer]
        changes = []
        for z in d.get("zmianyUmowy") or []:
            changes.append({"type": z.get("rodzajZmiany"), "code": _change_code(z.get("rodzajZmiany")),
                            "date": _pl_date(z.get("dataZmiany")).isoformat() if _pl_date(z.get("dataZmiany")) else z.get("dataZmiany"),
                            "comment": z.get("komentarz"), "value": z.get("wartosc") or z.get("wartoscPoZmianie")})
        jobs = sorted(hit_jobs.get(idu, set()))
        title = sz.get("przedmiotUmowy") or s.get("przedmiotUmowy")
        value = sz.get("wartoscPrzedmiotu") if d else s.get("wartoscPrzedmiotuUmowy")
        adr = (buyer or {}).get("daneAdresowe") or {}
        e_src = de if d else se
        yield ExternalRecord(
            source=SOURCE, kind="cru_agreement", external_id=idu,
            title=(title or "").strip() or None,
            published_on=_pl_date(pd.get("dataZawarciaUmowy") or s.get("dataZawarciaUmowy")),
            buyer_nip=(buyer or {}).get("nip") or nip_of.get(idu),
            buyer_regon=(buyer or {}).get("regon") or s.get("regon"),
            buyer_name=(buyer or {}).get("nazwa") or s.get("nazwa"),
            province=adr.get("wojewodztwo"),
            value_amount=_dec(value), value_currency="PLN" if value is not None else None,
            value_vat_basis=_vat_basis(sz.get("opisWartosciPrzedmiotu")) if value is not None else None,
            url=PORTAL_URL.format(idu), raw_path=e_src.get("path"), raw_sha256=e_src.get("sha256"),
            data={
                "api_url": DETAIL_URL.format(idu), "detail_fetched": bool(d),
                "status": pd.get("statusUmowy") or s.get("statusUmowy"),
                "contract_number": pd.get("numerUmowy"),
                "signed_on": _iso(_pl_date(pd.get("dataZawarciaUmowy") or s.get("dataZawarciaUmowy"))),
                "end_date": _iso(_pl_date(pd.get("dataZakonczeniaUmowy") or s.get("dataZakonczeniaUmowy"))),
                "period": (d.get("okresObowiazywania") or {}).get("okres"),
                "indefinite": (d.get("okresObowiazywania") or {}).get("umowaNaCzasNieoznaczony"),
                "value_description": sz.get("opisWartosciPrzedmiotu"),
                "currency_note": "CRU does not state currency or VAT basis; PLN assumed",
                "eu_funded": d.get("finansowanaZeSrodkow"),
                "buyer_address": {k: adr.get(k) for k in ("wojewodztwo", "powiat", "gminaMiastoDzielnica", "miejscowosc")} if adr else None,
                "contractors": others,
                "changes": changes, "n_changes": len(changes),
                "change_codes": sorted({c["code"] for c in changes if c["code"]}),
                "published": _iso(_pl_date(d.get("dataPublikacji"))), "modified": _iso(_pl_date(d.get("dataModyfikacji"))),
                "water_relevant": bool(WATER_RX.search(title or "")),
                "found_by": jobs,
                "summary_raw_path": se.get("path") if se else None,
            },
        )

    # per pilot buyer / project
    projects = _pilot()
    for nip, es in buyer_entries.items():
        hits = buyer_hits.get(nip, {})
        by_name = name_hits.get(nip, {}) if not hits else {}
        rel = {idu: it for idu, it in {**hits, **by_name}.items() if WATER_RX.search(it.get("przedmiotUmowy") or "")}
        ok = any(e.get("status") == "ok" for e in es)
        result = (("partial" if by_name else "found") if rel else "not_found") if ok else (
            "blocked" if any(e.get("status") == "blocked" for e in es) else "error")
        checked = max((datetime.strptime(e["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                       for e in es if e.get("fetched_at")), default=None)
        note = (f"CRU (contracts since 2026-07-01): {len(hits)} contracts of this NIP, "
                f"{len(rel)} water/sewage-related by subject")
        q: dict[str, Any] = {"menuGlowne": {"nip": nip}, "url": SEARCH_URL}
        if not hits and any("job=buyer_name" in (e.get("note") or "") for e in es):
            place = next((e["note"].split("name=", 1)[-1] for e in es if "job=buyer_name" in (e.get("note") or "")), "")
            names = sorted({f"{it.get('nazwa')} (REGON {it.get('regon')})" for it in by_name.values()})
            q["fallback"] = {"menuGlowne": {"nazwa": place}}
            note += (f"; fallback by publisher name '{place}': {len(by_name)} contracts"
                     + (f" published by {', '.join(names[:5])} - verify it is the same buyer" if names else ""))
        yield SourceCheck(source=SOURCE, subject_type="organization", subject_key=nip, query=q, n_hits=len(hits),
                          n_relevant=len(rel), result=result, matched_ids=sorted(rel), note=note,
                          checked_at=checked, raw_path=es[-1].get("path"))
        for p in projects:
            if p["buyer_nip"] != nip:
                continue
            yield SourceCheck(source=SOURCE, subject_type="project", subject_key=p["rm_id"], query=q,
                              n_hits=len(hits), n_relevant=len(rel), result=result, matched_ids=sorted(rel),
                              note=note + "; pilot contract was signed before CRU started, so its absence is expected"
                              if not rel else note + "; candidates only, not linked to the pilot contract",
                              checked_at=checked, raw_path=es[-1].get("path"))
