"""Config, the in-memory case base (CaseBase) and refs shared by every analytics module (analytics.md §1).

The base population is `an_contract` from the plan, built here as a plain SELECT (no materialized view, so the data
session can DROP + CREATE `rc_contract` freely):
    sector = 'wod-kan' AND relevance IN ('core','cpv_only') AND scope_kind = 'works'   (live: 11 222 rows)
with quality flags `time_ok` / `cost_ok` and the reconciled duration ratio `ratio_rec` (§3.2).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analytics.lengths import lengths
from riskminer.config import app_config

DEFAULTS: dict[str, Any] = {
    "min_n_share": 30,
    "min_n_tail": 50,
    "insufficient_n": 10,
    "bootstrap_b": 1000,
    "mc_draws": 20000,
    "kernel_sigma_ln": 0.5,
    "prior_m": 10,
    "as_of": None,
    "cause_source": "ai_then_keyword",   # ai_then_keyword | keyword (change-cause codes behind the simulation)
    "reload_seconds": 21600,      # case base reload (6 h): a reload costs ~5 s on the next request
}

DAYS_PER_MONTH = 30.4375
SUBSECTORS = ("SAN", "WOD", "DESZ", "OCZ", "SUW")
FAMILY = {"SAN": "net", "WOD": "net", "DESZ": "net", "OCZ": "plant", "SUW": "plant"}
BUCKETS = ["<0.5m", "0.5-1m", "1-2m", "2-5m", "5-10m", ">10m"]
BUCKET_EDGES = [0, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, float("inf")]
BUCKET_LABEL = {"<0.5m": "wartość do 0,5 mln zł", "0.5-1m": "wartość 0,5–1 mln zł", "1-2m": "wartość 1–2 mln zł",
                "2-5m": "wartość 2–5 mln zł", "5-10m": "wartość 5–10 mln zł", ">10m": "wartość powyżej 10 mln zł"}
SUB_LABEL = {"SAN": "kanalizacja sanitarna", "WOD": "sieć wodociągowa", "DESZ": "kanalizacja deszczowa",
             "OCZ": "oczyszczalnia ścieków", "SUW": "stacja uzdatniania wody"}
SUB_LABEL_GEN = {"SAN": "kanalizacji sanitarnej", "WOD": "sieci wodociągowej", "DESZ": "kanalizacji deszczowej",
                 "OCZ": "oczyszczalni ścieków", "SUW": "stacji uzdatniania wody"}
WORK_LABEL = {"build": "budowa", "renovation": "przebudowa lub modernizacja", "mixed": "budowa i przebudowa"}
WOJ_NAME = {"02": "dolnośląskie", "04": "kujawsko-pomorskie", "06": "lubelskie", "08": "lubuskie", "10": "łódzkie",
            "12": "małopolskie", "14": "mazowieckie", "16": "opolskie", "18": "podkarpackie", "20": "podlaskie",
            "22": "pomorskie", "24": "śląskie", "26": "świętokrzyskie", "28": "warmińsko-mazurskie",
            "30": "wielkopolskie", "32": "zachodniopomorskie"}


def acfg() -> dict[str, Any]:
    c = dict(DEFAULTS)
    c.update(app_config().get("analytics") or {})
    return c


def bucket_of(v: float | None) -> str | None:
    if v is None or not np.isfinite(v):
        return None
    for i in range(len(BUCKETS)):
        if BUCKET_EDGES[i] <= v < BUCKET_EDGES[i + 1]:
            return BUCKETS[i]
    return None


def as_of() -> date:
    a = acfg().get("as_of")
    if a:
        return date.fromisoformat(str(a))
    return date.today()


# ---- sector packs (catalogue/<sector>/pack.yaml `analytics` block; a new sector is data, not code) -----------------

DEFAULT_SECTOR = "wod-kan"
_WODKAN_PACK = {
    "sector": "wod-kan", "name": "Gospodarka wodno-ściekowa (wod-kan)", "label_short": "wod-kan",
    "base_population": {"sector": "wod-kan", "relevance": ["core", "cpv_only"], "scope_kind": "works",
                        "require_subsector": False},
    "base_label": "wszystkie wykonane umowy wod-kan, 2021–2026",
    "unit_cost": {"subsectors": ["SAN", "WOD", "DESZ"], "unit": "km", "label": "koszt kilometra sieci"},
    "subsectors": [], "sub_labels": dict(SUB_LABEL), "tech_tags": None, "sector_detect": [], "status": "approved",
}
_PACKS: dict[str, dict] = {}


def sector_pack(sector: str | None) -> dict:
    """Analytics view of a sector pack: base population, labels, subsector patterns, unit-cost subsectors, tags."""
    import re

    import yaml

    from riskminer.config import settings
    sector = sector or DEFAULT_SECTOR
    if sector in _PACKS:
        return _PACKS[sector]
    if sector == DEFAULT_SECTOR:
        _PACKS[sector] = _WODKAN_PACK
        return _WODKAN_PACK
    root = Path(settings().catalogue_dir) / sector
    if not (root / "pack.yaml").exists():
        raise KeyError(sector)

    def y(name: str) -> dict:
        f = root / name
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}

    pack = y("pack.yaml")
    an = pack.get("analytics") or {}
    subs = y("subsectors.yaml").get("subsectors") or []
    lex = y("lexicon.yaml")
    out = {
        "sector": sector, "name": pack.get("name", sector), "label_short": pack.get("label_short", sector),
        "status": pack.get("status", "proposed"),
        "base_population": {"sector": sector, "relevance": ["core", "cpv_only", "component", "none"],
                            "scope_kind": "works", "require_subsector": False, **(an.get("base_population") or {})},
        "base_label": an.get("base_label") or f"wszystkie wykonane umowy ({sector})",
        "unit_cost": an.get("unit_cost") or {"subsectors": [], "unit": "km", "label": "koszt kilometra"},
        "subsectors": [{"code": x["code"], "name": x["name"],
                        "rx": [re.compile(p) for p in x.get("patterns") or []],
                        "ex": [re.compile(p) for p in x.get("exclude") or []]} for x in subs],
        "sub_labels": {x["code"]: x["name"][:1].lower() + x["name"][1:] for x in subs},
        "tech_tags": [(t["name"], t["pattern"]) for t in lex.get("tech_tags") or []] or None,
        "sector_detect": lex.get("sector_detect") or [],
        "reuse_from": an.get("reuse_from"),
    }
    _PACKS[sector] = out
    return out


def classify_subsector(pack: dict, title: str | None) -> str | None:
    t = (title or "").lower()
    for sub in pack["subsectors"]:
        if any(r.search(t) for r in sub["rx"]) and not any(r.search(t) for r in sub["ex"]):
            return sub["code"]
    return None


def known_sectors() -> list[str]:
    from riskminer.config import settings
    root = Path(settings().catalogue_dir)
    return sorted(p.name for p in root.iterdir() if (p / "pack.yaml").exists()) if root.exists() else [DEFAULT_SECTOR]


# ---------------------------------------------------------------------------------------------------------------------

_CASE_SQL = """
SELECT r.performance_id, r.contract_id, r.procedure_id, r.ocid, r.subsector_main, r.subsectors, r.work_type,
       r.design_build, r.eu_funded, r.province, p.title, p.buyer_nip, p.buyer_name, p.city AS buyer_city,
       n.extracted->'data'->>'description' AS cp_description, n.bzp_number AS cp_bzp_number,
       n.url AS cp_url, n.source_id AS cp_source_id, n.published_at::date AS cp_published_on,
       n.object_id AS cp_object_id,
       r.signed_on, r.contract_year, r.completed_on, r.completion_year, r.value_gross::float8 AS value_gross,
       r.value_bucket, r.paid_gross::float8 AS paid_gross, r.planned_days, r.actual_days, r.on_time_declared, r.late,
       r.delay_days, r.cost_dev_pct, r.changes_count, r.legal_bases, r.cause_codes, r.properly_performed,
       l.n_offers {extra}
FROM rc_contract r
JOIN contract_performance pf ON pf.id = r.performance_id
JOIN notice n ON n.id = pf.notice_id
JOIN procedure p ON p.id = r.procedure_id
LEFT JOIN contract c ON c.id = r.contract_id
LEFT JOIN lot l ON l.id = c.lot_id
WHERE r.sector = :sector AND r.relevance = ANY(:rel) AND r.scope_kind = :scope
ORDER BY r.performance_id
"""

_TENDER_DAYS_SQL = """
SELECT r.subsector_main, (r.signed_on - n.published_at::date) AS d
FROM rc_contract r JOIN notice n ON n.procedure_id = r.procedure_id AND n.notice_type = 'ContractNotice' AND n.is_latest
WHERE r.sector = :sector AND r.relevance = ANY(:rel) AND r.scope_kind = :scope
  AND r.signed_on >= n.published_at::date AND r.signed_on - n.published_at::date < 730
"""

_PILOT_SQL = """
SELECT pp.procedure_id, pr.rm_id, pr.title, pr.funding_programme, pr.works_type, pr.delivery_model, pr.subsector_main,
       pr.city
FROM project_procedure pp JOIN project pr ON pr.id = pp.project_id
WHERE coalesce(pp.review_status, 'auto') <> 'rejected'
"""

_LOTS_SQL = """
SELECT p.subsector_main, l.estimated_value_amount::float8 AS est_net, l.winning_offer_amount::float8 AS win_gross,
       l.n_offers, l.cancelled, l.cancel_basis, n.published_at::date AS published_on, p.design_build, p.title
FROM lot l JOIN procedure p ON p.id = l.procedure_id JOIN notice n ON n.id = l.result_notice_id
WHERE p.sector = :sector AND p.relevance = ANY(:rel) AND p.scope_kind = :scope
  AND l.cancelled IS NOT NULL
"""


def _arr(rows: list[dict], key: str, dtype=object, default=None) -> np.ndarray:
    if dtype is object:
        a = np.empty(len(rows), dtype=object)
        a[:] = [r.get(key, default) for r in rows]
        return a
    return np.array([default if r.get(key) is None else r.get(key) for r in rows], dtype=dtype)


def _tri(rows: list[dict], key: str) -> np.ndarray:
    """bool|None -> int8 1/0/-1."""
    return np.array([-1 if r.get(key) is None else int(bool(r.get(key))) for r in rows], dtype=np.int8)


def _dates(rows: list[dict], key: str) -> np.ndarray:
    return np.array([np.datetime64(r[key], "D") if r.get(key) else np.datetime64("NaT", "D") for r in rows],
                    dtype="datetime64[D]")


@dataclass
class CaseBase:
    n: int
    cols: dict[str, np.ndarray]
    tender_days: dict[str, np.ndarray]
    pilots: dict[int, list[dict]]            # procedure_id -> pilot projects linked to it
    lots: dict[str, np.ndarray]
    loaded_at: datetime
    data_as_of: date | None
    length_source: str                       # "procedure.length_km" | "regex_v1 (fallback)"
    cause_mode: str = "keyword"              # "ai_then_keyword" | "keyword"
    sector: str = DEFAULT_SECTOR
    idx_by_perf: dict[int, int] = field(default_factory=dict)

    def __getitem__(self, k: str) -> np.ndarray:
        return self.cols[k]

    @property
    def data_version(self) -> str:
        return f"an_contract:{self.sector}@{self.loaded_at.strftime('%Y-%m-%dT%H:%M:%SZ')}/{self.n}"

    @property
    def pack(self) -> dict:
        return sector_pack(self.sector)

    def mask_all(self) -> np.ndarray:
        return np.ones(self.n, dtype=bool)


async def _has_column(s: AsyncSession, table: str, col: str) -> bool:
    q = text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c")
    return (await s.execute(q, {"t": table, "c": col})).first() is not None


async def load_casebase(s: AsyncSession, sector: str = DEFAULT_SECTOR) -> CaseBase:
    pack = sector_pack(sector)
    bp = pack["base_population"]
    qp = {"sector": bp["sector"], "rel": list(bp["relevance"]), "scope": bp["scope_kind"]}
    has_len = await _has_column(s, "procedure", "length_km")
    extra = ", p.length_km::float8 AS length_km_db, p.conn_km::float8 AS conn_km_db" if has_len else ""
    rows = [dict(r) for r in (await s.execute(text(_CASE_SQL.format(extra=extra)), qp)).mappings().all()]
    if pack["subsectors"]:
        # the sector's own subsectors from title patterns (rc_contract.subsector_main is the wod-kan classifier)
        for r in rows:
            r["subsector_main"] = classify_subsector(pack, r.get("title"))
            r["subsectors"] = [r["subsector_main"]] if r["subsector_main"] else []
        if bp.get("require_subsector"):
            rows = [r for r in rows if r["subsector_main"]]
    c: dict[str, np.ndarray] = {}
    for k in ("performance_id", "contract_id", "procedure_id"):
        c[k] = _arr(rows, k, np.int64, 0)
    for k in ("ocid", "subsector_main", "work_type", "province", "title", "buyer_nip", "buyer_name", "buyer_city",
              "cp_description", "cp_bzp_number", "cp_url", "cp_object_id", "value_bucket"):
        c[k] = _arr(rows, k)
    for k in ("subsectors", "legal_bases", "cause_codes"):
        c[k] = np.empty(len(rows), dtype=object)
        c[k][:] = [list(r.get(k) or []) for r in rows]
    c["cp_source_id"] = _arr(rows, "cp_source_id", np.int64, 0)
    c["design_build"] = _tri(rows, "design_build")
    c["eu_funded"] = _tri(rows, "eu_funded")
    c["on_time_declared"] = _tri(rows, "on_time_declared")
    c["late"] = _tri(rows, "late")
    c["properly_performed"] = _tri(rows, "properly_performed")
    for k in ("value_gross", "paid_gross", "planned_days", "actual_days", "delay_days", "cost_dev_pct",
              "changes_count", "n_offers", "contract_year", "completion_year"):
        c[k] = _arr(rows, k, float, np.nan)
    for k in ("signed_on", "completed_on", "cp_published_on"):
        c[k] = _dates(rows, k)
    c["woj"] = np.array([(p or "")[2:4] for p in c["province"]], dtype=object)

    # quality flags (port of 04_reference_stats.py)
    comp, pub = c["completed_on"], c["cp_published_on"]
    pl, ac = c["planned_days"], c["actual_days"]
    with np.errstate(invalid="ignore"):
        c["time_ok"] = (~np.isnat(comp)) & (~np.isnat(pub)) & (comp <= pub) & (ac >= 0) & (pl > 0) & (pl <= 1826) \
            & (ac <= 1826)
        v, p = c["value_gross"], c["paid_gross"]
        ratio_paid = np.where(v > 0, p / np.where(v > 0, v, 1), np.nan)
        c["cost_ok"] = (p > 0) & (v > 0) & (ratio_paid >= 0.5) & (ratio_paid <= 2.0)
        ontime = c["time_ok"] & (c["on_time_declared"] == 1)
        late = c["time_ok"] & (c["late"] == 1) & (c["delay_days"] > 0)
        r = np.full(len(rows), np.nan)
        safe_pl = np.where(pl > 0, pl, 1)
        r[ontime] = np.minimum(ac[ontime] / safe_pl[ontime], 1.0)
        r[late] = 1.0 + c["delay_days"][late] / safe_pl[late]
        c["ratio"] = r

    # lengths: data session's column if present, else in-process regex
    L = [lengths(f"{r.get('title') or ''}. {r.get('cp_description') or ''}") for r in rows]
    c["cp_description"] = np.array([(r.get("cp_description") or "")[:1500] for r in rows], dtype=object)
    rx_len = np.array([x["net_km"] if x["net_km"] is not None else np.nan for x in L], dtype=float)
    rx_conn = np.array([x["conn_km"] if x["conn_km"] is not None else np.nan for x in L], dtype=float)
    length_source = "regex_v1"
    if has_len:
        db_len = _arr(rows, "length_km_db", float, np.nan)
        db_conn = _arr(rows, "conn_km_db", float, np.nan)
        if np.isfinite(db_len).sum() > 0.2 * len(rows):      # the data session's column is filled: prefer it
            rx_len = np.where(np.isfinite(db_len), db_len, rx_len)
            rx_conn = np.where(np.isfinite(db_conn), db_conn, rx_conn)
            length_source = "procedure.length_km"
    c["length_km"], c["conn_km"] = rx_len, rx_conn

    # change-cause codes: L's AI classification (v_contract_cause_ai, confidence >= 0.6, verified quote) first,
    # keyword rules as fallback
    c["cause_codes_kw"] = c["cause_codes"].copy()
    c["cause_source"] = np.array(["kw" if r else "" for r in c["cause_codes_kw"]], dtype=object)
    cause_mode = "keyword"
    if acfg().get("cause_source", "ai_then_keyword") == "ai_then_keyword":
        try:
            ai = {int(r[0]): list(r[1] or []) for r in (await s.execute(text(
                "SELECT contract_id, cause_codes_ai FROM v_contract_cause_ai"))).all()}
        except Exception:  # noqa: BLE001 - view owned by session L (0008); absent on older DBs
            await s.rollback()
            ai = {}
        if ai:
            cause_mode = "ai_then_keyword"
            for i, cid in enumerate(c["contract_id"]):
                codes = ai.get(int(cid))
                if codes:
                    c["cause_codes"][i] = codes
                    c["cause_source"][i] = "ai"

    # tender durations CN -> signing per subsector
    td_rows = (await s.execute(text(_TENDER_DAYS_SQL), qp)).all()
    td: dict[str, list[float]] = {}
    for sub, d in td_rows:
        td.setdefault(sub or "", []).append(float(d))
        td.setdefault("*", []).append(float(d))
    tender_days = {k: np.array(v, dtype=float) for k, v in td.items()}

    pilots: dict[int, list[dict]] = {}
    for r in (await s.execute(text(_PILOT_SQL))).mappings().all():
        pilots.setdefault(int(r["procedure_id"]), []).append(dict(r))

    lot_rows = [dict(r) for r in (await s.execute(text(_LOTS_SQL), qp)).mappings().all()]
    if pack["subsectors"]:
        for r in lot_rows:
            r["subsector_main"] = classify_subsector(pack, r.get("title"))
        if bp.get("require_subsector"):
            lot_rows = [r for r in lot_rows if r["subsector_main"]]
    lots = {
        "subsector_main": _arr(lot_rows, "subsector_main"),
        "est_net": _arr(lot_rows, "est_net", float, np.nan),
        "win_gross": _arr(lot_rows, "win_gross", float, np.nan),
        "n_offers": _arr(lot_rows, "n_offers", float, np.nan),
        "cancelled": _tri(lot_rows, "cancelled"),
        "cancel_basis": _arr(lot_rows, "cancel_basis"),
        "published_on": _dates(lot_rows, "published_on"),
        "design_build": _tri(lot_rows, "design_build"),
    }

    pubmax = c["cp_published_on"][~np.isnat(c["cp_published_on"])].max() if len(rows) else None
    cb = CaseBase(n=len(rows), cols=c, tender_days=tender_days, pilots=pilots, lots=lots,
                  loaded_at=datetime.now(UTC), data_as_of=pubmax.astype(date) if pubmax is not None else None,
                  length_source=length_source, cause_mode=cause_mode, sector=sector)
    cb.idx_by_perf = {int(pid): i for i, pid in enumerate(c["performance_id"])}
    return cb


_CBS: dict[str, tuple[CaseBase, float]] = {}
_LOCK = asyncio.Lock()


async def get_casebase(s: AsyncSession, force: bool = False, sector: str | None = None) -> CaseBase:
    """Process-level cache per sector; reloads after `analytics.reload_seconds`."""
    sector = sector or DEFAULT_SECTOR

    def fresh() -> CaseBase | None:
        hit = _CBS.get(sector)
        if hit and not force and time.monotonic() - hit[1] < acfg()["reload_seconds"]:
            return hit[0]
        return None

    if (cb := fresh()) is not None:
        return cb
    async with _LOCK:
        if (cb := fresh()) is not None:
            return cb
        # load in a worker thread with its own event loop and connection: the ~2–20 s of SQL + regex + numpy must
        # not block the API's event loop (other requests keep being served meanwhile)
        cb = await asyncio.to_thread(_load_in_thread, sector)
        _CBS[sector] = (cb, time.monotonic())
        return cb


def _load_in_thread(sector: str) -> CaseBase:
    async def run() -> CaseBase:
        from sqlalchemy.ext.asyncio import AsyncSession as _AS
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from riskminer.config import settings
        eng = create_async_engine(settings().database_url, poolclass=NullPool)
        try:
            async with _AS(eng) as s2:
                return await load_casebase(s2, sector)
        finally:
            await eng.dispose()
    return asyncio.run(run())


def cached_casebase(sector: str | None = None) -> CaseBase | None:
    hit = _CBS.get(sector or DEFAULT_SECTOR)
    return hit[0] if hit else None
