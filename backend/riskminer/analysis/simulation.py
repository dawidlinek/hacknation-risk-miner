"""Screen 1.4 payload (frontend.md §2 `SimulationOut`): every subset of the mitigation options precomputed for three
metrics, plus drivers (tornado), what-ifs and provenance. Deterministic: seed = hash(code, version)."""
from __future__ import annotations

import itertools
import math
from datetime import date, timedelta

import numpy as np

from riskminer.analytics import montecarlo as MC
from riskminer.analytics import refclass as RC
from riskminer.analytics import templates as T
from riskminer.analytics.base import BUCKET_EDGES, BUCKETS, DAYS_PER_MONTH, CaseBase, acfg, as_of, bucket_of
from riskminer.analytics.catalogue import programme_deadline
from riskminer.analytics.forecast import seed_of, tender_days

CODE_LABEL = {"R01": "R01 zakres", "R02": "R02 grunt", "R03": "R03 tereny i kolizje", "R04": "R04 decyzje",
              "R05": "R05 odpowiedzialność", "R06": "R06 harmonogram", "R07": "R07 roboty dodatkowe",
              "R08": "R08 rozliczenie", "R09": "R09 wymagania techniczne", "R10": "R10 odbiory",
              "R11": "R11 postępowanie", "R12": "R12 dostawy", "R13": "R13 finansowanie", "N-WEATHER": "pogoda",
              "N-SCOPE-RED": "ograniczenie zakresu", "N-CLIENT": "decyzje zamawiającego", "N-PRICE": "ceny",
              "N-COVID": "COVID-19", "N-LAW": "przepisy", MC.UNATTR: "bez rozpoznanej przyczyny"}
HIDDEN_CODES = {"R06", "R11"}           # keyword precision ~0 (analytics.md §3.5.3): hidden until LLM codes exist
HIDE_IN_TORNADO = {"R11"}
_CACHE: dict[tuple, dict] = {}


def _effects(opt: dict) -> list[MC.Effect]:
    return [MC.Effect(e["risk"], float(e.get("p_keep", 1.0)), float(e.get("time_cut", 0.0)),
                      float(e.get("cost_cut", 0.0))) for e in opt.get("effects") or []]


def _subset_key(keys: list[str]) -> str:
    return "+".join(keys)


def _ticks(lo: float, hi: float, n: int = 5, dec: int = 0) -> list[list]:
    step = (hi - lo) / (n - 1)
    return [[round(lo + i * step, 3), T.pl_num(lo + i * step, dec)] for i in range(n)]


def build(cb: CaseBase, cat: dict, ft: RC.Features, code: str, version: int, today: date | None = None) -> dict:
    key = (code, version, cb.data_version, cat.get("version"), cat["mitigations"].get("source"))
    if key in _CACHE:
        return _CACHE[key]
    cfg = acfg()
    draws = int(cfg["mc_draws"])
    tdraws = max(4000, draws // 4)
    seed = seed_of(code, version, "sim")
    today = today or date.today()
    rc = RC.build(cb, ft)
    D = ft.plan_days or float(np.median(cb["planned_days"][rc.mask & cb["time_ok"]]))
    plan_m = D / DAYS_PER_MONTH
    budget = ft.value_gross or float(np.median(cb["value_gross"][rc.mask]))
    tm = MC.time_model(cb, rc.mask, cfg["kernel_sigma_ln"])
    cm = MC.cost_model(cb, rc.mask)
    n = rc.n
    if n < cfg["insufficient_n"] or tm is None or cm is None:
        return {"n": n, "runs": 0, "insufficient": True, "options": [], "metrics": {}, "whatifs": [],
                "message": f"Za mało podobnych umów, żeby symulować (n = {n}). Pokazujemy tylko zakresy z raportu."}
    med_plan = float(np.median(cb["planned_days"][rc.mask & cb["time_ok"]]))
    opts_cat = cat["mitigations"]["items"]
    defaults = cat["mitigations"]["defaults"]
    decay = float(defaults.get("offers_decay", 0.85))
    floor_pct = float(defaults.get("cancel_floor_pct", 4))
    materials = float(defaults.get("materials_share", 0.5))

    # programme deadline in months from (median) signing
    deadline_iso = ft.deadline or programme_deadline(cat, ft.funding_programme)[0]
    _, prog = programme_deadline(cat, ft.funding_programme)
    announce = date.fromisoformat(ft.announce_date) if ft.announce_date else today
    td = tender_days(cb, ft.subsector_main)
    sign_p50 = announce + timedelta(days=float(np.median(td)))
    prog_x = None
    if deadline_iso:
        prog_x = (date.fromisoformat(deadline_iso) - sign_p50).days / DAYS_PER_MONTH

    options = []
    for o in opts_cat:
        metrics = [m if m != "competition" else "comp" for m in (o.get("metrics") or ["time", "cost", "comp"])]
        risk = (o.get("effects") or [{}])[0].get("risk") or ""
        short, label = o.get("short") or o.get("label"), o.get("label")
        if (o.get("plan") or {}).get("set") == "class_median":
            # the label must follow this analysis: the class median plan vs the plan read from the description
            med_m = round(med_plan / DAYS_PER_MONTH)
            own_m = round(ft.plan_days / DAYS_PER_MONTH) if ft.plan_days else None
            short = f"Plan {med_m} mies."
            label = (f"Termin {med_m} miesięcy (mediana grupy) zamiast {own_m}" if own_m and own_m != med_m
                     else f"Termin jak mediana grupy: {med_m} miesięcy")
        options.append({"key": o["key"], "code": o["code"], "short": short,
                        "label": label, "detail": o.get("description") or "", "risk_code": risk,
                        "affects": metrics, "effect_label": {}, "default_on": False, "assumption": True,
                        "status": o.get("status", "proposed"), "clause_refs": o.get("clause_refs") or [],
                        "plan_override": bool(o.get("plan")),
                        "prov": {"role": "source", "review_status": "approved" if o.get("status") == "approved"
                                 else "proposed", "assumption": True,
                                 "refs": [{"kind": "catalogue", "id": f"mitigation:{o['code']}",
                                           "label": "założenie eksperta"}]}})
    by_key = {o["key"]: o for o in opts_cat}
    keys = [o["key"] for o in options]
    subsets = [list(c) for r in range(len(keys) + 1) for c in itertools.combinations(keys, r)]

    # --- time ------------------------------------------------------------------------------------------------------
    time_T: dict[str, np.ndarray] = {}
    eval_by: dict[str, float] = {}
    for sub in subsets:
        effs = [e for k in sub if "time" in _metrics(by_key[k]) for e in _effects(by_key[k])]
        plan = med_plan if any(by_key[k].get("plan") for k in sub) else D
        time_T[_subset_key(sub)] = MC.sim_time(tm, plan, effs, draws, seed, w_D=plan)
        if plan != D:
            eval_by[_subset_key(sub)] = round(plan / DAYS_PER_MONTH, 2)
    allT = np.concatenate([v for v in time_T.values()]) / DAYS_PER_MONTH
    x_lo = math.floor(min(np.percentile(allT, 2), plan_m) - 1)
    x_hi = math.ceil(max(np.percentile(allT, 97), plan_m + 2, (prog_x or 0) + 1 if prog_x and prog_x < 60 else 0))
    grid = np.unique(np.concatenate([np.linspace(x_lo, x_hi, 49), [plan_m - 1e-3, plan_m, med_plan / DAYS_PER_MONTH - 1e-3,
                                                                     med_plan / DAYS_PER_MONTH]]))
    time_curves = {k: MC.cdf_points(v / DAYS_PER_MONTH, grid) for k, v in time_T.items()}
    markers_t = [{"x": round(plan_m, 2), "label": "Twój plan", "tone": "ink"}]
    if prog_x is not None and prog_x < x_hi + 6:
        markers_t.append({"x": round(prog_x, 2), "label": "koniec programu", "tone": "attention"})
    time_drivers: dict[str, dict] = {}
    for sub in subsets:
        k = _subset_key(sub)
        effs = [e for kk in sub if "time" in _metrics(by_key[kk]) for e in _effects(by_key[kk])]
        plan = med_plan if any(by_key[kk].get("plan") for kk in sub) else D
        rows = [r for r in MC.tornado_time(tm, plan, effs, tdraws, seed + 1, top=7, w_D=plan)
                if not (r["risk"] in HIDE_IN_TORNADO and cb.cause_mode == "keyword")
                and r["risk"] not in ("N-UNSPEC", "N-FORMAL")][:5]
        time_drivers[k] = {
            "title": "Co najbardziej przesuwa termin", "desc": "Dni dodawane do wyniku „8 na 10” przez każde ryzyko",
            "rows": [{"label": CODE_LABEL.get(r["risk"], r["risk"]), "risk": r["risk"], "value": round(r["delta"], 1),
                      "display": f"+{T.pl_num(max(r['delta'], 0))} d", "n_r": r["n_r"]} for r in rows],
            "provenance": f"obliczenie, symulacja {T.pl_num(tdraws)} losowań, n = {tm.idx.size}; "
                          f"{T.CAUSES_SHORT.get(cb.cause_mode, '')}"}

    # --- cost ------------------------------------------------------------------------------------------------------
    cost_C: dict[str, np.ndarray] = {}
    for sub in subsets:
        effs = [e for k in sub if "cost" in _metrics(by_key[k]) for e in _effects(by_key[k])]
        cost_C[_subset_key(sub)] = MC.sim_cost(cm, budget, effs, draws, seed + 2) / 1e6
    allC = np.concatenate(list(cost_C.values()))
    b_m = budget / 1e6
    c_lo = round(min(np.percentile(allC, 1), b_m * 0.97), 2)
    c_hi = round(max(np.percentile(allC, 98), b_m * 1.12), 2)
    cgrid = np.unique(np.concatenate([np.linspace(c_lo, c_hi, 49), [b_m - 1e-4, b_m, b_m * 1.1]]))
    cost_curves = {k: MC.cdf_points(v, cgrid) for k, v in cost_C.items()}
    cost_drivers = {}
    for sub in subsets:
        k = _subset_key(sub)
        effs = [e for kk in sub if "cost" in _metrics(by_key[kk]) for e in _effects(by_key[kk])]
        rows = MC.tornado_cost(cm, budget, effs, tdraws, seed + 3, top=5)
        cost_drivers[k] = {
            "title": "Co najbardziej podnosi koszt", "desc": "Punkty procentowe dodawane do wyniku „9 na 10”",
            "rows": [{"label": CODE_LABEL.get(r["risk"], r["risk"]), "risk": r["risk"], "value": round(r["delta"], 2),
                      "display": f"+{T.pl_num(max(r['delta'], 0), 1)} pp", "n_r": r["n_r"]} for r in rows],
            "provenance": f"obliczenie, symulacja, n = {cm.idx.size}; koszt względem wartości umowy (dolna granica)"}

    # --- competition -----------------------------------------------------------------------------------------------
    b = bucket_of(ft.value_gross)
    edges = (BUCKET_EDGES[BUCKETS.index(b)], BUCKET_EDGES[BUCKETS.index(b) + 1]) if b else None
    comp = MC.competition(cb, ft.subsector_main, ft.value_gross, np.datetime64(as_of(), "D"), edges)
    comp_curves, extras = {}, {}
    base_cancel = comp.cancel_share * 100
    for sub in subsets:
        shift = sum(float((by_key[k].get("competition") or {}).get("offers_shift", 0)) for k in sub)
        cpp = sum(float((by_key[k].get("competition") or {}).get("cancel_pp", 0)) for k in sub)
        f = decay ** shift
        pts = [[N, round(float(1 - (1 - p) * f), 4)] for N, p in zip(range(1, 11), comp.p_ge, strict=True)]
        comp_curves[_subset_key(sub)] = pts
        extras[_subset_key(sub)] = {"cancel_pct": round(max(floor_pct, base_cancel + cpp) if sub else base_cancel, 1)}
    lbo = MC.late_by_offers(cb)
    comp_drivers_row = {
        "title": "Więcej ofert, mniej opóźnień",
        "desc": "Odsetek umów zakończonych po terminie według liczby ofert w przetargu",
        "rows": [{"label": lab, "value": round(v * 100, 1), "display": f"{T.pl_num(v * 100, 1)}%", "n": nn}
                 for lab, v, nn in lbo],
        "provenance": f"obliczenie, {T.pl_num(sum(x[2] for x in lbo))} wykonanych umów wod-kan, ogłoszenia o wyniku"}
    comp_drivers = {_subset_key(s): comp_drivers_row for s in subsets}

    # --- effect labels (data-driven) -------------------------------------------------------------------------------
    t80_0 = np.percentile(time_T[""], 80)
    c90_0 = np.percentile(cost_C[""], 90)
    for o in options:
        k = o["key"]
        if "time" in o["affects"]:
            if o["plan_override"]:
                o["effect_label"]["time"] = f"plan {T.pl_num(med_plan / DAYS_PER_MONTH, 0)} mies."
            else:
                d = (t80_0 - np.percentile(time_T[k], 80))
                o["effect_label"]["time"] = f"„8 na 10” −{T.pl_num(d)} dni" if d >= 1 else "krzywa prawie bez zmian"
        if "cost" in o["affects"]:
            d = (c90_0 - np.percentile(cost_C[k], 90)) / b_m * 100
            o["effect_label"]["cost"] = f"P90 −{T.pl_num(d, 1)} pp" if d >= 0.05 else "P90 bez zmian"
        if "comp" in o["affects"]:
            sh = float((by_key[k].get("competition") or {}).get("offers_shift", 0))
            o["effect_label"]["comp"] = f"+{T.pl_num(sh, 1)} oferty"

    # --- what-ifs ----------------------------------------------------------------------------------------------------
    whatifs = []
    if prog_x is not None:
        ans = {}
        for sub in subsets:
            k = _subset_key(sub)
            Tm = time_T[k] / DAYS_PER_MONTH
            a = float((Tm > prog_x).mean())
            b2 = float((Tm > prog_x - 61 / DAYS_PER_MONTH).mean())
            tail = " przy zaznaczonych zmianach." if sub else "."
            risk = (f"Ryzyko odbioru po terminie programu się nie zmienia, ok. {T.pct(a)}{tail}"
                    if T.pct(a) == T.pct(b2) else
                    f"Ryzyko odbioru po terminie programu rośnie z {T.pct(a)} do {T.pct(b2)}{tail}")
            ans[k] = (f"Do końca programu zostanie wtedy ok. {T.pl_num(prog_x - 2, 0)} mies. od podpisania umowy "
                      f"zamiast {T.pl_num(prog_x, 0)}. " + risk)
        whatifs.append({"key": "late2", "question": "Co jeśli ogłosimy przetarg 2 miesiące później?",
                        "answer_by_subset": ans, "provenance": "obliczenie, ta sama symulacja (szablon, bez AI)",
                        "cta": "Pokaż na wykresie", "cta_active": "Usuń z wykresu",
                        "action": {"kind": "marker", "metric": "time", "x": round(prog_x - 2, 2),
                                   "label": "przetarg +2 mies."}})
    one, eight = lbo[0], lbo[-1]
    ans = {}
    for sub in subsets:
        pts = comp_curves[_subset_key(sub)]
        p1 = pts[0][1] - pts[1][1]
        ans[_subset_key(sub)] = (f"Umowy z jedną ofertą kończyły się po terminie w {T.pct(one[1])} przypadków, przy 8 "
                                 f"i więcej ofertach w {T.pct(eight[1])}. Szansa na jedną ofertę w Twoim przetargu to "
                                 f"ok. {T.pct(p1)}.")
    whatifs.append({"key": "one", "question": "Co jeśli przyjdzie tylko jedna oferta?", "answer_by_subset": ans,
                    "provenance": f"obliczenie, {T.pl_num(one[2] + sum(x[2] for x in lbo[1:]))} wykonanych umów "
                                  f"wod-kan; przetargi: n = {comp.n} ({comp.level}, ostatnie 24 mies.)",
                    "cta": "Pokaż konkurencję", "action": {"kind": "metric", "metric": "comp"}})
    k07 = next((o for o in opts_cat if o.get("price_pass_through")), None)
    ans = {}
    shock = budget * materials * 0.10
    for sub in subsets:
        if k07 and k07["key"] in sub:
            cap = float(k07["price_pass_through"].get("cap_pct", 10)) / 100 * budget
            ans[_subset_key(sub)] = (f"Z klauzulą {k07['code'].replace('M-', '')} część wzrostu zapłacisz w trakcie "
                                     f"budowy, ok. {T.pl_num(min(shock, cap) / 1e6, 2)} mln zł, jeśli materiały to "
                                     f"{T.pct(materials)} wartości robót. Bez klauzuli wykonawcy doliczą to ryzyko do "
                                     "ofert z góry.")
        else:
            ans[_subset_key(sub)] = ("Bez klauzuli waloryzacyjnej wykonawcy doliczą to ryzyko do ofert z góry, a przy "
                                     "robotach dłuższych niż 6 mies. klauzula i tak jest obowiązkowa (art. 439 Pzp).")
    whatifs.append({"key": "price", "question": "Co jeśli ceny materiałów wzrosną o 10%?", "answer_by_subset": ans,
                    "provenance": f"założenie eksperta: materiały to {T.pct(materials)} wartości robót (Katalog)",
                    "cta": "Pokaż koszt", "action": {"kind": "metric", "metric": "cost"}})

    exc_t = np.maximum(tm.ratios - 1, 0)
    k_none, k_exc = MC.unattributed_share(tm.attr, exc_t)
    honesty = (f"Efekt liczony tylko z umów, w których rozpoznano przyczynę zmiany ({k_exc - k_none} z {k_exc} "
               "opóźnionych); wielkości wpływu to założenia eksperta z Katalogu. " + T.causes_limit(cb.cause_mode))
    ref = {"kind": "query", "id": rc.query_id(), "label": f"klasa: {rc.label()} ({T.umow(n)})"}
    out = {
        "n": n, "runs": draws, "seed": seed, "insufficient": False,
        "options": options,
        "plan_x": round(plan_m, 2), "programme_x": round(prog_x, 2) if prog_x is not None else None,
        "programme": {"code": (prog or {}).get("code"), "name": (prog or {}).get("name"), "deadline": deadline_iso,
                      "sign_p50": sign_p50.isoformat()} if deadline_iso else None,
        "metrics": {
            "time": {"title": "Kiedy skończysz: odsetek ukończonych w czasie", "x_label": "miesiące od podpisania umowy",
                     "y_label": "odsetek ukończonych umów", "x_domain": [x_lo, x_hi],
                     "x_ticks": _ticks(x_lo, x_hi, 5), "shape": "cdf", "eval_x": round(plan_m, 2),
                     "eval_x_by_subset": eval_by, "markers": markers_t, "curves": time_curves,
                     "drivers": time_drivers, "n": int(tm.idx.size)},
            "cost": {"title": "Ile zapłacisz: odsetek umów do danej kwoty", "x_label": "koszt końcowy, mln zł brutto",
                     "y_label": "odsetek umów do tej kwoty", "x_domain": [c_lo, c_hi],
                     "x_ticks": _ticks(c_lo, c_hi, 5, 1), "shape": "cdf", "eval_x": round(b_m * 1.1, 3),
                     "markers": [{"x": round(b_m, 3), "label": f"budżet {T.pl_num(b_m, 1)}", "tone": "ink"},
                                 {"x": round(b_m * 1.1, 3), "label": "budżet + 10%", "tone": "muted"}],
                     "curves": cost_curves, "drivers": cost_drivers, "n": int(cm.idx.size)},
            "comp": {"title": "Ile przyjdzie ofert: szansa na co najmniej N", "x_label": "liczba ofert",
                     "y_label": "szansa na co najmniej N ofert", "x_domain": [1, 10],
                     "x_ticks": [[1, "1"], [2, "2"], [4, "4"], [6, "6"], [8, "8"], [10, "10"]], "shape": "survival",
                     "eval_x": 2, "markers": [{"x": 2, "label": "co najmniej 2 oferty", "tone": "muted"}],
                     "curves": comp_curves, "extras": extras, "drivers": comp_drivers, "n": comp.n,
                     "level": comp.level},
        },
        "whatifs": whatifs,
        "honesty_note": honesty,
        "limitations": [honesty, "Krzywe bazowe z umów klasy porównawczej (losowanie całych umów, więc opóźnienie, "
                                 "koszt i przyczyny pozostają powiązane)."],
        "cause_source": cb.cause_mode,
        "prov": {"role": "calc", "review_status": "auto", "n": n,
                 "method": f"monte_carlo(case_resampling, causes={cb.cause_mode})",
                 "refs": [ref, {"kind": "catalogue", "id": "mitigation:*", "label": "założenia eksperta"}]},
        "per_risk": per_risk(cb, rc, ft, D, budget),
    }
    _CACHE[key] = out
    if len(_CACHE) > 64:
        _CACHE.pop(next(iter(_CACHE)))
    return out


def _metrics(o: dict) -> list[str]:
    return [m if m != "competition" else "comp" for m in (o.get("metrics") or ["time", "cost", "comp"])]


def per_risk(cb: CaseBase, rc: RC.RefClass, ft: RC.Features, D: float, budget: float) -> list[dict]:
    """P(r) and impact | r at the parent level (subsector, value >= 2 mln), scaled to the user's plan and budget."""
    m = np.ones(cb.n, dtype=bool)
    if ft.subsector_main:
        m &= cb["subsector_main"] == ft.subsector_main
    if (ft.value_gross or 0) >= 2_000_000:
        m &= cb["value_gross"] >= 2_000_000
    tm = MC.time_model(cb, m, 0.5)
    cm = MC.cost_model(cb, m)
    if tm is None or cm is None:
        return []
    ex_t = np.maximum(tm.ratios - 1, 0)            # share of plan
    ex_c = np.maximum(cm.dev, 0)                    # share of value
    out = []
    for c in tm.attr.codes:
        kt = tm.attr.col(c)
        kc = cm.attr.col(c)
        has_t = tm.attr.share[:, kt] > 0
        n_r = int(has_t.sum())
        if n_r < 3:
            continue
        att_t = ex_t * tm.attr.share[:, kt]                         # attributed share of plan per case
        att_c = ex_c * cm.attr.share[:, kc] if kc is not None else np.zeros(cm.idx.size)
        has_c = cm.attr.share[:, kc] > 0 if kc is not None else np.zeros(cm.idx.size, dtype=bool)
        out.append({
            "risk": c, "label": CODE_LABEL.get(c, c), "n_r": n_r, "n": int(tm.idx.size),
            "p_r": round(n_r / tm.idx.size, 4),
            "hidden": c in HIDDEN_CODES and cb.cause_mode == "keyword",
            "impact_days": {"p50": round(float(np.percentile(att_t[has_t], 50) * D), 1),
                            "p80": round(float(np.percentile(att_t[has_t], 80) * D), 1)},
            "impact_cost_pct": {"p50": round(float(np.percentile(att_c[has_c], 50) * 100), 2) if has_c.any() else 0.0,
                                "p80": round(float(np.percentile(att_c[has_c], 80) * 100), 2) if has_c.any() else 0.0},
            "e_days": float(att_t.mean() * D),                         # expected attributed days, all cases
            "e_cost_share": float(att_c.mean()) if att_c.size else 0.0,
            "level": ("podsektor " + (ft.subsector_main or "") + (", wartość od 2 mln zł"
                                                                   if (ft.value_gross or 0) >= 2e6 else "")).strip(),
        })
    out.sort(key=lambda r: -r["p_r"])
    _ = budget
    return out
