"""EU Funds project lists ("Lista projektów realizowanych z Funduszy Europejskich w Polsce") (docs/scrape.md §2).

* FE 2021-2027 (status 01.11.2026), xlsx ~41 MB:
  https://funduszeeuropejskie.gov.pl/wp-content/uploads/2026/11/Lista_projektow_FE_2021_2027_01112026.xlsx
* FE 2014-2020 (status 01.11.2026), CSV (the xlsx twin is ~59 MB):
  https://www.funduszeeuropejskie.gov.pl/media/177088/Lista_projektow_FE_2014_2020_01112026.csv
  (listed on .../projekty/lista-projektow/lista-projektow-realizowanych-z-funduszy-europejskich-w-polsce-w-latach-2014-2020/)

parse(): keeps water/sewage-related rows -> ExternalRecord kind="fe_project" with beneficiary, values, dates,
programme/measure, location (+ TERYT where resolvable). Relevance = EU intervention-field code for water supply /
waste water (2014-20: 020-022; 2021-27: 062-066) OR a water/sewage keyword in title/measure (kanalizac,
wodociąg, oczyszczal, ściek, uzdatnian, wodno-ściek, sieci wod, ...); the reason is kept in data.relevance.
Neither list has a beneficiary NIP column (checked 2026-11-21). KPO is NOT in these lists (0 rows with a KPO
programme / KPOD contract number; logged at parse time).
Licence: public (MFiPR).
"""
from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
import warnings
from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl

from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext
from riskminer.connectors.records import ExternalRecord, SourceCheck

log = logging.getLogger("riskminer.connectors.fe_projects")

SOURCE = "fe_projects"
DEFAULTS = {"min_interval": 1.0, "timeout": 900.0}

FILES = {
    "fe2021": ("https://funduszeeuropejskie.gov.pl/wp-content/uploads/2026/11/Lista_projektow_FE_2021_2027_01112026.xlsx",
               "Lista_projektow_FE_2021_2027_01112026.xlsx"),
    "fe2014": ("https://www.funduszeeuropejskie.gov.pl/media/177088/Lista_projektow_FE_2014_2020_01112026.csv",
               "Lista_projektow_FE_2014_2020_01112026.csv"),
}


def run(ctx: ScrapeContext, *, since=None, until=None, limit: int | None = None, only: list[str] | None = None,
        **opts: Any) -> dict:
    """only = fe2021 / fe2014."""
    out = {}
    for key, (url, name) in FILES.items():
        if only and key not in only:
            continue
        r = ctx.fetch(url, rel_path=name, ttl=None, note=f"{key} project list (MFiPR); public", check_blocked=False)
        out[key] = {"status": r.status, "bytes": len(r.content or b"")}
    return out


CODES_2014 = {"020", "021", "022"}                 # water supply, water management, waste water treatment
CODES_2021 = {"062", "063", "064", "065", "066"}   # water supply, water mgmt, waste water collection/treatment
KW = re.compile(r"kanaliz|wodociąg|wodociag|oczyszczal|ściek|sciek|uzdatnian|wodno-?\s*ściek|sieci wod|"
                r"stacji uzdatniania|\bSUW\b|przepompown|deszczow", re.IGNORECASE)
KW_STRONG = re.compile(r"kanaliz|wodociąg|oczyszczal|ściek|uzdatnian", re.IGNORECASE)


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    try:
        return Decimal(re.sub(r"[\s\u00a0]", "", str(v)).replace(",", "."))
    except InvalidOperation:
        return None


def _d(v: Any) -> str | None:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(v or ""))
    return m.group(0) if m else None


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ł", "l")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s)).strip()


class _Teryt:
    def __init__(self) -> None:
        self.woj: dict[str, str] = {}
        self.pow: dict[tuple[str, str], list[str]] = {}
        self.gmi: dict[tuple[str, str], list[str]] = {}
        p = settings().ref_dir / "teryt_terc.csv"
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                k = _fold(r["name"])
                if r["level"] == "woj":
                    self.woj[k] = r["woj"]
                elif r["level"] == "pow":
                    self.pow.setdefault((r["woj"], k), []).append(r["terc"])
                elif r["level"] == "gmi":
                    self.gmi.setdefault((r["woj"], k), []).append(r["terc"])

    def resolve(self, loc: str) -> str | None:
        """'WOJ.: LUBELSKIE, POW.: Biała Podlaska, GM.: X' (first location only)."""
        first = re.split(r"\s*\|\s*|;", loc or "")[0]
        m_w = re.search(r"WOJ\.:\s*([^,]+)", first)
        if not m_w:
            return None
        woj = self.woj.get(_fold(m_w.group(1)))
        if not woj:
            return None
        m_p = re.search(r"POW\.:\s*([^,]+)", first)
        m_g = re.search(r"GM\.:\s*([^,|]+)", first)
        pows = self.pow.get((woj, _fold(m_p.group(1)))) if m_p else None
        if m_g:
            g = [c for c in self.gmi.get((woj, _fold(m_g.group(1))), []) if not pows or c[:4] in pows]
            if len(g) == 1:
                return g[0]
        if pows and len(pows) == 1:
            return pows[0]
        return woj


def _relevance(title: str, measure: str, category: str, codes: set[str]) -> str | None:
    code = re.match(r"^\s*(?:[A-Z]+-)?(\d{3})", category or "")
    if code and code.group(1) in codes:
        return f"intervention_code:{code.group(1)}"
    if KW_STRONG.search(title or "") or KW.search(measure or ""):
        return "keyword"
    return None


def _rows_2021(path) -> Iterable[dict]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    hdr = None
    for i, r in enumerate(it, start=1):
        if hdr is None:
            if r and isinstance(r[0], str) and r[0].startswith("Nazwa projektu"):
                hdr = r
            continue
        if not r or not r[0]:
            continue
        g = dict(zip(range(len(r)), r, strict=False))
        yield {"row": i, "title": g.get(0), "summary": g.get(1), "contract_no": g.get(2), "beneficiary": g.get(3),
               "fund": g.get(6), "specific_objective": g.get(7), "programme": g.get(8), "priority": g.get(9),
               "measure": g.get(10), "value_total": _dec(g.get(11)), "eu_rate_pct": g.get(12),
               "value_eu": _dec(g.get(13)), "location": g.get(15), "start": _d(g.get(16)), "end": _d(g.get(17)),
               "category": g.get(18), "_codes": CODES_2021, "perspective": "2021-2027"}
    wb.close()


def _rows_2014(path) -> Iterable[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh, delimiter=";")
        for i, r in enumerate(rd, start=1):
            if i <= 3 or not r or not r[0]:
                continue
            g = dict(zip(range(len(r)), r, strict=False))
            yield {"row": i, "title": g.get(0), "summary": g.get(1), "contract_no": g.get(2), "beneficiary": g.get(3),
                   "fund": g.get(4), "programme": g.get(5), "priority": g.get(6), "measure": g.get(7),
                   "submeasure": g.get(8), "value_total": _dec(g.get(9)), "value_eligible": _dec(g.get(10)),
                   "value_eu": _dec(g.get(11)), "eu_rate_pct": g.get(12), "finance_form": g.get(13),
                   "location": g.get(14), "start": _d(g.get(16)), "end": _d(g.get(17)),
                   "category": g.get(20), "thematic_objective": g.get(21), "funding_completed": g.get(24),
                   "_codes": CODES_2014, "perspective": "2014-2020"}


def parse(store: RawStore) -> Iterable[ExternalRecord]:
    latest: dict[str, dict] = {}
    for e in store.entries():
        if e.get("status") == "ok" and e.get("path"):
            for key, (url, _name) in FILES.items():
                if e.get("url") == url:
                    latest[key] = e
    ter = _Teryt()
    kept: list[tuple[str, str, str]] = []
    stats: Counter[str] = Counter()
    seen: set[str] = set()
    for key, e in latest.items():
        path = store.abs(e["path"])
        rows = _rows_2021(path) if key == "fe2021" else _rows_2014(path)
        for r in rows:
            stats[f"{key}:rows"] += 1
            prog = f"{r.get('programme') or ''} {r.get('fund') or ''}"
            if re.search(r"odbudowy|\bKPO\b", prog, re.IGNORECASE) or str(r.get("contract_no") or "").startswith("KPO"):
                stats[f"{key}:kpo_rows"] += 1
            rel = _relevance(str(r.get("title") or ""), str(r.get("measure") or ""), str(r.get("category") or ""),
                             r["_codes"])
            if not rel:
                continue
            stats[f"{key}:kept"] += 1
            cno = re.sub(r"\s+", " ", str(r.get("contract_no") or f"{key}-r{r['row']}")).strip()
            ext = cno if cno not in seen else f"{cno}#r{r['row']}"
            seen.add(ext)
            ewt = bool(re.search(r"interreg|EWT|współpracy terytorialnej", prog, re.IGNORECASE))
            data = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items() if not k.startswith("_")}
            data.update(relevance=rel, list=key, currency_note="EUR (EWT/Interreg project)" if ewt else "PLN")
            kept.append((ext, str(r.get("beneficiary") or ""), ter.resolve(str(r.get("location") or "")) or ""))
            yield ExternalRecord(
                source=SOURCE, kind="fe_project", external_id=ext, title=r.get("title"),
                buyer_name=r.get("beneficiary"), teryt=ter.resolve(str(r.get("location") or "")),
                value_amount=r.get("value_total"), value_currency="EUR" if ewt else "PLN", value_vat_basis="unknown",
                published_on=None, url=FILES[key][0], raw_path=e["path"], raw_sha256=e.get("sha256"),
                text=(r.get("summary") or None), data=data)
    log.info("fe_projects parse stats: %s", dict(stats))
    # per pilot buyer: water/sewage FE projects of that beneficiary (name + voivodeship)
    p = settings().ref_dir / "pilot_projects.json"
    if not p.exists():
        return
    buyers: dict[str, dict] = {}
    for proj in json.loads(p.read_text(encoding="utf-8")):
        if proj.get("buyer_nip"):
            buyers.setdefault(proj["buyer_nip"], proj)
    note_kpo = f"KPO rows in lists: {stats.get('fe2021:kpo_rows', 0) + stats.get('fe2014:kpo_rows', 0)}"
    for nip, proj in sorted(buyers.items()):
        bn = _fold(re.sub(r"\s*[–-].*$", "", proj.get("buyer_name") or ""))
        bn = re.sub(r"^gmina ", "", bn)
        hits = [ext for ext, ben, terc in kept
                if terc[:2] == (proj.get("woj_teryt") or "") and re.sub(r"^(gmina|urzad gminy|urzad miejski w) ", "",
                                                                         _fold(ben)) == bn]
        yield SourceCheck(
            source=SOURCE, subject_type="organization", subject_key=nip,
            query={"beneficiary": proj.get("buyer_name"), "woj": proj.get("woj_teryt"), "lists": list(FILES)},
            n_hits=len(hits), n_relevant=len(hits), result="found" if hits else "not_found", matched_ids=hits,
            note=(f"{len(hits)} water/sewage FE 2014-20/2021-27 project(s) of this beneficiary; " if hits else
                  "no water/sewage FE 2014-20/2021-27 project with this beneficiary name; ") + note_kpo)
