"""Red flags that are code predicates (analytics.md §3.11): F6, F5, F12, F14. CALC, review_status auto."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from riskminer.analytics import templates as T
from riskminer.analytics.base import DAYS_PER_MONTH
from riskminer.analytics.forecast import DeadlineForecast, TimeForecast
from riskminer.analytics.refclass import Features


@dataclass
class Flag:
    code: str              # catalogue red_flag code (F6...)
    rule: str
    title: str
    text: str
    risk_codes: list[str]
    inputs: dict = field(default_factory=dict)
    n: int | None = None


def evaluate(ft: Features, tf: TimeForecast | None, dl: DeadlineForecast | None, programme_name: str | None,
             sign_date: date | None) -> list[Flag]:
    out: list[Flag] = []
    if ft.plan_days and tf is not None:
        plan_m = ft.plan_days / DAYS_PER_MONTH
        med_m, p25_m = tf.planned_p50 / DAYS_PER_MONTH, tf.planned_p25 / DAYS_PER_MONTH
        if ft.plan_days < tf.planned_p25:
            title, text = T.flag_f6(plan_m, med_m, p25_m)
            out.append(Flag("F6", "plan_days < class planned P25", title, text, ["R06"],
                            {"plan_days": ft.plan_days, "planned_p25": tf.planned_p25, "planned_p50": tf.planned_p50},
                            tf.n))
        if ft.design_build and plan_m < 12 and (ft.subsector_main in {"SAN", "OCZ", "SUW", "DESZ"}):
            title, text = T.flag_f12(plan_m)
            out.append(Flag("F12", "design_build AND plan < 12 mies.", title, text, ["R04", "R06"],
                            {"plan_months": plan_m}))
        if sign_date and ft.plan_days < tf.planned_p50:
            end = sign_date + timedelta(days=ft.plan_days)
            if _covers_winter(sign_date, end):
                title, text = T.flag_f14(plan_m, med_m)
                out.append(Flag("F14", "works window covers Dec-Feb AND plan < class median", title, text, ["R16"],
                                {"start": sign_date.isoformat(), "end": end.isoformat()}, tf.n))
    if dl is not None and dl.buffer_days < 60:
        title, text = T.flag_f5(dl.buffer_days, dl.deadline.strftime("%d.%m.%Y"), programme_name or "program")
        out.append(Flag("F5", "deadline - (sign_P50 + plan) < 60 d", title, text, ["R06", "R15"],
                        {"buffer_days": dl.buffer_days, "deadline": dl.deadline.isoformat(),
                         "sign_p50": dl.sign_p50.isoformat()}, dl.n))
    return out


def _covers_winter(start: date, end: date) -> bool:
    d = start
    while d <= end:
        if d.month in (12, 1, 2):
            return True
        d += timedelta(days=15)
    return end.month in (12, 1, 2)


def contractor_load_flag(ongoing: int, ongoing_value: float, hist_median: float | None, hist_value_median: float | None,
                         n: int, *, min_n: int = 5) -> Flag | None:
    """R12 "obciążenie wykonawcy": concurrent ongoing contracts versus the contractor's own 24-month history (W10).

    Raised when the contractor holds at least 5 ongoing contracts and at least 1.5x its median concurrent load; neutral
    fact, not a ranking. Needs n >= min_n contracts, otherwise None (insufficient data)."""
    if n < min_n or hist_median is None or ongoing < 5:
        return None
    base = max(hist_median, 1.0)
    if ongoing < 1.5 * base:
        return None
    from riskminer.api.prov import fmt_num
    val = f" o wartości {fmt_num(ongoing_value / 1e6, 1)} mln zł brutto" if ongoing_value else ""
    return Flag("R12", "ongoing >= 5 AND ongoing >= 1.5 x median concurrent (24 mies.)", "Obciążenie wykonawcy",
                f"Wykonawca ma teraz {ongoing} umów w toku{val}; zwykle prowadził ich równolegle około {fmt_num(base, 1)}.",
                ["R12"], {"ongoing": ongoing, "ongoing_value": ongoing_value, "history_median": hist_median,
                          "history_median_value": hist_value_median}, n)
