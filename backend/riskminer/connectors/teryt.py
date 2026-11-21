"""TERYT TERC dictionary (województwa / powiaty / gminy) -> data/ref/teryt_terc.csv (docs/scrape.md §5).

Primary source (method=eteryt, default): the official GUS eTERYT full file "TERC urzędowy"
  GET  https://eteryt.stat.gov.pl/.../pliki_pelne.aspx            (ASP.NET page: __VIEWSTATE)
  POST same page, __EVENTTARGET=ctl00$body$BTERCUrzedowyPobierz   -> TERC_Urzedowy_<date>.zip (XML + CSV)
No login, 2 requests. The zip is re-downloaded only if the last one is older than `max_age_days` (30).

Secondary source (method=bip): the dictionary JSON behind the central BIP register
  https://aplikacje.gov.pl/app/bip-back/api/dictionaries/voivodeships[/{w}/districts[/{p}/communes]]
~400 requests. Checked 2026-11-21: it is STALE/incomplete (lists one gmina per name within a powiat, so
144 rural gminas such as Oława 0215042 are missing, and 82 codes still carry the pre-2025 rodz digit).
Kept only as a fallback; parse() uses eTERYT whenever a TERC zip is in the raw store.

rodz (7th digit): 1 gmina miejska, 2 gmina wiejska, 3 gmina miejsko-wiejska, 4 miasto w gminie
miejsko-wiejskiej, 5 obszar wiejski gminy miejsko-wiejskiej, 8 dzielnica m.st. Warszawy, 9 delegatura.
CSV level: woj | pow | gmi (rodz 1-3) | part (rodz 4,5,8,9: parts of a gmina, not gminas).
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext, utcnow
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.teryt")

SOURCE = "teryt"
DEFAULTS = {"min_interval": 1.0}

ETERYT = ("https://eteryt.stat.gov.pl/eTeryt/rejestr_teryt/udostepnianie_danych/baza_teryt/"
          "uzytkownicy_indywidualni/pobieranie/pliki_pelne.aspx")
BASE = "https://aplikacje.gov.pl/app/bip-back/api/dictionaries/voivodeships"
RODZ = {"1": "gmina miejska", "2": "gmina wiejska", "3": "gmina miejsko-wiejska",
        "4": "miasto w gminie miejsko-wiejskiej", "5": "obszar wiejski w gminie miejsko-wiejskiej",
        "8": "dzielnica m.st. Warszawy", "9": "delegatura"}
CSV_COLUMNS = ["terc", "level", "woj", "pow", "gmi", "rodz", "terc7", "name", "kind", "woj_name", "pow_name",
               "province_code", "stan_na", "source"]
_PL_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
              "października", "listopada", "grudnia"]


def csv_path():
    return settings().ref_dir / "teryt_terc.csv"


def _items(r) -> list[dict]:
    if not r.ok:
        return []
    try:
        return list((r.json() or {}).get("items") or [])
    except (json.JSONDecodeError, AttributeError):
        return []


def _hidden(page: str, name: str) -> str:
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', page)
    return html.unescape(m.group(1)) if m else ""


def _latest_zip(store: RawStore) -> dict | None:
    best = None
    for e in store.entries():
        if (e.get("status") == "ok" and e.get("method") == "POST" and e.get("url") == ETERYT and e.get("path")
                and (best is None or e["fetched_at"] >= best["fetched_at"])):
            best = e
    return best


def run_eteryt(ctx: ScrapeContext, *, refresh: bool = False, max_age_days: int = 30) -> dict:
    last = _latest_zip(ctx.store)
    if last and not refresh:
        age = utcnow() - datetime.strptime(last["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if age < timedelta(days=max_age_days):
            return {"eteryt": "cached", "zip": last["path"]}
    page = ctx.fetch(ETERYT, params={"contrast": "default"}, rel_path="eteryt_pliki_pelne.html",
                     ttl=timedelta(seconds=0), note="eTERYT full files page (form state)")
    if not page.ok:
        return {"eteryt": page.status}
    t = page.text()
    today = utcnow().date()
    data = {
        "__EVENTTARGET": "ctl00$body$BTERCUrzedowyPobierz", "__EVENTARGUMENT": "",
        "__VIEWSTATE": _hidden(t, "__VIEWSTATE"), "__VIEWSTATEGENERATOR": _hidden(t, "__VIEWSTATEGENERATOR"),
        "ctl00$body$TBData": _hidden(t, "ctl00$body$TBData") or f"{today.day} {_PL_MONTHS[today.month - 1]} {today.year}",
    }
    ev = _hidden(t, "__EVENTVALIDATION")
    if ev:
        data["__EVENTVALIDATION"] = ev
    r = ctx.fetch(ETERYT, method="POST", params={"contrast": "default"}, data=data,
                  rel_path=f"TERC_Urzedowy_{today.isoformat()}.zip", ttl=timedelta(seconds=0),
                  note="eTERYT TERC urzedowy full file (GUS)", check_blocked=False,
                  empty_if=lambda b: not b.startswith(b"PK"))
    return {"eteryt": r.status, "zip": str(r.path) if r.path else None, "bytes": len(r.content or b"")}


def run_bip(ctx: ScrapeContext, *, only: list[str] | None = None, limit: int | None = None) -> dict:
    r = ctx.fetch(BASE, rel_path="voivodeships.json", note="TERC voivodeships (BIP register dictionary)")
    wojs = sorted(_items(r), key=lambda x: x["id"])
    if only:
        wojs = [w for w in wojs if w["id"] in set(only)]
    n_comm = 0
    for w in wojs:
        rd = ctx.fetch(f"{BASE}/{w['id']}/districts", rel_path=f"districts_{w['id']}.json",
                       note=f"TERC districts {w['id']}")
        for d in sorted(_items(rd), key=lambda x: x["id"]):
            if limit and n_comm >= limit:
                break
            ctx.fetch(f"{BASE}/{w['id']}/districts/{d['id']}/communes", rel_path=f"communes_{d['id']}.json",
                      note=f"TERC communes {d['id']}")
            n_comm += 1
    return {"bip_voivodeships": len(wojs), "bip_district_requests": n_comm}


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        method: str = "eteryt", refresh: bool = False, max_age_days: int = 30, **opts: Any) -> dict:
    """method: eteryt (default) | bip | both. only/limit apply to the BIP crawl (voivodeship codes)."""
    out: dict[str, Any] = {}
    if method in ("eteryt", "both"):
        out.update(run_eteryt(ctx, refresh=refresh, max_age_days=max_age_days))
    if method in ("bip", "both") or (method == "eteryt" and out.get("eteryt") not in ("ok", "cached")):
        out.update(run_bip(ctx, only=only, limit=limit))
    rows, src = build_rows(ctx.store)
    write_csv(rows)
    out.update({"csv_rows": len(rows), "csv_source": src, "csv": str(csv_path())})
    return out


# ---------------------------------------------------------------------------------------------
def _level(rodz: str, pow_: str, gmi: str) -> str:
    if not pow_:
        return "woj"
    if not gmi:
        return "pow"
    return "gmi" if rodz in ("1", "2", "3") else "part"


def rows_from_eteryt(store: RawStore, e: dict) -> list[dict]:
    p = store.abs(e["path"])
    z = zipfile.ZipFile(io.BytesIO(p.read_bytes()))
    name = next(n for n in z.namelist() if n.lower().endswith(".xml"))
    root = ET.fromstring(z.read(name))
    raw = []
    for row in root.iter("row"):
        d = {c.tag: (c.text or "").strip() for c in row}
        raw.append(d)
    woj_names = {d["WOJ"]: d["NAZWA"].lower() for d in raw if not d.get("POW")}
    pow_names = {d["WOJ"] + d["POW"]: d["NAZWA"] for d in raw if d.get("POW") and not d.get("GMI")}
    rows = []
    for d in raw:
        woj, pow_, gmi, rodz = d.get("WOJ", ""), d.get("POW", ""), d.get("GMI", ""), d.get("RODZ", "")
        lvl = _level(rodz, pow_, gmi)
        terc = woj + pow_ + gmi + rodz
        name = d["NAZWA"].lower() if lvl == "woj" else d["NAZWA"]
        kind = d.get("NAZWA_DOD", "")
        rows.append({"terc": terc, "level": lvl, "woj": woj, "pow": pow_, "gmi": gmi, "rodz": rodz,
                     "terc7": terc if len(terc) == 7 else "", "name": name, "kind": kind,
                     "woj_name": woj_names.get(woj, ""), "pow_name": pow_names.get(woj + pow_, "") if pow_ else "",
                     "province_code": f"PL{woj}", "stan_na": d.get("STAN_NA", ""), "source": "eteryt_terc",
                     "_raw": e})
    return rows


def rows_from_bip(store: RawStore) -> list[dict]:
    latest: dict[str, tuple[dict, list[dict]]] = {}
    for e in store.entries():
        if e.get("status") != "ok" or not e.get("path") or not str(e.get("url", "")).startswith(BASE):
            continue
        p = store.abs(e["path"])
        if not p.exists():
            continue
        try:
            items = (json.loads(p.read_bytes()) or {}).get("items") or []
        except json.JSONDecodeError:
            continue
        latest[e["url"]] = (e, items)
    rows: list[dict] = []
    woj_names: dict[str, str] = {}
    pow_names: dict[str, str] = {}
    base = {"stan_na": "", "source": "bip_dictionary"}
    if BASE in latest:
        e, items = latest[BASE]
        for w in items:
            woj_names[w["id"]] = w["name"].lower()
            rows.append({"terc": w["id"], "level": "woj", "woj": w["id"], "pow": "", "gmi": "", "rodz": "",
                         "terc7": "", "name": w["name"].lower(), "kind": "województwo",
                         "woj_name": w["name"].lower(), "pow_name": "", "province_code": f"PL{w['id']}",
                         "_raw": e, **base})
    for url, (e, items) in latest.items():
        if url.endswith("/districts"):
            woj = url.rsplit("/", 2)[-2]
            for d in items:
                code = d["id"]
                pow_names[code] = d["name"]
                kind = "miasto na prawach powiatu" if int(code[2:4]) >= 61 else "powiat"
                rows.append({"terc": code, "level": "pow", "woj": woj, "pow": code[2:4], "gmi": "", "rodz": "",
                             "terc7": "", "name": d["name"], "kind": kind, "woj_name": woj_names.get(woj, ""),
                             "pow_name": d["name"], "province_code": f"PL{woj}", "_raw": e, **base})
    for url, (e, items) in latest.items():
        if url.endswith("/communes"):
            for g in items:
                code = g["id"]
                if len(code) != 7:
                    continue
                rows.append({"terc": code, "level": _level(code[6], code[2:4], code[4:6]), "woj": code[:2],
                             "pow": code[2:4], "gmi": code[4:6], "rodz": code[6], "terc7": code, "name": g["name"],
                             "kind": RODZ.get(code[6], ""), "woj_name": woj_names.get(code[:2], ""),
                             "pow_name": pow_names.get(code[:4], ""), "province_code": f"PL{code[:2]}",
                             "_raw": e, **base})
    return rows


def build_rows(store: RawStore) -> tuple[list[dict], str]:
    z = _latest_zip(store)
    if z and store.abs(z["path"]).exists():
        rows, src = rows_from_eteryt(store, z), "eteryt_terc"
    else:
        rows, src = rows_from_bip(store), "bip_dictionary"
    order = {"woj": 0, "pow": 1, "gmi": 2, "part": 3}
    rows.sort(key=lambda r: (r["woj"], r["pow"], r["gmi"], order[r["level"]], r["rodz"]))
    seen: set[str] = set()
    out = []
    for r in rows:
        if r["terc"] in seen:
            continue
        seen.add(r["terc"])
        out.append(r)
    return out, src


def write_csv(rows: list[dict]) -> None:
    if not rows:
        return
    p = csv_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    p.write_text(buf.getvalue(), encoding="utf-8")


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    rows, _ = build_rows(store)
    write_csv(rows)
    for r in rows:
        e = r["_raw"]
        yield ExternalRecord(
            source=SOURCE, kind="teryt_unit", external_id=r["terc"], title=r["name"], teryt=r["terc"],
            province=r["woj_name"] or None, published_on=r["stan_na"] or None,
            url=e["url"] if r["source"] != "eteryt_terc" else ETERYT,
            raw_path=e["path"], raw_sha256=e.get("sha256"), data={k: r[k] for k in CSV_COLUMNS})
