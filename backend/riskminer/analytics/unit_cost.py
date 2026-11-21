"""Unit cost per km of network (§3.3). Class = subsector only (value is in the numerator, conditioning on it biases)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from riskminer.analytics.base import CaseBase
from riskminer.config import settings

NETWORK_SUBSECTORS = ("SAN", "WOD", "DESZ")          # wod-kan default; other sectors: pack analytics.unit_cost


def unit_cost_subsectors(cb: CaseBase) -> tuple[str, ...]:
    return tuple(cb.pack["unit_cost"].get("subsectors") or ())


@dataclass
class UnitCost:
    subsector: str
    user_ppk: float | None               # PLN/km
    q: dict[str, float]                  # p25, p50, p75, p90 PLN/km
    user_percentile: float | None        # share of class ppk <= user (0..1)
    n: int
    coverage: float                      # rows with a length / class rows
    length_source: str
    indexed_to: int | None = None
    sample: list[dict] = field(default_factory=list)
    case_idx: np.ndarray = field(default=None, repr=False)


def class_ppk(cb: CaseBase, subsector: str, index_to: int | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    sub = cb["subsector_main"] == subsector
    L, v = cb["length_km"], cb["value_gross"]
    with np.errstate(invalid="ignore", divide="ignore"):
        ppk = v / L
        ok = sub & np.isfinite(L) & (L >= 0.1) & (L <= 100) & (v > 50_000) & (ppk >= 50_000) & (ppk <= 20_000_000)
    idx = np.flatnonzero(ok)
    vals = ppk[idx]
    if index_to:
        idxs = price_index()
        target = idxs.get(index_to) or max(idxs.values())
        years = cb["contract_year"][idx]
        fac = np.array([target / idxs[int(y)] if np.isfinite(y) and int(y) in idxs else 1.0 for y in years])
        vals = vals * fac
    coverage = float((sub & np.isfinite(L)).sum() / max(1, sub.sum()))
    return idx, vals, coverage


def unit_cost(cb: CaseBase, subsector: str | None, budget: float | None, length_km: float | None,
              index_to: int | None = None) -> UnitCost | None:
    if subsector not in unit_cost_subsectors(cb):
        return None
    idx, vals, coverage = class_ppk(cb, subsector, index_to)
    if vals.size == 0:
        return None
    q = np.quantile(vals, [0.25, 0.5, 0.75, 0.9])
    user = budget / length_km if budget and length_km and length_km > 0 else None
    pct = float((vals <= user).mean()) if user is not None else None
    order = np.argsort(np.abs(vals - (user or q[1])))[:5]
    sample = [{"performance_id": int(cb["performance_id"][idx[i]]), "bzp_number": cb["cp_bzp_number"][idx[i]],
               "title": cb["title"][idx[i]], "length_km": float(cb["length_km"][idx[i]]),
               "value_gross": float(cb["value_gross"][idx[i]]), "ppk": float(vals[i])} for i in order]
    return UnitCost(subsector=subsector, user_ppk=user, q={"p25": float(q[0]), "p50": float(q[1]), "p75": float(q[2]),
                                                           "p90": float(q[3])},
                    user_percentile=pct, n=int(vals.size), coverage=coverage, length_source=cb.length_source,
                    indexed_to=index_to, sample=sample, case_idx=idx)


@lru_cache
def price_index() -> dict[int, float]:
    """GUS construction price index, annual, 2015 = 100 (data/ref/price_index_construction.csv). Fallback: plan §3.3."""
    fallback = {2021: 113.9, 2022: 128.4, 2023: 141.5, 2024: 150.0, 2025: 154.8}
    p = settings().ref_dir / "price_index_construction.csv"
    try:
        out: dict[int, float] = {}
        with p.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                kind = (r.get("kind") or r.get("type") or r.get("freq") or "").upper()
                base = (r.get("base") or "").upper()
                if kind.startswith("Y") and ("I4" in base or "2015" in base):
                    out[int(r.get("year"))] = float(str(r.get("value")).replace(",", "."))
        return out or fallback
    except Exception:  # noqa: BLE001 - optional reference file
        return fallback
