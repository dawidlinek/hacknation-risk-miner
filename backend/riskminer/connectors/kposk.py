"""KPOŚK annual implementation reports (dane.gov.pl dataset 3213, CC BY 4.0) (docs/scrape.md §2, §3.8).

run():   GET https://api.dane.gov.pl/1.4/datasets/3213/resources  -> one xls/xlsx per report year
         (2020, 2021 are legacy .xls; 2022-2024 .xlsx), stored unchanged.
parse(): sheets "Aglomeracje" and "Oczyszczalnie" -> ExternalRecord kind="kposk_agglomeration" /
         "kposk_wwtp", one per row per report year (external_id "<year>:<id>").
         Legacy .xls files are converted to .xlsx with LibreOffice (`soffice --headless --convert-to`,
         used as a local build tool only; cached under data/derived/kposk/xlsx/).
         Investments listed in the agglomeration rows ("w trakcie realizacji" / "planowane": name, cost,
         completion date) are matched across report years per agglomeration, and the schedule-slip
         signal (planned completion date / cost changes between reports) is put into `data.slip`.
"""
from __future__ import annotations

import csv
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl
from rapidfuzz import fuzz

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.kposk")

SOURCE = "kposk"
DEFAULTS = {"min_interval": 1.0, "timeout": 180.0}

DATASET = 3213
API = f"https://api.dane.gov.pl/1.4/datasets/{DATASET}/resources"


def _year(title: str) -> str | None:
    m = re.search(r"za\s+(\d{4})", title or "")
    return m.group(1) if m else None


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        **opts: Any) -> dict:
    """only = report years (e.g. 2023,2024)."""
    r = ctx.fetch(API, params={"per_page": "100"}, rel_path="resources.json", note=f"dataset {DATASET} resources",
                  ttl=None)
    files = 0
    if not r.ok:
        return {"resources": r.status}
    res = (r.json() or {}).get("data") or []
    for item in sorted(res, key=lambda x: _year(x["attributes"].get("title")) or ""):
        a = item["attributes"]
        year = _year(a.get("title"))
        if only and year not in set(map(str, only)):
            continue
        fmt = (a.get("format") or "bin").lower()
        url = a.get("file_url") or a.get("download_url")
        if not url:
            continue
        fr = ctx.fetch(url, rel_path=f"kposk_{year}_{item['id']}.{fmt}", ttl=None,
                       note=f"KPOŚK report {year} (resource {item['id']}, {a.get('title')}); CC BY 4.0",
                       check_blocked=False)
        files += int(fr.ok)
        if limit and files >= limit:
            break
    return {"resources": len(res), "files_ok": files}


# ---------------------------------------------------------------------------------------------
# parse

def _xlsx_for(store: RawStore, e: dict) -> Path | None:
    """Raw xlsx as is; legacy xls converted once with LibreOffice into data/derived/kposk/xlsx/."""
    p = store.abs(e["path"])
    if p.suffix.lower() == ".xlsx":
        return p
    out_dir = Path(settings().data_dir) / "derived" / SOURCE / "xlsx"
    out = out_dir / (p.stem + ".xlsx")
    if out.exists() and out.stat().st_mtime >= p.stat().st_mtime:
        return out
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        log.warning("cannot read %s: LibreOffice (soffice) not installed", p.name)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as prof, tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "xlsx",
                        "--outdir", tmp, str(p)], check=False, capture_output=True, timeout=600,
                       cwd=tmp, env={**os.environ, "HOME": prof})
        conv = Path(tmp) / (p.stem + ".xlsx")
        if not conv.exists():
            log.warning("LibreOffice conversion failed for %s", p.name)
            return None
        shutil.move(str(conv), out)
    return out


def _s(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""


def _header(ws) -> tuple[list[str], list[str], int]:
    """(full labels, leaf labels, index of the first data row) using the column-numbering row."""
    rows = list(ws.iter_rows(min_row=1, max_row=14, values_only=True))
    num = None
    for i, r in enumerate(rows):
        vals = [c for c in r if c not in (None, "")]
        nums = [c for c in vals if isinstance(c, (int, float)) or (isinstance(c, str) and re.fullmatch(r"\d+[a-z]?", c.strip()))]
        if len(vals) > 10 and len(nums) / len(vals) > 0.8:
            num = i
            break
    if num is None:
        return [], [], 0
    hdr = rows[:num]
    ncol = max(len(r) for r in rows)
    full, leaf = [], []
    ff = []
    for ri, r in enumerate(hdr):
        last, outr = "", []
        for ci in range(ncol):
            v = _s(r[ci]) if ci < len(r) else ""
            if v:
                last = v
            outr.append(v or (last if ri < len(hdr) - 1 else ""))
        ff.append(outr)
    for ci in range(ncol):
        parts: list[str] = []
        for r in ff:
            if r[ci] and r[ci] not in parts:
                parts.append(r[ci])
        full.append(" / ".join(parts))
        lf = ""
        for r in hdr:
            v = _s(r[ci]) if ci < len(r) else ""
            if v:
                lf = v
        leaf.append(lf)
    return full, leaf, num + 1


def _date(v: Any) -> str | None:
    d = _date_raw(v)
    if d is None:
        return None
    try:
        date.fromisoformat(d)
    except ValueError:
        return None
    return d


def _date_raw(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    t = _s(v)
    if not t:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", t)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(20\d{2})\b", t)
    return f"{m.group(1)}-12-31" if m else None


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    t = _s(v).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(t) if t else None
    except ValueError:
        return None


AGG_FIELDS = [  # (field, "leaf"|"full", regex)
    ("agg_id", "leaf", r"^i_?d aglomeracji$"),
    ("agg_name", "leaf", r"^nazwa aglomeracji$"),
    ("status", "leaf", r"^status aglomeracji"),
    ("agg_type", "leaf", r"^rodzaj aglomeracji"),
    ("voivodeship", "leaf", r"^województwo$"),
    ("powiat", "leaf", r"^powiat$"),
    ("gmina_lead", "leaf", r"gmina wiodąca"),
    ("gmina_kind", "leaf", r"^rodzaj gminy"),
    ("gminy", "leaf", r"nazwy gmin w aglomeracji"),
    ("rlm", "leaf", r"^RLM aglomeracji"),
    ("population", "leaf", r"liczba mieszkańców w granicach aglomeracji"),
    ("pct_sewered", "leaf", r"procent skanalizowania"),
    ("sewer_km_sanitary", "full", r"sanitarnej w aglomeracji / ogółem"),
    ("sewer_km_total", "full", r"sanitarnej i ogólnospławnej \(?raz.* / ogółem"),
    ("sewer_km_built_year", "full", r"wybudowanej i odebranej.* / ogółem"),
    ("sewer_km_modernised_year", "full", r"zmodernizowanej w roku.* / ogółem"),
    ("spend_network_year_kpln", "leaf", r"^wydatki na sieć \(suma poniesionych"),
    ("spend_wwtp_year_kpln", "leaf", r"^wydatki na oczyszczalnie \(suma"),
    ("tariff_pln_m3", "leaf", r"taryf"),
    ("lat", "full", r"współrzędne geograficzne aglomeracji.*szerokość"),
    ("lon", "full", r"współrzędne geograficzne aglomeracji.*długość \(E\)"),
    ("compliant_91_271", "leaf", r"spełnienie łącznie 3 warunków"),
]
WWTP_FIELDS = [
    ("agg_id", "leaf", r"^i_?d aglomeracji$"),
    ("agg_name", "leaf", r"^nazwa aglomeracji$"),
    ("wwtp_id", "leaf", r"^i_?d oczyszczalni"),
    ("wwtp_name", "leaf", r"^nazwa oczyszczalni"),
    ("status", "leaf", r"^status oczyszczalni"),
    ("wwtp_type", "leaf", r"rodzaj oczyszczalni"),
    ("capacity_m3d", "leaf", r"^średnia \[m3/d\]"),
    ("capacity_rlm", "leaf", r"maksymalna wydajność oczyszczalni w RLM|^wydajność oczyszczalni"),
    ("lat", "full", r"współrzędne geograficzne oczyszczalni.*szerokość"),
    ("lon", "full", r"współrzędne geograficzne oczyszczalni.*długość \(E\)"),
    ("akpok_investment_type", "leaf", r"^rodzaj planowanej inwestycji zgodnie z"),
    ("akpok_completion_date", "leaf", r"^termin zakończenia inwestycji podany w"),
    ("investment_completed_in_year", "leaf", r"^inwestycja zakończona w roku"),
    ("spend_year_kpln", "leaf", r"^wydatki na oczyszczalnie \(suma"),
]
_NAME_COL = re.compile(r"^nazw[ay] (inwestycji, któr|planowanej inwestycji)", re.IGNORECASE)
BLOCK_FIELDS = [
    ("km", r"^długość"),
    ("cost_to_complete_kpln", r"^nakłady finansowe niezbędne"),
    ("in_akpok", r"^czy inwestycja była ujęta"),
    ("eu_granted_kpln", r"przyznano z UE"),
    ("date_akpok", r"^wg V?I* ?AKPOŚK|^termin zakończenia inwestycji podany w"),
    ("date_current", r"^aktualn.*termin|^planowany termin zakończenia"),
]
_STOP = re.compile(r"NAKŁADY RAZEM|WARUNKI ZGODNOŚCI|^uwagi$", re.IGNORECASE)
_DATE_FIELDS = {"date_akpok", "date_current", "akpok_completion_date"}
_NUM_FIELDS = {"km", "cost_to_complete_kpln", "eu_granted_kpln", "rlm", "population", "pct_sewered",
               "sewer_km_sanitary", "sewer_km_total", "sewer_km_built_year", "sewer_km_modernised_year",
               "spend_network_year_kpln", "spend_wwtp_year_kpln", "tariff_pln_m3", "lat", "lon", "capacity_m3d",
               "capacity_rlm", "spend_year_kpln"}


def _colmap(full: list[str], leaf: list[str], spec) -> dict[str, int]:
    out: dict[str, int] = {}
    for name, where, rx in spec:
        r = re.compile(rx, re.IGNORECASE)
        for ci in range(len(full)):
            if r.search(leaf[ci] if where == "leaf" else full[ci]):
                out[name] = ci
                break
    return out


def _blocks(full: list[str], leaf: list[str], wwtp: bool) -> list[dict]:
    names = [ci for ci, lf in enumerate(leaf) if _NAME_COL.search(lf)]
    out = []
    for k, ci in enumerate(names):
        end = names[k + 1] if k + 1 < len(names) else min(len(leaf), ci + 22)
        cols: dict[str, int] = {}
        for cj in range(ci + 1, end):
            if _STOP.search(leaf[cj]) or (not wwtp and "oczyszczal" in leaf[cj].lower() and "inwestycje" in leaf[cj].lower()):
                break
            for f, rx in BLOCK_FIELDS:
                if f not in cols and re.search(rx, leaf[cj], re.IGNORECASE):
                    cols[f] = cj
        status = "ongoing" if re.search(r"zaczęła|zaczęły", leaf[ci], re.IGNORECASE) else "planned"
        sector = "wwtp" if wwtp else ("network_modernisation" if "moderniz" in full[ci].lower() else "network_build")
        out.append({"key": f"{sector}/{status}", "name_col": ci, "cols": cols})
    return out


def _conv(field: str, v: Any) -> Any:
    if field in _DATE_FIELDS:
        return _date(v)
    if field in _NUM_FIELDS:
        n = _num(v)
        return n if n is not None else (_s(v) or None)
    if isinstance(v, (datetime, date)):
        return _date(v)
    return _s(v) or None


def _sheet_rows(ws, kind: str) -> Iterable[tuple[int, dict]]:
    full, leaf, start = _header(ws)
    if not full:
        return
    spec = WWTP_FIELDS if kind == "wwtp" else AGG_FIELDS
    cm = _colmap(full, leaf, spec)
    blocks = _blocks(full, leaf, wwtp=(kind == "wwtp"))
    completed_cols = [ci for ci, f in enumerate(full) if "data odbioru technicznego" in f.lower()]
    for ri, row in enumerate(ws.iter_rows(min_row=start + 1, values_only=True), start=start + 1):
        if not row or all(c in (None, "") for c in row[:8]):
            continue
        rec = {f: _conv(f, row[ci]) if ci < len(row) else None for f, ci in cm.items()}
        idk = "wwtp_id" if kind == "wwtp" else "agg_id"
        if not rec.get(idk) or not re.match(r"^PL", str(rec[idk])):
            continue
        invs = []
        for b in blocks:
            nm = _s(row[b["name_col"]]) if b["name_col"] < len(row) else ""
            vals = {f: _conv(f, row[ci]) if ci < len(row) else None for f, ci in b["cols"].items()}
            if not nm and not any(v not in (None, "", 0, 0.0) for v in vals.values()):
                continue
            inv = {"block": b["key"], "name": nm or None, **vals}
            if inv.get("date_akpok") and inv.get("date_current"):
                inv["delay_vs_akpok_days"] = (date.fromisoformat(inv["date_current"])
                                              - date.fromisoformat(inv["date_akpok"])).days
            invs.append(inv)
        rec["investments"] = invs
        if completed_cols:
            done = {leaf[ci]: _date(row[ci]) for ci in completed_cols if ci < len(row) and _date(row[ci])}
            if done:
                rec["investments_completed_in_year"] = done
        yield ri, rec


def _sheets(wb) -> list[tuple[Any, str]]:
    out = []
    for ws in wb.worksheets:
        t = ws.title.lower()
        if "aglomeracje" in t:
            out.append((ws, "agg"))
        elif "oczyszczalnie" in t:
            out.append((ws, "wwtp"))
        elif re.search(r"sprawozdanie\s*\d{4}", t):
            out.append((ws, "agg"))
            out.append((ws, "wwtp"))
    return out


# ---- TERYT for agglomerations (lead gmina + voivodeship) -------------------------------------
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


class _Teryt:
    def __init__(self) -> None:
        self.woj: dict[str, str] = {}
        self.gmi: dict[tuple[str, str], list[dict]] = {}
        p = settings().ref_dir / "teryt_terc.csv"
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                if r["level"] == "woj":
                    self.woj[_fold(r["name"])] = r["woj"]
                elif r["level"] == "gmi":
                    self.gmi.setdefault((r["woj"], _fold(r["name"])), []).append(r)

    def gmina(self, woj_name: str | None, gmina: str | None, kind: str | None) -> str | None:
        woj = self.woj.get(_fold(woj_name or ""))
        if not woj or not gmina:
            return woj
        name = _fold(gmina)
        name = re.sub(r"\b(gmina|gminy|miejska|wiejska|miasto|miasta|m|w|gm)\b", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        cands = self.gmi.get((woj, name), [])
        if not cands and name:
            pool = [(k[1], rows) for k, rows in self.gmi.items() if k[0] == woj]
            best = max(pool, key=lambda kv: fuzz.ratio(kv[0], name), default=None)
            if best and fuzz.ratio(best[0], name) >= 88:
                cands = best[1]
        if len(cands) > 1 and kind:
            want = {"miejska": "1", "wiejska": "2", "miejsko-wiejska": "3"}
            k = next((v for key, v in sorted(want.items(), key=lambda x: -len(x[0])) if key in kind.lower()), None)
            cands = [c for c in cands if c["rodz"] == k] or cands
        return cands[0]["terc"] if len(cands) == 1 else woj


def _slip(prev: dict, cur: dict) -> list[dict]:
    out = []
    for inv in cur.get("investments") or []:
        same = [p for p in prev.get("investments") or [] if p["block"].split("/")[0] == inv["block"].split("/")[0]]
        if not same:
            continue
        def score(p: dict, inv: dict = inv) -> float:
            sim = fuzz.token_sort_ratio(p.get("name") or "", inv.get("name") or "")
            return sim + (5 if p["block"] == inv["block"] else 0)
        best = max(same, key=score)
        sim = fuzz.token_sort_ratio(best.get("name") or "", inv.get("name") or "")
        if (inv.get("name") or best.get("name")) and sim < 75:
            continue
        d = {"block_prev": best["block"], "block_now": inv["block"], "name_now": (inv.get("name") or "")[:200],
             "name_similarity": round(sim, 1), "date_prev": best.get("date_current"), "date_now": inv.get("date_current"),
             "cost_prev_kpln": best.get("cost_to_complete_kpln"), "cost_now_kpln": inv.get("cost_to_complete_kpln")}
        if d["date_prev"] and d["date_now"]:
            d["shift_days"] = (date.fromisoformat(d["date_now"]) - date.fromisoformat(d["date_prev"])).days
        if isinstance(d["cost_prev_kpln"], float) and isinstance(d["cost_now_kpln"], float) and d["cost_prev_kpln"]:
            d["cost_change_pct"] = round(100 * (d["cost_now_kpln"] / d["cost_prev_kpln"] - 1), 1)
        out.append(d)
    return out


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    files: dict[str, dict] = {}
    for e in store.entries():
        if e.get("status") == "ok" and e.get("path") and re.search(r"kposk_(\d{4})_\d+\.xlsx?$", e["path"]):
            year = re.search(r"kposk_(\d{4})_", e["path"]).group(1)
            files[year] = e                                  # latest download per year wins
    ter = _Teryt()
    per_year: dict[str, dict[str, dict[str, tuple[int, dict, dict]]]] = {}
    for year in sorted(files):
        e = files[year]
        x = _xlsx_for(store, e)
        if x is None:
            continue
        wb = openpyxl.load_workbook(x, read_only=True, data_only=True)
        for ws, kind in _sheets(wb):
            bucket = per_year.setdefault(year, {}).setdefault(kind, {})
            idk = "wwtp_id" if kind == "wwtp" else "agg_id"
            for ri, rec in _sheet_rows(ws, kind):
                key = str(rec[idk]).strip()
                if key in bucket:      # 2020/21 combined sheet: one row per WWTP; keep the first agglomeration row
                    continue
                bucket[key] = (ri, rec, {"sheet": ws.title, "row": ri})
        wb.close()
    years = sorted(per_year)
    agg_teryt: dict[tuple[str, str], str | None] = {}
    for year in years:
        for key, (_ri, rec, _loc) in per_year[year].get("agg", {}).items():
            agg_teryt[(year, key)] = ter.gmina(rec.get("voivodeship"), rec.get("gmina_lead"), rec.get("gmina_kind"))
    for kind in ("agg", "wwtp"):
        for i, year in enumerate(years):
            prev = per_year.get(years[i - 1], {}).get(kind, {}) if i else {}
            e = files[year]
            for key, (_ri, rec, loc) in per_year[year].get(kind, {}).items():
                slip = _slip(prev[key][1], rec) if key in prev else []
                delays = [inv["delay_vs_akpok_days"] for inv in rec.get("investments") or [] if "delay_vs_akpok_days" in inv]
                shifts = [s["shift_days"] for s in slip if "shift_days" in s]
                signal = {"max_delay_vs_akpok_days": max(delays) if delays else None,
                          "max_shift_vs_prev_report_days": max(shifts) if shifts else None,
                          "prev_report_year": years[i - 1] if (i and key in prev) else None,
                          "slipped": bool((delays and max(delays) > 0) or (shifts and max(shifts) > 0))}
                teryt = agg_teryt.get((year, key if kind == "agg" else str(rec.get("agg_id") or "").strip()))
                yield ExternalRecord(
                    source=SOURCE, kind="kposk_agglomeration" if kind == "agg" else "kposk_wwtp",
                    external_id=f"{year}:{key}",
                    title=(rec.get("agg_name") if kind == "agg" else rec.get("wwtp_name")) or key,
                    published_on=None, teryt=teryt, province=rec.get("voivodeship") if kind == "agg" else None,
                    url=f"https://dane.gov.pl/pl/dataset/{DATASET}",
                    raw_path=e["path"], raw_sha256=e.get("sha256"),
                    data={"report_year": int(year), **rec, "slip": slip, "slip_signal": signal, "raw_location": loc})
