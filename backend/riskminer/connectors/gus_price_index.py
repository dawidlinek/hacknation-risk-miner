"""GUS construction price index ("wskaźnik cen produkcji budowlano-montażowej") -> data/ref/price_index_construction.csv.

Source: GUS "Wskaźniki makroekonomiczne" (https://stat.gov.pl/wskazniki-makroekonomiczne/), three xlsx files:
  monthly (cz. I), quarterly (cz. II), annual (cz. III), each with a row/series for
  "wskaźnik cen produkcji budowlano-montażowej" (previous period / same period of the previous year = 100).
BDL has no construction price variable (checked 2026-11-21). Licence: GUS open data, attribution.

CSV columns: period, freq (M/Q/Y), index, base, series, source_url, raw_file.
Base codes are decoded from the sheet legend (e.g. A = same period of the previous year = 100,
B = previous period = 100, C = December of the previous year = 100, I4 = 2015 = 100). Periods >= 2015 kept.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import warnings
from collections.abc import Iterable
from typing import Any

import openpyxl

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.gus_price_index")

SOURCE = "gus_price_index"
DEFAULTS = {"min_interval": 1.0, "timeout": 120.0}

PAGE = "https://stat.gov.pl/wskazniki-makroekonomiczne/"
BASE = "https://stat.gov.pl"


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        refresh: bool = False, **opts: Any) -> dict:
    from datetime import timedelta
    ttl = timedelta(seconds=0) if refresh else None
    r = ctx.fetch(PAGE, rel_path="wskazniki_makroekonomiczne.html", ttl=ttl, note="GUS macro indicators page")
    if not r.ok:
        return {"page": r.status}
    links = sorted(set(re.findall(r'href="(/download/[^"]+\.xlsx)"', r.text())))
    got = 0
    for href in links:
        name = href.rsplit("/", 1)[1]
        fr = ctx.fetch(BASE + href, rel_path=name, ttl=ttl, note=f"GUS macro indicators {name}; GUS open data",
                       check_blocked=False)
        got += int(fr.ok)
    return {"xlsx_links": len(links), "files_ok": got}


SERIES_RX = re.compile(r"cen produkcji budowlano-?\s*montażowej", re.IGNORECASE)
FREQ = {"roczne": "Y", "kwartalne": "Q", "miesieczne": "M"}
CSV_COLUMNS = ["period", "freq", "index", "base_code", "base", "series", "source_url", "raw_file", "updated"]
MIN_YEAR = 2015


def csv_path():
    return settings().ref_dir / "price_index_construction.csv"


def _legend(text: str) -> dict[str, str]:
    out = {}
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*([A-Z]\d?)\s*[–—-]\s*(.+?)\s*$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def rows_from_file(path, freq: str) -> tuple[list[dict], str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = next((w for w in wb.worksheets if w.title.strip().upper() == "WSKAŹNIKI CEN"), None)
    if ws is None:
        return [], ""
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    updated = ""
    legend: dict[str, str] = {}
    hdr_i = None
    for i, r in enumerate(rows[:12]):
        for c in r:
            if isinstance(c, str) and c.strip().startswith("Wyszczególnienie"):
                legend = _legend(c)
                hdr_i = i
            if hasattr(c, "isoformat") and not updated:
                updated = c.isoformat()[:10]
    if hdr_i is None:
        return [], updated
    years_row = rows[hdr_i]
    sub_row = rows[hdr_i + 1] if freq in ("Q", "M") else None
    periods: dict[int, str] = {}
    year = None
    for ci in range(3, len(years_row)):
        y = years_row[ci]
        if y not in (None, ""):
            m = re.match(r"^(\d{4})", str(y).strip())
            year = m.group(1) if m else year
        if year is None:
            continue
        if freq == "Y":
            periods[ci] = year
        else:
            sub = sub_row[ci] if sub_row and ci < len(sub_row) else None
            if sub in (None, ""):
                continue
            t = str(sub).strip()
            if freq == "Q":
                q = re.match(r"^(\d)", t)
                if q:
                    periods[ci] = f"{year}-Q{q.group(1)}"
            else:
                mm = re.match(r"^(\d{1,2})", t)
                if mm:
                    periods[ci] = f"{year}-{int(mm.group(1)):02d}"
    out = []
    in_block = False
    series = ""
    for r in rows[hdr_i + 1:]:
        label = r[1] if len(r) > 1 else None
        code = str(r[2]).strip() if len(r) > 2 and r[2] not in (None, "") else ""
        if isinstance(label, str) and label.strip():
            in_block = bool(SERIES_RX.search(label))
            series = re.sub(r"\s+", " ", label).strip() if in_block else series
        if not in_block or not code:
            continue
        for ci, per in periods.items():
            v = r[ci] if ci < len(r) else None
            try:
                val = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if int(per[:4]) < MIN_YEAR:
                continue
            out.append({"period": per, "freq": freq, "index": val, "base_code": code,
                        "base": legend.get(code, code), "series": series})
    return out, updated


def build(store: RawStore) -> list[dict]:
    latest: dict[str, dict] = {}
    for e in store.entries():
        if e.get("status") == "ok" and e.get("path", "").endswith(".xlsx"):
            latest[e["url"]] = e
    rows = []
    for url, e in latest.items():
        name = url.rsplit("/", 1)[1]
        freq = next((v for k, v in FREQ.items() if k in name), None)
        if not freq:
            continue
        rs, updated = rows_from_file(store.abs(e["path"]), freq)
        for r in rs:
            r.update(source_url=url, raw_file=e["path"], updated=updated, _e=e)
        rows.extend(rs)
    order = {"Y": 0, "Q": 1, "M": 2}
    rows.sort(key=lambda r: (order[r["freq"]], r["base_code"], r["period"]))
    return rows


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    rows = build(store)
    if rows:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        csv_path().parent.mkdir(parents=True, exist_ok=True)
        csv_path().write_text(buf.getvalue(), encoding="utf-8")
    for r in rows:
        e = r["_e"]
        yield ExternalRecord(
            source=SOURCE, kind="price_index", external_id=f"{r['freq']}:{r['base_code']}:{r['period']}",
            title=f"{r['series']} {r['period']} ({r['base']})", url=PAGE, raw_path=e["path"],
            raw_sha256=e.get("sha256"), data={k: r[k] for k in CSV_COLUMNS})
