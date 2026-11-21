"""Typed "co jeśli" questions computed from the simulation (riskminer/llm/whatif.py), on the frontend demo fixture."""
from __future__ import annotations

import json

import pytest

from riskminer.config import REPO_ROOT
from riskminer.llm import whatif as W

SIM = json.loads((REPO_ROOT / "frontend/src/features/simulation/__fixtures__/simulation.demo.json").read_text())


@pytest.mark.parametrize("q,kind,x", [
    ("co jeśli ceny materiałów wzrosną o 15%", "price", 15), ("Co jeśli ogłosimy przetarg 3 miesiące później?", "delay", 3),
    ("co jeśli przyjdą 2 oferty", "offers", 2), ("co jeśli przyjdzie tylko jedna oferta?", "offers", 1),
    ("co jeśli termin 18 miesięcy", "plan", 18)])
def test_parse(q, kind, x):
    assert W.parse(q) == (kind, x)


def test_unparsable_falls_back_to_the_llm():
    assert W.parse("co jeśli będzie padać") is None and W.answer("co jeśli będzie padać", SIM, 7e6) is None


def test_price_uses_budget_and_materials_share():
    a = W.answer("co jeśli ceny materiałów wzrosną o 15%", SIM, 7_000_000)
    assert a["role"] == "calc" and "0,53 mln zł" in a["text"] and "50%" in a["text"]


def test_plan_and_offers_read_the_curves():
    assert "79%" in W.answer("co jeśli termin 18 miesięcy", SIM, 7e6)["text"]
    one = W.answer("co jeśli przyjdzie tylko jedna oferta?", SIM, 7e6)["text"]
    assert one.startswith("Przy jednej ofercie") and "31,9%" in one


def test_curve_interpolation():
    assert W.curve_at([[10, 0.0], [20, 1.0]], 15) == 0.5 and W.curve_at([[10, 0.0], [20, 1.0]], 25) == 1.0
