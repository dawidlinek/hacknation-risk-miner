"""NFOŚiGW priority programme "Gospodarka wodno-ściekowa w aglomeracjach": agreements signed per year
(dane.gov.pl dataset 2037, CC0) (docs/scrape.md §2, §3.8).

run():   GET https://api.dane.gov.pl/1.4/datasets/2037/resources -> one xlsx per year (2019-2025), stored unchanged.
parse(): every agreement row -> ExternalRecord kind="nfosigw_grant" (external_id "<year>:<agreement no.>" or
         "<year>:r<row>"), beneficiary, agreement value / grant / loan amounts, dates, TERYT where resolvable.
"""
from __future__ import annotations

import logging
import re
import warnings
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl

from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord

log = logging.getLogger("riskminer.connectors.nfosigw")

SOURCE = "nfosigw"
DEFAULTS = {"min_interval": 1.0, "timeout": 180.0}

DATASET = 2037
API = f"https://api.dane.gov.pl/1.4/datasets/{DATASET}/resources"


def _year(title: str) -> str | None:
    m = re.search(r"w\s+(\d{4})\s*r", title or "")
    return m.group(1) if m else None


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        **opts: Any) -> dict:
    """only = years."""
    r = ctx.fetch(API, params={"per_page": "100"}, rel_path="resources.json", note=f"dataset {DATASET} resources",
                  ttl=None)
    if not r.ok:
        return {"resources": r.status}
    res = (r.json() or {}).get("data") or []
    files = 0
    for item in res:
        a = item["attributes"]
        year = _year(a.get("title")) or "x"
        if only and year not in set(map(str, only)):
            continue
        url = a.get("file_url") or a.get("download_url")
        if not url:
            continue
        fmt = (a.get("format") or "bin").lower()
        fr = ctx.fetch(url, rel_path=f"nfosigw_{year}_{item['id']}.{fmt}", ttl=None, check_blocked=False,
                       note=f"NFOŚiGW agreements {year} (resource {item['id']}: {a.get('title')}); CC0")
        files += int(fr.ok)
        if limit and files >= limit:
            break
    return {"resources": len(res), "files_ok": files}


COLS = {  # header regex -> field
    r"^lp": "lp", r"numer umowy": "agreement_no", r"nazwa beneficjenta": "beneficiary",
    r"nazwa przedsięwzięcia": "title", r"kwota dofinansowania": "grant_kpln", r"koszt całkowity": "total_cost_kpln",
    r"pożyczk": "loan_kpln", r"dotacj": "subsidy_kpln", r"data": "date",
}


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v).replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    files: dict[str, dict] = {}
    for e in store.entries():
        m = re.search(r"nfosigw_(\d{4}|x)_(\d+)\.xlsx$", e.get("path") or "")
        if e.get("status") == "ok" and m:
            files[m.group(1)] = e
    for year in sorted(files):
        e = files[year]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(store.abs(e["path"]), read_only=True, data_only=True)
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            hi = next((i for i, r in enumerate(rows[:10]) if any(isinstance(c, str) and "umowy" in c.lower() for c in r)), None)
            if hi is None:
                continue
            cmap: dict[int, str] = {}
            for ci, h in enumerate(rows[hi]):
                for rx, f in COLS.items():
                    if isinstance(h, str) and re.search(rx, h.strip().lower()) and f not in cmap.values():
                        cmap[ci] = f
                        break
            for ri, r in enumerate(rows[hi + 1:], start=hi + 2):
                d = {f: (r[ci] if ci < len(r) else None) for ci, f in cmap.items()}
                if not d.get("beneficiary") and not d.get("agreement_no"):
                    continue
                for f in ("grant_kpln", "total_cost_kpln", "loan_kpln", "subsidy_kpln"):
                    if f in d:
                        d[f] = _dec(d[f])
                for f in ("beneficiary", "title", "agreement_no"):
                    if d.get(f) is not None:
                        d[f] = re.sub(r"\s+", " ", str(d[f])).strip()
                no = d.get("agreement_no") or f"r{ri}"
                total = d.get("total_cost_kpln")
                yield ExternalRecord(
                    source=SOURCE, kind="nfosigw_grant", external_id=f"{year}:{no}", title=d.get("title"),
                    buyer_name=d.get("beneficiary"),
                    value_amount=(total * 1000) if total is not None else None,
                    value_currency="PLN" if total is not None else None, value_vat_basis="unknown",
                    url=f"https://dane.gov.pl/pl/dataset/{DATASET}", raw_path=e["path"], raw_sha256=e.get("sha256"),
                    data={**{k: v for k, v in d.items() if k != "lp"}, "year_signed": int(year) if year.isdigit() else None,
                          "programme": "Gospodarka wodno-ściekowa w aglomeracjach (NFOŚiGW)",
                          "amounts_unit": "tys. zł (as published)", "sheet": ws.title, "row": ri})
        wb.close()
