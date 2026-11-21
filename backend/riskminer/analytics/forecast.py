"""Forecasts over a reference class: time (ratio model + plan-length kernel), cost, shares, programme deadline (§3.2)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from riskminer.analytics.base import DAYS_PER_MONTH, CaseBase, acfg
from riskminer.analytics.stats import ci90, kish, tier, wilson, wquantile

QS = (0.1, 0.5, 0.8, 0.9)


def seed_of(*parts: Any) -> int:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "little")


def kernel_weights(planned: np.ndarray, plan_days: float, sigma: float) -> np.ndarray:
    med = float(np.median(planned))
    rel_u = plan_days / med
    return np.exp(-np.log((planned / med) / rel_u) ** 2 / (2 * sigma ** 2))


@dataclass
class TimeForecast:
    plan_days: float
    p_on_time: float
    p_on_time_ci90: tuple[float, float]
    q_days: dict[str, float]              # p10, p50, p80, p90 (days from signing)
    q_ci90: dict[str, tuple[float, float]]
    n: int                                 # rows with known ratio
    n_eff: float
    n_unknown: int
    tier: str
    planned_p25: float
    planned_p50: float
    cdf_months: list[tuple[float, float]]  # (month, share finished)
    case_idx: np.ndarray = field(repr=False)
    weights: np.ndarray = field(repr=False)
    ratios: np.ndarray = field(repr=False)

    def months(self, q: str) -> float:
        return self.q_days[q] / DAYS_PER_MONTH

    def p_le_months(self, m: float) -> float:
        d = m * DAYS_PER_MONTH
        T = self.ratios * self.plan_days
        return float((self.weights * (T <= d)).sum() / self.weights.sum())


def time_forecast(cb: CaseBase, mask: np.ndarray, plan_days: float, seed: int = 0) -> TimeForecast | None:
    cfg = acfg()
    known = mask & np.isfinite(cb["ratio"])
    idx = np.flatnonzero(known)
    n_unknown = int((mask & cb["time_ok"] & ~np.isfinite(cb["ratio"])).sum())
    if idx.size == 0:
        return None
    r = cb["ratio"][idx]
    planned = cb["planned_days"][idx]
    w = kernel_weights(planned, plan_days, cfg["kernel_sigma_ln"])
    q = wquantile(r, w, QS) * plan_days
    p_on = float((w * (r <= 1)).sum() / w.sum())
    n = int(idx.size)
    rng = np.random.default_rng(seed)
    p = w / w.sum()

    if n >= 3:
        B = cfg["bootstrap_b"]
        rr = r[rng.choice(n, size=(B, n), replace=True, p=p)]
        bs = np.column_stack([(rr <= 1).mean(axis=1), np.quantile(rr, 0.5, axis=1) * plan_days,
                              np.quantile(rr, 0.8, axis=1) * plan_days])
    else:
        bs = np.full((1, 3), np.nan)
    pl_all = cb["planned_days"][mask & cb["time_ok"]]
    T = r * plan_days
    grid = np.linspace(max(1.0, plan_days * 0.5 / DAYS_PER_MONTH), max(T.max(), plan_days * 1.2) / DAYS_PER_MONTH, 60)
    order = np.argsort(T)
    cw = np.cumsum(w[order]) / w.sum()
    cdf = [(float(m), float(np.interp(m * DAYS_PER_MONTH, T[order], cw, left=0.0, right=1.0))) for m in grid]
    return TimeForecast(
        plan_days=plan_days, p_on_time=p_on, p_on_time_ci90=ci90(bs[:, 0]),
        q_days={f"p{int(x * 100)}": float(v) for x, v in zip(QS, q, strict=True)},
        q_ci90={"p50": ci90(bs[:, 1]), "p80": ci90(bs[:, 2])},
        n=n, n_eff=kish(w), n_unknown=n_unknown, tier=tier(kish(w), cfg),
        planned_p25=float(np.percentile(pl_all, 25)) if pl_all.size else float("nan"),
        planned_p50=float(np.median(pl_all)) if pl_all.size else float("nan"),
        cdf_months=cdf, case_idx=idx, weights=w, ratios=r)


@dataclass
class CostForecast:
    budget: float | None
    p_no_overrun: float
    p_within_10pct: float
    q_pct: dict[str, float]              # p50, p80, p90 of cost deviation in %
    paid_above_share: float
    paid_above_median_pct: float | None  # typical overrun among those who paid above
    n: int
    tier: str
    case_idx: np.ndarray = field(repr=False)


def cost_forecast(cb: CaseBase, mask: np.ndarray, budget: float | None) -> CostForecast | None:
    idx = np.flatnonzero(mask & cb["cost_ok"] & np.isfinite(cb["cost_dev_pct"]))
    if idx.size == 0:
        return None
    c = cb["cost_dev_pct"][idx]
    q = np.quantile(c, [0.5, 0.8, 0.9])
    above = c > 0.5
    return CostForecast(budget=budget, p_no_overrun=float((c <= 0.5).mean()), p_within_10pct=float((c <= 10).mean()),
                        q_pct={"p50": float(q[0]), "p80": float(q[1]), "p90": float(q[2])},
                        paid_above_share=float(above.mean()),
                        paid_above_median_pct=float(np.median(c[above])) if above.any() else None,
                        n=int(idx.size), tier=tier(idx.size, acfg()), case_idx=idx)


@dataclass
class Share:
    key: str
    k: int
    n: int
    share: float
    ci90: tuple[float, float]


def shares(cb: CaseBase, mask: np.ndarray) -> dict[str, Share]:
    out: dict[str, Share] = {}
    late = cb["late"]
    m = mask & (late >= 0)
    k, n = int((late[m] == 1).sum()), int(m.sum())
    out["late"] = Share("late", k, n, k / n if n else float("nan"), wilson(k, n))
    ch = cb["changes_count"]
    m = mask & np.isfinite(ch)
    k, n = int((ch[m] > 0).sum()), int(m.sum())
    out["changes"] = Share("changes", k, n, k / n if n else float("nan"), wilson(k, n))
    m = mask & cb["cost_ok"]
    c = cb["cost_dev_pct"][m]
    k, n = int((c > 0.5).sum()), int(m.sum())
    out["paid_above"] = Share("paid_above", k, n, k / n if n else float("nan"), wilson(k, n))
    return out


@dataclass
class DeadlineForecast:
    deadline: date
    sign_p50: date
    months_available: float          # deadline - median signing date, months
    p_before_deadline: float
    n: int
    tender_n: int
    plan_end_p50: date               # sign_p50 + plan
    buffer_days: int                 # deadline - (sign_p50 + plan)


def tender_days(cb: CaseBase, subsector: str | None) -> np.ndarray:
    a = cb.tender_days.get(subsector or "*")
    if a is None or a.size < 30:
        a = cb.tender_days.get("*", np.array([60.0]))
    return a


def deadline_forecast(cb: CaseBase, tf: TimeForecast, subsector: str | None, deadline: date, announce: date,
                      seed: int, draws: int | None = None, extra_delay_days: float = 0.0) -> DeadlineForecast:
    draws = draws or acfg()["mc_draws"]
    rng = np.random.default_rng(seed)
    td = tender_days(cb, subsector)
    p = tf.weights / tf.weights.sum()
    j = rng.choice(tf.ratios.size, size=draws, p=p)
    T = tf.ratios[j] * tf.plan_days
    sign = rng.choice(td, size=draws) + extra_delay_days
    avail = (deadline - announce).days
    p_before = float(((sign + T) <= avail).mean())
    sign_p50 = announce + timedelta(days=float(np.median(td) + extra_delay_days))
    end_p50 = sign_p50 + timedelta(days=tf.plan_days)
    return DeadlineForecast(deadline=deadline, sign_p50=sign_p50,
                            months_available=(deadline - sign_p50).days / DAYS_PER_MONTH,
                            p_before_deadline=p_before, n=tf.n, tender_n=int(td.size), plan_end_p50=end_p50,
                            buffer_days=(deadline - end_p50).days)


def verbal(p: float) -> tuple[str, int]:
    """Q card verbal answer from a probability (mockup's four steps)."""
    if p < 0.25:
        return "Nie", 0
    if p < 0.5:
        return "Raczej nie", 1
    if p < 0.75:
        return "Raczej tak", 2
    return "Tak", 3
