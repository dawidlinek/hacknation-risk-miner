"""`extract_features`: AI chips with page refs, verified quotes and the uncertain flag (screen 1.1, docs/impl/llm.md §2.1).

One call for the user's description and one per document (in parallel). Every chip's quote goes through the verifier;
numbers must be printed inside the verified quote, otherwise the chip becomes uncertain. Table totals are computed by
code from verified rows (origin CALC, inputs AI), never taken from the model.

Output chips use session A's keys and body shape (`riskminer.analysis.features.chip`), origin AI, review_status
proposed. A inserts them as analysis_item(section='feature') rows; `feature_items()` gives the insert dicts.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from riskminer.llm import gateway
from riskminer.llm.backends.base import PageText, Text
from riskminer.llm.docs import load_documents, pick_pages
from riskminer.llm.errors import LLMError, SovereignUnavailable
from riskminer.llm.gateway import LLMRequest, LLMResult
from riskminer.llm.sanitize import copy_rules, scrub_contact
from riskminer.llm.schemas import Chip, Features
from riskminer.llm.verify import QuoteCheck, match_in_text, numbers_supported, parse_numbers, verify_quote

WOJ_CODE = {"dolnośląskie": "02", "kujawsko-pomorskie": "04", "lubelskie": "06", "lubuskie": "08", "łódzkie": "10",
            "małopolskie": "12", "mazowieckie": "14", "opolskie": "16", "podkarpackie": "18", "podlaskie": "20",
            "pomorskie": "22", "śląskie": "24", "świętokrzyskie": "26", "warmińsko-mazurskie": "28",
            "wielkopolskie": "30", "zachodniopomorskie": "32"}
SELECT_CODES = {
    "podsektor": {"SAN", "WOD", "DESZ", "OCZ", "SUW"},
    "formula": {"design_build", "build"},
    "rodzaj_robot": {"build", "renovation", "mixed"},
    "finansowanie": {"KPO_B311", "FENIKS", "FEP_RPO", "PROW", "RFIL_PIS", "OWN"},
}
NUMERIC = {"dlugosc_km", "przepompownie", "przylacza", "budzet", "termin_mies"}
A_KEYS = {"podsektor", "formula", "rodzaj_robot", "dlugosc_km", "przepompownie", "przylacza", "budzet", "termin_mies",
          "finansowanie", "wojewodztwo"}           # keys session A's FEATURE_DEFS knows; others go to `extra`
DAYS_PER_MONTH = 30.4375
APPROX = re.compile(r"\bok\.|około|orientac|szacun|\bdo\s+\d|~", re.IGNORECASE)


@dataclass
class FeatureResult:
    chips: dict[str, dict[str, Any]] = field(default_factory=dict)      # key -> A-shaped chip body (AI, proposed)
    extra: dict[str, dict[str, Any]] = field(default_factory=dict)      # wynagrodzenie, technologie
    rows: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    processing: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)                    # per source: {source, code, detail}
    llm_call_ids: list[int] = field(default_factory=list)


def _value(c: Chip) -> tuple[Any, str | None]:
    """Chip → (A-shaped value, problem). Numbers come from the model reading but are checked against the quote."""
    k = c.key
    if k in SELECT_CODES:
        v = (c.value_code or "").strip()
        if k == "finansowanie":
            v = v.upper()
        return (v, None) if v in SELECT_CODES[k] else (None, f"nieznany kod {v!r}")
    if k == "wojewodztwo":
        name = (c.value_code or c.value_text or "").strip().lower().removeprefix("województwo ").strip()
        return (WOJ_CODE[name], None) if name in WOJ_CODE else (None, f"nieznane województwo {name!r}")
    if k in ("wynagrodzenie",):
        v = (c.value_code or "").lower()
        return (v, None) if v in ("ryczalt", "kosztorys") else (None, f"nieznana forma {v!r}")
    if k == "technologie":
        return c.value_text, None
    if c.value_num is None:
        return None, "brak liczby"
    if k == "dlugosc_km":
        return round(float(c.value_num), 3), None
    if k in ("przepompownie", "przylacza"):
        return round(c.value_num), None
    if k == "termin_mies":
        u = (c.unit or "").lower()
        if u.startswith(("dni", "dzie")):
            return round(float(c.value_num) / DAYS_PER_MONTH, 1), None
        if u.startswith("data") or u == "date":
            return None, "termin jako data"
        return float(c.value_num), None
    if k == "budzet":
        amt = float(c.value_num)
        vat = c.vat_basis or "unknown"
        if vat == "net":
            return {"amount": f"{amt * 1.23:.2f}", "currency": "PLN", "vat_basis": "gross", "net_amount": f"{amt:.2f}"}, None
        return {"amount": f"{amt:.2f}", "currency": "PLN", "vat_basis": "gross" if vat == "gross" else "unknown"}, None
    return c.value_text, None


def _number_ok(c: Chip) -> bool:
    if c.key not in NUMERIC or c.value_num is None:
        return True
    unit = {"dlugosc_km": "km"}.get(c.key)
    return numbers_supported(c.value_num, c.quote, unit=unit, money=c.key == "budzet")


def _verify(c: Chip | Any, desc: str, docs: dict[int, dict]) -> QuoteCheck:
    if getattr(c, "source", "dokument") == "opis" or not docs:
        r = match_in_text(c.quote, desc or "")
        return r
    doc = docs.get(c.document_id) if c.document_id else (next(iter(docs.values())) if len(docs) == 1 else None)
    if doc is None:                                    # unknown doc id: search every document
        for d in docs.values():
            r = verify_quote(c.quote, d["pages"], c.page)
            if r.ok:
                c.document_id = d["id"]
                return r
        return QuoteCheck("unverified", stated_page=c.page)
    c.document_id = doc["id"]
    return verify_quote(c.quote, doc["pages"], c.page)


def _chip_body(c: Chip, value: Any, qc: QuoteCheck, res: LLMResult, docs: dict[int, dict], unsure: bool,
               reason: str | None, needs_review: bool) -> dict[str, Any]:
    from riskminer.analysis.features import FEATURE_DEFS, display

    d = FEATURE_DEFS.get(c.key, {"label": c.key, "editor": "text"})
    src = None
    source_label = "opis"
    if c.source == "dokument" and c.document_id:
        doc = docs.get(c.document_id) or {}
        page = qc.page or c.page
        src = {"document_id": c.document_id, "page": page}
        source_label = f"{doc.get('doc_type') or 'dokument'} s. {page}" if page else (doc.get("doc_type") or "dokument")
    try:
        disp = display(c.key, value, unsure) if c.key in FEATURE_DEFS else str(value)
    except Exception:  # noqa: BLE001
        disp = c.value_text
    return {"key": c.key, "label": d["label"], "value": value, "display": disp, "source_label": source_label,
            "source": src, "unsure": unsure, "editor": d.get("editor"), "options": d.get("options"), "unit": d.get("unit"),
            "origin": "AI", "review_status": "proposed", "method": "llm:extract_features",
            "quote": scrub_contact(c.quote), "verification": qc.status, "quote_score": qc.score,
            "char_start": qc.char_start, "char_end": qc.char_end, "page_mismatch": qc.page_mismatch or None,
            "value_text": copy_rules(c.value_text), "uncertain_reason": copy_rules(reason), "needs_review": needs_review,
            "pkt": c.pkt, "llm": res.llm_info, "llm_call_id": res.llm_call_id}


async def _call(source: str, parts: list, sens: str, refs: list[str], subject: str | None, timeout_kind: str) -> LLMResult:
    # the description alone goes to the fast alias (chips appear while the user types); documents to strong
    task = "extract_features_text" if source == "opis" else "extract_features"
    return await gateway.run(LLMRequest(task=task, sensitivity=sens, prompt="extract_features",  # type: ignore[arg-type]
                                        parts=parts, output=Features, input_refs=refs, subject=subject,
                                        timeout_kind=timeout_kind, max_output_tokens=8192))


async def extract_features(text: str | None, document_ids: list[int] | None = None, *, sensitivity: str = "public",
                           subject: str | None = None, docs: dict[int, dict] | None = None) -> FeatureResult:
    """AI chips from the description and documents. Never raises for a model failure: errors are listed in
    `.errors` (SovereignUnavailable included) and the caller keeps its regex chips."""
    document_ids = list(document_ids or [])
    docs = docs if docs is not None else await load_documents(document_ids)
    jobs: list[tuple[str, Any]] = []
    if text and text.strip():
        jobs.append(("opis", _call("opis", [Text("<opis_uzytkownika>\n" + text.strip() + "\n</opis_uzytkownika>")],
                                   sensitivity, [], subject, "interactive")))
    for did, d in docs.items():
        sens = "confidential" if (d.get("sensitivity") == "confidential" or sensitivity == "confidential") else "public"
        pages = pick_pages(d["pages"])
        if not pages:
            continue
        head = Text(f"Dokument id={did}, typ {d.get('doc_type')}, plik {d.get('filename')}, {len(d['pages'])} stron.")
        parts = [head] + [PageText(did, p, d["pages"][p]) for p in pages]
        jobs.append((f"document:{did}", _call(f"document:{did}", parts, sens, [f"document:{did}"], subject, "document")))
    out = FeatureResult()
    results = await asyncio.gather(*(j for _, j in jobs), return_exceptions=True)
    candidates: dict[str, list[dict]] = {}
    for (src, _), res in zip(jobs, results):
        if isinstance(res, BaseException):
            code = res.code if isinstance(res, LLMError) else "error"
            detail = res.detail if isinstance(res, LLMError) else str(res)[:200]
            out.errors.append({"source": src, "code": code, "detail": detail,
                               "sovereign_unavailable": isinstance(res, SovereignUnavailable)})
            continue
        out.processing.append({"task": "features", "source": src, **res.processing})
        if res.llm_call_id:
            out.llm_call_ids.append(res.llm_call_id)
        feats: Features = res.data
        for c in feats.chips:
            if src == "opis":
                c.source, c.document_id, c.page = "opis", None, None
            else:
                c.source = "dokument"
                c.document_id = int(src.split(":")[1])
            qc = _verify(c, text or "", docs)
            value, problem = _value(c)
            if value is None and problem:
                continue
            num_ok = _number_ok(c) if qc.ok else False
            approx = c.key in NUMERIC and bool(APPROX.search(c.value_text or ""))
            unsure = bool(c.uncertain and (c.key in NUMERIC or c.uncertain_reason)) or approx or not qc.ok or not num_ok
            reason = c.uncertain_reason
            if not qc.ok:
                reason = "cytat nie znaleziony w tekście"
            elif not num_ok:
                reason = "liczby nie ma w cytacie"
            body = _chip_body(c, value, qc, res, docs, unsure, reason, needs_review=not (qc.ok and num_ok))
            candidates.setdefault(c.key, []).append(body)
        for r in feats.rows:
            r.document_id = int(src.split(":")[1]) if src != "opis" else None
            qc = _verify(r, text or "", docs) if src != "opis" else match_in_text(r.quote, text or "")
            ok = qc.ok and (r.value_num is None or numbers_supported(r.value_num, r.quote, unit=r.unit and r.unit.lower()))
            out.rows.append({**r.model_dump(), "quote": scrub_contact(r.quote), "verification": qc.status,
                             "page": qc.page or r.page, "number_ok": ok, "llm_call_id": res.llm_call_id})
        out.missing += [m for m in feats.missing if m not in out.missing]
    # computed totals from verified rows (origin CALC, inputs AI)
    for key in ("dlugosc_km", "przylacza", "przepompownie"):
        rows = [r for r in out.rows if r["key"] == key and r["number_ok"] and r["value_num"] is not None]
        if len(rows) >= 2 and not any(not c["needs_review"] for c in candidates.get(key, [])):
            total = 0.0
            for r in rows:
                total += _row_value(r, key)
            value = round(total, 3) if key == "dlugosc_km" else round(total)
            from riskminer.analysis.features import FEATURE_DEFS, display
            first = rows[0]
            candidates.setdefault(key, []).insert(0, {
                "key": key, "label": FEATURE_DEFS[key]["label"], "value": value, "display": display(key, value, False),
                "source_label": f"suma {len(rows)} wierszy tabeli", "source": {"document_id": first["document_id"], "page": first["page"]}
                if first.get("document_id") else None, "unsure": False, "editor": FEATURE_DEFS[key]["editor"],
                "options": None, "unit": FEATURE_DEFS[key].get("unit"), "origin": "CALC", "review_status": "proposed",
                "method": "calc:sum_rows(ai)", "quote": first["quote"], "verification": first["verification"],
                "rows": rows, "needs_review": False, "llm_call_id": first.get("llm_call_id")})
    # merge: prefer verified, then documents over description; disagreement → uncertain
    for key, cands in candidates.items():
        good = [c for c in cands if not c["needs_review"]] or cands
        best = min(good, key=lambda c: (c["origin"] != "CALC", c["source"] is None))
        vals = {_vkey(c["value"]) for c in good}
        if len(vals) > 1:
            best = {**best, "unsure": True, "uncertain_reason": "opis i dokument podają różne wartości",
                    "alternatives": [{"value": c["value"], "source_label": c["source_label"], "quote": c["quote"]} for c in good if c is not best]}
            try:
                from riskminer.analysis.features import display
                best["display"] = display(key, best["value"], True)
            except Exception:  # noqa: BLE001
                pass
        (out.chips if key in A_KEYS else out.extra)[key] = best
    out.missing = [m for m in out.missing if m not in out.chips and m not in out.extra]
    return out


def _row_value(r: dict, key: str) -> float:
    """Row quantity read by code from the printed value (km for lengths), falling back to the model's number."""
    toks = parse_numbers(r.get("value_text")) or []
    if key == "dlugosc_km":
        for t in toks:
            if t.unit == "km":
                return t.value
            if t.unit == "m":
                return t.value / 1000
        v = float(r["value_num"])
        u = (r.get("unit") or "").lower()
        return v / 1000 if u in ("m", "mb", "m.b.") and v > 50 else v
    for t in toks:
        if t.unit in (None, "count"):
            return t.value
    return float(r["value_num"])


def _vkey(v: Any) -> Any:
    if isinstance(v, dict):
        return round(float(v.get("amount") or 0), -3)
    if isinstance(v, float):
        return round(v, 2)
    return v


def feature_items(res: FeatureResult) -> list[dict[str, Any]]:
    """Dicts for session A's `_insert_item` (section 'feature', origin AI/CALC, review_status proposed)."""
    items = []
    for k, c in res.chips.items():
        items.append({"section": "feature", "key": k, "title": c["label"], "origin": c["origin"],
                      "review_status": "proposed", "body": c, "quote": c.get("quote"),
                      "document_id": (c.get("source") or {}).get("document_id"), "page_no": (c.get("source") or {}).get("page"),
                      "verification": c.get("verification"), "llm_call_id": c.get("llm_call_id")})
    return items
