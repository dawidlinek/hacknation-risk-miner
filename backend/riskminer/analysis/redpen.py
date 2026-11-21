"""Screen 1.3 data (frontend.md §2 `RedPenOut`): page text split into paragraphs with marks, notes found in the text
and missing items.

Three sources of notes:
* AI notes written by session L's scan job: `analysis_item(section='redpen_note', origin='AI', review_status='proposed',
  document_id, page_no, char_start, char_end, quote, verification, llm_call_id, body={no?, title, why|text,
  risk_codes, locator|clause_ref, suggested_clause, llm})`.
* Regex notes (CALC, analytics.md §3.11 F1/F2/F4/F8): the quote is the matched text itself, so it is verified by
  construction.
* Missing items (CALC rules, evidence states): art. 439 indexation (F7), geotechnical documentation (F1), decision on
  environmental conditions for networks >= 1 km (F3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DOC_TYPE = {"pfu": "PFU", "ppu": "PPU", "swz": "SWZ", "umowa": "umowa", "opz": "PFU", "projekt_umowy": "PPU"}


def doc_type_ui(dt: str | None) -> str:
    return DOC_TYPE.get((dt or "").lower(), (dt or "inne").upper() if (dt or "").lower() in DOC_TYPE else "inne")


@dataclass
class Rule:
    code: str
    risk: str
    title: str
    why: str
    rx: re.Pattern
    clause: str | None
    needs: re.Pattern | None = None       # must also appear somewhere in the package


RULES = [
    Rule("F8", "R01.2", "Ryczałt przy ilościach orientacyjnych",
         "Długość lub ilości są podane orientacyjnie, a wynagrodzenie jest ryczałtowe: wykonawca wyceni najdłuższy "
         "wariant.", re.compile(r"\bok\.\s?\d+(?:[,.]\d+)?\s?(?:km|mb|m)\b|około\s+\d+(?:[,.]\d+)?\s?(?:km|mb|m)\b|"
                                r"wartości\s+(?:są\s+)?orientacyjn\w*|ilości\s+orientacyjn\w*", re.IGNORECASE),
         "R01.2-K1", re.compile(r"ryczałt", re.IGNORECASE)),
    Rule("F4", "R03.3", "Przekroczenie cieku, drogi lub kolei",
         "Trasa przecina przeszkodę wymagającą uzgodnień zarządcy; ich termin nie jest znany.",
         re.compile(r"przekrocz\w*\s+(?:rzek|ciek|rów|potok)\w*|drog\w*\s+(?:krajow|wojewódzk)\w*|\bDK\s?\d+|"
                    r"\bPKP\b|lini\w*\s+kolejow\w*|przewiert\w*|przecisk\w*", re.IGNORECASE), "R03.3-K1"),
    Rule("F2", "R03.2", "Grunty prywatne na trasie",
         "Trasa przebiega przez działki prywatne; bez zgód właścicieli przekazanie terenu się opóźni.",
         re.compile(r"działk\w*\s+prywatn\w*|służebnoś\w*|zgod\w*\s+właściciel\w*|grunt\w*\s+prywatn\w*", re.IGNORECASE),
         "R03.2-K1"),
    Rule("F1", "R02.1", "Warunki gruntowo-wodne po stronie wykonawcy",
         "Ryzyko gruntu przeniesione na wykonawcę lub woda gruntowa bez badań: wykonawca wyceni je w ciemno.",
         re.compile(r"wod\w*\s+gruntow\w*|warunk\w*\s+gruntowo[- ]wodn\w*|badani\w*\s+(?:podłoża|geotechn)\w*\s+"
                    r"(?:wykona|po stronie)\s+wykonawc\w*|ryzyk\w*\s+(?:warunków\s+)?gruntow\w*", re.IGNORECASE), "R02.1-K1"),
]

RX_439 = re.compile(r"waloryzac\w*|art\.?\s*439|zmian\w*\s+wynagrodzenia[^.]{0,80}cen", re.IGNORECASE)
RX_GEO = re.compile(r"dokumentacj\w*\s+geotechn\w*|opini\w*\s+geotechn\w*|badani\w*\s+(?:podłoża|geotechn)\w*|"
                    r"projekt\w*\s+geotechn\w*", re.IGNORECASE)
RX_DSU = re.compile(r"decyzj\w*\s+o\s+środowiskowych\s+uwarunkowaniach|\bDŚU\b|decyzj\w*\s+środowiskow\w*|"
                    r"uwarunkowa\w*\s+środowiskow\w*", re.IGNORECASE)


def paragraphs(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of paragraphs (blank-line or line separated, empty lines skipped)."""
    out, pos = [], 0
    for m in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text or ""):
        if m.group(0).strip():
            out.append((m.start(), m.end()))
        pos = m.end()
    return out


def _sentence(text: str, s: int, e: int) -> tuple[int, int]:
    """The sentence around a match (PDF line breaks are not sentence ends), at most ~200 chars each side."""
    a = max(text.rfind(".", 0, s) + 1, text.rfind(";", 0, s) + 1, s - 200, 0)
    if a == s - 200 and a > 0:                       # cut inside a sentence: start at the next word
        sp = text.find(" ", a)
        a = sp + 1 if 0 <= sp < s else a
    ends = [x for x in (text.find(".", e), text.find(";", e)) if x != -1]
    b = min(min(ends) + 1 if ends else len(text), e + 200)
    while a < s and text[a].isspace():
        a += 1
    return a, b


_SKIP_CTX = re.compile(r"głębok|poniżej|powyżej|szerok|wysok|grubo|średnic|odległoś|zagłębie", re.IGNORECASE)


def _ok_match(rule: Rule, t: str, m: re.Match) -> bool:
    if rule.code != "F8":
        return True
    if _SKIP_CTX.search(t[max(0, m.start() - 40): m.start()]):
        return False
    g = re.search(r"(\d+(?:[,.]\d+)?)\s?(km|mb|m)\b", m.group(0), re.IGNORECASE)
    if not g:
        return True                                  # "wartości orientacyjne"
    v = float(g.group(1).replace(",", "."))
    return v >= 0.3 if g.group(2).lower() == "km" else v >= 100


def regex_notes(pages: list[dict], package_text: str) -> list[dict]:
    notes = []
    for rule in RULES:
        if rule.needs is not None and not rule.needs.search(package_text):
            continue
        for p in pages:
            t = p["text"] or ""
            m = next((x for x in rule.rx.finditer(t) if _ok_match(rule, t, x)), None)
            if not m:
                continue
            a, b = _sentence(t, m.start(), m.end())
            notes.append({"kind": "found", "rule": rule.code, "risk_codes": [rule.risk], "page": p["page_no"],
                          "char_start": a, "char_end": b, "quote": t[a:b].strip(), "title": rule.title,
                          "why": rule.why, "suggested_clause": rule.clause, "origin": "CALC",
                          "review_status": "auto", "verification": "exact"})
            break
    return notes


def missing_items(docs: list[dict], texts: dict[int, str], plan_days: float | None, length_km: float | None,
                  subsector: str | None) -> list[dict]:
    types = {d["doc_type"] for d in docs}
    out = []
    contract_docs = [d for d in docs if d["doc_type"] in ("PPU", "umowa", "SWZ")]
    if (plan_days or 0) > 182:
        if not contract_docs:
            out.append({"rule": "F7", "title": "Brak: projekt umowy (PPU)", "risk_codes": ["R08.1"],
                        "evidence_state": "BRAK_W_PACZCE", "state_label": "nie ma w paczce",
                        "limits": "Nie sprawdzimy klauzuli waloryzacyjnej (art. 439 Pzp) ani podziału ryzyk w umowie.",
                        "suggested_clause": "R08.1-K1"})
        elif not any(RX_439.search(texts.get(d["document_id"], "")) for d in contract_docs):
            out.append({"rule": "F7", "title": "Brak: klauzula waloryzacyjna w PPU", "risk_codes": ["R08.1"],
                        "evidence_state": "DOKUMENT_NIE_WSPOMINA", "state_label": "dokument nie wspomina",
                        "limits": "Roboty trwają dłużej niż 6 mies., a art. 439 Pzp wymaga waloryzacji.",
                        "suggested_clause": "R08.1-K1"})
    all_text = " ".join(texts.values())
    if "GEOTECH" not in types and not RX_GEO.search(all_text):
        out.append({"rule": "F1", "title": "Brak: dokumentacja geotechniczna", "risk_codes": ["R02.1"],
                    "evidence_state": "BRAK_W_PACZCE" if docs else "BRAK_W_PACZCE", "state_label": "nie ma w paczce",
                    "limits": "Ogranicza ocenę ryzyka R02 (warunki gruntowe).", "suggested_clause": "R02.1-K1"})
    if subsector in ("SAN", "WOD", "DESZ") and (length_km or 0) >= 1 and not RX_DSU.search(all_text):
        out.append({"rule": "F3", "title": "Brak: informacja o decyzji środowiskowej", "risk_codes": ["R04.1"],
                    "evidence_state": "DOKUMENT_NIE_WSPOMINA" if docs else "BRAK_W_PACZCE",
                    "state_label": "dokument nie wspomina" if docs else "nie ma w paczce",
                    "limits": "Sieć od 1 km zwykle wymaga decyzji o środowiskowych uwarunkowaniach; termin jej "
                              "uzyskania nie jest znany.", "suggested_clause": None})
    for i, m in enumerate(out):
        m["no"] = chr(ord("A") + i)
        m["kind"] = "missing"
        m["origin"] = "CALC"
        m["review_status"] = "auto"
    return out


def build_pages(pages: list[dict], notes: list[dict], only_noted: bool) -> list[dict]:
    by_page: dict[int, list[dict]] = {}
    for n in notes:
        if n.get("page") and n.get("char_start") is not None:
            by_page.setdefault(int(n["page"]), []).append(n)
    out = []
    for p in pages:
        pn = p["page_no"]
        if only_noted and pn not in by_page:
            continue
        t = p["text"] or ""
        paras = []
        for a, b in paragraphs(t):
            marks = []
            for n in by_page.get(pn, []):
                s, e = int(n["char_start"]), int(n["char_end"])
                if s < b and e > a:
                    marks.append({"note_no": n["no"], "start": max(s, a) - a, "end": min(e, b) - a})
            seg = t[a:b]
            heading = len(seg) < 90 and bool(re.match(r"^\s*(\d+(\.\d+)*\.?|[IVX]+\.|§\s*\d+|ROZDZIAŁ)", seg, re.IGNORECASE))
            paras.append({"text": seg, "heading": heading, "marks": marks})
        out.append({"page_no": pn, "title": None, "paragraphs": paras, "chars": len(t)})
    return out


def note_out(n: dict, clauses: dict, in_pack: set[str], cases: list[dict]) -> dict[str, Any]:
    cl = n.get("suggested_clause")
    c = clauses.get(cl) if cl else None
    q = n.get("quote")
    return {
        "no": n["no"], "kind": n["kind"], "risk_codes": n.get("risk_codes") or [], "page": n.get("page"),
        "locator": n.get("locator"), "title": n.get("title"), "why": n.get("why") or n.get("limits") or "",
        "review_status": n.get("review_status", "auto"), "origin": n.get("origin", "CALC"),
        "evidence_state": n.get("evidence_state"), "state_label": n.get("state_label"), "limits": n.get("limits"),
        "quote": {"text": q, "verified": n.get("verification") == "exact"} if q else None,
        "cases": cases, "item_id": n.get("item_id"), "rule": n.get("rule"),
        "clause": {"code": cl, "text": c.get("text") if c else "", "in_pack": cl in in_pack} if cl else None,
        "prov": {"role": "ai" if n.get("origin") == "AI" else "calc", "review_status": n.get("review_status", "auto"),
                 "n": None if n.get("origin") == "AI" else 1,
                 "method": n.get("method") or (f"rule:{n.get('rule')}" if n.get("rule") else "llm:redpen_scan"),
                 "refs": [{"kind": "document", "id": str(n.get("document_id") or ""), "label": f"s. {n.get('page')}",
                           "page_no": n.get("page"), "quote": q, "verification": n.get("verification")}]
                 if n.get("page") else [{"kind": "catalogue", "id": f"red_flag:{n.get('rule')}", "label": "Katalog"}],
                 **({"llm": n["llm"]} if n.get("llm") else {})},
    }
