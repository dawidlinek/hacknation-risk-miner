"""Feature chips: definitions (frontend keys), regex extraction from the user's text, conversion to engine Features.

Chip keys follow the frontend contract (`podsektor, formula, dlugosc_km, przepompownie, budzet, termin_mies,
finansowanie, przylacza`) plus `rodzaj_robot`, `wojewodztwo`, `rok`, `ogloszenie`, `termin_programu`.
Regex chips are CALC (method `regex:*`); LLM chips (session L) are inserted as AI/proposed analysis_item rows with the
same keys; owner edits become `edited`. Precedence when several exist: edited > approved > AI > regex.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from riskminer.analytics.base import DAYS_PER_MONTH, SUB_LABEL, WOJ_NAME, WORK_LABEL, classify_subsector, sector_pack
from riskminer.analytics.lengths import lengths
from riskminer.analytics.refclass import Features
from riskminer.config import feature

PROGRAMME_LABEL = {"KPO_B311": "KPO", "FENIKS": "FEnIKS 2021–2027", "FEP_RPO": "Fundusze Europejskie dla województwa",
                   "PROW": "PROW 2014–2020", "RFIL_PIS": "Rządowe programy (RFIL, Polski Ład)", "OWN": "środki własne"}

SECTOR_LABEL = {"wod-kan": "wod-kan"}   # extension sectors come from catalogue/<sector>/pack.yaml (sector_labels)


def extension_sectors() -> list[str]:
    """Sector packs other than wod-kan, in detection order (assign.priority, then name); [] while the flag is off.
    A new sector is data: a catalogue/<sector>/pack.yaml with an `analytics` block, no code change."""
    if not feature("sector_roads"):
        return []
    from riskminer.analytics.base import DEFAULT_SECTOR, known_sectors
    out = []
    for sec in known_sectors():
        if sec == DEFAULT_SECTOR:
            continue
        try:
            out.append((sector_pack(sec)["priority"], sec))
        except (KeyError, OSError, ValueError):
            continue
    return [sec for _, sec in sorted(out)]


def sector_labels() -> dict[str, str]:
    out = dict(SECTOR_LABEL)
    for sec in extension_sectors():
        out[sec] = f"{sector_pack(sec)['label_short']} (rozszerzenie pilotażu)"
    return out


def sector_options() -> list[dict]:
    return [{"value": k, "label": v} for k, v in sector_labels().items()]

FEATURE_DEFS: dict[str, dict[str, Any]] = {
    "sektor": {"label": "sektor", "editor": "select", "options": None},   # sector_options(), read per request
    "podsektor": {"label": "podsektor", "editor": "select",
                  "options": [{"value": k, "label": v} for k, v in SUB_LABEL.items()]},
    "formula": {"label": "formuła", "editor": "select",
                "options": [{"value": "design_build", "label": "zaprojektuj i wybuduj"},
                            {"value": "build", "label": "samo wykonanie"}]},
    "rodzaj_robot": {"label": "rodzaj robót", "editor": "select",
                     "options": [{"value": k, "label": v} for k, v in WORK_LABEL.items()]},
    "dlugosc_km": {"label": "długość", "editor": "number", "unit": "km"},
    "przepompownie": {"label": "przepompownie", "editor": "number", "unit": "szt."},
    "przylacza": {"label": "przyłącza", "editor": "number", "unit": "szt."},
    "budzet": {"label": "budżet", "editor": "money", "unit": "zł brutto"},
    "termin_mies": {"label": "termin", "editor": "months", "unit": "mies."},
    "finansowanie": {"label": "finansowanie", "editor": "select",
                     "options": [{"value": k, "label": v} for k, v in PROGRAMME_LABEL.items()]},
    "termin_programu": {"label": "termin programu", "editor": "text", "unit": "data"},
    "wojewodztwo": {"label": "województwo", "editor": "select",
                    "options": [{"value": k, "label": v} for k, v in WOJ_NAME.items()]},
    "rok": {"label": "rok ogłoszenia", "editor": "number"},
    "ogloszenie": {"label": "planowane ogłoszenie", "editor": "text", "unit": "data"},
}
CHIP_ORDER = ["sektor", "podsektor", "formula", "dlugosc_km", "przepompownie", "budzet", "termin_mies", "finansowanie",
              "przylacza", "rodzaj_robot", "wojewodztwo", "rok", "ogloszenie", "termin_programu"]
REQUIRED = ["podsektor", "budzet", "termin_mies"]

_NUM = r"(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[,.](\d+))?"


def _f(m: re.Match, g1: int = 1, g2: int = 2) -> float:
    return float(re.sub(r"[  ]", "", m.group(g1)) + ("." + m.group(g2) if m.group(g2) else ""))


def pl_dec(x: float, d: int = 1) -> str:
    s = f"{x:.{d}f}".rstrip("0").rstrip(".") if d else f"{x:.0f}"
    return s.replace(".", ",")


def display(key: str, value: Any, unsure: bool = False) -> str:
    if value is None:
        return "brak"
    q = "?" if unsure else ""
    if key == "podsektor":
        return all_sub_labels().get(value, str(value))
    if key == "sektor":
        return sector_labels().get(value, str(value))
    if key == "formula":
        return "zaprojektuj i wybuduj" if value in (True, "design_build") else "samo wykonanie"
    if key == "rodzaj_robot":
        return WORK_LABEL.get(value, str(value))
    if key == "dlugosc_km":
        return f"{'ok. ' if unsure else ''}{pl_dec(float(value), 2)} km{q}"
    if key in ("przepompownie", "przylacza"):
        return f"{int(value)} szt."
    if key == "budzet":
        amt = float(value["amount"]) if isinstance(value, dict) else float(value)
        vat = value.get("vat_basis", "gross") if isinstance(value, dict) else "gross"
        return f"{pl_dec(amt / 1e6, 2)} mln zł {'brutto' if vat == 'gross' else 'netto'}"
    if key == "termin_mies":
        return f"{pl_dec(float(value), 1)} mies."
    if key == "finansowanie":
        return PROGRAMME_LABEL.get(value, str(value))
    if key == "wojewodztwo":
        return WOJ_NAME.get(value, str(value))
    return str(value)


def all_sub_labels() -> dict[str, str]:
    out = dict(SUB_LABEL)
    for sec in reversed(extension_sectors()):       # shared codes (INNE) keep the first pack's label; chip() uses options
        out.update(sector_pack(sec)["sub_labels"])
    return out


def subsector_options(sector: str | None) -> list[dict]:
    if sector and sector != "wod-kan":
        try:
            return [{"value": k, "label": v} for k, v in sector_pack(sector)["sub_labels"].items()]
        except KeyError:
            pass
    return [{"value": k, "label": v} for k, v in SUB_LABEL.items()]


_WODKAN_WORDS = re.compile(r"kanalizac|wodociąg|ściek|oczyszczal|uzdatnian|przepompown|suw|wod-kan")


def detect_sector(text: str) -> tuple[str, re.Match | None]:
    """wod-kan unless the description says nothing about water or sewage and matches an extension pack's
    `sector_detect` words (catalogue/<sector>/lexicon.yaml), tried in assign.priority order (flag sector_roads)."""
    lo = (text or "").lower()
    if _WODKAN_WORDS.search(lo):
        return "wod-kan", None
    for sec in extension_sectors():
        for p in sector_pack(sec)["sector_detect"]:
            m = re.search(p, lo)
            if m:
                return sec, m
    return "wod-kan", None


_WODKAN_SUBS = (("OCZ", r"oczyszczal"), ("SUW", r"uzdatnian|\bsuw\b"), ("DESZ", r"deszczow"),
                 ("SAN", r"kanalizac\w*\s+sanitarn|kanalizac|ściek"), ("WOD", r"wodociąg|sieci? wodn"))


def wodkan_subsector(lo: str) -> tuple[str, re.Match] | None:
    for code, rx in _WODKAN_SUBS:
        m = re.search(rx, lo)
        if m:
            return code, m
    return None


def chip(key: str, value: Any, *, source_label: str = "opis", method: str = "regex", unsure: bool = False,
         origin: str = "CALC", review_status: str = "auto", quote: str | None = None,
         source: dict | None = None, options: list[dict] | None = None) -> dict[str, Any]:
    d = FEATURE_DEFS[key]
    if options is None and key == "sektor":
        options = sector_options()
    disp = display(key, value, unsure)
    if options and key == "podsektor":                  # sector-specific label (INNE exists in several packs)
        disp = next((o["label"] for o in options if o["value"] == value), disp)
    return {"key": key, "label": d["label"], "value": value, "display": disp,
            "source_label": source_label, "source": source, "unsure": unsure, "editor": d["editor"],
            "options": options if options is not None else d.get("options"), "unit": d.get("unit"), "origin": origin, "review_status": review_status,
            "method": method, "quote": quote}


def extract(text: str) -> dict[str, dict[str, Any]]:
    """Regex chips from the user's description (CALC, method regex:*)."""
    t = text or ""
    lo = t.lower()
    out: dict[str, dict[str, Any]] = {}

    def q(m: re.Match) -> str:
        return t[max(0, m.start() - 20): m.end() + 20].strip()

    sector, sm = detect_sector(t)
    if sector != "wod-kan":
        out["sektor"] = chip("sektor", sector, method="regex:sector", quote=q(sm) if sm else None)
        code = classify_subsector(sector_pack(sector), lo)
        if code:
            out["podsektor"] = chip("podsektor", code, method="regex:subsector", options=subsector_options(sector))
    elif feature("sector_roads"):
        out["sektor"] = chip("sektor", "wod-kan", method="regex:sector", unsure=False)
    sub = None
    for code, rx in (() if sector != "wod-kan" else (("OCZ", r"oczyszczal"), ("SUW", r"uzdatnian|\bsuw\b"), ("DESZ", r"deszczow"),
                     ("SAN", r"kanalizac\w*\s+sanitarn|kanalizac|ściek"), ("WOD", r"wodociąg|sieci? wodn"))):
        m = re.search(rx, lo)
        if m:
            sub = code
            out["podsektor"] = chip("podsektor", code, method="regex:subsector", quote=q(m))
            break
    m = re.search(r"zaprojektuj\w*\s+i\s+wybuduj|projektuj\s+i\s+buduj|\bziw\b|zaprojektowani\w*\s+i\s+wykonani", lo)
    if m:
        out["formula"] = chip("formula", "design_build", method="regex:formula", quote=q(m))
    elif re.search(r"wg\s+projektu|według\s+(dokumentacji|projektu)|samo\s+wykonanie|na\s+podstawie\s+projektu", lo):
        out["formula"] = chip("formula", "build", method="regex:formula", unsure=True)
    ren = re.search(r"przebudow|modernizac|renowac|remont", lo)
    bud = re.search(r"\bbudow|rozbudow|wybudow", lo)
    if ren or bud:
        wt = "mixed" if ren and bud else ("renovation" if ren else "build")
        out["rodzaj_robot"] = chip("rodzaj_robot", wt, method="regex:works_type", unsure=bool(ren and bud))
    L = lengths(t)
    if L["net_km"]:
        unsure = bool(re.search(r"\bok\.|około|orientac|szacun", lo))
        out["dlugosc_km"] = chip("dlugosc_km", round(L["net_km"], 3), method="regex:lengths", unsure=unsure)
    m = re.search(r"(\d+)\s*(?:szt\.?\s*)?(?:przepompowni|pompowni)", lo)
    if m:
        out["przepompownie"] = chip("przepompownie", int(m.group(1)), method="regex:count", quote=q(m))
    m = re.search(r"(\d+)\s*(?:szt\.?\s*)?(?:przyłącz|przykanalik|sięgacz)", lo)
    if m:
        out["przylacza"] = chip("przylacza", int(m.group(1)), method="regex:count", quote=q(m))
    m = re.search(_NUM + r"\s*(mln|mld|tys\.?)?\s*(zł|pln)?\s*(brutto|netto)?", lo)
    best = None
    for m in re.finditer(_NUM + r"\s*(mln|milion\w*|tys\.?|tysi\w*)?\s*(zł|pln)\s*(brutto|netto)?|" + _NUM
                         + r"\s*(mln|milion\w*)\s*(zł|pln)?\s*(brutto|netto)?", lo):
        if m.group(1):
            v, mult, vat = _f(m, 1, 2), m.group(3), m.group(5)
        else:
            v, mult, vat = _f(m, 6, 7), m.group(8), m.group(10)
        if mult and mult.startswith(("mln", "milion")):
            v *= 1e6
        elif mult and mult.startswith(("tys", "tysi")):
            v *= 1e3
        if v >= 100_000 and (best is None or v > best[0]):
            best = (v, vat, m)
    if best:
        v, vat, m = best
        net = vat == "netto"
        amount = v * 1.23 if net else v
        out["budzet"] = chip("budzet", {"amount": f"{amount:.2f}", "currency": "PLN", "vat_basis": "gross"},
                             method="regex:money" + (":net×1.23" if net else ""), unsure=vat is None, quote=q(m))
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:mies|miesi)", lo)
    if m:
        out["termin_mies"] = chip("termin_mies", float(m.group(1).replace(",", ".")), method="regex:months",
                                  quote=q(m))
    else:
        m = re.search(r"(\d+)\s*(?:dni)\b", lo)
        if m and int(m.group(1)) >= 60:
            out["termin_mies"] = chip("termin_mies", round(int(m.group(1)) / DAYS_PER_MONTH, 1),
                                      method="regex:days", quote=q(m))
    for code, rx in (("KPO_B311", r"\bkpo\b|krajow\w+ plan\w* odbudowy"), ("FENIKS", r"feniks"),
                     ("FEP_RPO", r"\brpo\b|fundusze europejskie dla|\bfe[pdlmsw]\w*\b 2021"), ("PROW", r"\bprow\b"),
                     ("RFIL_PIS", r"rfil|polski ład|polskiego ładu|\bpis\b|rządow"),
                     ("OWN", r"środk\w* własn|budżet\w* gminy")):
        m = re.search(rx, lo)
        if m:
            out["finansowanie"] = chip("finansowanie", code, method="regex:programme", quote=q(m))
            break
    for code, name in WOJ_NAME.items():
        if name in lo or name.replace("skie", "skim") in lo or name.replace("kie", "kiego") in lo:
            out["wojewodztwo"] = chip("wojewodztwo", code, method="regex:province")
            break
    m = re.search(r"\b(202[5-9]|203\d)\b", lo)
    if m:
        out["rok"] = chip("rok", int(m.group(1)), method="regex:year", unsure=True)
    _ = sub
    return out


def follow_ups(chips: dict[str, dict], skipped: list[str]) -> list[dict[str, Any]]:
    fu = []
    sub = (chips.get("podsektor") or {}).get("value")
    if "dlugosc_km" not in chips and "dlugosc_km" not in skipped and sub in ("SAN", "WOD", "DESZ", None):
        fu.append({"key": "dlugosc_km", "title": "Jaka będzie długość sieci?",
                   "why": "Bez długości nie policzymy kosztu kilometra ani nie dobierzemy przypadków o podobnym zakresie.",
                   "input": "number", "placeholder": "np. 6", "skippable": True})
    if "budzet" not in chips and "budzet" not in skipped:
        fu.append({"key": "budzet", "title": "Jaki jest budżet brutto?",
                   "why": "Wartość wyznacza grupę porównawczą (przedział wartości umów).",
                   "input": "number", "placeholder": "np. 7000000", "skippable": True})
    if "termin_mies" not in chips and "termin_mies" not in skipped:
        fu.append({"key": "termin_mies", "title": "Ile miesięcy na wykonanie?",
                   "why": "Bez terminu nie policzymy szansy na zdążenie.", "input": "number",
                   "placeholder": "np. 14", "skippable": True})
    if "przylacza" not in chips and "przylacza" not in skipped and sub in ("SAN", "WOD"):
        fu.append({"key": "przylacza", "title": "Ile będzie przyłączy?",
                   "why": "Nie ma tego w opisie ani w PFU. Z tą liczbą lepiej dobierzemy podobne przypadki.",
                   "input": "number", "placeholder": "np. 120", "skippable": True})
    return fu


def coerce(key: str, value: Any) -> Any:
    """Normalise a value sent by the owner in PATCH."""
    if value is None or value == "":
        return None
    if key == "budzet":
        if isinstance(value, dict):
            amt = float(str(value.get("amount")).replace(",", "."))
            vat = value.get("vat_basis") or "gross"
            if vat == "net":
                amt *= 1.23
            return {"amount": f"{amt:.2f}", "currency": "PLN", "vat_basis": "gross"}
        return {"amount": f"{float(str(value).replace(',', '.').replace(' ', '')):.2f}", "currency": "PLN",
                "vat_basis": "gross"}
    if key in ("dlugosc_km", "termin_mies"):
        return float(str(value).replace(",", "."))
    if key in ("przepompownie", "przylacza", "rok"):
        return int(float(str(value).replace(",", ".")))
    if key == "formula" and isinstance(value, bool):
        return "design_build" if value else "build"
    if key in ("ogloszenie", "termin_programu"):
        return date.fromisoformat(str(value)[:10]).isoformat()
    return value


def to_features(chips: dict[str, dict], text: str) -> Features:
    def v(k: str) -> Any:
        c = chips.get(k)
        return None if c is None else c.get("value")

    bud = v("budzet")
    budget = float(bud["amount"]) if isinstance(bud, dict) and bud.get("amount") else (float(bud) if bud else None)
    months = v("termin_mies")
    form = v("formula")
    rok = v("rok")
    ann = v("ogloszenie")
    return Features(
        subsector_main=v("podsektor"),
        sector=v("sektor") or "wod-kan",
        value_gross=budget,
        design_build=None if form is None else form in ("design_build", True),
        work_type=v("rodzaj_robot"),
        plan_days=float(months) * DAYS_PER_MONTH if months else None,
        length_km=float(v("dlugosc_km")) if v("dlugosc_km") else None,
        pumping_stations=v("przepompownie"),
        connections=v("przylacza"),
        funding_programme=v("finansowanie"),
        deadline=v("termin_programu"),
        announce_date=ann,
        woj=v("wojewodztwo"),
        planned_year=int(rok) if rok else (int(ann[:4]) if ann else date.today().year + 1),
        text=text or "",
    )


_PREC = {"edited": 4, "approved": 3}


def pick(items: list[dict]) -> dict[str, dict]:
    """Choose one chip per key: edited > approved > AI > regex (rejected dropped)."""
    best: dict[str, tuple[int, dict]] = {}
    for it in items:
        if it.get("review_status") == "rejected":
            continue
        rank = _PREC.get(it.get("review_status"), 2 if it.get("origin") == "AI" else 1)
        k = it["key"]
        if k not in best or rank >= best[k][0]:
            best[k] = (rank, it)
    return {k: v[1] for k, v in best.items()}
