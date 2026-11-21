"""Report composition for screen 1.2 (frontend.md §2 `AnalysisReport`, plus api_contract J2 fields and `prov`).

Pure: takes the case base, catalogue and features, returns (report dict, analysis items). Every number carries
provenance: `provenance` (ProvLine for the UI) and `prov` (api/prov.py Prov: role, n, method, refs, ci90).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from riskminer.analytics import flags as FL
from riskminer.analytics import forecast as F
from riskminer.analytics import refclass as RC
from riskminer.analytics import similarity as SIM
from riskminer.analytics import templates as T
from riskminer.analytics import unit_cost as U
from riskminer.analytics.base import DAYS_PER_MONTH, SUB_LABEL, CaseBase, acfg
from riskminer.analytics.catalogue import programme_deadline

CAUSE_LABEL = {"N-WEATHER": "warunki atmosferyczne", "N-SCOPE-RED": "ograniczenie zakresu",
               "N-CLIENT": "decyzje zamawiającego", "N-PRICE": "wzrost cen", "N-COVID": "COVID-19",
               "N-LAW": "zmiana przepisów", "N-FORMAL": "zmiany formalne", "N-UNSPEC": "bez wskazanej przyczyny"}


# --- provenance helpers ---------------------------------------------------------------------------------------------

def q_ref(rc: RC.RefClass) -> dict:
    return {"kind": "query", "id": rc.query_id(), "label": f"klasa: {rc.label()} ({T.umow(rc.n)} z BZP)"}


def prov_calc(n: int, method: str, refs: list[dict], ci90: tuple[float, float] | None = None,
              assumption: bool = False) -> dict:
    ins = n < acfg()["insufficient_n"]
    p = {"role": "calc", "review_status": "auto", "n": int(n), "method": method, "refs": refs,
         "ci90": [round(ci90[0], 4), round(ci90[1], 4)] if ci90 and all(map(math.isfinite, ci90)) else None,
         "insufficient": True if ins else None}
    if assumption:
        p["assumption"] = True
    return p


def provline(n: int | None, text: str, origin: str = "CALC", review_status: str = "auto") -> dict:
    return {"origin": origin, "text": text, "n": n, "review_status": review_status}


def num(value: float | None, display: str, unit: str, prov: dict) -> dict:
    if prov.get("insufficient"):
        return {"value": None, "display": T.pl_num(None) if value is None else "za mało danych", "unit": unit,
                "prov": prov}
    return {"value": None if value is None else round(float(value), 4), "display": display, "unit": unit, "prov": prov}


def _r(x: float | None, d: int = 2) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), d)


# --- main -----------------------------------------------------------------------------------------------------------

def compose(cb: CaseBase, cat: dict, ft: RC.Features, *, code: str, version: int, seed: int,
            documents: list[dict] | None = None, chips: dict | None = None, ai_flags: list[dict] | None = None,
            in_pack: set[str] | None = None, analysis_date: date | None = None) -> tuple[dict, list[dict]]:
    cfg = acfg()
    documents = documents or []
    chips = chips or {}
    in_pack = in_pack or set()
    today = analysis_date or date.today()
    items: list[dict] = []

    rc = RC.build(cb, ft)
    ref = q_ref(rc)
    tf = F.time_forecast(cb, rc.mask, ft.plan_days, seed=seed) if ft.plan_days else None
    cf = F.cost_forecast(cb, rc.mask, ft.value_gross)
    sh = F.shares(cb, rc.mask)
    uc = U.unit_cost(cb, ft.subsector_main, ft.value_gross, ft.length_km)
    insufficient = rc.n < cfg["insufficient_n"]

    # programme deadline
    deadline_iso, prog = (ft.deadline, None) if ft.deadline else programme_deadline(cat, ft.funding_programme)
    if ft.deadline and ft.funding_programme:
        _, prog = programme_deadline(cat, ft.funding_programme)
    announce = date.fromisoformat(ft.announce_date) if ft.announce_date else today
    dl = None
    if tf is not None and deadline_iso:
        dl = F.deadline_forecast(cb, tf, ft.subsector_main, date.fromisoformat(deadline_iso), announce, seed + 7)
    sign_p50 = announce + timedelta(days=float(np.median(F.tender_days(cb, ft.subsector_main))))

    # --- funnel ------------------------------------------------------------------------------------------------------
    funnel = [{"key": lv.key, "label": lv.label, "n": lv.n, "n_time": lv.n_time, "n_cost": lv.n_cost,
               "filter": lv.filters, "width_pct": round(RC.funnel_bar_width(lv.n, rc.n_all), 1),
               "prov": prov_calc(lv.n, "rc_count", [{"kind": "query", "id": "rc:" + ("|".join(
                   f"{k}={v}" for k, v in lv.filters.items()) or "all"), "label": lv.label}])}
              for lv in rc.funnel]
    reference_class = {"label": rc.label(), "n": rc.n, "funnel": funnel,
                       "final": {"n": rc.n, "n_time": rc.chosen.n_time, "n_cost": rc.chosen.n_cost,
                                 "label": rc.chosen.label, "filter": rc.chosen.filters, "widened": rc.widened,
                                 "min_n": {"share": cfg["min_n_share"], "tail": cfg["min_n_tail"]}},
                       "widened": rc.widened, "widen_note": rc.widen_note, "reweight_note": rc.reweight_note,
                       "tier": tf.tier if tf else None, "data_version": cb.data_version,
                       "sector": cb.sector, "sector_label": cb.pack["name"], "sector_status": cb.pack["status"],
                       "period": ["2021-01-01", cb.data_as_of.isoformat() if cb.data_as_of else None]}
    items.append({"section": "funnel", "key": "funnel", "title": "Grupa porównawcza", "origin": "CALC",
                  "body": reference_class})

    # --- questions ---------------------------------------------------------------------------------------------------
    questions: list[dict] = []
    plan_m = ft.plan_days / DAYS_PER_MONTH if ft.plan_days else None
    if tf is not None and plan_m:
        ins = tf.n < cfg["insufficient_n"]
        ans, step = F.verbal(tf.p_on_time) if not ins else ("Nie wiemy", None)
        p10, p50, p80, p90 = (tf.months(k) for k in ("p10", "p50", "p80", "p90"))
        show_p90 = tf.n_eff >= cfg["min_n_tail"]
        lo_ax = max(0, math.floor(min(p10, plan_m) - 2))
        hi_ax = math.ceil(max(p90 if show_p90 else p80, plan_m, (dl.months_available if dl else 0) or 0) + 2) \
            if dl and dl.months_available < 60 else math.ceil(max(p90 if show_p90 else p80, plan_m) + 2)
        prog_x = round(dl.months_available, 1) if dl and dl.months_available < 60 else None
        method = "rc_ratio_kernel+bootstrap_ci90"
        pv = prov_calc(tf.n, method, [ref], tf.p_on_time_ci90)
        txt = f"obliczenie, n = {tf.n}" + (f", przedział 90%: {T.pct(tf.p_on_time_ci90[0])}–"
                                            f"{T.pct(tf.p_on_time_ci90[1])}" if not ins else "")
        qc = {
            "key": "time", "question": T.q_time(plan_m), "answer": ans, "answer_step": step,
            "tone": "neutral" if ins else ("bad" if tf.p_on_time < 0.5 else "good"),
            "key_value": None if ins else _r(tf.p_on_time, 3), "key_kind": "chance",
            "key_display": "za mało danych" if ins else f"{T.pct(tf.p_on_time)} szans",
            "scale": {"min": lo_ax, "max": hi_ax, "lo_label": f"{lo_ax} mies.", "hi_label": f"{hi_ax} mies."},
            "band": None if ins else {"from": _r(p10, 1), "to": _r(p90 if show_p90 else p80, 1),
                                      "kind": "p10_p90" if show_p90 else "p10_p80",
                                      "caption": T.BAND_CAPTION if show_p90 else "7 na 10 podobnych umów"},
            "median": None if ins else _r(p50, 1), "you": _r(plan_m, 1), "programme_end": prog_x,
            "n": tf.n, "insufficient": ins,
            "aria": (f"Szansa na termin {T.pct(tf.p_on_time)}; 8 na 10 podobnych umów trwało od "
                     f"{T.pl_num(p10, 1)} do {T.pl_num(p90, 1)} mies.; mediana {T.pl_num(p50, 1)} mies.")
            if not ins else f"Za mało danych (n = {tf.n}).",
            "provenance": provline(tf.n, txt), "metric": "time",
            "key_number": num(tf.p_on_time, f"{T.pct(tf.p_on_time)} szans", "share", pv),
            "range": {"unit": "months", "axis": [lo_ax, hi_ax], "p10": _r(p10, 1), "p50": _r(p50, 1),
                      "p80": _r(p80, 1), "p90": _r(p90, 1) if show_p90 else None, "you": _r(plan_m, 1),
                      "marker": {"x": prog_x, "label": "koniec programu"} if prog_x else None, "n": tf.n,
                      "plain": f"8 na 10 podobnych umów trwało do {T.pl_num(p80, 1)} mies."},
            "stats": {"p_on_time": _r(tf.p_on_time, 4), "ci90": [_r(x, 4) for x in tf.p_on_time_ci90],
                      "q_months": {k: _r(tf.months(k), 2) for k in ("p10", "p50", "p80", "p90")},
                      "q_ci90_days": {k: [_r(a, 1) for a in v] for k, v in tf.q_ci90.items()},
                      "n_eff": _r(tf.n_eff, 1), "n_unknown": tf.n_unknown, "tier": tf.tier,
                      "planned_p25_months": _r(tf.planned_p25 / DAYS_PER_MONTH, 1),
                      "planned_p50_months": _r(tf.planned_p50 / DAYS_PER_MONTH, 1),
                      "p_le_18": _r(tf.p_le_months(18), 3),
                      "definition": "termin = data wykonania (5.2) wobec planowanego końca (4.2); w terminie wg 5.3"},
        }
        questions.append(qc)
        items.append({"section": "q_time", "key": "time", "title": qc["question"], "origin": "CALC", "body": qc})

    if ft.subsector_main in U.unit_cost_subsectors(cb):
        if uc is not None and uc.user_ppk is not None:
            pctl = uc.user_percentile
            ins = uc.n < cfg["insufficient_n"]
            # answer: is the budget enough? higher ppk than most = enough
            ans = "Nie wiemy" if ins else ("Nie" if pctl < 0.25 else "Raczej nie" if pctl < 0.5 else
                                           "Raczej tak" if pctl < 0.75 else "Tak")
            ppk_m = uc.user_ppk / 1e6
            qv = {k: v / 1e6 for k, v in uc.q.items()}
            hi = max(2.0, math.ceil(max(qv["p75"], ppk_m) * 1.2 * 2) / 2)
            pv = prov_calc(uc.n, "unit_cost_percentile", [{"kind": "query", "id": f"rc:{ft.subsector_main}|length_km",
                                                           "label": "umowy z długością sieci w opisie"}])
            qc = {
                "key": "budget", "question": T.q_budget(ft.value_gross), "answer": ans,
                "answer_step": None if ins else ["Nie", "Raczej nie", "Raczej tak", "Tak"].index(ans),
                "tone": "neutral" if ins else ("bad" if pctl < 0.25 else "good" if pctl >= 0.5 else "neutral"),
                "key_value": _r(ppk_m, 3), "key_kind": "mln_per_km", "key_display": f"{T.pl_num(ppk_m, 2)} mln zł/km",
                "scale": {"min": 0, "max": hi, "lo_label": "0", "hi_label": f"{T.pl_num(hi, 1)} mln zł/km"},
                "band": {"from": _r(qv["p25"], 3), "to": _r(qv["p75"], 3), "kind": "p25_p75",
                         "caption": T.BAND_CAPTION_PPK},
                "median": _r(qv["p50"], 3), "you": _r(ppk_m, 3), "programme_end": None, "n": uc.n,
                "insufficient": ins,
                "aria": (f"Koszt kilometra {T.pl_num(ppk_m, 2)} mln zł; połowa podobnych umów między "
                         f"{T.pl_num(qv['p25'], 2)} a {T.pl_num(qv['p75'], 2)} mln zł/km; wyżej niż "
                         f"{T.pct(pctl)} umów."),
                "provenance": provline(uc.n, f"obliczenie, n = {uc.n}, {T.pl_num(pctl * 100, 0)}. percentyl"),
                "metric": "cost",
                "key_number": num(ppk_m, f"{T.pl_num(ppk_m, 2)} mln zł/km", "mln_pln_per_km", pv),
                "range": {"unit": "mln_pln_per_km", "axis": [0, hi], "p25": _r(qv["p25"], 3), "p50": _r(qv["p50"], 3),
                          "p75": _r(qv["p75"], 3), "p90": _r(qv["p90"], 3), "you": _r(ppk_m, 3), "n": uc.n,
                          "plain": f"{T.pl_num(pctl * 100, 0)}. percentyl"},
                "stats": {"percentile": _r(pctl, 4), "coverage": _r(uc.coverage, 3), "length_source": uc.length_source,
                          "sample": uc.sample, "nominal": True},
            }
            questions.append(qc)
            items.append({"section": "q_cost", "key": "budget", "title": qc["question"], "origin": "CALC",
                          "body": qc})
        else:
            questions.append(_q_unknown("budget", T.q_budget(ft.value_gross), "mln_per_km",
                                        "Podaj długość sieci i budżet, żeby policzyć koszt kilometra.", "cost"))
    if cf is not None:
        items.append({"section": "q_cost", "key": "cost_dev", "title": "Odchylenie kosztu", "origin": "CALC",
                      "body": {"q_pct": {k: _r(v, 2) for k, v in cf.q_pct.items()},
                               "p_no_overrun": _r(cf.p_no_overrun, 3), "p_within_10pct": _r(cf.p_within_10pct, 3),
                               "paid_above_share": _r(cf.paid_above_share, 3),
                               "paid_above_median_pct": _r(cf.paid_above_median_pct, 2), "n": cf.n,
                               "prov": prov_calc(cf.n, "rc_quantiles(cost_dev_pct)", [ref])}})

    if tf is not None and dl is not None:
        ans, step = F.verbal(dl.p_before_deadline)
        pv = prov_calc(dl.n, "monte_carlo(tender_days+plan_ratio)+programme_end",
                       [ref, {"kind": "catalogue", "id": f"funding_programme:{ft.funding_programme or 'umowa'}",
                              "label": "koniec programu"}])
        pv_dead = {"role": "source", "review_status": "approved" if (prog or {}).get("status") == "approved"
                   else "proposed", "assumption": True,
                   "refs": [{"kind": "catalogue", "id": f"funding_programme:{(prog or {}).get('code', 'umowa')}",
                             "label": "Katalog: programy finansowania"}]}
        prog_x = round(dl.months_available, 1)
        T_end = [tf.months(k) for k in ("p10", "p50", "p90")]
        qc = {
            "key": "programme", "question": T.Q_PROGRAMME, "answer": ans, "answer_step": step,
            "tone": "bad" if dl.p_before_deadline < 0.5 else "good",
            "key_value": _r(dl.p_before_deadline, 3), "key_kind": "chance",
            "key_display": f"{T.pct(dl.p_before_deadline)} szans",
            "scale": {"min": max(0, math.floor(min(T_end[0], prog_x) - 2)),
                      "max": math.ceil(max(T_end[2], prog_x) + 2),
                      "lo_label": f"{max(0, math.floor(min(T_end[0], prog_x) - 2))} mies.",
                      "hi_label": f"{math.ceil(max(T_end[2], prog_x) + 2)} mies."},
            "band": {"from": _r(T_end[0], 1), "to": _r(T_end[2], 1), "kind": "p10_p90", "caption": T.BAND_CAPTION},
            "median": _r(T_end[1], 1), "you": _r(plan_m, 1), "programme_end": prog_x, "n": dl.n,
            "insufficient": False,
            "aria": (f"Szansa na odbiór przed końcem programu {T.pct(dl.p_before_deadline)}; od podpisania umowy "
                     f"do końca programu zostaje ok. {T.pl_num(prog_x, 1)} mies."),
            "provenance": provline(dl.n, f"obliczenie, n = {dl.n}; termin programu: założenie eksperta"),
            "metric": "time",
            "key_number": num(dl.p_before_deadline, f"{T.pct(dl.p_before_deadline)} szans", "share", pv),
            "deadline": {"date": dl.deadline.isoformat(), "programme": (prog or {}).get("name"),
                         "prov": pv_dead},
            "stats": {"sign_p50": dl.sign_p50.isoformat(), "months_available": _r(dl.months_available, 1),
                      "buffer_days": dl.buffer_days, "tender_n": dl.tender_n},
        }
        questions.append(qc)
        items.append({"section": "q_deadline", "key": "programme", "title": qc["question"], "origin": "CALC",
                      "body": qc})
    else:
        questions.append(_q_unknown("programme", T.Q_PROGRAMME, "chance",
                                    "Brak terminu programu: wybierz program lub wpisz termin z umowy o dofinansowanie.",
                                    "time"))

    # --- shares --------------------------------------------------------------------------------------------------------
    shares_out = {}
    for k, s in sh.items():
        pv = prov_calc(s.n, "rc_share+wilson_ci90", [ref], s.ci90)
        shares_out[k] = {"k": s.k, "n": s.n, **num(s.share, f"{T.pct(s.share)} ({s.k} z {s.n})", "share", pv)}
    items.append({"section": "shares", "key": "shares", "title": "Udziały w grupie porównawczej", "origin": "CALC",
                  "body": shares_out})

    # --- flags ---------------------------------------------------------------------------------------------------------
    flag_list: list[dict] = []
    for i, f in enumerate(FL.evaluate(ft, tf, dl, (prog or {}).get("name"), sign_p50)):
        fid = f"calc-{f.code}"
        meta = f"{', '.join(f.risk_codes)}, obliczenie" + (f", n = {f.n}" if f.n else "")
        fl = {"id": fid, "origin": "CALC", "review_status": "auto", "title": f.title, "text": f.text, "meta": meta,
              "risk_codes": f.risk_codes, "doc": None, "review_item_id": None, "kind": "calc", "rule": f.code,
              "rule_text": f.rule, "inputs": f.inputs,
              "prov": prov_calc(f.n or rc.n, f"rule:{f.code}", [ref, {"kind": "catalogue", "id": f"red_flag:{f.code}",
                                                                       "label": "Katalog: czerwone flagi"}])}
        flag_list.append(fl)
        items.append({"section": "flag", "key": fid, "title": f.title, "origin": "CALC", "body": fl,
                      "catalogue_code": f.code, "rank": i})
    for af in ai_flags or []:
        flag_list.append(af)

    # --- similar cases -------------------------------------------------------------------------------------------------
    sims = similar_cases(cb, cat, ft, k=4)
    pool_codes = similar_code_counts(cb, cat, ft)
    flagged = {c.split(".")[0] for f in flag_list for c in f.get("risk_codes") or []}
    for sc_ in sims:
        own = {c.split(".")[0] for c in sc_.get("cause_codes") or []}
        ov = sorted(flagged & own)
        sc_["risk_overlap"] = [{"risk": r, "text": f"sygnał {r} w Twojej analizie; w tym przypadku zmiany z tej przyczyny"}
                               for r in ov]
    for i, s in enumerate(sims):
        items.append({"section": "similar", "key": s["project_id"], "title": s["title"], "origin": "CALC", "body": s,
                      "rank": i})

    # --- clauses -------------------------------------------------------------------------------------------------------
    clauses = clause_hints(cb, cat, rc, sh, flag_list, in_pack)
    for i, c in enumerate(clauses):
        items.append({"section": "clause", "key": c["code"], "title": c["title"], "origin": "CALC", "body": c,
                      "rank": i})

    # --- limitations ---------------------------------------------------------------------------------------------------
    limits = [*T.LIMITS_BASE, T.causes_limit(cb.cause_mode)]
    if rc.widened and rc.widen_note:
        limits.insert(0, rc.widen_note)
    if rc.reweight_note:
        limits.insert(1, rc.reweight_note)
    if ft.subsector_main in U.unit_cost_subsectors(cb):
        if uc is not None and ft.length_km:
            limits.append(T.LIMIT_NOMINAL)
            limits.append(T.LIMIT_LENGTH.format(source=T.LENGTH_SOURCE.get(uc.length_source, uc.length_source),
                                                cov=T.pct(uc.coverage)))
        else:
            limits.append(T.LIMIT_NO_LENGTH)
    elif ft.subsector_main:
        limits.append(T.LIMIT_PLANT if cb.sector == "wod-kan" else T.LIMIT_NO_KM_SECTOR)
    if cb.sector != "wod-kan":
        limits.insert(0, T.LIMIT_SECTOR_EXTENSION.format(name=cb.pack["name"]))
    if not deadline_iso:
        limits.append(T.LIMIT_NO_PROGRAMME)
    elif prog and prog.get("status") != "approved" and not ft.deadline:
        limits.append(T.LIMIT_PROGRAMME_ASSUMPTION.format(name=prog.get("name"), status="do zatwierdzenia"))
    if not documents:
        limits.append(T.LIMIT_NO_DOCS)
    limits.append(T.LIMIT_MITIGATIONS)
    for i, lt in enumerate(limits):
        items.append({"section": "limit", "key": f"limit-{i}", "title": lt, "origin": "CALC", "body": {"text": lt},
                      "rank": i})

    # --- summary -------------------------------------------------------------------------------------------------------
    late = sh["late"].share if sh["late"].n else None
    sentence = T.summary_sentence(
        rc.n, rc.label(), late, plan_m, tf.p_on_time if tf else None, tf.months("p80") if tf else None,
        uc.user_ppk / 1e6 if uc and uc.user_ppk else None, uc.user_percentile if uc else None, insufficient)
    sp = prov_calc(rc.n, "template:summary_v1", [ref])
    summary = {"text": sentence, "provenance": f"obliczenie, n = {rc.n}, szablon (bez AI)", "sentence": sentence,
               "prov": sp}
    items.append({"section": "summary", "key": "summary", "title": "W skrócie", "origin": "CALC", "body": summary})

    # --- header --------------------------------------------------------------------------------------------------------
    sub_labels = cb.pack["sub_labels"] or SUB_LABEL
    title_parts = [sub_labels.get(ft.subsector_main or "", f"Inwestycja {cb.pack['label_short']}").capitalize()]
    if ft.length_km:
        title_parts.append(f"{T.pl_num(ft.length_km, 1 if ft.length_km % 1 else 0)} km")
    if ft.pumping_stations:
        title_parts.append(f"{ft.pumping_stations} {T.plural(ft.pumping_stations, 'przepompownia', 'przepompownie', 'przepompowni')}")
    sub_parts = [code]
    if ft.value_gross:
        sub_parts.append(f"{T.pl_num(ft.value_gross / 1e6, 1 if (ft.value_gross / 1e6) % 1 else 0)} mln zł brutto")
    if plan_m:
        sub_parts.append(f"{T.pl_num(plan_m)} {T.plural(round(plan_m), 'miesiąc', 'miesiące', 'miesięcy')}")
    if prog:
        sub_parts.append(prog.get("name", ""))
    from riskminer.analytics.backtest import backtest
    _bt = backtest(cb)
    _bias = (_bt["late"]["observed"] - _bt["late"]["predicted"]) * 100
    if _bias > 3:
        limits.append(f"Sprawdzian na umowach zakończonych od 2024 r.: odsetek opóźnionych był o ok. "
                      f"{T.pl_num(_bias)} pp wyższy niż prognoza, więc szanse na termin mogą być zawyżone.")
    pending = sum(1 for f in flag_list if f.get("origin") == "AI" and f.get("review_status") == "proposed")

    report = {
        "id": code, "code": code, "version": version, "status": "ready", "error": None,
        "title": ", ".join(title_parts), "subtitle": ", ".join(p for p in sub_parts if p),
        "summary": summary, "questions": questions, "flags": flag_list, "similar_cases": sims,
        "clauses": clauses, "reference_class": reference_class, "limitations": limits,
        "shares": shares_out,
        "cost": items[[i for i, it in enumerate(items) if it["key"] == "cost_dev"][0]]["body"] if cf else None,
        "similar_code_counts": pool_codes,
        "backtest_note": _bt["note"], "backtest": {"note": _bt["note"], "prov": _bt["prov"], "inside_p10_p90": _r(_bt["delay_days"]["inside_p10_p90"], 3), "n_test": _bt["delay_days"]["n_test"], "late_bias_pp": _r((_bt["late"]["observed"] - _bt["late"]["predicted"]) * 100, 1)}, "pending_review": pending, "unverified_hidden": 0, "documents": documents,
        "chat": {"suggestions": ["Co zmienić w PFU?", "Najbliższy podobny przypadek",
                                 "Dlaczego taka szansa na termin?"]},
        "data_as_of": cb.data_as_of.isoformat() if cb.data_as_of else None, "data_version": cb.data_version,
        "catalogue_version": cat.get("version"), "seed": seed,
        "features_used": {k: v for k, v in ft.as_dict().items() if k != "text"},
    }
    return report, items


def _q_unknown(key: str, question: str, kind: str, why: str, metric: str) -> dict:
    return {"key": key, "question": question, "answer": "Nie wiemy", "answer_step": None, "tone": "neutral",
            "key_value": None, "key_kind": kind, "key_display": "brak danych",
            "scale": {"min": 0, "max": 1, "lo_label": "", "hi_label": ""}, "band": None, "median": None, "you": None,
            "programme_end": None, "n": 0, "insufficient": True, "aria": why,
            "provenance": provline(0, why), "metric": metric, "missing": why}


# --- similar cases ------------------------------------------------------------------------------------------------------

def _outcome(cb: CaseBase, i: int) -> tuple[float | None, float | None]:
    ot = cb["on_time_declared"][i]
    d = cb["delay_days"][i]
    if ot == 1:
        delay = 0.0
    elif cb["late"][i] == 1 and np.isfinite(d) and d > 0:
        delay = float(d)
    else:
        delay = None
    c = cb["cost_dev_pct"][i]
    cost = float(c) if cb["cost_ok"][i] and np.isfinite(c) else None
    return delay, cost


def why_text(sc: SIM.Scored, i: int, cb: CaseBase, ft: RC.Features) -> tuple[str, str]:
    cs = sorted(SIM.contributions(sc, i), key=lambda c: -c["c"])
    why, diff = [], []
    for c in cs:
        f, s = c["feature"], c["s"]
        if len(why) < 3 and s >= 0.6:
            if f == "subsector_main":
                why.append("ten sam podsektor" if s == 1 else "podsektor z tej samej grupy")
            elif f == "formula":
                why.append("też „zaprojektuj i wybuduj”" if ft.design_build else "też samo wykonanie")
            elif f == "value":
                why.append(f"podobna wartość ({T.pl_num(cb['value_gross'][i] / 1e6, 1)} wobec "
                           f"{T.pl_num((ft.value_gross or 0) / 1e6, 1)} mln zł)")
            elif f == "physical_size":
                why.append(f"podobna długość sieci ({T.pl_num(cb['length_km'][i], 1)} wobec "
                           f"{T.pl_num(ft.length_km or 0, 1)} km)")
            elif f == "tech_tags":
                common = [t for t in SIM.case_tags(i) if t in SIM.tag_names(sc.user_tags)]
                if common:
                    why.append(", ".join(common[:2]))
            elif f == "period":
                why.append("ten sam okres cen")
            elif f == "region":
                why.append("to samo województwo" if s == 1 else "sąsiednie województwo")
            elif f == "text" and sc.matched_terms:
                why.append("podobny opis")
            elif f == "works_type":
                why.append("ten sam rodzaj robót")
        if len(diff) < 2 and s < 0.5 and c["gap"] > 0.03:
            if f == "formula":
                diff.append("inna formuła")
            elif f == "value":
                diff.append(f"wartość {T.pl_num(cb['value_gross'][i] / 1e6, 1)} wobec "
                            f"{T.pl_num((ft.value_gross or 0) / 1e6, 1)} mln zł")
            elif f == "subsector_main":
                diff.append(f"inny podsektor: {(cb.pack['sub_labels'] or SUB_LABEL).get(cb['subsector_main'][i], '?')}")
            elif f == "period":
                diff.append("inny okres cenowy")
    return ", ".join(why) or "podobne cechy", ", ".join(diff)


def similar_cases(cb: CaseBase, cat: dict, ft: RC.Features, k: int = 4) -> list[dict]:
    simcfg = cat.get("similarity") or {}
    sc = SIM.score_pool(cb, ft, simcfg.get("features"))
    min_s = float(simcfg.get("min_similarity", 0.55))
    min_cov = float(simcfg.get("min_coverage", 0.5))
    ranked = SIM.top(cb, sc, 200, min_s, min_cov)
    pilots, nat, seen_rm = [], [], set()
    for i in ranked:
        if SIM.is_pilot(i):
            r = SIM.rm_id(i)
            if r in seen_rm:
                continue
            seen_rm.add(r)
            pilots.append(i)
        else:
            nat.append(i)
    chosen = sorted(pilots[:2] + nat[: max(0, k - min(2, len(pilots)))], key=lambda i: -sc.S[i])[:k]
    out = []
    for rank, i in enumerate(chosen, 1):
        delay, cost = _outcome(cb, i)
        rm = SIM.rm_id(i)
        bzp = cb["cp_bzp_number"][i]
        notice_ref = {"kind": "notice", "id": bzp or str(cb["cp_object_id"][i]), "label": "ogł. o wykonaniu",
                      "url": cb["cp_url"][i], "field_code": "5.2"}
        why, diff = why_text(sc, i, cb, ft)
        contrib = SIM.contributions(sc, i)
        S = float(sc.S[i])
        out.append({
            "rank": rank, "project_id": rm or cb["ocid"][i], "rm_id": rm, "ocid": cb["ocid"][i],
            "is_pilot": bool(rm), "badge": "przypadek zweryfikowany" if rm else None,
            "title": cb["title"][i], "why": why, "diff": diff, "score": round(S, 3),
            "contributions": SIM.grouped(contrib),
            "contributions_detail": [{k2: (round(v, 4) if isinstance(v, float) else v) for k2, v in c.items()}
                                     for c in contrib],
            "coverage": round(float(sc.coverage[i]), 3),
            "matched_terms": sc.matched_terms[:3],
            "delay_days": delay, "cost_dev_pct": None if cost is None else round(cost, 1),
            "late": bool(cb["late"][i] == 1), "changes": int(cb["changes_count"][i])
            if np.isfinite(cb["changes_count"][i]) else None,
            "cause_codes": list(cb["cause_codes"][i]),
            "buyer_name": cb["buyer_name"][i], "woj": cb["woj"][i],
            "value_gross": {"amount": f"{cb['value_gross'][i]:.2f}", "currency": "PLN", "vat_basis": "gross"},
            "href": f"/projekty/{rm}" if rm else f"/projekty/{cb['ocid'][i]}",
            "score_num": {"value": round(S, 3), "display": T.pl_num(S, 2), "unit": "score",
                          "prov": {"role": "calc", "review_status": "auto", "n": int(cb.n),
                                   "method": "weighted_similarity_v1",
                                   "refs": [{"kind": "catalogue", "id": "similarity:default", "label": "wagi podobieństwa"}]}},
            "outcome": {
                "delay_days": {"value": delay, "display": "w terminie" if delay == 0 else
                               (f"+{T.pl_num(delay)} dni" if delay is not None else "b.d."), "unit": "days",
                               "prov": {"role": "case", "review_status": "auto", "refs": [notice_ref]}},
                "cost_dev_pct": {"value": None if cost is None else round(cost, 1),
                                 "display": "b.d." if cost is None else f"{cost:+.1f}%".replace(".", ","),
                                 "unit": "pct", "prov": {"role": "case", "review_status": "auto",
                                                         "refs": [{**notice_ref, "field_code": "5.5"}]}}},
            "performance_id": int(cb["performance_id"][i]),
        })
    return out


def similar_code_counts(cb: CaseBase, cat: dict, ft: RC.Features, k: int = 30) -> dict:
    """For each cause code: in how many of the k most similar contracts did a change have it (case hints, 1.3)."""
    simcfg = cat.get("similarity") or {}
    sc = SIM.score_pool(cb, ft, simcfg.get("features"))
    top = SIM.top(cb, sc, k, float(simcfg.get("min_similarity", 0.55)), float(simcfg.get("min_coverage", 0.5)))
    out: dict[str, dict] = {}
    for i in top:
        for c in {x.split(".")[0] for x in cb["cause_codes"][i]}:
            if c in ("N-FORMAL", "N-UNSPEC"):
                continue
            e = out.setdefault(c, {"k": 0, "n": len(top), "cases": []})
            e["k"] += 1
            if len(e["cases"]) < 3:
                rm = SIM.rm_id(i)
                e["cases"].append({"label": (cb["buyer_name"][i] or cb["title"][i] or "")[:50],
                                   "href": f"/projekty/{rm or cb['ocid'][i]}", "bzp": cb["cp_bzp_number"][i]})
    return out



# --- clauses ------------------------------------------------------------------------------------------------------------

def _risk_share(cb: CaseBase, mask: np.ndarray, code: str) -> tuple[int, int]:
    idx = np.flatnonzero(mask)
    k = sum(1 for i in idx if any(c == code or c.startswith(code + ".") for c in cb["cause_codes"][i]))
    return k, int(idx.size)


CLAUSE_TITLE = {"R02": "Badania gruntu i protokół konieczności", "R03": "Prawo do dysponowania gruntem",
                "R04": "Termin a decyzje organów", "R06": "Harmonogram i kamienie milowe",
                "R08": "Waloryzacja i model wynagrodzenia (art. 439)", "R13": "Finansowanie i płatności",
                "R01": "Ryczałt a ilości orientacyjne", "R07": "Roboty dodatkowe i zamienne",
                "R12": "Dostawy urządzeń i materiałów", "R16": "Warunki atmosferyczne"}


def clause_hints(cb: CaseBase, cat: dict, rc: RC.RefClass, sh: dict, flags: list[dict], in_pack: set[str],
                 k: int = 3) -> list[dict]:
    clauses = cat.get("clauses") or {}
    names = cat.get("risk_names") or {}
    cand: list[tuple[float, str, str]] = []           # (priority, risk, why)
    # risks behind fired flags first
    for f in flags:
        for r in f.get("risk_codes") or []:
            cand.append((2.0, r.split(".")[0], f.get("title", "")))
    # most frequent cause codes in the class
    for r in ("R07", "R04", "R08", "R03", "R02", "R06", "R13", "R01"):
        kk, n = _risk_share(cb, rc.mask, r)
        if n and kk:
            cand.append((kk / n, r, f"W {kk} z {n} podobnych umów zmiany dotyczyły: "
                                    f"{(names.get(r) or r).lower()}."))
    # price risk: always relevant for works > 6 months
    pa = sh.get("paid_above")
    if pa and pa.n:
        cand.append((0.5, "R08", f"{T.pct(pa.share)} podobnych umów rozliczono ponad wartość ({pa.k} z {pa.n})."))
    out, seen = [], set()
    for _, r, why in sorted(cand, key=lambda x: -x[0]):
        cl = _clause_for(clauses, r)
        if not cl or cl["code"] in seen:
            continue
        seen.add(cl["code"])
        kk, n = _risk_share(cb, rc.mask, r)
        out.append({"code": cl["code"], "title": CLAUSE_TITLE.get(r) or names.get(r) or r, "why": why,
                    "in_pack": cl["code"] in in_pack, "risk_codes": [r], "text": cl.get("text"),
                    "status": cl.get("status"),
                    "number": num(kk / n if n else None, f"{T.pct(kk / n if n else None)}", "share",
                                  prov_calc(n, f"rc_share(cause_codes~{r})", [q_ref(rc)]))})
        if len(out) >= k:
            break
    return out


def _clause_for(clauses: dict, risk: str) -> dict | None:
    alias = {"N-PRICE": "R08", "R07": "R01", "R16": "R06"}
    for r in (risk, alias.get(risk, risk)):
        for code, c in clauses.items():
            rc = str(c.get("risk_code") or "")
            if rc == r or rc.startswith(r + "."):
                return c
    return None
