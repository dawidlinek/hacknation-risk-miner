"""GUS Bank Danych Lokalnych (BDL) API: water/sewage network indicators per gmina-year (docs/scrape.md §2, §3.8).

`GET https://bdl.stat.gov.pl/api/v1/data/by-variable/{var}?unit-level=6&year=2015&...&year=2025&page-size=100`
One request returns 100 units x all requested years; ~41 pages per variable (4,042 level-6 units: gminy
and the urban/rural parts of urban-rural gminy). 11 variables -> ~450 requests.

Anonymous limits (GUS): 5/s, 100/15 min, 1,000/12 h, 10,000/7 days. DEFAULTS space requests 12 s apart
(75 per 15 min; do not make other BDL calls meanwhile); responses are cached forever. Licence: GUS open data, attribution.
2026-11-21: after ~66 connector requests (9.2 s apart) plus ~10 manual metadata calls within ~15 min the GUS WAF blocked the
IP for every BDL URL (HTTP 500 "Web Page Blocked!"). The run stops at the first failure and records
`blocked`; re-running later resumes from the cache. Consider an API key (X-ClientId header) for volume.

TERYT: the 12-digit BDL unit id encodes TERC as id[2:4] (woj) + id[7:9] (powiat) + id[9:11] (gmina)
+ id[11] (rodz), e.g. 030210126052 -> 0226052 (Zagrodno). Records: ExternalRecord kind="bdl_value",
external_id "<var>:<unit>:<year>".
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.gus_bdl")

SOURCE = "gus_bdl"
DEFAULTS = {"min_interval": 12.0, "headers": {"Accept": "application/json"}}   # 75 req / 15 min

API = "https://bdl.stat.gov.pl/api/v1"
YEARS = list(range(2015, 2026))
# priority order: if a run is cut short, the most useful variables are complete first
VARIABLES: dict[int, dict[str, str]] = {
    494: {"name": "długość czynnej sieci kanalizacyjnej", "unit": "km", "code": "sewer_km"},
    9153: {"name": "ludność korzystająca z sieci kanalizacyjnej", "unit": "osoba", "code": "sewer_pop"},
    489: {"name": "długość czynnej sieci rozdzielczej (wodociągowej)", "unit": "km", "code": "water_km"},
    9152: {"name": "ludność korzystająca z sieci wodociągowej", "unit": "osoba", "code": "water_pop"},
    79130: {"name": "korzystający z instalacji w % ogółu ludności: kanalizacja (ogółem)", "unit": "%",
            "code": "sewer_pct"},
    79133: {"name": "korzystający z instalacji w % ogółu ludności: wodociąg (ogółem)", "unit": "%",
            "code": "water_pct"},
    495: {"name": "przyłącza kanalizacyjne prowadzące do budynków mieszkalnych i zbiorowego zamieszkania",
          "unit": "szt.", "code": "sewer_connections"},
    490: {"name": "przyłącza wodociągowe prowadzące do budynków mieszkalnych i zbiorowego zamieszkania",
          "unit": "szt.", "code": "water_connections"},
    475706: {"name": "awarie sieci kanalizacyjnej", "unit": "szt.", "code": "sewer_failures"},
    475705: {"name": "awarie sieci wodociągowej", "unit": "szt.", "code": "water_failures"},
    497: {"name": "ścieki oczyszczane odprowadzone", "unit": "dam3", "code": "treated_sewage"},
}


def bdl_to_terc(unit_id: str) -> str | None:
    if not unit_id or len(unit_id) != 12 or not unit_id.isdigit():
        return None
    return unit_id[2:4] + unit_id[7:9] + unit_id[9:11] + unit_id[11]


def page_url(var: int, page: int, years: list[int]) -> str:
    """Query string in the URL (repeated `year` keys), so manifest `params` stays a dict."""
    ys = "&".join(f"year={y}" for y in years)
    return f"{API}/data/by-variable/{var}?unit-level=6&{ys}&page-size=100&page={page}&format=json"


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        years: list[int] | None = None, max_requests: int = 900, interval: float | None = None, **opts: Any) -> dict:
    """only = variable ids; limit = max pages per variable (smoke tests); max_requests = network budget per run;
    interval = seconds between requests (never below 12)."""
    if interval:
        ctx.min_interval = max(12.0, float(interval))
    vars_ = [int(v) for v in only] if only else list(VARIABLES)
    yrs = [int(y) for y in (years or YEARS)]
    sent = 0
    out: dict[str, Any] = {}
    for var in vars_:
        page, last = 0, None
        while last is None or page <= last:
            if ctx.stats["requests"] >= max_requests:
                log.warning("request budget %s reached; stopping (re-run continues from cache)", max_requests)
                return {**out, "stopped": "budget"}
            r = ctx.fetch(page_url(var, page, yrs),
                          rel_path=f"var_{var}/page_{page:03d}.json", ttl=None,
                          note=f"BDL var {var} ({VARIABLES.get(var, {}).get('code', '')}) page {page}; "
                               "GUS open data, attribution")
            sent += 1
            if not r.ok:
                # 2026-11-21: after ~120 anonymous requests in ~20 min the GUS WAF answered every BDL URL with
                # HTTP 500 {"page_title":"Web Page Blocked!"}; never retry around it - stop the run, re-run later
                log.warning("var %s page %s: %s; stopping (BDL WAF block suspected)", var, page, r.status)
                for v2 in vars_[vars_.index(var):]:
                    ctx.record(f"{API}/data/by-variable/{v2}", "blocked",
                               note="not fetched: BDL WAF block suspected (HTTP 500 'Web Page Blocked!'); re-run later")
                return {**out, "stopped": "blocked", "blocked_at": f"var {var} page {page}"}
            body = r.json() or {}
            if last is None:
                total = int(body.get("totalRecords") or 0)
                last = max(0, (total - 1) // 100)
                if limit:
                    last = min(last, int(limit) - 1)
            if not body.get("results"):
                break
            page += 1
        out[str(var)] = {"pages": page}
    return out


def parse(store: RawStore, include_parts: bool = False) -> Iterable[ExternalRecord]:
    """Gminy only (rodz 1-3) by default; urban/rural parts and Warsaw districts (rodz 4,5,8,9) are in raw."""
    seen: set[str] = set()
    entries = [e for e in store.entries() if e.get("status") == "ok" and e.get("path")]
    for e in reversed(entries):            # latest first; dedupe on (var, unit, year)
        url = e.get("url", "")
        if "/data/by-variable/" not in url:
            continue
        var = int(url.split("?", 1)[0].rsplit("/", 1)[1])
        meta = VARIABLES.get(var, {})
        p = store.abs(e["path"])
        if not p.exists():
            continue
        try:
            body = json.loads(p.read_bytes())
        except json.JSONDecodeError:
            continue
        for u in body.get("results") or []:
            uid = u.get("id")
            terc = bdl_to_terc(uid)
            if not include_parts and terc and terc[6] not in "123":
                continue
            for v in u.get("values") or []:
                key = f"{var}:{uid}:{v.get('year')}"
                if key in seen:
                    continue
                seen.add(key)
                val = v.get("val")
                yield ExternalRecord(
                    source=SOURCE, kind="bdl_value", external_id=key,
                    title=f"{meta.get('name', var)} - {u.get('name')} {v.get('year')}",
                    teryt=terc, province=terc[:2] if terc else None,
                    url=f"https://bdl.stat.gov.pl/bdl/dane/podgrup/wymiary?zmienna={var}",
                    raw_path=e.get("path"), raw_sha256=e.get("sha256"),
                    data={"var_id": var, "var_code": meta.get("code"), "var_name": meta.get("name"),
                          "measure_unit": meta.get("unit"), "bdl_unit_id": uid, "unit_name": u.get("name"),
                          "year": int(v["year"]) if str(v.get("year", "")).isdigit() else v.get("year"),
                          "value": val, "attr_id": v.get("attrId"), "terc7": terc,
                          "rodz": terc[6] if terc else None})
