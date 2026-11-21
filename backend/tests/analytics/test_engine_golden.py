"""Golden numbers on the live case base (read-only; analytics.md §6 tests 1-5, 8, 10-11, 13-15, 18).
Ranges leave room for the live BZP delta."""
from __future__ import annotations

import time

import numpy as np
import pytest

from riskminer.analytics import forecast as F
from riskminer.analytics import montecarlo as MC
from riskminer.analytics import refclass as RC
from riskminer.analytics import similarity as SIM
from riskminer.analytics import unit_cost as U
from riskminer.analytics.base import DAYS_PER_MONTH, load_casebase
from riskminer.analytics.headline import headline
from riskminer.db.session import sessionmaker

pytestmark = pytest.mark.fulldb

DEMO = RC.Features(subsector_main="SAN", value_gross=7e6, design_build=True, plan_days=14 * DAYS_PER_MONTH,
                   length_km=6.0, pumping_stations=3, work_type="build", planned_year=2027, funding_programme="FENIKS",
                   text="Budowa kanalizacji sanitarnej grawitacyjno-tłocznej z przepompowniami ścieków, "
                        "zaprojektuj i wybuduj")


@pytest.fixture(scope="module")
async def cb():
    async with sessionmaker()() as s:
        return await load_casebase(s)


async def test_base_population(cb):
    assert 11150 <= cb.n <= 11450
    assert 0.95 <= cb["time_ok"].mean() <= 0.98
    assert 0.98 <= cb["cost_ok"].mean() <= 1.0
    t = cb["time_ok"]
    assert not (cb["completed_on"][t] > cb["cp_published_on"][t]).any()


async def test_headline(cb):
    h = headline(cb)
    assert 0.295 <= h["late_share"]["value"] <= 0.310
    assert 0.405 <= h["change_share"]["value"] <= 0.425
    assert 255_000 <= h["delay_days_total"]["value"] <= 275_000
    assert 55 <= h["delay_if_late_p50"]["value"] <= 61 and 180 <= h["delay_if_late_p90"]["value"] <= 196
    assert 6.5 <= h["cost_p90_pct"]["value"] <= 7.3
    assert 560e6 <= float(h["overpaid"]["money"]["amount"]) <= 610e6


async def test_funnel_and_class_stats(cb):
    rc = RC.build(cb, DEMO)
    n = [lv.n for lv in rc.funnel]
    assert 11150 <= n[0] <= 11450 and 4250 <= n[1] <= 4420 and 360 <= n[2] <= 395 and 78 <= n[3] <= 92
    assert rc.chosen.key == "formula" and not rc.widened
    sh = F.shares(cb, rc.mask)
    assert 0.60 <= sh["late"].share <= 0.67 and 0.73 <= sh["changes"].share <= 0.80
    cf = F.cost_forecast(cb, rc.mask, 7e6)
    assert 3.5 <= cf.q_pct["p80"] <= 4.8 and 9.5 <= cf.q_pct["p90"] <= 12.5


async def test_widening(cb):
    rc = RC.build(cb, RC.Features(subsector_main="DESZ", value_gross=7e6, design_build=True))
    assert rc.widened and rc.widen_note and rc.chosen.n_time >= 50


async def test_forecast_demo_14m(cb):
    rc = RC.build(cb, DEMO)
    tf = F.time_forecast(cb, rc.mask, DEMO.plan_days, seed=1)
    assert 0.30 <= tf.p_on_time <= 0.42
    lo, hi = tf.p_on_time_ci90
    assert 0.12 <= hi - lo <= 0.24
    m = {k: tf.months(k) for k in ("p10", "p50", "p80", "p90")}
    assert 12.5 <= m["p10"] <= 14.5 and 15.0 <= m["p50"] <= 16.5 and 17.5 <= m["p80"] <= 19.5
    assert 19.5 <= m["p90"] <= 22.5
    assert 0.70 <= tf.p_le_months(18) <= 0.85
    assert DEMO.plan_days < tf.planned_p25          # F6 fires
    again = F.time_forecast(cb, rc.mask, DEMO.plan_days, seed=1)
    assert again.p_on_time_ci90 == tf.p_on_time_ci90


async def test_unit_cost_san(cb):
    u = U.unit_cost(cb, "SAN", 7e6, 6)
    assert 1700 <= u.n <= 2100
    assert 0.40e6 <= u.q["p25"] <= 0.56e6 and 0.76e6 <= u.q["p50"] <= 0.92e6 and 1.30e6 <= u.q["p75"] <= 1.52e6
    assert 0.60 <= u.user_percentile <= 0.72
    assert 0.45 <= u.coverage <= 0.58
    assert U.unit_cost(cb, "OCZ", 7e6, 6) is None


async def test_similarity_demo(cb):
    sc = SIM.score_pool(cb, DEMO)
    pil = [i for i in np.argsort(-sc.S) if SIM.is_pilot(i)]
    rms = []
    for i in pil:
        if SIM.rm_id(i) not in rms:
            rms.append(SIM.rm_id(i))
    assert "RM-2026-013" in rms[:3]
    best = {r: max(sc.S[i] for i in pil if SIM.rm_id(i) == r) for r in rms}
    assert best["RM-2026-013"] >= 0.65 and best.get("RM-2026-003", 0) < best["RM-2026-013"]
    i = pil[0]
    assert abs(sum(c["c"] for c in SIM.contributions(sc, i)) - sc.S[i]) < 1e-9


async def test_mc_demo_and_perf(cb):
    rc = RC.build(cb, DEMO)
    tm = MC.time_model(cb, rc.mask, 0.5)
    cm = MC.cost_model(cb, rc.mask)
    t0 = time.perf_counter()
    T = MC.sim_time(tm, DEMO.plan_days, [], 20000, 7)
    assert time.perf_counter() - t0 < 0.05
    tf = F.time_forecast(cb, rc.mask, DEMO.plan_days, seed=1)
    assert abs((T <= DEMO.plan_days).mean() - tf.p_on_time) <= 0.03
    assert 17.5 <= np.percentile(T, 80) / DAYS_PER_MONTH <= 19.5
    C = MC.sim_cost(cm, 7e6, [], 20000, 7)
    assert 0.09 <= np.percentile(C, 90) / 7e6 - 1 <= 0.125
    assert 0.85 <= (C <= 7.7e6).mean() <= 0.92
    top = [r["risk"] for r in MC.tornado_time(tm, DEMO.plan_days, [], 5000, 3, top=3)]
    assert "R04" in top and "R07" in top
    geo = MC.sim_time(tm, DEMO.plan_days, [MC.Effect("R02", 0.5, 0.4, 0.4)], 20000, 7)
    assert np.percentile(geo, 80) <= np.percentile(T, 80) + 1e-9


async def test_competition_demo(cb):
    comp = MC.competition(cb, "SAN", 7e6, np.datetime64("2026-11-21", "D"), (5e6, 10e6))
    assert 0.93 <= comp.p_ge[1] <= 0.98
    med = 1 + int((comp.p_ge >= 0.5).sum()) - 1
    assert 5 <= med <= 7


async def test_backtest(cb):
    from riskminer.analytics.backtest import backtest
    b = backtest(cb)
    assert 0.83 <= b["delay_days"]["inside_p10_p90"] <= 0.87
    assert 0.86 <= b["delay_pct_of_plan"]["inside_p10_p90"] <= 0.90
    assert 0.77 <= b["cost_dev_pct"]["inside_p10_p90"] <= 0.82
    assert b["late"]["brier_class"] < b["late"]["brier_global"]


async def test_tender_by_year(cb):
    from riskminer.analytics.competition import tenders_by_year
    gold = {2021: (26.9, 14.8, 24.0), 2022: (32.7, 20.3, 24.6), 2023: (26.2, 17.3, 18.1), 2024: (19.1, 12.3, 12.4),
            2025: (14.3, 7.8, 11.5), 2026: (14.2, 7.2, 8.6)}
    rows = {r["year"]: r for r in tenders_by_year(cb)}
    for y, (canc, price, single) in gold.items():
        r = rows[y]
        assert abs(r["cancelled_pct"] - canc) <= 1.5 and abs(r["cancelled_price_pct"] - price) <= 1.5
        assert abs(r["single_offer_pct"] - single) <= 1.5


async def test_cause_codes_source(cb):
    has = np.array([bool(c) for c in cb["cause_codes"]])
    changed = cb["changes_count"] > 0
    assert has[changed].mean() >= 0.80             # AI codes (or keyword fallback) cover most changed contracts
