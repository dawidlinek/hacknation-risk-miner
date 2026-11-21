"""Analytics engine unit tests without a database (analytics.md §6: tests 6, 7, 9, 12 (partly), 19)."""
from __future__ import annotations

import numpy as np
import pytest

from riskminer.analysis import allocation as AL
from riskminer.analysis.features import extract
from riskminer.analytics import stats
from riskminer.analytics.lengths import lengths
from riskminer.analytics.similarity import BM25, log_gauss, tokens

pytestmark = pytest.mark.unit

CFG = {"min_n_tail": 50, "min_n_share": 30, "insufficient_n": 10}


def test_tiers():
    assert stats.tier(8, CFG) == "insufficient"
    assert stats.tier(25, CFG) == "low"
    assert stats.tier(40, CFG) == "medium"
    assert stats.tier(80, CFG) == "high"


def test_wilson_and_quantiles():
    lo, hi = stats.wilson(3, 9)
    assert 0.12 <= lo <= 0.16 and 0.58 <= hi <= 0.64
    lo, hi = stats.wilson(52, 82)
    assert 0.53 <= lo <= 0.56 and 0.71 <= hi <= 0.73
    x = np.arange(1, 101, dtype=float)
    assert abs(stats.wquantile(x, None, [0.5])[0] - 50.5) < 1e-9
    w = np.ones(100)
    assert abs(stats.kish(w) - 100) < 1e-9


@pytest.mark.parametrize("text,net,conn", [
    ("budowa sieci ok. 6 km", 6.0, None),
    ("kanał 1 234,5 mb", 1.2345, None),
    ("przyłącza o długości 250 m", None, 0.25),
    ("rurociąg na głębokości 3 m", None, None),
    ("sieć o łącznej długości 2 064 mb oraz odcinek 100 m", 2.064, None),
    ("przepompownia 450 m n.p.m.", None, None),
    ("rury DN 160 mm", None, None),
])
def test_lengths_regex(text, net, conn):
    r = lengths(text)
    assert (r["net_km"] is None) == (net is None)
    if net is not None:
        assert abs(r["net_km"] - net) < 1e-6
    if conn is not None:
        assert abs(r["conn_km"] - conn) < 1e-6


def test_allocation_mockup_math():
    # A5-Podzial.dc.html default state
    e = {"R02": 210, "R03": 90, "R04": 120, "R06": 160, "R08": 250, "R13": 230}
    ctl = {"R02": "buyer", "R03": "buyer", "R04": "neither", "R06": "neither", "R08": "buyer", "R13": "neither"}
    rec = {"R02": 0, "R03": 0, "R04": 1, "R06": 1, "R08": 1, "R13": 1}
    chosen = {"R02": 0, "R03": 0, "R04": 1, "R06": 1, "R08": 2, "R13": 1}
    rows = [{"code": c, "expected_cost_tpln": e[c], "controlled_by": ctl[c], "recommended": rec[c],
             "chosen": chosen[c]} for c in e]
    prem = {"shared": 0.1, "contractor": 0.6, "shared_if_contractor_controls": 0.0,
            "contractor_if_contractor_controls": 0.1}
    b = AL.balance(rows, prem)
    assert round(b["buyer_tpln"]) == 555 and round(b["contractor_tpln"]) == 505
    assert round(b["premium_tpln"]) == 201 and b["off_recommendation"] == 1
    assert AL.note(1).startswith("1 ryzyko podzielone")
    assert AL.note(2).startswith("2 ryzyka podzielone")


def test_similarity_kernels_and_bm25():
    v = log_gauss(np.array([7e6, 3.5e6, 14e6, 1e6]), 7e6, 0.693)
    assert abs(v[0] - 1.0) < 1e-12 and abs(v[1] - v[2]) < 1e-12 and v[3] < v[1]
    idx = BM25.build(["budowa kanalizacji sanitarnej z przepompowniami", "modernizacja stacji uzdatniania wody",
                      "kanalizacja deszczowa w drodze"])
    s, terms = idx.score("kanalizacja sanitarna i przepompownie")
    assert int(np.argmax(s)) == 0 and "sanita" in terms
    assert "gmina" not in tokens("Gmina Bestwina")


def test_regex_chips_demo():
    c = extract("Budowa kanalizacji sanitarnej ok. 6 km, 3 przepompownie, ZiW, 7 mln zł netto, 14 miesięcy, KPO")
    assert c["podsektor"]["value"] == "SAN" and c["formula"]["value"] == "design_build"
    assert abs(float(c["budzet"]["value"]["amount"]) - 7e6 * 1.23) < 1
    assert c["budzet"]["value"]["vat_basis"] == "gross" and "net" in c["budzet"]["method"]
    assert c["finansowanie"]["value"] == "KPO_B311" and c["przepompownie"]["value"] == 3


def test_templates_house_style():
    import inspect

    from riskminer.analysis import allocation, report, simulation
    from riskminer.analytics import templates
    for mod in (templates, report, simulation, allocation):
        src = inspect.getsource(mod)
        assert "\u2014" not in src and "\u00b7" not in src, mod.__name__
