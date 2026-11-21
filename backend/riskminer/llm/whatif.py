"""Typed "co jeśli" questions computed from the simulation (user report, 22.11.2026: free-text what-ifs got a promise
"Policzę to w symulacji" instead of numbers). The suggested what-ifs are precomputed in analysis/simulation.py; this
module handles the same kinds with the user's own numbers, deterministically, before the LLM chat:
  materials +X%           cost shock = budget x materials share x X% (materials share: expert assumption, Katalog)
  tender N months later   risk of finishing after the programme deadline, before and after the shift (time curve)
  N offers                late share for that offer count (BZP result notices) and the chance of at least N offers
  plan X months           chance of finishing within X months (time curve), compared with the current plan
Anything else returns None and the caller falls back to the LLM chat.
"""
from __future__ import annotations

import itertools
import re

WORD_NUM = {"jedn": 1, "dw": 2, "trz": 3, "czter": 4, "pięć": 5, "pięci": 5, "sześ": 6}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _pl(x: float, dec: int = 0) -> str:
    s = f"{x:,.{dec}f}".replace(",", " ").replace(".", ",")
    return s


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def curve_at(points: list[list[float]], x: float) -> float:
    """Cumulative share completed by month x (step-wise linear interpolation, clamped)."""
    if not points:
        return 0.0
    if x <= points[0][0]:
        return float(points[0][1]) if x == points[0][0] else 0.0
    for (x0, y0), (x1, y1) in itertools.pairwise(points):
        if x0 <= x <= x1:
            return float(y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(points[-1][1])


def parse(q: str) -> tuple[str, float] | None:
    t = (q or "").lower()
    m = re.search(r"(cen\w*|materia\w*|stal\w*|asfalt\w*|rur\w*).{0,40}?(\d+(?:[,.]\d+)?)\s*(%|proc)", t) or \
        re.search(r"(\d+(?:[,.]\d+)?)\s*(%|proc)\w*.{0,40}?(cen\w*|materia\w*)", t)
    if m:
        num = next(g for g in m.groups() if g and re.fullmatch(r"\d+(?:[,.]\d+)?", g))
        return "price", _num(num)
    m = re.search(r"(przetarg|ogłosi\w*|ogłoszeni\w*|start\w*|rozpocz\w*|podpisz\w*|podpisani\w*)\D{0,30}?"
                  r"(\d+(?:[,.]\d+)?)\s*(mies|miesi)", t)
    if m and re.search(r"późn|opóźn|przesun", t):
        return "delay", _num(m.group(2))
    m = re.search(r"(\d+)\s*ofert", t)
    if m:
        return "offers", float(m.group(1))
    m = re.search(r"\b(jedn|dw|trz|czter|pięć|pięci|sześ)\w*\s+ofert", t)
    if m:
        return "offers", float(WORD_NUM[m.group(1)])
    m = re.search(r"(termin|czas|plan\w*|harmonogram\w*|budow\w*|robot\w*)\D{0,25}?(\d+(?:[,.]\d+)?)\s*(mies|miesi)", t)
    if m:
        return "plan", _num(m.group(2))
    return None


def _materials_share(sim: dict) -> float:
    for w in sim.get("whatifs") or []:
        if w.get("key") == "price":
            m = re.search(r"(\d+)%", w.get("provenance") or "")
            if m:
                return int(m.group(1)) / 100
    return 0.5


def answer(question: str, sim: dict, budget: float | None) -> dict | None:
    """Answer-shaped dict (role calc) or None when the question is not a computable what-if."""
    p = parse(question)
    if not p or sim.get("insufficient"):
        return None
    kind, x = p
    n = sim.get("n")
    src = [{"kind": "query", "id": "simulation", "label": f"symulacja, n = {n}"}]
    if kind == "price":
        if not budget:
            return None
        share = _materials_share(sim)
        shock = budget * share * x / 100
        text = (f"Wzrost cen materiałów o {_pl(x, 0 if x == int(x) else 1)}% to ok. {_pl(shock / 1e6, 2)} mln zł przy "
                f"budżecie {_pl(budget / 1e6, 1)} mln zł, jeśli materiały to {_pct(share)} wartości robót (założenie "
                "eksperta z Katalogu). Bez klauzuli waloryzacyjnej wykonawcy doliczą to ryzyko do ofert z góry; przy "
                "robotach dłuższych niż 6 mies. klauzula i tak jest obowiązkowa (art. 439 Pzp).")
        src = [{"kind": "catalogue", "id": "defaults", "label": f"założenie eksperta: materiały {_pct(share)} wartości robót"}]
    elif kind in ("delay", "plan"):
        curve = (((sim.get("metrics") or {}).get("time") or {}).get("curves") or {}).get("")
        if not curve:
            return None
        if kind == "delay":
            prog = sim.get("programme_x")
            if prog is None:
                return None
            a, b = 1 - curve_at(curve, prog), 1 - curve_at(curve, prog - x)
            text = (f"Przy przetargu {_pl(x, 0 if x == int(x) else 1)} mies. później do końca programu zostanie ok. "
                    f"{_pl(prog - x)} mies. od podpisania umowy zamiast {_pl(prog)}. Ryzyko odbioru po terminie programu "
                    + (f"się nie zmienia, ok. {_pct(a)}." if _pct(a) == _pct(b) else f"rośnie z {_pct(a)} do {_pct(b)}."))
        else:
            plan = sim.get("plan_x")
            c = curve_at(curve, x)
            text = f"Przy terminie {_pl(x, 0 if x == int(x) else 1)} mies. szansa na ukończenie w terminie to ok. {_pct(c)}"
            text += (f" (przy obecnym planie {_pl(plan)} mies. ok. {_pct(curve_at(curve, plan))})." if plan else ".")
    else:
        comp = (sim.get("metrics") or {}).get("comp") or {}
        rows = ((comp.get("drivers") or {}).get("") or {}).get("rows") or []
        k = int(x)
        row = next((r for r in rows if _offer_bucket(r["label"], k)), None)
        pts = (comp.get("curves") or {}).get("") or []
        ge = next((pt[1] for pt in pts if int(pt[0]) == k), None)
        if row is None and ge is None:
            return None
        at = "jednej ofercie" if k == 1 else f"{k} ofertach"
        parts = []
        if row is not None:
            parts.append(f"Przy {at} umowy kończyły się po terminie w {row['display']} przypadków (grupa: {row['label']})")
        if k == 1 and len(pts) > 1:
            parts.append(f"szansa, że w Twoim przetargu przyjdzie tylko jedna oferta, to ok. {_pct(pts[0][1] - pts[1][1])}")
        elif ge is not None:
            parts.append(f"szansa na co najmniej {k} {'oferty' if 2 <= k <= 4 else 'ofert'} w Twoim przetargu to ok. "
                         f"{_pct(ge)}")
        text = ", a ".join(parts) + "."
        src = [{"kind": "query", "id": "competition", "label": f"konkurencja, n = {comp.get('n')}"}]
    return {"code": None, "role": "calc", "role_label": "obliczenie", "text": text, "bars": [],
            "method": {"kind": "template", "sql": None, "template": f"whatif:{kind}"}, "sources": src, "n": n,
            "missing": [], "actions": []}


def _offer_bucket(label: str, k: int) -> bool:
    nums = [int(v) for v in re.findall(r"\d+", label)]
    if not nums:
        return False
    if "więcej" in label:
        return k >= nums[0]
    return nums[0] <= k <= (nums[-1] if len(nums) > 1 else nums[0])
