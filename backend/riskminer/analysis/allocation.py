"""Screen 1.5 payload (frontend.md §2 `AllocationOut`, plus api_contract J5 fields): expected cost per risk from the
data (parent-level attribution, analytics.md §3.7) and the balance math of the mockup. Positions 0 buyer, 1 shared,
2 contractor. Premium factors, delay cost rate, controllability and recommendations are expert assumptions."""
from __future__ import annotations

from typing import Any

from riskminer.analytics import templates as T
from riskminer.analytics.base import DAYS_PER_MONTH

POS = ["buyer", "shared", "contractor"]
WHO = ["Zamawiający", "Wspólnie", "Wykonawca"]
CTL = {"buyer": "buyer", "shared": "neither", "contractor": "contractor"}
DATA_CODES = {"R13": ["N-PRICE", "R13"], "R06": ["R06"], "R08": ["R08", "R01"]}
COST_RISKS = {"R08", "R13", "R01", "R07"}


def _pos(v: Any) -> int:
    if isinstance(v, int) and 0 <= v <= 2:
        return v
    if isinstance(v, str) and v in POS:
        return POS.index(v)
    raise ValueError(v)


def balance(rows: list[dict], prem: dict) -> dict:
    buyer = contr = premium = 0.0
    for r in rows:
        e, w, ctl = r["expected_cost_tpln"], r["chosen"], r["controlled_by"]
        if w == 0:
            buyer += e
        elif w == 1:
            buyer += e / 2
            contr += e / 2
            premium += e * (prem["shared_if_contractor_controls"] if ctl == "contractor" else prem["shared"])
        else:
            contr += e
            premium += e * (prem["contractor_if_contractor_controls"] if ctl == "contractor" else prem["contractor"])
    off = sum(1 for r in rows if r["chosen"] != r["recommended"])
    return {"buyer_tpln": buyer, "contractor_tpln": contr, "premium_tpln": premium, "off_recommendation": off}


def note(off: int) -> str:
    if off == 0:
        return "Podział zgodny z zaleceniami. Wykonawcy doliczą głównie za ryzyka dzielone."
    return (f"{off} {T.plural(off, 'ryzyko podzielone', 'ryzyka podzielone', 'ryzyk podzielonych')} inaczej niż "
            "zalecamy. Sprawdź uwagi pod nimi.")


def build(report: dict, sim: dict, cat: dict, choices: dict[str, Any] | None, budget: float | None,
          plan_days: float | None) -> dict:
    alloc = cat["allocation"]
    d = alloc["defaults"]
    rate = float(d.get("delay_cost_rate_per_month", 0.005))
    p = d.get("premium") or {}
    prem = {"shared": float(p.get("shared", 0.1)), "contractor": float(p.get("contractor_uncontrolled", 0.6)),
            "shared_if_contractor_controls": 0.0,
            "contractor_if_contractor_controls": float(p.get("contractor_controlled", 0.1))}
    budget = budget or 0.0
    per = {r["risk"]: r for r in (sim.get("per_risk") or [])}
    flagged = {c.split(".")[0] for f in report.get("flags", []) for c in f.get("risk_codes") or []}
    sims = report.get("similar_cases") or []
    choices = choices or {}
    rows = []
    for code, rk in alloc["risks"].items():
        if not rk.get("how"):
            continue
        dc = DATA_CODES.get(code, [code])
        stats = [per[c] for c in dc if c in per]
        e_days = sum(s["e_days"] for s in stats)
        e_cost = sum(s["e_cost_share"] for s in stats)
        n_r = sum(s["n_r"] for s in stats)
        n = stats[0]["n"] if stats else 0
        e_pln = budget * e_cost + budget * rate * e_days / DAYS_PER_MONTH
        if code in COST_RISKS and stats:
            c80 = max(s["impact_cost_pct"]["p80"] for s in stats)
            impact = f"koszt P80 +{T.pl_num(c80, 1)}%"
            impact_num = {"value": c80, "display": impact, "unit": "pct"}
        elif stats:
            d80 = max(s["impact_days"]["p80"] for s in stats)
            impact = f"P80 +{T.pl_num(d80)} dni"
            impact_num = {"value": d80, "display": impact, "unit": "days"}
        else:
            impact, impact_num = "brak danych", {"value": None, "display": "brak danych", "unit": "days"}
        rec = _pos(rk.get("recommended", "shared"))
        chosen = _pos(choices[code]) if code in choices else rec
        how = rk.get("how") or {}
        case = next((s for s in sims if any(c.split(".")[0] in dc for c in s.get("cause_codes") or [])), None)
        if case:
            dd = case.get("delay_days")
            warn = (f"W podobnej umowie ({case.get('buyer_name') or case['title'][:60]}) zmiany miały tę przyczynę"
                    + (f"; opóźnienie {T.pl_num(dd)} dni." if dd else "."))
            cases = [{"label": (case.get("buyer_name") or case["title"])[:60], "href": case["href"]}]
        else:
            warn = (f"Zalecamy: {WHO[rec].lower()}. Ryzyko po stronie, która nad nim nie panuje, wykonawca wyceni "
                    "w ofercie.")
            cases = []
        prov_calc = {"role": "calc", "review_status": "auto", "n": int(n), "method": "p(r)*impact*budget",
                     "refs": [{"kind": "query", "id": f"per_risk:{'|'.join(dc)}",
                               "label": stats[0]["level"] if stats else "brak przypadków"},
                              {"kind": "catalogue", "id": f"allocation:{code}", "label": "założenie eksperta"}]}
        rows.append({
            "code": code, "title": rk.get("label") or code, "impact_label": impact,
            "expected_cost_tpln": round(e_pln / 1000, 1),
            "controlled_by": CTL.get(rk.get("controllability", "shared"), "neither"),
            "recommended": rec, "chosen": chosen,
            "how": [how.get("buyer", ""), how.get("shared", ""), how.get("contractor", "")],
            "warning": warn, "cases": cases, "flagged": code in flagged, "n_r": n_r,
            "status": rk.get("status", "proposed"), "clause_refs": rk.get("clause_refs") or [],
            "expected_cost": {"money": {"amount": f"{e_pln:.2f}", "currency": "PLN", "vat_basis": "gross"},
                              "prov": prov_calc},
            "impact": {**impact_num, "prov": {**prov_calc, "n": int(n_r), "method": "per_risk_p80"}},
            "positions": [{"key": POS[i], "label": WHO[i], "how": h} for i, h in
                          enumerate([how.get("buyer", ""), how.get("shared", ""), how.get("contractor", "")])],
        })
    b = balance(rows, prem)
    money = lambda t: {"amount": f"{t * 1000:.2f}", "currency": "PLN", "vat_basis": "gross"}
    assumption = {"role": "source", "review_status": "proposed", "assumption": True,
                  "refs": [{"kind": "catalogue", "id": "allocation:defaults", "label": "założenie eksperta"}]}
    pending_ai = sum(1 for f in report.get("flags", []) if f.get("origin") == "AI" and f.get("review_status") == "proposed")
    in_pack = [c for c in report.get("clauses", []) if c.get("in_pack")]
    return {
        "risks": rows, "premium": prem, "premium_prov": assumption,
        "premium_attention_tpln": round(budget * 0.017 / 1000, 0) if budget else 120,
        "delay_cost_rate_per_month": rate,
        "balance": {"buyer": money(b["buyer_tpln"]), "contractor": money(b["contractor_tpln"]),
                    "premium": money(b["premium_tpln"]), "off_recommendation": b["off_recommendation"],
                    "note": note(b["off_recommendation"]),
                    "prov": {"role": "calc", "review_status": "auto", "n": len(rows), "method": "allocation_balance_v1",
                             "refs": assumption["refs"], "assumption": True}},
        "note": note(b["off_recommendation"]),
        "pack": {"items": [
            {"key": "register", "title": "Rejestr ryzyk", "note": f"{len(rows)} {T.plural(len(rows), 'ryzyko', 'ryzyka', 'ryzyk')}", "included": True},
            {"key": "matrix", "title": "Macierz podziału ryzyk", "note": "Twoje wybory", "included": True},
            {"key": "checklist", "title": "Lista kontrolna przygotowania", "note": "braki w dokumentach", "included": True},
            {"key": "clauses", "title": "Proponowane zapisy do PPU", "note": f"{len(in_pack)} w pakiecie", "included": True},
            {"key": "annex", "title": "Źródła i cytaty", "note": "numery ogłoszeń, strony dokumentów", "included": True}],
            "pending_ai": pending_ai, "formats": ["docx", "pdf", "csv", "json"]},
        "limitations": ["Oczekiwany koszt ryzyka liczony z przyczyn zmian w podobnych umowach; premie i koszt "
                        "miesiąca opóźnienia to założenia eksperta z Katalogu.", T.causes_limit(sim.get("cause_source", "keyword"))],
        "plan_days": plan_days,
    }
