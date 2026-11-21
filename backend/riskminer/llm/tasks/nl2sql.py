"""`nl2sql`: "Zapytaj pamięć" (1.6, Pulpit), docs/impl/llm.md §2.5.

The model writes SQL + a sentence template; code validates the SQL (sqlguard), forces the core wod-kan filter by
rewriting the view references, runs it read-only, fills the template from row 0 with Polish number formatting and
builds bars. The model never writes the numbers. n < 10 → "za mało danych"."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import sqlglot
from sqlglot import exp

from riskminer.llm import gateway, sqlguard
from riskminer.llm.backends.base import Text
from riskminer.llm.gateway import LLMRequest, LLMResult
from riskminer.llm.sanitize import copy_rules
from riskminer.llm.schemas import SqlPlan

VIEWS = {"v_ask_contract", "v_ask_change", "v_ask_procedure", "v_ask_signal"}
# The views are core wod-kan only since data-db's 0011 (sector 'wod-kan' AND relevance 'core'), so no rewrite is needed;
# CORE_FILTER stays as a hook if a wider view (e.g. *_all) is ever whitelisted.
CORE_FILTER: dict[str, str] = {}
INSUFFICIENT_N = 10


def enforce_core(sql: str) -> str:
    tree = sqlglot.parse_one(sql, read="postgres")

    def tf(node):
        if isinstance(node, exp.Table) and node.name.lower() in CORE_FILTER and not node.db:
            name = node.name.lower()
            alias = node.alias or name
            sub = sqlglot.parse_one(f"(SELECT * FROM {name} WHERE {CORE_FILTER[name]}) AS {alias}", read="postgres")
            return sub
        return node

    return tree.transform(tf).sql(dialect="postgres")


def fmt_pl(v: Any) -> str:
    if v is None:
        return "brak"
    if isinstance(v, bool):
        return "tak" if v else "nie"
    if isinstance(v, Decimal):
        v = float(v)
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, float):
        if abs(v) >= 1000:
            return f"{v:,.0f}".replace(",", " ")
        s = f"{v:.1f}" if abs(v) >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")
        return s.replace(".", ",")
    return str(v)


def fill(template: str, row: dict) -> str:
    def rep(m: re.Match) -> str:
        k = m.group(1)
        return fmt_pl(row.get(k)) if k in row else m.group(0)
    return re.sub(r"\{(\w+)\}", rep, template or "")


@dataclass
class AskOutcome:
    answer: dict
    sql: str | None
    rows: list[dict]
    llm: LLMResult | None


def _num_rows(rows: list[dict]) -> int | None:
    if not rows:
        return 0
    if "n" in rows[0]:
        try:
            return int(sum(float(r["n"] or 0) for r in rows)) if len(rows) > 1 else int(rows[0]["n"] or 0)
        except (TypeError, ValueError):
            return None
    return len(rows)


def _bars(plan: SqlPlan, rows: list[dict]) -> list[dict]:
    if not plan.bars or len(rows) < 2:
        return []
    lc, vc = plan.bars.label_col, plan.bars.value_col
    if lc not in rows[0] or vc not in rows[0]:
        return []
    out = []
    for r in rows[:30]:
        v = r[vc]
        try:
            fv = float(v) if v is not None else None
        except (TypeError, ValueError):
            fv = None
        pct = "pct" in vc.lower() or "share" in vc.lower() or "odsetek" in vc.lower()
        out.append({"label": str(r[lc]), "value": fv, "display": fmt_pl(v) + ("%" if pct and v is not None else ""), "highlight": False})
    return out


async def ask(question: str, *, subject: str | None = None) -> AskOutcome:
    req = LLMRequest(task="nl2sql", sensitivity="public", prompt="nl2sql", parts=[Text(f"<pytanie>{question.strip()[:800]}</pytanie>")],
                     output=SqlPlan, subject=subject, max_output_tokens=1200)
    res = await gateway.run(req)
    plan: SqlPlan = res.data
    if not plan.sql or plan.cannot_answer:
        return AskOutcome(_no_data(plan.cannot_answer or "Widoki nie odpowiadają na to pytanie.", res, plan), None, [], res)
    err = None
    for attempt in range(2):
        try:
            checked = sqlguard.check(plan.sql, VIEWS)
            sql = enforce_core(checked.sql)
            cols, rows = await sqlguard.execute(sql)
            return AskOutcome(_answer(plan, sql, cols, rows, res), sql, rows, res)
        except (sqlguard.SqlRejected, Exception) as e:  # noqa: BLE001  Postgres errors included
            err = str(e)[:400]
            if attempt == 1:
                break
            req.extra_user = f"Twoje zapytanie SQL zostało odrzucone albo zwróciło błąd: {err}\nPopraw je."
            res = await gateway.run(req)
            plan = res.data
            if not plan.sql:
                return AskOutcome(_no_data(plan.cannot_answer or "Widoki nie odpowiadają na to pytanie.", res, plan), None, [], res)
    out = _no_data("Nie udało się policzyć odpowiedzi z dostępnych widoków.", res, plan)
    out["method"] = {"kind": "sql", "sql": plan.sql}
    out["missing"].append(f"błąd zapytania: {err}")
    return AskOutcome(out, plan.sql, [], res)


def _no_data(reason: str, res: LLMResult | None, plan: SqlPlan | None) -> dict:
    return {"id": "", "code": None, "role": "no_data", "role_label": "brak danych", "text": copy_rules(reason),
            "bars": [], "numbers": [], "method": {"kind": "llm"}, "sources": [], "n": None,
            "missing": [copy_rules(reason)], "actions": [], "apply": None,
            "processing": res.processing if res else None, "title": plan.title if plan else None}


def _answer(plan: SqlPlan, sql: str, cols: list[str], rows: list[dict], res: LLMResult) -> dict:
    n = _num_rows(rows)
    views = sorted({t for t in VIEWS if t in sql})
    q_ref = {"kind": "query", "id": ",".join(views) or "ask", "label": f"n = {fmt_pl(n)}" if n is not None else "zapytanie SQL"}
    if not rows:
        text = "Brak umów spełniających te warunki."
    elif n is not None and n < INSUFFICIENT_N:
        text = f"Za mało danych: tylko {n} przypadków spełnia te warunki."
    else:
        text = copy_rules(fill(plan.answer_template or "", rows[0])) or "Wynik w tabeli poniżej."
        if re.search(r"\{\w+\}", text):
            text = "Wynik w tabeli poniżej."
        elif len(rows) > 1:
            text = f"{text} Pełne zestawienie: {len(rows)} pozycji poniżej."
    numbers = []
    if rows and n is not None and n >= INSUFFICIENT_N:
        for c in cols:
            v = rows[0].get(c)
            if c == "n" or isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
                continue
            unit = "pct" if "pct" in c or "share" in c else ("pln" if any(x in c for x in ("value", "gross", "amount", "sum", "pln")) else
                                                             ("days" if "days" in c else "count"))
            numbers.append({"value": float(v), "display": fmt_pl(v) + ("%" if unit == "pct" else ""), "unit": unit,
                            "prov": {"role": "calc", "review_status": "auto", "n": n, "method": "sql", "refs": [q_ref]}})
    return {"id": "", "code": None, "role": "calc" if rows and (n or 0) >= INSUFFICIENT_N else "no_data",
            "role_label": "obliczenie" if rows and (n or 0) >= INSUFFICIENT_N else "brak danych", "text": text,
            "bars": _bars(plan, rows), "numbers": numbers[:6], "method": {"kind": "sql", "sql": sql, "view": ",".join(views)},
            "sources": [q_ref], "n": n, "missing": [] if rows else ["brak wierszy dla tych warunków"],
            "actions": [{"kind": "save", "label": "Zapisz jako rekord"}, {"kind": "rows_csv", "label": "Pobierz wiersze (CSV)"}],
            "apply": None, "processing": res.processing, "title": copy_rules(plan.title)}
