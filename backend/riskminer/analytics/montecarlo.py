"""Monte Carlo for screen 1.4: case resampling with risk attribution, mitigations, tornado (analytics.md §3.5).

Whole cases are resampled (delay, cost and causes stay correlated). Each case's excess (days over plan, cost over
value) is split equally over its cause codes; a mitigation removes part of the share of the codes it targets.
Excess of cases without a recognised cause is never removed (row „bez rozpoznanej przyczyny”).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from riskminer.analytics.base import DAYS_PER_MONTH, CaseBase
from riskminer.analytics.forecast import kernel_weights

IGNORE = {"N-FORMAL", "N-UNSPEC"}
UNATTR = "_none"


def top_code(c: str) -> str:
    return c.split(".")[0]


@dataclass
class Attribution:
    codes: list[str]                     # column order
    share: np.ndarray                    # (n_rows, n_codes), rows sum to 1 or 0
    n_r: dict[str, int]                  # rows carrying each code

    def col(self, code: str) -> int | None:
        c = top_code(code)
        return self.codes.index(c) if c in self.codes else None


def attribution(cb: CaseBase, idx: np.ndarray) -> Attribution:
    sets = [{top_code(c) for c in cb["cause_codes"][i] if c not in IGNORE} for i in idx]
    counts: dict[str, int] = {}
    for s in sets:
        for c in s:
            counts[c] = counts.get(c, 0) + 1
    codes = sorted(counts, key=lambda c: (-counts[c], c))
    share = np.zeros((len(idx), len(codes)), dtype=float)
    pos = {c: k for k, c in enumerate(codes)}
    for r, s in enumerate(sets):
        if s:
            for c in s:
                share[r, pos[c]] = 1.0 / len(s)
    return Attribution(codes=codes, share=share, n_r=counts)


@dataclass
class Effect:
    risk: str
    p_keep: float
    time_cut: float
    cost_cut: float


@dataclass
class TimeModel:
    idx: np.ndarray                      # class rows with known ratio
    ratios: np.ndarray
    planned: np.ndarray
    attr: Attribution
    sigma: float

    def weights(self, D: float) -> np.ndarray:
        return kernel_weights(self.planned, D, self.sigma)


@dataclass
class CostModel:
    idx: np.ndarray
    dev: np.ndarray                      # cost deviation as a fraction (0.04 = +4%)
    attr: Attribution


def time_model(cb: CaseBase, mask: np.ndarray, sigma: float) -> TimeModel | None:
    idx = np.flatnonzero(mask & np.isfinite(cb["ratio"]))
    if idx.size == 0:
        return None
    return TimeModel(idx=idx, ratios=cb["ratio"][idx], planned=cb["planned_days"][idx], attr=attribution(cb, idx),
                     sigma=sigma)


def cost_model(cb: CaseBase, mask: np.ndarray) -> CostModel | None:
    idx = np.flatnonzero(mask & cb["cost_ok"] & np.isfinite(cb["cost_dev_pct"]))
    if idx.size == 0:
        return None
    return CostModel(idx=idx, dev=cb["cost_dev_pct"][idx] / 100.0, attr=attribution(cb, idx))


def _removed(sh: np.ndarray, attr: Attribution, effects: list[Effect], rng: np.random.Generator,
             which: str) -> np.ndarray:
    red = np.zeros(sh.shape[0])
    for e in effects:
        k = attr.col(e.risk)
        if k is None:
            continue
        s = sh[:, k]
        prevented = rng.random(sh.shape[0]) > e.p_keep
        cut = e.time_cut if which == "time" else e.cost_cut
        red += s * np.where(prevented, 1.0, cut)
    return np.minimum(red, 1.0)


def sim_time(tm: TimeModel, D: float, effects: list[Effect], draws: int, seed: int,
             w_D: float | None = None) -> np.ndarray:
    """Durations T (days) for plan D. `w_D` = plan used for the kernel weights (default D)."""
    rng = np.random.default_rng(seed)
    w = tm.weights(w_D or D)
    j = rng.choice(tm.idx.size, size=draws, p=w / w.sum())
    r = tm.ratios[j]
    ex = np.maximum(r - 1, 0) * D
    red = _removed(tm.attr.share[j], tm.attr, effects, rng, "time")
    return D * np.minimum(r, 1) + ex * (1 - red)


def sim_cost(cm: CostModel, budget: float, effects: list[Effect], draws: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    j = rng.integers(0, cm.idx.size, size=draws)
    c = cm.dev[j]
    ex = np.maximum(c, 0)
    red = _removed(cm.attr.share[j], cm.attr, effects, rng, "cost")
    return budget * (1 + np.minimum(c, 0) + ex * (1 - red))


def cdf_points(x: np.ndarray, grid: np.ndarray) -> list[list[float]]:
    xs = np.sort(x)
    y = np.searchsorted(xs, grid, side="right") / xs.size
    return [[round(float(a), 3), round(float(b), 4)] for a, b in zip(grid, y, strict=True)]


def _band(x: np.ndarray, q: float) -> float:
    """Quantile smoothed over q±5 (the class has few cases, a single quantile jumps between them)."""
    return float(np.mean(np.percentile(x, np.linspace(q - 5, min(q + 5, 99), 11))))


@dataclass
class Tornado:
    rows: list[dict] = field(default_factory=list)


def tornado_time(tm: TimeModel, D: float, base_effects: list[Effect], draws: int, seed: int, top: int = 6,
                 min_n: int = 3, w_D: float | None = None) -> list[dict]:
    base = _band(sim_time(tm, D, base_effects, draws, seed, w_D), 80)
    out = []
    for c in tm.attr.codes:
        if tm.attr.n_r.get(c, 0) < min_n:
            continue
        T = sim_time(tm, D, base_effects + [Effect(c, 0.0, 1.0, 1.0)], draws, seed, w_D)
        out.append({"risk": c, "delta": float(base - _band(T, 80)), "n_r": tm.attr.n_r[c]})
    out.sort(key=lambda r: -r["delta"])
    return out[:top]


def tornado_cost(cm: CostModel, budget: float, base_effects: list[Effect], draws: int, seed: int, top: int = 6,
                 min_n: int = 3) -> list[dict]:
    base = _band(sim_cost(cm, budget, base_effects, draws, seed), 90)
    out = []
    for c in cm.attr.codes:
        if cm.attr.n_r.get(c, 0) < min_n:
            continue
        C = sim_cost(cm, budget, base_effects + [Effect(c, 0.0, 1.0, 1.0)], draws, seed)
        out.append({"risk": c, "delta": float((base - _band(C, 90)) / budget * 100), "n_r": cm.attr.n_r[c]})
    out.sort(key=lambda r: -r["delta"])
    return out[:top]


def unattributed_share(attr: Attribution, excess: np.ndarray) -> tuple[int, int]:
    """(cases with excess and no recognised cause, cases with excess)."""
    has = excess > 0
    none = has & (attr.share.sum(axis=1) == 0)
    return int(none.sum()), int(has.sum())


# --- competition ----------------------------------------------------------------------------------------------------

@dataclass
class Competition:
    p_ge: np.ndarray                     # P(n_offers >= N), N = 1..10
    n: int
    cancel_share: float
    n_cancel: int
    level: str


def competition(cb: CaseBase, subsector: str | None, value_gross: float | None, as_of: np.datetime64,
                bucket_edges: tuple[float, float] | None) -> Competition:
    L = cb.lots
    recent = (~np.isnat(L["published_on"])) & (L["published_on"] >= as_of - np.timedelta64(730, "D"))
    size = np.where(np.isfinite(L["est_net"]), L["est_net"] * 1.23, L["win_gross"])
    levels = []
    if subsector:
        sub = L["subsector_main"] == subsector
        if bucket_edges:
            lo, hi = bucket_edges
            levels.append(("podsektor i wartość", sub & (size >= lo) & (size < hi)))
        levels.append(("podsektor", sub))
    levels.append(("wszystkie wod-kan", np.ones(L["n_offers"].size, dtype=bool)))
    for label, m in levels:
        mm = m & recent
        offers = L["n_offers"][mm & np.isfinite(L["n_offers"]) & (L["n_offers"] > 0)]
        if offers.size >= 50 or label == "wszystkie wod-kan":
            canc = mm & (L["cancelled"] >= 0)
            p_ge = np.array([(offers >= k).mean() for k in range(1, 11)]) if offers.size else np.zeros(10)
            return Competition(p_ge=p_ge, n=int(offers.size),
                               cancel_share=float((L["cancelled"][canc] == 1).mean()) if canc.any() else 0.0,
                               n_cancel=int(canc.sum()), level=label)
    raise AssertionError("unreachable")


def late_by_offers(cb: CaseBase) -> list[tuple[str, float, int]]:
    """National late share by number of offers (what-if 'tylko jedna oferta')."""
    o, late = cb["n_offers"], cb["late"]
    ok = np.isfinite(o) & (late >= 0)
    out = []
    for label, lo, hi in (("1 oferta", 1, 1), ("2 oferty", 2, 2), ("3–4 oferty", 3, 4), ("5–7 ofert", 5, 7),
                          ("8 i więcej", 8, 999)):
        m = ok & (o >= lo) & (o <= hi)
        out.append((label, float((late[m] == 1).mean()) if m.any() else float("nan"), int(m.sum())))
    return out


def plan_days_months(d: float) -> float:
    return d / DAYS_PER_MONTH
