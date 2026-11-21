"""Small statistics toolkit: weighted quantiles, Kish n_eff, Wilson interval, bootstrap, tiers (analytics.md §1.3, §3.2)."""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

Z90 = 1.6448536269514722


def wquantile(x: np.ndarray, w: np.ndarray | None, qs: Sequence[float]) -> np.ndarray:
    """Weighted empirical quantiles with midpoint interpolation (03 §4.3). Unweighted when w is None."""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return np.full(len(qs), np.nan)
    if w is None:
        w = np.ones_like(x)
    o = np.argsort(x, kind="mergesort")
    xs, ws = x[o], np.asarray(w, dtype=float)[o]
    tot = ws.sum()
    if tot <= 0:
        return np.full(len(qs), np.nan)
    cw = (np.cumsum(ws) - ws / 2) / tot
    return np.interp(np.asarray(qs, dtype=float), cw, xs)


def kish(w: np.ndarray) -> float:
    w = np.asarray(w, dtype=float)
    s2 = float((w * w).sum())
    return float(w.sum() ** 2 / s2) if s2 > 0 else 0.0


def wilson(k: int, n: int, z: float = Z90) -> tuple[float, float]:
    """Wilson score interval (never Wald)."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap(stat: Callable[[np.ndarray], np.ndarray], n: int, p: np.ndarray | None, b: int,
              rng: np.random.Generator) -> np.ndarray:
    """Resample row indices (with probabilities p) b times; returns array (b, k) of stat(idx)."""
    out = []
    for _ in range(b):
        idx = rng.choice(n, size=n, replace=True, p=p)
        out.append(np.atleast_1d(stat(idx)))
    return np.vstack(out)


def ci90(samples: np.ndarray) -> tuple[float, float]:
    s = samples[~np.isnan(samples)]
    if s.size == 0:
        return (float("nan"), float("nan"))
    return (float(np.percentile(s, 5)), float(np.percentile(s, 95)))


def tier(n_eff: float, cfg: dict) -> str:
    if n_eff >= cfg["min_n_tail"]:
        return "high"
    if n_eff >= cfg["min_n_share"]:
        return "medium"
    if n_eff >= cfg["insufficient_n"]:
        return "low"
    return "insufficient"


TIER_LABEL = {
    "high": "Pewność: wysoka (n = {n})",
    "medium": "Pewność: średnia (n = {n})",
    "low": "Pewność: niska, mała grupa porównawcza (n = {n})",
    "insufficient": "Za mało danych (n = {n})",
}
