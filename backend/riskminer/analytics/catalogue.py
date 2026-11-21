"""Catalogue access for analytics: `catalogue_entry` (DB, editable in Katalog) first, YAML files second, built-in
defaults last (analytics.md §4). Expert assumptions (mitigations, funding deadlines, allocation) keep their `status`
so the UI can label them „założenie eksperta”.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import settings

SECTOR = "wod-kan"

# --- built-in defaults (analytics.md §4; used only when neither the DB nor the YAML has them) ------------------------
DEFAULT_MITIGATIONS: dict[str, Any] = {
    "defaults": {"offers_decay": 0.85, "cancel_floor_pct": 4, "materials_share": 0.5},
    "mitigations": [
        {"code": "M-GEO", "key": "geo", "short": "Badania gruntu", "label": "Badania gruntu przed przetargiem",
         "description": "Dokumentacja geotechniczna jako załącznik do SWZ.", "metrics": ["time", "cost", "comp"],
         "effects": [{"risk": "R02", "p_keep": 0.5, "time_cut": 0.4, "cost_cut": 0.4}],
         "competition": {"offers_shift": 0.3, "cancel_pp": -1}, "clause_refs": ["R02.1-K1"], "status": "proposed"},
        {"code": "M-PLAN18", "key": "plan18", "short": "Plan 18 mies.", "label": "Termin 18 miesięcy zamiast 14",
         "description": "Tyle wynosi mediana planowanych terminów w tej grupie.", "metrics": ["time", "cost", "comp"],
         "plan": {"set": "class_median"}, "effects": [{"risk": "R06", "p_keep": 0.5, "time_cut": 0.0, "cost_cut": 0.0}],
         "competition": {"offers_shift": 0.6, "cancel_pp": -1}, "status": "proposed"},
        {"code": "M-K07", "key": "k07", "short": "Waloryzacja", "label": "Klauzula waloryzacyjna K-07",
         "description": "Art. 439 Pzp, próg 5%, limit 10%.", "metrics": ["cost", "comp"],
         "effects": [{"risk": "N-PRICE", "p_keep": 1.0, "time_cut": 0.0, "cost_cut": 0.5},
                     {"risk": "R13", "p_keep": 1.0, "time_cut": 0.0, "cost_cut": 0.5}],
         "price_pass_through": {"threshold_pct": 5, "cap_pct": 10},
         "competition": {"offers_shift": 1.0, "cancel_pp": -2}, "clause_refs": ["R08.1-K1"], "status": "proposed"},
        {"code": "M-R08", "key": "r08", "short": "Cena za metr", "label": "Cena za metr sieci ponad 6 km",
         "description": "Ryczałt do 6,0 km, dalej cena jednostkowa z oferty.", "metrics": ["cost", "comp"],
         "effects": [{"risk": "R08", "p_keep": 1.0, "time_cut": 0.0, "cost_cut": 0.6},
                     {"risk": "R01", "p_keep": 1.0, "time_cut": 0.0, "cost_cut": 0.3}],
         "competition": {"offers_shift": 0.4, "cancel_pp": -1}, "clause_refs": ["R01.2-K1"], "status": "proposed"},
    ],
}

DEFAULT_FUNDING: dict[str, Any] = {"programmes": [
    {"code": "KPO_B311", "name": "KPO, inwestycja B3.1.1 (infrastruktura wodno-kanalizacyjna)", "family": "EU",
     "deadlines": [{"kind": "indicators_achieved", "date": "2026-08-31",
                    "source": "Rozporządzenie (UE) 2021/241; MFiPR, odpowiedź na interpelację 16654 (15.05.2026)"}],
     "buffer_days": 60, "status": "approved"},
    {"code": "FENIKS", "name": "FEnIKS 2021–2027", "family": "EU",
     "deadlines": [{"kind": "eligibility_end", "date": "2029-12-31",
                    "source": "Rozporządzenie (UE) 2021/1060, art. 63 ust. 2; termin z umowy o dofinansowanie ma "
                              "pierwszeństwo"}], "buffer_days": 60, "status": "proposed"},
    {"code": "FEP_RPO", "name": "Fundusze Europejskie dla województwa (2021–2027)", "family": "EU",
     "deadlines": [{"kind": "eligibility_end", "date": "2029-12-31", "source": "jw."}], "buffer_days": 60,
     "status": "proposed"},
    {"code": "PROW", "name": "PROW 2014–2020", "family": "EU", "deadlines": [], "status": "proposed"},
    {"code": "RFIL_PIS", "name": "Rządowe programy (RFIL, Polski Ład / PIS)", "family": "national", "deadlines": [],
     "status": "proposed"},
    {"code": "OWN", "name": "Środki własne", "family": "own", "deadlines": [], "status": "approved"},
]}

DEFAULT_ALLOCATION: dict[str, Any] = {
    "defaults": {"delay_cost_rate_per_month": 0.005,
                 "premium": {"shared": 0.10, "contractor_uncontrolled": 0.60, "contractor_controlled": 0.10}},
    "risks": [
        {"code": "R02", "label": "Nierozpoznany grunt", "controllability": "buyer", "recommended": "buyer",
         "how": {"buyer": "badania geotechniczne przed ogłoszeniem; reszta wg protokołu konieczności",
                 "shared": "badania przed ogłoszeniem, nadwyżka ponad raport dzielona po połowie",
                 "contractor": "wykonawca bada grunt po umowie, w ryczałcie"},
         "clause_refs": ["R02.1-K1"], "status": "proposed"},
        {"code": "R03", "label": "Służebności na trasie", "controllability": "buyer", "recommended": "buyer",
         "how": {"buyer": "zamawiający uzyskuje zgody przed przekazaniem terenu",
                 "shared": "zamawiający negocjuje, wykonawca projektuje obejścia",
                 "contractor": "wykonawca uzyskuje zgody właścicieli"}, "status": "proposed"},
        {"code": "R04", "label": "Decyzje organów", "controllability": "shared", "recommended": "shared",
         "how": {"buyer": "zamawiający uzyskuje decyzje przed przetargiem",
                 "shared": "klauzula K-12: termin wydłuża się o zwłokę organu",
                 "contractor": "wykonawca odpowiada za terminy decyzji"}, "status": "proposed"},
        {"code": "R06", "label": "Zbyt krótki termin", "controllability": "shared", "recommended": "shared",
         "how": {"buyer": "zamawiający wydłuża termin do mediany podobnych umów",
                 "shared": "kary umowne liczone od terminu realnego, kamienie milowe",
                 "contractor": "pełne kary od terminu z planu"}, "status": "proposed"},
        {"code": "R08", "label": "Długość sieci nieustalona", "controllability": "buyer", "recommended": "shared",
         "how": {"buyer": "rozliczenie powykonawcze za każdy metr",
                 "shared": "ryczałt do długości z PFU, dalej cena jednostkowa za metr",
                 "contractor": "ryczałt za całość, długość ryzykiem wykonawcy"}, "status": "proposed"},
        {"code": "R13", "label": "Wzrost cen materiałów", "controllability": "shared", "recommended": "shared",
         "how": {"buyer": "zamawiający pokrywa pełny wzrost cen",
                 "shared": "klauzula K-07 (art. 439 Pzp), próg 5%, limit 10%",
                 "contractor": "bez waloryzacji"}, "status": "proposed"},
    ],
}

_CACHE: dict[str, Any] = {}
_CACHE_AT = 0.0


def _yaml(name: str) -> dict[str, Any] | None:
    p = Path(settings().catalogue_dir) / SECTOR / name
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None


async def _entries(s: AsyncSession, table: str) -> list[dict]:
    try:
        q = text("SELECT code, data FROM catalogue_entry WHERE table_name = :t "
                 "AND coalesce(status, 'approved') NOT IN ('retired', 'rejected') ORDER BY code")
        return [{"code": r[0], **(r[1] or {})} for r in (await s.execute(q, {"t": table})).all()]
    except Exception:  # noqa: BLE001 - column/table differences: fall back to YAML
        await s.rollback()
        return []


async def load(s: AsyncSession, max_age: float = 60.0) -> dict[str, Any]:
    global _CACHE, _CACHE_AT
    if _CACHE and time.monotonic() - _CACHE_AT < max_age:
        return _CACHE
    cat: dict[str, Any] = {}

    risks_y = _yaml("risks.yaml") or {}
    cat["risk_names"] = {r["id"]: r.get("name") for r in risks_y.get("risks", []) if r.get("id")}
    cat["clauses"] = {c["code"]: c for c in (_yaml("clauses.yaml") or {}).get("clauses", [])}
    cat["red_flags"] = {c["code"]: c for c in (_yaml("red_flags.yaml") or {}).get("red_flags", [])}
    cat["similarity"] = ((_yaml("similarity.yaml") or {}).get("similarity")) or {}
    cat["lexicon"] = _yaml("lexicon.yaml") or {}
    cat["checklist"] = (_yaml("checklist.yaml") or {})

    # expert assumptions: DB entries > YAML > built-in
    mit = await _entries(s, "mitigation")
    mit_y = _yaml("mitigations.yaml")
    base = mit_y or DEFAULT_MITIGATIONS
    items = [m for m in mit if not _is_defaults(m["code"])] or list(base.get("mitigations", []))
    d_row = next((m for m in mit if _is_defaults(m["code"])), None)
    defaults = (d_row or {}).get("defaults") or d_row or base.get("defaults") or DEFAULT_MITIGATIONS["defaults"]
    order = [m["code"] for m in base.get("mitigations", [])] + [m["code"] for m in DEFAULT_MITIGATIONS["mitigations"]]
    items.sort(key=lambda m: order.index(m["code"]) if m["code"] in order else 99)
    key_map = {m["code"]: m.get("key") for m in DEFAULT_MITIGATIONS["mitigations"]}
    for m in items:
        m.setdefault("key", key_map.get(m["code"]) or m["code"].lower().replace("m-", ""))
    cat["mitigations"] = {"defaults": defaults, "items": items,
                          "source": "catalogue_entry" if mit else ("mitigations.yaml" if mit_y else "built-in")}

    fp = await _entries(s, "funding_programme")
    fp_y = _yaml("funding_programmes.yaml")
    progs = fp or (fp_y or DEFAULT_FUNDING).get("programmes", [])
    cat["funding"] = {p["code"]: p for p in progs}
    cat["funding_source"] = "catalogue_entry" if fp else ("funding_programmes.yaml" if fp_y else "built-in")

    al = await _entries(s, "allocation")
    al_y = _yaml("allocation.yaml")
    base_a = al_y or DEFAULT_ALLOCATION
    risks = [r for r in al if not _is_defaults(r["code"])] or base_a.get("risks", [])
    # YAML stubs may hold only code: fill from defaults
    dflt = {r["code"]: r for r in DEFAULT_ALLOCATION["risks"]}
    risks = [{**dflt.get(r["code"], {}), **{k: v for k, v in r.items() if v is not None}} for r in risks]
    a_row = next((r for r in al if _is_defaults(r["code"])), None)
    a_def = (a_row or {}).get("defaults") or base_a.get("defaults") or DEFAULT_ALLOCATION["defaults"]
    cat["allocation"] = {"defaults": a_def, "risks": {r["code"]: r for r in risks},
                         "source": "catalogue_entry" if al else ("allocation.yaml" if al_y else "built-in")}

    cv = None
    try:
        cv = (await s.execute(text("SELECT label FROM catalogue_version WHERE sector = :s ORDER BY id DESC LIMIT 1"),
                              {"s": SECTOR})).scalar()
    except Exception:  # noqa: BLE001 - table owned by session B (0009); may not exist
        await s.rollback()
    cat["version"] = cv or "v1"
    _CACHE, _CACHE_AT = cat, time.monotonic()
    return cat


def _is_defaults(code: str) -> bool:
    return code in ("defaults", "_defaults")


def programme_deadline(cat: dict, code: str | None) -> tuple[str | None, dict | None]:
    """(ISO date, programme) of the programme's binding deadline, or (None, programme)."""
    if not code:
        return None, None
    p = cat["funding"].get(code)
    if p is None:
        # loose match: "KPO, inwestycja B3" -> KPO_B311
        cu = code.upper()
        p = next((v for k, v in cat["funding"].items() if k.split("_")[0] in cu or cu in k), None)
    if not p:
        return None, None
    dls = p.get("deadlines") or []
    if not dls:
        return None, p
    d = dls[0].get("date")
    return (str(d) if d else None), p
