"""Analysis pack (api_contract §4): DOCX (python-docx, MIT), PDF (LibreOffice headless via documents.convert), CSV, JSON.

`manifest(report)` lists what goes in and what is excluded (AI conclusions the owner did not approve). `render(db, code, fmt, version)`
builds the file from the stored report (`analysis.service.get_report`), caches it under exports/packs/<code>-v<version>-<hash>.<ext>
and returns (path, filename, media_type). The annex lists every source with URL, page, quote, retrieved_at and sha256.
Session B. Permission checks stay in the analyses router (A)."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import settings
from riskminer.reporting import docx_kit as K

MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
         "csv": "text/csv; charset=utf-8", "json": "application/json"}
FORMATS = ["docx", "pdf", "csv", "json"]
STATE_LABEL = {"BRAK_W_PACZCE": "nie ma w paczce", "DOKUMENT_NIE_WSPOMINA": "dokument nie wspomina", "POTWIERDZONO": "potwierdzono",
               "NIECZYTELNY": "dokument nieczytelny", "BRAK_POTWIERDZENIA": "brak potwierdzenia", "SPRZECZNOSC": "sprzeczność"}
def _layout_key() -> str:
    """Hash of the renderer sources, part of the cache key: a layout change never serves an old cached file."""
    from riskminer.reporting import docx_kit
    h = hashlib.sha256()
    for f in (Path(__file__), Path(docx_kit.__file__)):
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


PACK_LAYOUT = _layout_key()
METHOD_NOTE = ("Liczby w tym dokumencie to obliczenia na umowach z ogłoszeń BZP (klasa odniesienia), z liczbą umów n przy każdej wartości. "
               "Wnioski modelu językowego są w pakiecie tylko wtedy, gdy zatwierdził je autor analizy. Założenia ekspertów są oznaczone. "
               "Ryzyka są liczone niezależnie, bez korelacji między nimi.")


# ------------------------------------------------------------------------------------------------------------ selection

def _ai_pending(f: dict) -> bool:
    return (f.get("origin") == "AI" or (f.get("prov") or {}).get("role") == "ai" or f.get("kind") == "ai") \
        and f.get("review_status", (f.get("prov") or {}).get("review_status")) not in ("approved", "edited")


def split_flags(report: dict) -> tuple[list[dict], list[dict]]:
    inc, exc = [], []
    for f in report.get("flags") or []:
        (exc if _ai_pending(f) else inc).append(f)
    return inc, exc


def pack_view(report: dict) -> dict:
    """The report as it goes into the pack: AI conclusions the owner did not approve are left out (also from the annex)."""
    inc, _ = split_flags(report)
    return {**report, "flags": inc}


def manifest(report: dict) -> dict:
    inc, exc = split_flags(report)
    clauses = [c for c in report.get("clauses") or [] if c.get("in_pack")]
    qs = report.get("questions") or []
    items = [{"key": "summary", "label": "Podsumowanie", "count_label": "1 zdanie"},
             {"key": "reference_class", "label": "Klasa odniesienia i prognozy", "count_label": f"{len(qs)} pytań"},
             {"key": "flags", "label": "Sygnały ryzyka", "count_label": f"{len(inc)} sygnałów"},
             {"key": "similar_cases", "label": "Podobne przypadki", "count_label": f"{len(report.get('similar_cases') or [])} przypadków"},
             {"key": "clauses", "label": "Proponowane zapisy umowne", "count_label": f"{len(clauses)} zapisów"},
             {"key": "limitations", "label": "Ograniczenia i metoda", "count_label": f"{len(report.get('limitations') or [])} uwag"},
             {"key": "annex", "label": "Załącznik: źródła i cytaty", "count_label": f"{len(collect_refs(pack_view(report)))} źródeł"}]
    return {"items": items, "excluded": [{"item_id": f.get("id"), "title": f.get("title"), "reason": "wniosek AI niezatwierdzony"} for f in exc],
            "formats": FORMATS}


# --------------------------------------------------------------------------------------------------------------- refs

def collect_refs(obj: Any) -> list[dict]:
    """Every distinct ref inside a report (Prov.refs), in first-seen order."""
    seen: dict[tuple, dict] = {}

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("refs"), list):
                for r in o["refs"]:
                    if isinstance(r, dict) and r.get("kind") and r.get("id") is not None:
                        seen.setdefault((r["kind"], str(r["id"]), r.get("field_code"), r.get("page_no")), r)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return list(seen.values())


async def resolve_hashes(db: AsyncSession, refs: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    doc_ids = [int(r["id"]) for r in refs if r["kind"] == "document" and str(r["id"]).isdigit()]
    if doc_ids:
        for r in (await db.execute(text("SELECT d.id, d.sha256, d.url, s.retrieved_at FROM document d LEFT JOIN source s ON s.id = d.source_id "
                                        "WHERE d.id = ANY(:i)"), {"i": doc_ids})).mappings():
            out[f"document:{r['id']}"] = {"sha256": r["sha256"], "url": r["url"], "retrieved_at": r["retrieved_at"]}
    nums = [r["id"] for r in refs if r["kind"] == "notice"]
    if nums:
        for r in (await db.execute(text("SELECT n.notice_number, n.url, s.sha256, s.retrieved_at FROM notice n LEFT JOIN source s ON s.id = n.source_id "
                                        "WHERE n.notice_number = ANY(:n)"), {"n": nums})).mappings():
            out[f"notice:{r['notice_number']}"] = {"sha256": r["sha256"], "url": r["url"], "retrieved_at": r["retrieved_at"]}
    return out


# ---------------------------------------------------------------------------------------------------------------- docx

def _disp(n: Any) -> str:
    if isinstance(n, dict):
        return str(n.get("display") if n.get("display") is not None else n.get("value", ""))
    return "" if n is None else str(n)


def _n_of(n: Any) -> str:
    p = (n or {}).get("prov") if isinstance(n, dict) else None
    return str(p.get("n")) if p and p.get("n") is not None else ""


def _date(s: Any) -> str:
    if not s:
        return ""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except Exception:
        return str(s)[:10]


def _owner(r: dict) -> str:
    """Chosen allocation position: key string (buyer|shared|contractor) or index 0|1|2 into positions / the default order."""
    ch = r.get("chosen")
    names = {"buyer": "Zamawiający", "shared": "Wspólnie", "contractor": "Wykonawca"}
    if isinstance(ch, int) and not isinstance(ch, bool):
        pos = r.get("positions") or []
        if 0 <= ch < len(pos) and isinstance(pos[ch], dict):
            return pos[ch].get("label") or names.get(pos[ch].get("key"), "")
        return ["Zamawiający", "Wspólnie", "Wykonawca"][ch] if 0 <= ch < 3 else ""
    return names.get(ch, ch or "")


def _money_pl(m: dict) -> str:
    """{'amount': '49903.54', 'currency': 'PLN', 'vat_basis': 'gross'} -> '49 903,54 zł brutto'."""
    if not m or m.get("amount") in (None, ""):
        return ""
    try:
        from riskminer.api.prov import fmt_num
        amt = fmt_num(float(m["amount"]), 2)
    except (TypeError, ValueError):
        return f"{m.get('amount')} {m.get('currency', '')}".strip()
    cur = "zł" if (m.get("currency") or "PLN") == "PLN" else m.get("currency")
    vat = {"gross": " brutto", "net": " netto"}.get(m.get("vat_basis") or "", "")
    return f"{amt} {cur}{vat}"


def _quote_of(f: dict) -> str:
    """The flag's quote with its page, for the signals table (the annex keeps the full source list)."""
    q = f.get("quote") or next((r.get("quote") for r in ((f.get("prov") or {}).get("refs") or []) if r.get("quote")), None)
    if not q:
        return ""
    page = (f.get("doc") or {}).get("page")
    q = " ".join(str(q).split())
    return f"„{q[:300]}{'…' if len(q) > 300 else ''}”" + (f" (s. {page})" if page else "")


def risk_register(report: dict, inc_flags: list[dict], sim: dict | None = None) -> list[list[str]]:
    """Rows: code, title, probability (share of class contracts with the cause, n), impact (P50/P80 days and cost), expected cost, owner.
    Uses report['allocation'] when present and the simulation's per-risk numbers when given."""
    rows: list[list[str]] = []
    per = {p.get("risk"): p for p in (sim or {}).get("per_risk") or [] if isinstance(p, dict)}
    alloc = (report.get("allocation") or {}).get("risks") if isinstance(report.get("allocation"), dict) else None
    if alloc:
        for r in alloc:
            ec = (r.get("expected_cost") or {}).get("money") or {}
            pr = per.get(r.get("code")) or {}
            prob = f"{K.pct(pr['p_r'])} ({pr.get('n_r')} z {K.fmt_num(pr.get('n'))} umów)" if pr.get("p_r") is not None else ""
            bits = []
            d, c = pr.get("impact_days") or {}, pr.get("impact_cost_pct") or {}
            if d.get("p50") is not None:
                bits.append(f"czas: P50 +{K.fmt_num(d['p50'])}, P80 +{K.fmt_num(d.get('p80'))} dni")
            if c.get("p50") is not None:
                bits.append(f"koszt: P50 +{K.fmt_num(c['p50'], 1)}%, P80 +{K.fmt_num(c.get('p80'), 1)}%")
            impact = "; ".join(bits) or _disp(r.get("impact")) or r.get("impact_label") or ""
            rows.append([r.get("code"), r.get("title"), prob, impact, _money_pl(ec), _owner(r)])
        return rows
    for f in inc_flags:
        for code in f.get("risk_codes") or [""]:
            pr = per.get(code) or per.get((code or "").split(".")[0]) or {}
            prob = f"{K.pct(pr['p_r'])} ({pr.get('n_r')} z {K.fmt_num(pr.get('n'))} umów)" if pr.get("p_r") is not None else _disp(f.get("number"))
            rows.append([code, f.get("title"), prob, "", "", ""])
    return rows


# ---------------------------------------------------------------------------------------------------------------- docx
# The pack is a block list (reporting/docx_kit.py): page 1 executive summary with the verdict, then the analysis, the data
# quality section, the closing method page and the annex. Only rule results and AI items the author approved are in it.

SUB_PL = {"SAN": "kanalizacja sanitarna", "WOD": "sieć wodociągowa", "DESZ": "kanalizacja deszczowa", "OCZ": "oczyszczalnia ścieków",
          "SUW": "stacja uzdatniania wody"}
WORK_PL = {"build": "budowa", "rebuild": "przebudowa", "extension": "rozbudowa", "renovation": "renowacja"}
CONTROL_PL = {"buyer": "zamawiający", "contractor": "wykonawca", "shared": "obie strony", "external": "nikt (czynnik zewnętrzny)",
              "neither": "żadna ze stron"}
DAYS_PER_MONTH = 30.4375


def _months(days: Any) -> str:
    try:
        return f"{K.fmt_num(float(days) / DAYS_PER_MONTH, 1)} mies."
    except (TypeError, ValueError):
        return ""


# feature key -> (features_used key, how to show the value used in the calculation, numeric value of the read feature)
def _used_value(key: str, fu: dict) -> tuple[str | None, float | None]:
    v = None
    if key in ("dlugosc_km", "length_km") and fu.get("length_km") is not None:
        v = float(fu["length_km"])
        return f"{K.fmt_num(v, 2)} km", v
    if key in ("budzet", "value_gross") and fu.get("value_gross") is not None:
        v = float(fu["value_gross"])
        return f"{K.mln(v)} brutto", v
    if key in ("termin_mies", "plan_months") and fu.get("plan_days") is not None:
        v = float(fu["plan_days"]) / DAYS_PER_MONTH
        return f"{K.fmt_num(v, 1)} mies.", v
    if key in ("przepompownie",) and fu.get("pumping_stations") is not None:
        v = float(fu["pumping_stations"])
        return f"{K.fmt_num(v)} szt.", v
    if key in ("przylacza",) and fu.get("connections") is not None:
        v = float(fu["connections"])
        return f"{K.fmt_num(v)} szt.", v
    if key in ("formula", "design_build") and fu.get("design_build") is not None:
        return ("zaprojektuj i wybuduj" if fu["design_build"] else "samo wykonanie"), None
    if key in ("podsektor", "subsector_main") and fu.get("subsector_main"):
        return SUB_PL.get(fu["subsector_main"], fu["subsector_main"]), None
    if key == "finansowanie" and fu.get("funding_programme"):
        return str(fu["funding_programme"]), None
    if key == "rodzaj_robot" and fu.get("work_type"):
        return WORK_PL.get(fu["work_type"], fu["work_type"]), None
    return None, None


def _read_number(f: dict) -> float | None:
    v = f.get("value")
    if isinstance(v, dict):
        v = v.get("amount")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def feature_rows(report: dict) -> tuple[list[list[Any]], list[str]]:
    """Features as read (with uncertain marks) next to the value used in the calculation; differences become discrepancies."""
    fu = report.get("features_used") or {}
    rows, diffs = [], []
    for f in report.get("features") or []:
        if not isinstance(f, dict):
            continue
        prov = f.get("prov") or {}
        status = f.get("review_status") or prov.get("review_status")
        origin = f.get("origin") or {"ai": "AI", "calc": "CALC", "source": "SOURCE"}.get(prov.get("role") or "", "CALC")
        ref = next((r for r in prov.get("refs") or [] if r.get("quote")), None)
        where: list = [f.get("source_label") or (ref or {}).get("label") or "opis"]
        if ref and ref.get("quote"):
            where += [": ", {"t": _q(ref["quote"], 150), "i": True}]
        used, used_num = _used_value(f.get("key") or "", fu)
        read_num = _read_number(f)
        disp = f.get("display") or (K.money_pl(f["value"]) if isinstance(f.get("value"), dict) else str(f.get("value") or ""))
        val: list = [disp]
        if f.get("unsure"):
            val += [" ", {"t": "niepewne", "b": True, "c": K.AMBER, "s": 7}]
        differs = used is not None and used_num is not None and read_num is not None and abs(used_num - read_num) > max(0.05 * abs(read_num), 0.01)
        used_cell: Any = used or "tak jak odczytano"
        if differs:
            used_cell = [{"t": used, "b": True}, " ", {"t": "inna niż odczyt", "b": True, "c": K.AMBER, "s": 7}]
            diffs.append(f"{f.get('label')}: w dokumencie {disp}, do obliczeń przyjęto {used} (wartość z opisu albo poprawka autora analizy).")
        rows.append([{"t": f.get("label") or f.get("key") or "", "b": True}, val, used_cell, where, [K.tag(K.prov_key(origin, status))]])
    return rows, diffs


def _ci(c: Any) -> str:
    return f"{K.pct(c[0])} do {K.pct(c[1])}" if c else ""


def _q(s: Any, n: int = 280) -> str:
    s = " ".join(str(s or "").split())
    return f"„{s[:n]}{'…' if len(s) > n else ''}”" if s else ""


def _curve_q(curve: list, q: float) -> float | None:
    for x, y in curve or []:
        if y >= q - 1e-9:
            return float(x)
    return None


def _curve_at(curve: list, x0: float) -> float | None:
    """CDF / survival value at x0 (last point with x <= x0)."""
    val = None
    for x, y in curve or []:
        if x <= x0 + 1e-9:
            val = float(y)
        else:
            break
    return val


def sim_summary(sim: dict | None) -> dict | None:
    """P50/P80/P90 of the baseline curves (no mitigation selected) + chances at the plan and the budget."""
    if not sim or sim.get("insufficient") or not sim.get("metrics"):
        return None
    m = sim["metrics"]
    out: dict = {"n": sim.get("n"), "runs": sim.get("runs"), "seed": sim.get("seed")}
    t = (m.get("time") or {}).get("curves", {}).get("")
    if t:
        out["time"] = {k: _curve_q(t, q) for k, q in (("p50", .5), ("p80", .8), ("p90", .9))}
        out["time"]["plan"] = sim.get("plan_x")
        out["time"]["p_plan"] = _curve_at(t, float(sim["plan_x"])) if sim.get("plan_x") is not None else None
        out["time"]["n"] = (m.get("time") or {}).get("n")
    c = (m.get("cost") or {}).get("curves", {}).get("")
    if c:
        out["cost"] = {k: _curve_q(c, q) for k, q in (("p50", .5), ("p80", .8), ("p90", .9))}
        mk = [x for x in (m.get("cost") or {}).get("markers") or [] if x.get("tone") == "ink"]
        if mk:
            out["cost"]["budget"] = float(mk[0]["x"])
            out["cost"]["p_budget"] = _curve_at(c, float(mk[0]["x"]))
        if (m.get("cost") or {}).get("eval_x") is not None:
            out["cost"]["p_budget10"] = _curve_at(c, float(m["cost"]["eval_x"]))
        out["cost"]["n"] = (m.get("cost") or {}).get("n")
    o = (m.get("comp") or {}).get("curves", {}).get("")
    if o:
        out["comp"] = {"p_ge2": _curve_at(o, 2.0), "n": (m.get("comp") or {}).get("n"),
                       "cancel_pct": (((m.get("comp") or {}).get("extras") or {}).get("") or {}).get("cancel_pct")}
    out["drivers_time"] = (((m.get("time") or {}).get("drivers") or {}).get("") or {}).get("rows") or []
    out["drivers_cost"] = (((m.get("cost") or {}).get("drivers") or {}).get("") or {}).get("rows") or []
    return out


def verdict(report: dict, inc: list[dict]) -> tuple[str, list[str], int]:
    """Overall risk from a fixed rule (shown in the method section): 2 points per key question answered badly, 1 point each for
    3+ and 6+ signals in the pack, a missing key document, and a late share of 50%+ in the reference class."""
    qs = report.get("questions") or []
    bad = [q for q in qs if q.get("tone") == "bad"]
    pts = 2 * len(bad) + (len(inc) >= 3) + (len(inc) >= 6)
    missing = [m for m in report.get("missing") or [] if isinstance(m, dict)]
    pts += 1 if missing else 0
    late = ((report.get("shares") or {}).get("late") or {}).get("value")
    pts += 1 if late is not None and late >= 0.5 else 0
    level = "WYSOKIE" if pts >= 5 else "PODWYŻSZONE" if pts >= 3 else "UMIARKOWANE"
    why = [f"{q.get('question')} {q.get('answer')}: {q.get('key_display') or _disp(q.get('key_number'))} (n = {q.get('n') or _n_of(q.get('key_number'))})" for q in bad]
    if late is not None:
        why.append(f"w klasie odniesienia po terminie kończyło się {K.pct(late)} umów")
    why.append(f"{K.plural(len(inc), 'sygnał', 'sygnały', 'sygnałów')} ryzyka w dokumentach i danych")
    if missing:
        why.append("brak dokumentu: " + ", ".join((m.get("title") or "").replace("Brak: ", "") for m in missing))
    return level, why, int(pts)


def actions(report: dict, sim: dict | None, inc: list[dict], exc: list[dict]) -> list[list[Any]]:
    """Investor action list derived by rules from the analysis (no model): [when, what, why]."""
    out: list[list[Any]] = []
    qs = {q.get("key"): q for q in report.get("questions") or []}
    if exc:
        out.append(["teraz", f"Rozstrzygnij {K.plural(len(exc), 'uwagę', 'uwagi', 'uwag')} modelu w Czerwonym długopisie",
                    "Do pakietu wchodzą tylko uwagi zatwierdzone przez autora analizy."])
    for m in report.get("missing") or []:
        if isinstance(m, dict):
            out.append(["przed ogłoszeniem", f"Uzupełnij dokument: {(m.get('title') or '').replace('Brak: ', '')}", m.get("limits") or ""])
    t = qs.get("time") or qs.get("on_time")
    st = (t or {}).get("stats") or {}
    if t and t.get("tone") == "bad":
        p50 = st.get("planned_p50_months")
        out.append(["przed ogłoszeniem", "Wydłuż termin umowy" + (f" do ok. {K.fmt_num(round(p50))} mies." if p50 else "") + " albo uzasadnij krótszy",
                    f"Szansa na termin przy planie {K.fmt_num(t.get('you'), 0)} mies.: {t.get('key_display')} (n = {t.get('n')})"
                    + (f"; mediana planowanych terminów w klasie {K.fmt_num(p50, 1)} mies." if p50 else "") + "."])
    for r in ((report.get("allocation") or {}).get("risks") or []) if isinstance(report.get("allocation"), dict) else []:
        if r.get("recommended") is not None and r.get("chosen") is not None and r.get("chosen") != r.get("recommended"):
            out.append(["przed ogłoszeniem", f"Przypisz ryzyko {r.get('code')} ({r.get('title')}) stronie zalecanej", r.get("warning") or ""])
    for o in (sim or {}).get("options") or []:
        if o.get("plan_override") and t and t.get("tone") == "bad":
            continue                                    # the longer-term option is already the "extend the term" action
        eff = ", ".join(f"{k}: {v}" for k, v in (("termin", (o.get("effect_label") or {}).get("time")), ("koszt", (o.get("effect_label") or {}).get("cost")),
                                                 ("oferty", (o.get("effect_label") or {}).get("comp"))) if v)
        when = "w projekcie umowy" if (o.get("clause_refs") and not o.get("plan_override") and o.get("key") != "geo") else "przed ogłoszeniem"
        out.append([when, f"{o.get('label')} ({o.get('risk_code')})", f"{o.get('detail') or ''} Efekt w symulacji: {eff}. Wielkość wpływu to założenie eksperta."])
    for c in report.get("clauses") or []:
        out.append(["w projekcie umowy", f"Wpisz zapis {c.get('code')}: {c.get('title')}", f"Sygnał: {c.get('why')}" if c.get("why") else ""])
    prog = qs.get("programme")
    if prog and prog.get("tone") == "bad":
        out.append(["przed ogłoszeniem", "Sprawdź termin kwalifikowalności w umowie o dofinansowanie", f"{prog.get('question')} {prog.get('key_display')}."])
    seen, uniq = set(), []
    for a in out:
        if a[1] not in seen:
            seen.add(a[1])
            uniq.append(a)
    return uniq[:12]


def _ref_where(r: dict) -> str:
    return ", ".join(x for x in (f"pole {r['field_code']}" if r.get("field_code") else "", f"s. {r['page_no']}" if r.get("page_no") else "") if x)


def build_docx(report: dict, annex: list[dict], hashes: dict[str, dict], sim: dict | None = None) -> bytes:
    return build_blocks(report, annex, hashes, sim).to_docx()


def build_blocks(report: dict, annex: list[dict], hashes: dict[str, dict], sim: dict | None = None) -> K.Blocks:
    code, version = report.get("code") or report.get("id") or "", report.get("version") or 1
    B = K.Blocks(doc_title="Analiza nowej inwestycji", doc_id=f"{code}, wersja {version}", subject=report.get("title") or "")
    inc, exc = split_flags(report)
    S = sim_summary(sim)
    qs = report.get("questions") or []
    qk = {q.get("key"): q for q in qs}
    docs = report.get("documents") or []
    rc = report.get("reference_class") or {}
    final = rc.get("final") or {}
    shares = report.get("shares") or {}

    # page 1 -------------------------------------------------------------------------------------------------------
    doc_line = "Dokumenty: " + "; ".join(f"{d.get('doc_type') or 'dokument'} {d.get('filename') or ''}, {K.fmt_num(d.get('pages'))} s." for d in docs) if docs \
        else "Dokumenty: tylko opis tekstowy (bez pliku)."
    B.title("Analiza ryzyk nowej inwestycji", report.get("title") or f"Analiza {code}",
            [report.get("subtitle") or f"{code}, wersja {version}", doc_line,
             f"Dane: umowy wod-kan z ogłoszeń BZP, stan na {_date(report.get('data_as_of')) or 'brak'}; Katalog ryzyk {report.get('catalogue_version') or 'brak'}."
             + (" Dokument poufny." if report.get("sensitivity") == "confidential" else "")])
    B.h1("Najważniejsze wnioski")
    level, why, _ = verdict(report, inc)
    B.callout([["Powody: " + "; ".join(why) + "."],
               [{"t": "Ocena wynika z reguły opisanej w sekcji „Metoda” (bez modelu językowego).", "c": K.MUTED, "s": 7.5}]],
              tone="attention" if level != "UMIARKOWANE" else "info", title=f"Werdykt: ryzyko {level.lower()}")
    tiles = []
    t = qk.get("time") or qk.get("on_time")
    if t:
        rng = t.get("range") or {}
        ci = ((t.get("stats") or {}).get("ci90")) or ((t.get("key_number") or {}).get("prov") or {}).get("ci90")
        tiles.append({"value": t.get("key_display") or _disp(t.get("key_number")), "label": t.get("question") or "Szansa na termin",
                      "foot": f"n = {t.get('n') or _n_of(t.get('key_number'))}" + (f", przedział 90%: {K.pct(ci[0])} do {K.pct(ci[1])}" if ci else "")
                      + (f"; 8 na 10 umów do {K.fmt_num(rng['p80'], 1)} mies." if rng.get("p80") else ""), "tone": "attention" if t.get("tone") == "bad" else None})
    bq = qk.get("budget")
    if bq:
        rng = bq.get("range") or {}
        tiles.append({"value": bq.get("key_display") or _disp(bq.get("key_number")), "label": "Koszt kilometra sieci (brutto)",
                      "foot": f"{rng.get('plain') or ''}, n = {bq.get('n')}" + (f"; połowa umów {K.fmt_num(rng['p25'], 2)} do {K.fmt_num(rng['p75'], 2)} mln zł/km" if rng.get("p25") is not None else ""),
                      "tone": "attention" if bq.get("tone") == "bad" else None})
    if S and S.get("cost"):
        sc = S["cost"]
        tiles.append({"value": f"{K.fmt_num(sc['p80'], 2)} mln zł", "label": "Koszt końcowy P80 (symulacja, brutto)",
                      "foot": f"P50 {K.fmt_num(sc['p50'], 2)}, P90 {K.fmt_num(sc['p90'], 2)} mln zł; n = {sc.get('n')}, {K.fmt_num(S.get('runs'))} losowań",
                      "tone": "attention" if sc.get("budget") and sc["p80"] > sc["budget"] * 1.1 else None})
    pq = qk.get("programme")
    if pq:
        tiles.append({"value": pq.get("key_display") or _disp(pq.get("key_number")), "label": pq.get("question") or "Termin programu",
                      "foot": f"n = {pq.get('n')}; koniec programu {_date((pq.get('deadline') or {}).get('date'))} (założenie eksperta)",
                      "tone": "attention" if pq.get("tone") == "bad" else None})
    if tiles:
        B.tiles(tiles[:4])
    bl: list[Any] = []
    summ = report.get("summary") or {}
    if isinstance(summ, dict) and summ.get("sentence"):
        bl.append(K.tagged("calc", summ["sentence"] + f" (n = {(summ.get('prov') or {}).get('n') or final.get('n') or ''})"))
    cost = report.get("cost") or {}
    if cost.get("q_pct"):
        qp = cost["q_pct"]
        bl.append(K.tagged("calc", f"Dopłaty w klasie odniesienia: bez dopłaty {K.pct(cost.get('p_no_overrun'))} umów, do +10% {K.pct(cost.get('p_within_10pct'))}; "
                           f"9 na 10 umów mieści się w +{K.fmt_num(qp.get('p90'), 1)}% wartości umowy (P80 +{K.fmt_num(qp.get('p80'), 1)}%, n = {cost.get('n')})."))
    if S and S.get("time"):
        st_ = S["time"]
        bl.append(K.tagged("calc", f"Symulacja ({K.fmt_num(S.get('runs'))} losowań całych umów, n = {S.get('n')}): czas realizacji P50 {K.fmt_num(st_['p50'], 1)}, "
                           f"P80 {K.fmt_num(st_['p80'], 1)}, P90 {K.fmt_num(st_['p90'], 1)} mies. wobec planu {K.fmt_num(st_.get('plan'), 1)} mies."))
    ch = shares.get("changes") or {}
    if ch.get("display"):
        top = (S or {}).get("drivers_time") or []
        bl.append(K.tagged("calc", f"Zmiany umów: {ch['display']} podobnych umów miało zmiany"
                           + (f"; najbardziej wydłuża termin {top[0]['label']} ({top[0]['display']} do wyniku P80, n = {top[0].get('n_r')})" if top else "") + "."))
    n_doc = sum(1 for f in inc if f.get("quote") or f.get("doc"))
    bl.append(K.tagged("calc", f"Czerwony długopis: w pakiecie {K.plural(len(inc), 'sygnał', 'sygnały', 'sygnałów')} "
                       f"({len(inc) - n_doc} z reguł na liczbach, {n_doc} z cytatem z dokumentu)"
                       + (f"; {K.plural(len(exc), 'uwaga modelu czeka', 'uwagi modelu czekają', 'uwag modelu czeka')} na decyzję autora i nie weszły do pakietu" if exc else "") + "."))
    _, diffs = feature_rows(report)
    miss = [m for m in report.get("missing") or [] if isinstance(m, dict)]
    if diffs or miss:
        bl.append(K.tagged("pending", "Do sprawdzenia: " + "; ".join(([f"{len(diffs)} cech z dokumentu różni się od wartości przyjętych do obliczeń"] if diffs else [])
                                                                + [m.get("title") or "" for m in miss]) + " (sekcja 9)."))
    B.bullets(bl[:6])
    B.legend(["src", "calc", "ai", "approved", "assumption"])

    # 1 features ------------------------------------------------------------------------------------------------------
    B.page_break()
    B.h1("1. Opis inwestycji: cechy odczytane z dokumentów")
    frows, diffs = feature_rows(report)
    if frows:
        B.table(["Cecha", "Odczytano", "Przyjęto do obliczeń", "Skąd (dokument, strona, cytat)", "Pochodzenie"], frows, [2.6, 3.0, 3.0, 6.6, 2.2], size=7.8)
        B.note("„niepewne”: model językowy sam oznaczył odczyt jako niepewny. „inna niż odczyt”: do obliczeń przyjęto inną wartość (z opisu albo poprawki autora); "
               "różnice są też w sekcji 9.")
    if report.get("text"):
        B.p([{"t": "Opis wpisany przez autora: ", "b": True}, _q(report["text"], 600)])

    # 2 reference class ---------------------------------------------------------------------------------------------
    B.h1("2. Klasa odniesienia i podobne przypadki")
    funnel = rc.get("funnel") or []
    if funnel:
        B.table(["Krok zawężania", "Umowy (n)", "z terminem", "z kosztem"],
                [[s.get("label") or "", K.fmt_num(s.get("n")), K.fmt_num(s.get("n_time")) if s.get("n_time") is not None else "",
                  K.fmt_num(s.get("n_cost")) if s.get("n_cost") is not None else ""] for s in funnel], [9.4, 2.6, 2.7, 2.7], right=(1, 2, 3))
    if final.get("n") is not None:
        B.p(K.tagged("calc", f"Klasa końcowa: {rc.get('label') or final.get('label') or ''}, n = {final['n']} umów"
                     + (" (klasa poszerzona, bo węższa była za mała)" if final.get("widened") else "") + "."))
    sh = [(lbl, shares.get(k)) for k, lbl in (("late", "skończone po terminie"), ("changes", "ze zmianą umowy"), ("paid_above", "z wypłatą ponad umowę"))]
    sh = [(lbl, v) for lbl, v in sh if isinstance(v, dict) and v.get("display")]
    if sh:
        B.table(["Udział umów w klasie", "Wynik", "Przedział 90%", "n"],
                [[lbl, v["display"], _ci((v.get("prov") or {}).get("ci90")), str(v.get("n") or "")] for lbl, v in sh],
                [7.4, 3.6, 4.0, 2.4], right=(3,))
    if report.get("backtest_note"):
        B.note("Sprawdzian wsteczny: " + report["backtest_note"])
    sim_cases = report.get("similar_cases") or []
    if sim_cases:
        B.h2(f"Podobne przypadki (najbliższe {len(sim_cases[:8])} z n = {((sim_cases[0].get('score_num') or sim_cases[0].get('score') or {}).get('prov') or {}).get('n') or 'brak'})")
        rows = []
        for s in sim_cases[:8]:
            o = s.get("outcome") or {}
            refs = ((o.get("delay_days") or {}).get("prov") or {}).get("refs") or []
            ref = refs[0] if refs else {}
            rows.append([str(s.get("rank") or ""), [{"t": s.get("title") or "", "b": True}, f"\n{s.get('buyer_name') or ''}"],
                         _disp(s.get("score_num")) or (K.fmt_num(float(s["score"]), 2) if isinstance(s.get("score"), (int, float)) else _disp(s.get("score"))),
                         _disp(o.get("delay_days")), _disp(o.get("cost_dev_pct")), s.get("why") or "",
                         {"t": str(ref.get("id") or ""), "link": ref.get("url")} if ref.get("url") else str(ref.get("id") or "")])
        B.table(["#", "Umowa i zamawiający", "Podob.", "Opóźnienie", "Koszt", "Dlaczego podobna", "Ogłoszenie o wykonaniu"], rows,
                [0.6, 5.2, 1.3, 1.8, 1.4, 4.4, 2.7], size=7.4, right=(2, 3, 4))

    # 3 chances -------------------------------------------------------------------------------------------------------
    B.h1("3. Szanse na termin i budżet")
    if qs:
        rows = []
        for q in qs:
            rng = q.get("range") or {}
            st = q.get("stats") or {}
            if rng.get("p10") is not None:
                band = f"P10 do P90: {K.fmt_num(rng['p10'], 1)} do {K.fmt_num(rng['p90'], 1)} mies.; mediana {K.fmt_num(rng.get('p50'), 1)}, P80 {K.fmt_num(rng.get('p80'), 1)}"
            elif rng.get("p25") is not None:
                band = f"P25 do P75: {K.fmt_num(rng['p25'], 2)} do {K.fmt_num(rng['p75'], 2)} mln zł/km; mediana {K.fmt_num(rng.get('p50'), 2)}"
            elif st.get("months_available") is not None:
                band = f"do końca programu ok. {K.fmt_num(st['months_available'], 1)} mies. od podpisania umowy"
            else:
                band = ""
            ci = st.get("ci90") or ((q.get("key_number") or {}).get("prov") or {}).get("ci90")
            if ci:
                band += f"; przedział 90% szansy: {K.pct(ci[0])} do {K.pct(ci[1])}"
            prov = q.get("provenance") or {}
            rows.append([{"t": q.get("question") or "", "b": True}, q.get("answer") or "", q.get("key_display") or _disp(q.get("key_number")), band,
                         str(q.get("n") or _n_of(q.get("key_number"))), [K.tag("calc"), " ", prov.get("text") or ((q.get("key_number") or {}).get("prov") or {}).get("method") or ""]])
        B.table(["Pytanie", "Odpowiedź", "Liczba", "Zakres", "n", "Pochodzenie"], rows, [3.3, 2.0, 2.0, 5.0, 1.1, 4.0], size=7.6, right=(4,))
    if cost.get("q_pct"):
        qp = cost["q_pct"]
        B.p(K.tagged("calc", f"Wypłata wobec wartości umowy w klasie (n = {cost.get('n')}): P50 {K.fmt_num(qp.get('p50'), 1)}%, P80 +{K.fmt_num(qp.get('p80'), 1)}%, "
                     f"P90 +{K.fmt_num(qp.get('p90'), 1)}%; bez dopłaty {K.pct(cost.get('p_no_overrun'))}, do +10% {K.pct(cost.get('p_within_10pct'))}."))

    # 4 simulation ----------------------------------------------------------------------------------------------------
    B.h1("4. Symulacja: czas, koszt i oferty")
    if S:
        rows = []
        if S.get("time"):
            st_ = S["time"]
            rows.append(["Czas realizacji (mies. od podpisania)", K.fmt_num(st_["p50"], 1), K.fmt_num(st_["p80"], 1), K.fmt_num(st_["p90"], 1),
                         f"plan {K.fmt_num(st_.get('plan'), 1)} mies.: szansa {K.pct(st_.get('p_plan'))}", str(st_.get("n") or "")])
        if S.get("cost"):
            sc = S["cost"]
            rows.append(["Koszt końcowy (mln zł brutto)", K.fmt_num(sc["p50"], 2), K.fmt_num(sc["p80"], 2), K.fmt_num(sc["p90"], 2),
                         (f"budżet {K.fmt_num(sc['budget'], 2)}: szansa {K.pct(sc.get('p_budget'))}; z rezerwą 10%: {K.pct(sc.get('p_budget10'))}" if sc.get("budget") else ""),
                         str(sc.get("n") or "")])
        if S.get("comp"):
            co = S["comp"]
            rows.append(["Liczba ofert", "", "", "", f"co najmniej 2 oferty: {K.pct(co.get('p_ge2'))}"
                         + (f"; unieważnienia w klasie: {K.fmt_num(co['cancel_pct'], 0)}%" if co.get("cancel_pct") is not None else ""), str(co.get("n") or "")])
        B.table(["Miara", "P50", "P80", "P90", "Wobec planu", "n"], rows, [4.4, 1.5, 1.5, 1.5, 7.3, 1.2], right=(1, 2, 3, 5))
        B.note(f"Monte Carlo: {K.fmt_num(S.get('runs'))} losowań całych umów z klasy odniesienia (opóźnienie, koszt i przyczyny zmian zostają powiązane), "
               f"ziarno {S.get('seed')}. P80 = wynik, którego nie przekracza 8 na 10 symulowanych umów. Bez działań ograniczających.")
        dt, dc = S.get("drivers_time") or [], S.get("drivers_cost") or []
        if dt or dc:
            B.h2("Co najbardziej przesuwa wynik")
            n = max(len(dt), len(dc))
            B.table(["Termin (dni do wyniku P80)", "", "n", "Koszt (pp do wyniku P90)", "", "n"],
                    [[(dt[i]["label"] if i < len(dt) else ""), (dt[i]["display"] if i < len(dt) else ""), (str(dt[i].get("n_r") or "") if i < len(dt) else ""),
                      (dc[i]["label"] if i < len(dc) else ""), (dc[i]["display"] if i < len(dc) else ""), (str(dc[i].get("n_r") or "") if i < len(dc) else "")]
                     for i in range(min(n, 5))], [5.0, 1.8, 1.1, 5.6, 2.0, 1.9], right=(1, 2, 4, 5))
        opts = (sim or {}).get("options") or []
        if opts:
            B.h2("Działania ograniczające w symulacji")
            B.table(["Działanie", "Ryzyko", "Termin", "Koszt", "Oferty", "Pochodzenie"],
                    [[[{"t": o.get("label") or "", "b": True}, f"\n{o.get('detail') or ''}"], o.get("risk_code") or "", (o.get("effect_label") or {}).get("time") or "",
                      (o.get("effect_label") or {}).get("cost") or "", (o.get("effect_label") or {}).get("comp") or "", [K.tag("assumption")]] for o in opts],
                    [6.4, 1.6, 2.4, 2.0, 2.0, 3.0], size=7.6)
        if (sim or {}).get("honesty_note"):
            B.note(sim["honesty_note"])
    else:
        B.p("Symulacji nie dołączono (za mało umów w klasie albo analiza w starszej wersji). Zakresy z sekcji 3 pozostają ważne.")

    # 5 red pen -------------------------------------------------------------------------------------------------------
    B.h1("5. Czerwony długopis: sygnały ryzyka w dokumentach")
    if inc:
        rows = []
        for f in inc:
            q = _quote_of(f)
            p = f.get("prov") or {}
            key = "approved" if f.get("origin") == "AI" else K.prov_key(f.get("origin") or "CALC", f.get("review_status") or p.get("review_status"))
            ev: Any = q or [{"t": f"reguła {f.get('rule') or p.get('method') or ''} z Katalogu czerwonych flag", "c": K.MUTED}]
            num = _disp(f.get("number"))
            n = _n_of(f.get("number")) or p.get("n")
            n = n if n and str(n) not in ("0", "1") else ""
            rows.append([[K.tag(key), "\n", {"t": f.get("title") or "", "b": True}], f.get("text") or "", ev, ", ".join(f.get("risk_codes") or []),
                         (num + (f" (n = {n})" if n else "")).strip() or (f"n = {n}" if n else "z dokumentu")])
        B.table(["Sygnał", "Co to znaczy", "Cytat (strona) albo reguła", "Kod R", "Liczba"], rows, [3.4, 5.0, 5.4, 1.4, 2.2], size=7.6)
    else:
        B.p("Brak sygnałów w pakiecie.")
    if exc:
        B.callout(f"{K.plural(len(exc), 'uwaga modelu językowego czeka', 'uwagi modelu językowego czekają', 'uwag modelu językowego czeka')} na decyzję autora "
                  "analizy w aplikacji (Czerwony długopis). Do pakietu wchodzą tylko uwagi zatwierdzone; niezatwierdzone nie wpływają na werdykt ani rejestr.",
                  tone="attention", title=f"Pominięto {K.plural(len(exc), 'wniosek AI', 'wnioski AI', 'wniosków AI')}, których autor analizy nie zatwierdził")

    # 6 register --------------------------------------------------------------------------------------------------------
    reg = risk_register(report, inc, sim)
    B.h1("6. Rejestr ryzyk")
    if reg:
        B.table(["Kod", "Ryzyko", "Częstość w klasie", "Skutek", "Koszt oczekiwany", "Właściciel"], reg, [1.4, 3.6, 3.0, 3.4, 3.0, 3.0], size=7.6)
        B.note("Częstość (prawdopodobieństwo): odsetek umów z tą przyczyną zmiany w grupie porównawczej (n). Skutek: P50 i P80 wydłużenia oraz wzrostu kosztu wśród umów, "
               "w których ryzyko wystąpiło. Koszt oczekiwany = prawdopodobieństwo x skutek x budżet (brutto). Właściciel: wybrana strona podziału ryzyk.")
    else:
        B.p("Brak ryzyk do rejestru.")

    # 7 allocation ------------------------------------------------------------------------------------------------------
    alloc = report.get("allocation") if isinstance(report.get("allocation"), dict) else None
    B.h1("7. Podział ryzyk")
    if alloc and alloc.get("risks"):
        rows, shade = [], {}
        for i, r in enumerate(alloc["risks"]):
            pos = r.get("positions") or []
            rec = r.get("recommended")
            rec_l = pos[rec].get("label") if isinstance(rec, int) and 0 <= rec < len(pos) else ""
            how = r.get("how") or []
            ch_ = r.get("chosen")
            how_l = how[ch_] if isinstance(ch_, int) and 0 <= ch_ < len(how) else ""
            off = rec is not None and ch_ is not None and rec != ch_
            if off:
                shade[i] = K.TINT_Y
            rows.append([{"t": r.get("code") or "", "b": True}, r.get("title") or "", CONTROL_PL.get(r.get("controlled_by"), r.get("controlled_by") or ""),
                         rec_l, [{"t": _owner(r), "b": True}] + ([" ", {"t": "inaczej niż zalecamy", "c": K.AMBER, "b": True, "s": 7}] if off else []), how_l])
        B.table(["Kod", "Ryzyko", "Kto nad nim panuje", "Zalecamy", "Wybrano", "Jak (wybrana pozycja)"], rows, [1.4, 3.4, 2.4, 2.2, 2.6, 5.4],
                size=7.6, shade_rows=shade, zebra=False)
        b = alloc.get("balance") or {}
        if b:
            B.p(K.tagged("calc", (b.get("note") or "") + " " + "; ".join(x for x in (
                f"koszt oczekiwany po stronie zamawiającego {K.money_pl(b['buyer'])}" if b.get("buyer") else "",
                f"po stronie wykonawcy {K.money_pl(b['contractor'])}" if b.get("contractor") else "",
                f"narzut wykonawcy w ofercie za ryzyka {K.money_pl(b['premium'])}" if b.get("premium") else "") if x) + "."))
            B.note("Narzut i podział liczone z założeń eksperta z Katalogu (wykonawca dolicza do ceny ryzyko, nad którym nie panuje).")
    else:
        B.p("Autor analizy nie ustalił podziału ryzyk.")

    # 8 clauses and actions ------------------------------------------------------------------------------------------------
    B.h1("8. Zalecane zapisy umowne i lista działań")
    clauses = report.get("clauses") or []
    if clauses:
        B.table(["Zapis", "Dlaczego", "Treść (szablon z Katalogu, do uzupełnienia)", "Status"],
                [[[{"t": c.get("code") or "", "b": True}, f"\n{c.get('title') or ''}"],
                  f"{c.get('why') or ''}" + (f" ({_disp(c.get('number'))} podobnych umów, n = {_n_of(c.get('number'))})" if _n_of(c.get("number")) else ""),
                  c.get("text") or "", "w pakiecie" if c.get("in_pack") else "zalecany, nie dodany"] for c in clauses],
                [2.8, 3.8, 8.6, 2.2], size=7.4)
    else:
        B.p("Brak zaleceń zapisów umownych.")
    acts = actions(report, sim, inc, exc)
    if acts:
        B.h2("Lista działań dla inwestora")
        B.table(["#", "Kiedy", "Działanie", "Dlaczego"], [[str(i), a[0], {"t": a[1], "b": True}, a[2]] for i, a in enumerate(acts, 1)],
                [0.6, 2.6, 6.0, 8.2], size=7.6)
        B.note("Lista powstaje z reguł na wynikach analizy (bez modelu językowego); kolejność: decyzje teraz, przed ogłoszeniem, w projekcie umowy.")

    # 9 data quality ------------------------------------------------------------------------------------------------------
    B.h1("9. Jakość danych, luki i rozbieżności")
    issues: list[list[Any]] = []
    for d in diffs:
        issues.append(["rozbieżność", d, "pokazane obie wartości; decyzja autora analizy"])
    for f in report.get("features") or []:
        if isinstance(f, dict) and f.get("unsure"):
            issues.append(["odczyt niepewny", f"{f.get('label')}: {f.get('display')} ({f.get('source_label') or 'opis'})", "sprawdź w dokumencie"])
    for m in report.get("missing") or []:
        if isinstance(m, dict):
            issues.append(["brak dokumentu", f"{m.get('title')}: {m.get('limits') or ''}", STATE_LABEL.get(m.get("evidence_state"), m.get("state_label") or "")])
    for g in report.get("gaps") or []:
        if isinstance(g, dict):
            issues.append(["luka", f"{g.get('title') or g.get('doc_type')}: {g.get('limits') or ''}", STATE_LABEL.get(g.get("evidence_state"), "")])
    if exc:
        issues.append(["propozycje AI", f"{K.plural(len(exc), 'uwaga czeka', 'uwagi czekają', 'uwag czeka')} na decyzję autora analizy", "nie weszły do pakietu"])
    if report.get("unverified_hidden"):
        issues.append(["widok", f"Ukryto {report['unverified_hidden']} niezweryfikowanych pozycji.", ""])
    for q in qs:
        if q.get("insufficient"):
            issues.append(["za mało danych", f"{q.get('question')}: za mało umów w klasie, odpowiedź „{q.get('answer')}”.", "poszerz klasę"])
    if issues:
        B.callout("Rozbieżności i luki pokazujemy, nie poprawiamy ich po cichu. Każdą rozstrzyga autor analizy albo ekspert.", tone="attention", title="Wymaga uwagi")
        B.table(["Rodzaj", "Opis", "Stan albo co dalej"], issues, [3.0, 10.2, 4.2], size=7.8)
    else:
        B.p("Nie wykryto rozbieżności ani luk.")

    # 10 method -----------------------------------------------------------------------------------------------------------
    B.page_break()
    B.h1("10. Metoda, źródła i ograniczenia")
    models = sorted({((f.get("prov") or {}).get("llm") or {}).get("model") for f in (report.get("features") or []) + (report.get("flags") or [])
                     if isinstance(f, dict) and ((f.get("prov") or {}).get("llm") or {}).get("model")} - {None})
    B.h2("Zbiory danych")
    rows = [["Umowy wod-kan z ogłoszeń BZP (kopia organizatora, ogłoszenia o wyniku i o wykonaniu)", _date(report.get("data_as_of")) or "brak",
             {"t": report.get("data_version") or "", "mono": True, "s": 6.5}],
            ["Katalog ryzyk wod-kan (kody R, czerwone flagi, założenia ekspertów)", "", report.get("catalogue_version") or ""]]
    for d in docs:
        h = hashes.get(f"document:{d.get('id') or d.get('document_id')}", {})
        rows.append([f"Dokument inwestycji: {d.get('filename') or d.get('label') or ''} ({d.get('doc_type') or ''}, {K.fmt_num(d.get('pages'))} s.)",
                     _date(h.get("retrieved_at")), {"t": h.get("sha256") or "", "mono": True, "s": 6.2}])
    B.table(["Zbiór", "Stan na / pobrano", "Wersja albo sha256"], rows, [8.2, 2.6, 6.6], size=7.6)
    B.h2("Co liczą reguły, a co model językowy")
    B.bullets([
        ("Reguły i statystyka (bez AI): klasa odniesienia i jej n, szanse na termin i budżet (z przedziałami 90%), koszt kilometra, symulacja Monte Carlo, "
         "sygnały z reguł Katalogu, rejestr i podział ryzyk, lista działań, werdykt."),
        ("Model językowy: odczyt cech z dokumentu (propozycje, oznaczone w sekcji 1) i uwagi czerwonego długopisu z cytatem i stroną; do pakietu wchodzą "
         "tylko uwagi zatwierdzone przez autora analizy. Cytaty są sprawdzane w tekście dokumentu (dokładnie albo po normalizacji)."
         + (f" Użyty model: {', '.join(models)}." if models else "")),
        "Przyczyny zmian w umowach historycznych sklasyfikował model językowy (ok. 8 na 10 trafień na próbie wzorcowej), a gdzie go brak, reguły słownikowe.",
        ("Werdykt: 2 punkty za każde pytanie z odpowiedzią negatywną, po 1 punkcie za co najmniej 3 i co najmniej 6 sygnałów w pakiecie, za brak kluczowego "
         "dokumentu i za odsetek opóźnionych w klasie od 50%. 5 i więcej punktów: ryzyko wysokie; 3 do 4: podwyższone; mniej: umiarkowane."),
        METHOD_NOTE])
    lims = list(report.get("limitations") or [])
    for x in (sim or {}).get("limitations") or []:
        if x not in lims:
            lims.append(x)
    if lims:
        B.h2("Ograniczenia")
        B.bullets(lims)
    proc = report.get("processing") or []
    if proc:
        B.note("Przetwarzanie: " + "; ".join(f"{x.get('task')}: {x.get('data_location') or ''}" for x in proc) + ".")
    B.note(f"Bieżąca wersja analizy: {K.APP_URL}/analizy/{code}. Pakiet pokazuje stan analizy w chwili wygenerowania.")

    # annex -----------------------------------------------------------------------------------------------------------------
    B.page_break()
    B.h1("Załącznik A. Źródła i cytaty")
    doc_refs = [r for r in annex if r.get("kind") == "document"]
    not_refs = [r for r in annex if r.get("kind") == "notice"]
    other = [r for r in annex if r.get("kind") not in ("document", "notice")]
    if doc_refs:
        B.h2("Cytaty z dokumentów inwestycji")
        seen, rows = set(), []
        for r in doc_refs:
            k = (r.get("id"), r.get("page_no"), r.get("quote"))
            if k in seen:
                continue
            seen.add(k)
            h = hashes.get(f"document:{r['id']}", {})
            rows.append([f"dokument {r['id']}", str(r.get("page_no") or ""), _q(r.get("quote"), 400) or (r.get("label") or ""),
                         {"exact": "dokładny", "fuzzy": "przybliżony"}.get(r.get("verification"), r.get("verification") or ""),
                         {"t": (h.get("sha256") or "")[:16], "mono": True, "s": 6.5}])
        B.table(["Dokument", "Strona", "Cytat", "Zgodność", "sha256 (początek)"], rows, [2.2, 1.3, 9.6, 1.6, 2.7], size=7.4, right=(1,))
    if not_refs:
        B.h2("Ogłoszenia BZP (wyniki podobnych umów)")
        seen, rows = set(), []
        for r in not_refs:
            k = (r.get("id"), r.get("field_code"))
            if k in seen:
                continue
            seen.add(k)
            h = hashes.get(f"notice:{r['id']}", {})
            url = r.get("url") or h.get("url")
            rows.append([{"t": str(r["id"]), "link": url} if url else str(r["id"]), r.get("label") or "", _ref_where(r), _date(r.get("retrieved_at") or h.get("retrieved_at")),
                         {"t": (h.get("sha256") or "")[:16], "mono": True, "s": 6.5}])
        if any(plain_ for row in rows for plain_ in (row[3], row[4]["t"])):
            B.table(["Ogłoszenie", "Rodzaj", "Pole", "Pobrano", "sha256 (początek)"], rows, [4.4, 4.0, 2.4, 2.6, 4.0], size=7.4)
        else:
            B.table(["Ogłoszenie (link do ezamowienia.gov.pl)", "Rodzaj", "Pole"], [row[:3] for row in rows], [7.4, 6.0, 4.0], size=7.4)
            B.note("Ogłoszenia pochodzą z kopii BZP organizatora (plik notices.jsonl, sha256 w metadanych źródła); numer pola według formularza BZP.")
    if other:
        B.h2("Zapytania do bazy i parametry Katalogu")
        grouped: dict[tuple, list[str]] = {}
        for r in other:
            ids_ = grouped.setdefault((r.get("kind"), r.get("label") or ""), [])
            if str(r.get("id")) not in ids_:
                ids_.append(str(r.get("id")))
        rows = [[{"query": "obliczenie", "catalogue": "Katalog", "input_text": "opis autora"}.get(k, k or ""), lbl,
                 {"t": ", ".join(v), "mono": True, "s": 6.5}] for (k, lbl), v in grouped.items()]
        B.table(["Rodzaj", "Opis", "Identyfikator"], rows, [2.4, 8.0, 7.0], size=7.4)
        B.note("Identyfikator zapytania opisuje filtr klasy odniesienia (np. podsektor, przedział wartości, formuła); to samo zapytanie daje ten sam wynik "
               "na tej samej wersji danych.")
    if not annex:
        B.p("Brak źródeł do wypisania.")
    return B


# ------------------------------------------------------------------------------------------------------- csv, json, pdf

def build_csv(report: dict) -> bytes:
    inc, _ = split_flags(report)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["kod", "ryzyko", "liczba", "n", "skutek", "koszt_oczekiwany", "wlasciciel", "pochodzenie", "status"])
    alloc = (report.get("allocation") or {}).get("risks") if isinstance(report.get("allocation"), dict) else None
    if alloc:
        for r in alloc:
            ec = (r.get("expected_cost") or {}).get("money") or {}
            w.writerow([r.get("code"), r.get("title"), "", (r.get("expected_cost") or {}).get("prov", {}).get("n"), _disp(r.get("impact")) or r.get("impact_label") or "",
                        f"{ec.get('amount', '')} {ec.get('currency', '')}".strip(), _owner(r), "obliczenie", "auto"])
    else:
        for f in inc:
            for code in f.get("risk_codes") or [""]:
                p = f.get("prov") or {}
                w.writerow([code, f.get("title"), _disp(f.get("number")), _n_of(f.get("number")), "", "", "", p.get("role") or f.get("origin") or "", f.get("review_status") or p.get("review_status") or ""])
    return ("﻿" + buf.getvalue()).encode()


def build_json(report: dict, annex: list[dict]) -> bytes:
    inc, exc = split_flags(report)
    out = {**report, "flags": inc, "excluded": manifest(report)["excluded"], "annex": annex}
    return json.dumps(out, ensure_ascii=False, indent=1, default=str).encode()


def to_pdf_bytes(docx: bytes) -> bytes:
    import tempfile

    from riskminer.documents.convert import to_pdf
    with tempfile.TemporaryDirectory(prefix="pack_") as d:
        src = Path(d) / "pack.docx"
        src.write_bytes(docx)
        return to_pdf(src, Path(d) / "out").read_bytes()


# ------------------------------------------------------------------------------------------------------------- render

class PackFile:
    def __init__(self, path: Path, filename: str, media_type: str):
        self.path, self.filename, self.media_type = path, filename, media_type


def packs_dir() -> Path:
    d = Path(settings().exports_dir) / "packs"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def render(db: AsyncSession, code: str, fmt: str, version: int | None = None) -> PackFile:
    """Build (or fetch from cache) the pack file for an analysis version. Raises analysis.service.NotFound for unknown code/version."""
    if fmt not in MEDIA:
        raise ValueError("unknown format")
    from riskminer.analysis import service as SV
    report = await SV.get_report(db, code, version)
    report.setdefault("code", code)
    v = report.get("version") or version or 1
    refs = collect_refs(pack_view(report))
    doc_refs = [{"kind": "document", "id": d.get("id") or d.get("document_id")} for d in report.get("documents") or [] if d.get("id") or d.get("document_id")]
    hashes = await resolve_hashes(db, refs + doc_refs)
    sim = None
    if fmt in ("docx", "pdf") and (version is None or version == report.get("version")):
        try:
            sim = await SV.simulation(db, code)
        except Exception:  # noqa: BLE001 - the pack renders without the simulation section (said so in the document)
            sim = None
    key = hashlib.sha256(json.dumps([PACK_LAYOUT, report, hashes, sim_summary(sim)], sort_keys=True, default=str).encode()).hexdigest()[:10]
    path = packs_dir() / f"{code}-v{v}-{key}.{fmt}"
    if not path.exists():
        if fmt == "docx":
            data = build_docx(report, refs, hashes, sim)
        elif fmt == "pdf":
            docx_path = packs_dir() / f"{code}-v{v}-{key}.docx"
            if not docx_path.exists():
                docx_path.write_bytes(build_docx(report, refs, hashes, sim))
            data = await asyncio.to_thread(to_pdf_bytes, docx_path.read_bytes())
        elif fmt == "csv":
            data = build_csv(report)
        else:
            data = build_json(report, refs)
        path.write_bytes(data)
    return PackFile(path, f"{code}-v{v}.{fmt}", MEDIA[fmt])
