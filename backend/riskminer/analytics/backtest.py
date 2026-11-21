"""Backtest W3 (analytics.md §3.8): train on contracts completed before 2024-01-01, test on later ones; class =
subsector x value bucket from the training set, global band when the class has n < 30."""
from __future__ import annotations

from typing import Any

import numpy as np

from riskminer.analytics import templates as T
from riskminer.analytics.base import CaseBase

_CACHE: dict[str, dict] = {}


def _delay(cb: CaseBase) -> np.ndarray:
    d = np.full(cb.n, np.nan)
    ok = cb["time_ok"]
    d[ok & (cb["on_time_declared"] == 1)] = 0.0
    late = ok & (cb["late"] == 1) & np.isfinite(cb["delay_days"]) & (cb["delay_days"] > 0)
    d[late] = cb["delay_days"][late]
    return d


def _pinball(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    e = y - q
    return float(np.mean(np.maximum(tau * e, (tau - 1) * e)))


def _bands(values: np.ndarray, cut: np.ndarray, test: np.ndarray, keys: np.ndarray) -> dict[str, Any]:
    ok = np.isfinite(values)
    tr, te = ok & cut, ok & test
    g = np.quantile(values[tr], [0.1, 0.8, 0.9])
    lo = np.empty(te.sum())
    p80 = np.empty_like(lo)
    p90 = np.empty_like(lo)
    y = values[te]
    kt = keys[te]
    cache: dict[str, np.ndarray] = {}
    for i, k in enumerate(kt):
        if k not in cache:
            v = values[tr & (keys == k)]
            cache[k] = np.quantile(v, [0.1, 0.8, 0.9]) if v.size >= 30 else g
        lo[i], p80[i], p90[i] = cache[k]
    return {"n_train": int(tr.sum()), "n_test": int(te.sum()),
            "inside_p10_p90": float(((y >= lo) & (y <= p90)).mean()), "above_p90": float((y > p90).mean()),
            "le_p80": float((y <= p80).mean()),
            "pinball_p90_class": _pinball(y, p90, 0.9), "pinball_p90_global": _pinball(y, np.full_like(y, g[2]), 0.9)}


def backtest(cb: CaseBase) -> dict[str, Any]:
    if cb.data_version in _CACHE:
        return _CACHE[cb.data_version]
    comp = cb["completed_on"]
    has = ~np.isnat(comp)
    cut = has & (comp < np.datetime64("2024-01-01", "D"))
    test = has & (comp >= np.datetime64("2024-01-01", "D"))
    keys = np.array([f"{s}|{b}" for s, b in zip(cb["subsector_main"], cb["value_bucket"], strict=True)], dtype=object)
    delay = _bands(_delay(cb), cut, test, keys)
    pl = cb["planned_days"]
    with np.errstate(invalid="ignore", divide="ignore"):
        delay_pct = _bands(_delay(cb) / pl * 100, cut, test, keys)
    cost = _bands(np.where(cb["cost_ok"], cb["cost_dev_pct"], np.nan), cut, test, keys)
    late = cb["late"]
    lk = late >= 0
    tr, te = lk & cut, lk & test
    glob = float((late[tr] == 1).mean())
    pred = np.empty(te.sum())
    pc: dict[str, float] = {}
    for i, k in enumerate(keys[te]):
        if k not in pc:
            m = tr & (keys == k)
            pc[k] = float((late[m] == 1).mean()) if m.sum() >= 30 else glob
        pred[i] = pc[k]
    y = (late[te] == 1).astype(float)
    out = {"delay_days": delay, "delay_pct_of_plan": delay_pct, "cost_dev_pct": cost,
           "late": {"brier_class": float(np.mean((pred - y) ** 2)), "brier_global": float(np.mean((glob - y) ** 2)),
                    "predicted": float(pred.mean()), "observed": float(y.mean()), "n_test": int(te.sum())},
           "split": "completed_on < 2024-01-01 (train) / >= 2024-01-01 (test)", "data_version": cb.data_version}
    out["note"] = (f"Sprawdziliśmy prognozy na {T.pl_num(delay['n_test'])} umowach zakończonych później: "
                   f"{T.pct(delay['inside_p10_p90'])} opóźnień mieściło się w przedziale 8 na 10.")
    out["prov"] = {"role": "calc", "review_status": "auto", "n": delay["n_test"], "method": "backtest_w3",
                   "refs": [{"kind": "query", "id": "an_contract:completed_on>=2024", "label": "umowy zakończone od 2024 r."}]}
    _CACHE[cb.data_version] = out
    return out
