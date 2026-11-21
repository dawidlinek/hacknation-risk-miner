"""`document_facts`: facts from a newly uploaded project document (docs/impl/new_documents.md §1, §2 step 5; gap G2).

Rules pass first (always available, also for confidential documents with no sovereign model): document kind and date,
identifiers (KPO number, contract number + date, NIP/REGON with checksums, sign), change (kinds, durations, old/new
end dates, money with VAT basis, art. 455 basis), cause keywords → catalogue codes, the dependency on a linked
investment (R18), and flags (mixed art. 455 premises, NIP checksum). Every rule fact carries a verbatim quote with page
and character offsets (verified by construction).

LLM pass second, under sensitivity routing (public → bulk/fast; confidential → sovereign chain or skipped): structured
change + causes + mitigation with quotes verified on the page. It adds causes the rules missed and mitigation lessons;
rules win on numbers. All output is a proposal; session B (G3) links it and writes records.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from riskminer.llm import gateway
from riskminer.llm.backends.base import PageText, Text
from riskminer.llm.errors import LLMError, SovereignUnavailable
from riskminer.llm.gateway import LLMRequest
from riskminer.llm.sanitize import copy_rules, scrub_contact
from riskminer.llm.verify import numbers_supported, parse_numbers, verify_quote
from riskminer.validators import nip_check, nip_valid as nip_ok, regon_valid as regon_ok  # one shared rule (D)

VERSION = 1
KIND_LABEL = {"protokol_koniecznosci_aneksowania": "protokół konieczności aneksowania umowy",
              "protokol_koniecznosci": "protokół konieczności (roboty dodatkowe)",
              "pismo_do_instytucji": "pismo do instytucji pośredniczącej",
              "aneks": "aneks do umowy", "inne": "inny dokument"}

# cause keyword rules → catalogue codes (sector pack wod-kan); first matching pattern per code is quoted
CAUSE_RULES: list[tuple[str, str, str]] = [
    ("R03", r"kolizj\w*\s+z\s+(?:sieci\w*|uzbrojeni\w*|infrastruktur\w*)", "kolizja z istniejącą siecią lub uzbrojeniem"),
    ("R03", r"uzgodnieni\w*\s+z\s+mieszkańc\w*|zgod\w*\s+właściciel\w*|now\w*\s+zabudow\w*", "dostęp do terenu, mieszkańcy, nowa zabudowa"),
    ("R02", r"wysoki\w*\s+poziom\w*\s+wód\s+gruntow\w*|wód\s+gruntow\w*", "woda gruntowa"),
    ("R02", r"stan\w*\s+techniczn\w*[^.]{0,260}?(?:odkryciu|ocenie technicznej)", "stan istniejących obiektów wyszedł po odkryciu"),
    ("R02", r"uwarunkowani\w*\s+terenow\w*|grunt\w*\s+nienośn\w*", "warunki terenowe i gruntowe"),
    ("R07", r"konieczno\w*\s+wykonania\s+(?:dodatkow\w*\s+robót|robót\s+dodatkow\w*)", "roboty dodatkowe"),
    ("R07", r"(?:dodatkow\w*\s+robót|robót\s+dodatkow\w*|roboty\s+dodatkowe)", "roboty dodatkowe"),
    ("R01", r"projekt\w*\s+sporządzon\w*\s+kilkanaście\s+lat\s+wcześniej|nieaktualn\w*\s+(?:projekt|dokumentacj)\w*",
     "nieaktualny projekt"),
    ("R09", r"modyfikowani\w*\s+tras|odstęps\w*\s+od\s+zatwierdzon\w*\s+projekt\w*", "zmiany rozwiązań i tras względem projektu"),
    ("R05", r"deklaracj\w*\s+przedstawion\w*\s+przez\s+Inwestora", "błędne założenie po stronie inwestora"),
    ("R13", r"Regulamin\w*\s+Wyboru\s+Przedsięwzięć|termin\w*\s+realizacji\s+projektu", "finansowanie i termin programu"),
    ("R16", r"warunk\w*\s+atmosferyczn\w*|opad\w*\s+deszcz\w*|mróz|mrozy", "pogoda"),
    ("R04", r"pozwoleni\w*\s+(?:na budowę|wodnoprawn\w*)|decyzj\w*\s+(?:środowiskow|o pozwoleniu)", "decyzje i pozwolenia"),
]
R18_RULE = (r"(?:przyłącza|podłączeni\w*)\s+do\s+budowan\w*\s+(oczyszczalni\w*\s+ścieków\s+w\s+\w+)|"
            r"nieterminow\w*\s+przebieg\w*\s+realizacji\s+tej\s+inwestycji")
MITIGATION = {
    "R02": "Przed przetargiem zinwentaryzuj i oceń stan istniejących obiektów oraz wykonaj badania gruntu i wód gruntowych.",
    "R03": "Przed projektem zinwentaryzuj uzbrojenie terenu i uzgodnij przebieg z gestorami sieci oraz mieszkańcami.",
    "R01": "Zaktualizuj projekt przed przetargiem, gdy minęło kilka lat od jego sporządzenia.",
    "R09": "Przewiduj w umowie procedurę zmian tras w ramach nieistotnych odstępstw od projektu.",
    "R07": "Ustal w umowie zasady wyceny robót dodatkowych (ceny jednostkowe, kosztorys).",
    "R13": "Planuj termin z zapasem względem końca programu finansowania.",
    "R18": "Zsynchronizuj harmonogram z inwestycją powiązaną (np. oczyszczalnią) i przewidź efekt częściowy.",
}

KPO_RE = re.compile(r"KPOD\.\d{2}\.\d{2}-IW\.\d{2}-\d{4}/\d{2}")
CONTRACT_RE = re.compile(r"[Uu]mow\w*\s+nr:?\s*([A-Z0-9][\w./-]*\d)\s*(?:r\.)?\s*\n?\s*z\s+dnia:?\s*(\d{1,2}\.\d{1,2}\.\d{4})")
NIP_RE = re.compile(r"NIP:?\s*(\d{3}-?\d{3}-?\d{2}-?\d{2}|\d{10})")
REGON_RE = re.compile(r"REGON:?\s*(\d{9}|\d{14})")
SIGN_RE = re.compile(r"(?m)^\s*([A-ZŁŚ]{2,5}\.\d{3,4}(?:\.\d+)*\.\d{4})\s*$")
DATE_RE = r"(\d{1,2})\.(\d{1,2})\.(\d{4})|(\d{4})-(\d{2})-(\d{2})"


def _date(m: re.Match | tuple) -> date | None:
    g = m.groups() if isinstance(m, re.Match) else m
    try:
        if g[0]:
            return date(int(g[2]), int(g[1]), int(g[0]))
        return date(int(g[3]), int(g[4]), int(g[5]))
    except (ValueError, TypeError):
        return None


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


class _Page:
    def __init__(self, pages: dict[int, str]):
        self.pages = pages

    def find(self, pattern: str, flags: int = re.I) -> tuple[int, re.Match] | None:
        rx = re.compile(pattern, flags)
        for p in sorted(self.pages):
            m = rx.search(self.pages[p] or "")
            if m:
                return p, m
        return None

    def quote(self, page: int, start: int, end: int, max_len: int = 300) -> dict:
        """Sentence (or bullet) around a match, verbatim, with offsets into the page text; for long sentences the clause
        (between commas) around the match, so the quote always contains the trigger phrase."""
        q = self._quote(page, start, end, max_len, ".:;")
        if len(q["quote"]) > 220:
            q = self._quote(page, start, end, max_len, ".:;,")
        return q

    def _quote(self, page: int, start: int, end: int, max_len: int, stops: str) -> dict:
        t = self.pages[page]
        a = start
        while a > 0 and not (t[a - 1] in stops and (a >= len(t) or t[a].isspace())) and not (t[a - 1] == "\n" and t[a] in "–-•"):
            if start - a > 220:
                break
            a -= 1
        b = end
        while b < len(t) and t[b] not in ".;" + ("," if "," in stops else "") and not (t[b] == "," and b + 1 < len(t) and t[b + 1] == "\n"):
            if b - end > 220:
                break
            b += 1
        b = min(b + 1, len(t)) if b < len(t) and t[b] == "." else b
        while a < b and (t[a].isspace() or t[a] in "–-•"):
            a += 1
        q = re.sub(r"\s+", " ", t[a:b]).strip()
        if len(q) > max_len:
            q = q[:max_len].rsplit(" ", 1)[0]
            b = a + len(q)
        return {"quote": scrub_contact(q), "page": page, "char_start": a, "char_end": b, "verification": "exact"}


def _kind(text: str) -> str:
    lo = text.lower()
    if re.search(r"protok\w*\s+konieczno\w*\s+aneks", lo):
        return "protokol_koniecznosci_aneksowania"
    if re.search(r"protok\w*\s+konieczno", lo):
        return "protokol_koniecznosci"
    if re.search(r"urząd\s+marszałkowski|instytucj\w*\s+pośrednicz|wojewódzki\w*\s+fundusz", lo) and re.search(r"wnios\w*|zwraca się", lo):
        return "pismo_do_instytucji"
    if re.search(r"\baneks\w*\s+nr", lo):
        return "aneks"
    return "inne"


def rules_pass(pages: dict[int, str]) -> dict[str, Any]:
    P = _Page(pages)
    full = "\n".join(pages[p] or "" for p in sorted(pages))
    out: dict[str, Any] = {"facts": [], "causes": [], "effects": [], "flags": [], "mitigations": []}

    def fact(field: str, value: Any, display: str, hit: tuple[int, re.Match] | None, method: str):
        f = {"field": field, "value": value, "display": display, "origin": "CALC", "method": f"rule:{method}"}
        if hit:
            f.update(P.quote(hit[0], hit[1].start(), hit[1].end()))
        out["facts"].append(f)
        return f

    kind = _kind(full)
    out["doc_kind"], out["doc_kind_label"] = kind, KIND_LABEL[kind]
    out["phase"] = "realizacja" if kind in ("protokol_koniecznosci_aneksowania", "protokol_koniecznosci", "aneks", "pismo_do_instytucji") else None
    # document date: "sporządzony dnia", "<miejscowość>, dnia", "<miejscowość>, 2025-11-06"
    hit = (P.find(r"sporządzon\w*\s+dnia\s+" + f"(?:{DATE_RE})") or P.find(r"\w+,\s+(?:dnia\s+)?" + f"(?:{DATE_RE})"))
    doc_date = None
    if hit:
        dm = re.search(DATE_RE, hit[1].group())
        doc_date = _date(dm) if dm else None
        if doc_date:
            fact("doc_date", doc_date.isoformat(), doc_date.strftime("%d.%m.%Y"), hit, "date")
    out["doc_date"] = doc_date.isoformat() if doc_date else None
    # identifiers
    ids: dict[str, Any] = {"kpo": sorted(set(KPO_RE.findall(full))), "contract": None, "nip": [], "regon": [], "sign": None,
                           "buyer": None, "contractor": None, "task_title": None, "recipient": None}
    for k in ids["kpo"]:
        fact("kpo_number", k, k, P.find(re.escape(k), 0), "kpo")
    hit = P.find(CONTRACT_RE.pattern, 0)
    if hit:
        cd = _date(re.search(DATE_RE, hit[1].group(2)))
        ids["contract"] = {"number": hit[1].group(1), "date": cd.isoformat() if cd else None}
        fact("contract_ref", ids["contract"], f"umowa nr {hit[1].group(1)} z dnia {hit[1].group(2)}", hit, "contract")
    for m in NIP_RE.finditer(full):
        v = re.sub(r"\D", "", m.group(1))
        ok = nip_ok(v)
        ids["nip"].append({"value": v, "checksum_ok": ok})
        if not ok:
            out["flags"].append({"code": "nip_checksum", "value": v,
                                 "detail": nip_check(v),
                                 "text": f"NIP {v} w dokumencie nie przechodzi sumy kontrolnej. Sprawdź z rejestrem, niczego nie poprawiamy samodzielnie."})
    for m in REGON_RE.finditer(full):
        ok = regon_ok(m.group(1))
        ids["regon"].append({"value": m.group(1), "checksum_ok": ok})
        if not ok:
            out["flags"].append({"code": "regon_checksum", "value": m.group(1),
                                 "text": f"REGON {m.group(1)} w dokumencie nie przechodzi sumy kontrolnej. Sprawdź z rejestrem."})
    m = SIGN_RE.search(full)
    ids["sign"] = m.group(1) if m else None
    for field, rx in (("buyer", r"Zamawiając\w*:\s*([^\n,]+?)(?:\s+ul\.|,|\n)"), ("contractor", r"Wykonawc\w*:\s*([^\n]+)"),
                      ("task_title", r"(?:Zadanie|Dotyczy):\s*[„\"]([^”\"]+)[”\"]")):
        h = P.find(rx, 0)
        if h:
            ids[field] = re.sub(r"\s+", " ", h[1].group(1)).strip().rstrip(".")
    if not ids["buyer"]:
        h = P.find(r"(?m)^(GMINA\s+[A-ZĄĆĘŁŃÓŚŹŻ][A-ZĄĆĘŁŃÓŚŹŻ \-]+)$", 0)
        if h:
            ids["buyer"] = h[1].group(1).strip().title().replace("Gmina", "Gmina")
    h = P.find(r"(Urząd\s+Marszałkowski\s+Województwa\s+\w+)")
    if h:
        ids["recipient"] = re.sub(r"\s+", " ", h[1].group(1))
    out["identifiers"] = ids
    out["level"] = "grant" if (kind == "pismo_do_instytucji" or (ids["kpo"] and not ids["contract"] and
                                                              re.search(r"realizacji\s+projektu", full, re.I))) else "contract"
    # change
    ch: dict[str, Any] = {"kinds": [], "delta_months": None, "delta_days": None, "old_end": None, "new_end": None,
                          "new_term_months": None, "planned_end_calc": None, "requested_end": None, "value": None,
                          "legal_basis": [], "legal_basis_state": "DOKUMENT_NIE_WSPOMINA"}
    h = P.find(r"(?:przedłużeni\w*|wydłużeni\w*)\s+terminu\s+realizacji\s+(?:przedmiotu\s+umowy\s+|umowy\s+)?o\s+(?:okres\s+)?(\d+)\s+miesi")
    if h:
        ch["delta_months"] = int(h[1].group(1))
        fact("delta_months", ch["delta_months"], f"+{ch['delta_months']} mies.", h, "duration")
    h = P.find(r"do\s+(\d+)\s+miesięcy\s+od\s+dnia\s+zawarcia\s+umowy")
    if h:
        ch["new_term_months"] = int(h[1].group(1))
        fact("new_term", ch["new_term_months"], f"{ch['new_term_months']} mies. od zawarcia umowy", h, "duration")
        if ids["contract"] and ids["contract"]["date"]:
            pe = _add_months(date.fromisoformat(ids["contract"]["date"]), ch["new_term_months"])
            ch["planned_end_calc"] = pe.isoformat()
            out["facts"].append({"field": "planned_end", "value": pe.isoformat(), "display": pe.strftime("%d.%m.%Y"),
                                 "origin": "CALC", "method": "calc:contract_date+new_term_months"})
    ho = P.find(r"(?:Dotychczasowy|Obecny|Pierwotny)\s+termin\s+[^:\n]*:\s*" + f"(?:{DATE_RE})")
    hn = P.find(r"(?:Proponowany\s+)?[Nn]owy\s+termin\s+[^:\n]*:\s*" + f"(?:{DATE_RE})")
    if ho:
        ch["old_end"] = _date(re.search(DATE_RE, ho[1].group())).isoformat()
        fact("old_end", ch["old_end"], date.fromisoformat(ch["old_end"]).strftime("%d.%m.%Y"), ho, "date")
    if hn:
        ch["new_end"] = _date(re.search(DATE_RE, hn[1].group())).isoformat()
        fact("new_end", ch["new_end"], date.fromisoformat(ch["new_end"]).strftime("%d.%m.%Y"), hn, "date")
    if ch["old_end"] and ch["new_end"]:
        ch["delta_days"] = (date.fromisoformat(ch["new_end"]) - date.fromisoformat(ch["old_end"])).days
        out["facts"].append({"field": "delta_days", "value": ch["delta_days"], "display": f"+{ch['delta_days']} dni",
                             "origin": "CALC", "method": "calc:new_end-old_end"})
    if out["level"] == "grant":
        h = P.find(r"wydłużeni\w*\s+terminu[^.]{0,200}?do\s+" + f"(?:{DATE_RE})")
        if h:
            rd = _date(re.search(DATE_RE, h[1].group()))
            ch["requested_end"] = rd.isoformat() if rd else None
            fact("requested_end", ch["requested_end"], rd.strftime("%d.%m.%Y") if rd else "", h, "date")
    h = P.find(r"(?:kwot\w*|wartoś\w*|wynagrodzeni\w*)[^.\n]{0,40}?:?\s*(\d{1,3}(?:[  ]\d{3})*(?:,\d{2})?)\s*zł\s*(brutto|netto)?")
    if h:
        toks = parse_numbers(h[1].group(1) + " zł")
        if toks:
            vat = {"brutto": "gross", "netto": "net"}.get((h[1].group(2) or "").lower(), "unknown")
            ch["value"] = {"amount": f"{toks[0].value:.2f}", "currency": "PLN", "vat_basis": vat}
            fact("delta_value", ch["value"], f"{h[1].group(1)} zł {h[1].group(2) or ''}".strip(), h, "money")
    for m in re.finditer(r"art\.?\s*(\d{3})\s*ust\.?\s*(\d+)\s*pkt\.?\s*(\d+)", full, re.I):
        lb = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
        if lb not in ch["legal_basis"]:
            ch["legal_basis"].append(lb)
    if ch["legal_basis"]:
        ch["legal_basis_state"] = "stated"
        fact("legal_basis", ch["legal_basis"], ", ".join("art. " + b.replace(".", " ust. ", 1).replace(".", " pkt ") for b in ch["legal_basis"]),
             P.find(r"art\.?\s*\d{3}\s*ust\.?\s*\d+\s*pkt\.?\s*\d+"), "legal_basis")
    if ("455.1.3" in ch["legal_basis"] and re.search(r"nie\s+można\s+było\s+przewidzieć|nie\s+były\s+możliwe\s+do\s+przewidzenia", full, re.I)):
        out["flags"].append({"code": "mixed_legal_basis",
                             "text": "Uzasadnienie miesza przesłanki pkt 3 i pkt 4 art. 455 ust. 1 Pzp (roboty dodatkowe i okoliczności nieprzewidywalne)."})
    kinds = []
    if ch["delta_months"] or ch["new_end"] or ch["new_term_months"] or ch["requested_end"]:
        kinds.append("termin_projektu" if out["level"] == "grant" else "termin")
    if ch["value"]:
        kinds.append("wynagrodzenie")
    if re.search(r"robót\s+dodatkow|dodatkow\w*\s+robót|zakres\w*\s+(?:robót|zamówienia)\s+(?:rozszerz|zwiększ)", full, re.I):
        kinds.append("zakres")
    ch["kinds"] = kinds
    out["change"] = ch
    # causes
    seen: set[str] = set()
    for code, rx, why in CAUSE_RULES:
        if code in seen:
            continue
        h = P.find(rx)
        if h:
            seen.add(code)
            out["causes"].append({"code": code, "method": "rule", "origin": "CALC", "why": why, **P.quote(h[0], h[1].start(), h[1].end())})
    # dependency on a linked investment → R18 effect
    h = P.find(R18_RULE)
    if h:
        linked = None
        lm = re.search(r"budowan\w*\s+(oczyszczalni\w*\s+ścieków\s+w\s+\w+)", " ".join(pages.values()), re.I)
        if lm:
            linked = re.sub(r"oczyszczalni\w*", "oczyszczalnia", lm.group(1))
        months = None
        dm = P.find(r"przewidywan\w*\s+opóźnieni\w*\s+(\d+)\s+miesi")
        if dm:
            months = int(dm[1].group(1))
        q = P.quote(h[0], h[1].start(), h[1].end(), max_len=300)
        hq = P.find(r"Opóźnieni\w*\s+osiągnięci\w*\s+efektu\s+użytkowego")
        if hq:
            q = P.quote(hq[0], hq[1].start(), hq[1].end(), max_len=300)
        out["effects"].append({"code": "R18", "kind": "effect_delay", "months": months, "linked_investment": linked,
                               "method": "rule", "origin": "CALC", **q})
    for c in out["causes"] + out["effects"]:
        if c["code"] in MITIGATION and not any(m["for_code"] == c["code"] for m in out["mitigations"]):
            out["mitigations"].append({"for_code": c["code"], "text": MITIGATION[c["code"]], "method": "rule:catalogue"})
    return out


# ---------------------------------------------------------------------------------------------------------------------
# LLM pass
# ---------------------------------------------------------------------------------------------------------------------
class LCause(BaseModel):
    code: str = Field(description="kod ryzyka z katalogu, np. R02")
    page: int
    quote: str
    why: str


class LMitigation(BaseModel):
    text: str
    for_code: str | None = None


class LChange(BaseModel):
    level: Literal["contract", "grant", "none"]
    kinds: list[Literal["termin", "termin_projektu", "wynagrodzenie", "zakres", "inne"]] = []
    delta_days: int | None = None
    delta_months: int | None = None
    value_amount: float | None = None
    vat_basis: Literal["net", "gross", "unknown"] | None = None
    legal_basis: list[str] = []
    quote: str | None = None
    page: int | None = None


class LFacts(BaseModel):
    doc_kind: str
    change: LChange
    causes: list[LCause] = []
    linked_investment_delay: LCause | None = None
    mitigations: list[LMitigation] = []
    summary: str


async def llm_pass(doc: dict, sensitivity: str, subject: str | None, *, refs: bool = True,
                   examples: str = "", mistakes: str = "") -> tuple[LFacts | None, Any, str | None]:
    from riskminer.llm.tasks.redpen_scan import catalogue
    cat = catalogue()
    parts = [Text(f"Dokument id={doc['id']}, plik {doc.get('filename')}, {len(doc['pages'])} stron.")]
    parts += [PageText(doc["id"], p, doc["pages"][p]) for p in sorted(doc["pages"]) if (doc["pages"][p] or "").strip()]
    try:
        res = await gateway.run(LLMRequest(task="document_facts", sensitivity=sensitivity, prompt="document_facts",  # type: ignore[arg-type]
                                           parts=parts, output=LFacts,
                                           prompt_vars={"catalogue": cat["text"], "examples": examples, "mistakes": mistakes},
                                           input_refs=[f"document:{doc['id']}"] if refs and isinstance(doc["id"], int) and doc["id"] > 0 else [],
                                           subject=subject, timeout_kind="document", max_output_tokens=3000))
    except SovereignUnavailable:
        return None, None, "sovereign_unavailable"
    except LLMError as e:
        return None, None, e.code
    return res.data, res, None


def _merge_llm(out: dict, data: LFacts, res: Any, pages: dict[int, str]) -> None:
    from riskminer.llm.tasks.redpen_scan import catalogue
    codes = catalogue()["codes"]
    have = {c["code"] for c in out["causes"]}
    for c in data.causes:
        code = c.code.strip().upper()
        if code not in codes:
            code = code.split(".")[0]
            if code not in codes:
                continue
        qc = verify_quote(c.quote, pages, c.page)
        parent = code.split(".")[0]
        if code in have or parent in have:
            for r in out["causes"]:
                if r["code"] in (code, parent):
                    r["llm_agrees"] = True
                    if "." in code and qc.ok:
                        r["sub_code"] = code
            continue
        have.add(code)
        out["causes"].append({"code": code, "method": "llm", "origin": "AI", "why": copy_rules(c.why),
                              "quote": scrub_contact(c.quote), "page": qc.page or c.page, "char_start": qc.char_start,
                              "char_end": qc.char_end, "verification": qc.status, "llm": res.llm_info})
    if data.linked_investment_delay and not out["effects"]:
        c = data.linked_investment_delay
        qc = verify_quote(c.quote, pages, c.page)
        if qc.ok:
            out["effects"].append({"code": "R18", "kind": "effect_delay", "months": None, "linked_investment": None,
                                   "method": "llm", "origin": "AI", "quote": scrub_contact(c.quote), "page": qc.page,
                                   "char_start": qc.char_start, "char_end": qc.char_end, "verification": qc.status})
    for m in data.mitigations[:4]:
        fc = (m.for_code or "").strip().upper().split(".")[0] or None
        out["mitigations"].append({"for_code": fc, "text": copy_rules(m.text), "method": "llm", "origin": "AI"})
    ch = out["change"]
    lc = data.change
    # rules win on numbers; the model's reading is kept only when it is printed in its quote and rules found nothing
    if ch["value"] is None and lc.value_amount and lc.quote and numbers_supported(lc.value_amount, lc.quote, money=True):
        qc = verify_quote(lc.quote, pages, lc.page)
        if qc.ok:
            ch["value"] = {"amount": f"{lc.value_amount:.2f}", "currency": "PLN", "vat_basis": lc.vat_basis or "unknown"}
            ch["value_origin"] = "AI"
    if lc.level == "grant" and out["level"] != "grant":
        out.setdefault("flags", []).append({"code": "level_disagreement",
                                            "text": "Model uznał zmianę za dotyczącą projektu (umowy o dofinansowanie), reguły za zmianę umowy."})
    out["summary"] = copy_rules(data.summary)


async def document_facts(doc: dict, *, sensitivity: str = "confidential", subject: str | None = None,
                         use_llm: bool = True, refs: bool = True, r18_status: str | None = None,
                         learning: dict | None = None) -> dict[str, Any]:
    """doc = {id, filename, sensitivity, pages: {page_no: text}}. Never raises for model failures.
    `learning` = {"examples": str, "mistakes": str} few-shot text from expert decisions (llm/learning.py)."""
    pages = {int(p): t or "" for p, t in doc["pages"].items()}
    out = rules_pass(pages)
    out = {"version": VERSION, "document_id": doc.get("id"), **out, "catalogue_proposals": [], "processing": [{"pass": "rules"}],
           "llm_call_ids": [], "summary": None}
    sens = "confidential" if (doc.get("sensitivity") or "confidential") == "confidential" or sensitivity == "confidential" else "public"
    if use_llm and any(t.strip() for t in pages.values()):
        data, res, err = await llm_pass({**doc, "pages": pages}, sens, subject, refs=refs,
                                        examples=(learning or {}).get("examples", ""), mistakes=(learning or {}).get("mistakes", ""))
        if data is not None:
            _merge_llm(out, data, res, pages)
            out["processing"].append({"pass": "llm", **res.processing})
            if res.llm_call_id:
                out["llm_call_ids"].append(res.llm_call_id)
        else:
            out["processing"].append({"pass": "llm", "skipped": err})
    if any(e["code"] == "R18" for e in out["effects"]):
        out["catalogue_proposals"].append(await _r18_status(out, r18_status))
    for c in out["causes"] + out["effects"]:
        c.setdefault("review_status", "proposed")
        # evidence strength, not a calibrated probability: rule hit confirmed by the model > rule hit > model only
        if c["method"] == "rule":
            c["confidence"] = 0.9 if c.get("llm_agrees") else 0.75
        else:
            c["confidence"] = 0.6 if c.get("verification") in ("exact", "fuzzy") else 0.3
        c["risk_code"], c["page_no"] = c["code"], c.get("page")      # aliases used by the pipeline (S0) and B
    ch = out["change"]
    ch["kind"] = ch["kinds"][0] if ch["kinds"] else None
    ch["delta_value"] = ch["value"]
    return out


async def _r18_status(out: dict, known: str | None = None) -> dict:
    status = known or "missing"
    name = "Zależność efektu od zadań powiązanych"
    if known:
        e = next(e for e in out["effects"] if e["code"] == "R18")
        return {"code": "R18", "name": name, "catalogue_status": status,
                "action": "none" if status == "approved" else "propose_or_support",
                "text": "Zależność efektu od inwestycji powiązanej (np. oczyszczalni budowanej przez inny podmiot).",
                "quote": e.get("quote"), "page": e.get("page")}
    try:
        from riskminer.db.session import raw_conn
        async with raw_conn() as conn:
            r = await conn.fetchrow("SELECT status, name FROM catalogue_risk WHERE sector = 'wod-kan' AND code = 'R18' "
                                    "ORDER BY version DESC LIMIT 1")
        if r:
            status, name = r["status"], r["name"]
    except Exception:  # noqa: BLE001  no DB (unit tests): treat as unknown → proposal
        status = "unknown"
    e = next(e for e in out["effects"] if e["code"] == "R18")
    return {"code": "R18", "name": name, "catalogue_status": status,
            "action": "none" if status == "approved" else "propose_or_support",
            "text": "Zależność efektu od inwestycji powiązanej (np. oczyszczalni budowanej przez inny podmiot).",
            "quote": e.get("quote"), "page": e.get("page")}


_ = timedelta


async def extract_document(db, document_id: int, *, actor: str, request_id: str | None = None) -> dict:
    """Pipeline step for session S0's `document_process` (one AsyncSession, no commit): read the document and its pages
    through `db`, run rules + LLM (sensitivity from the document row, read here, so an uncommitted upload is routed by its
    real label), store `document.data.facts`, return a short summary."""
    import json as _json

    from sqlalchemy import text as _text

    from riskminer.llm.learning import few_shot
    row = (await db.execute(_text("SELECT id, filename, doc_type, sensitivity FROM document WHERE id = :i"),
                            {"i": document_id})).mappings().first()
    if row is None:
        return {"status": "not_found", "document_id": document_id}
    pages = {r["page_no"]: r["text"] or "" for r in (await db.execute(
        _text("SELECT page_no, text FROM document_page WHERE document_id = :i ORDER BY page_no"), {"i": document_id})).mappings()}
    if not any(t.strip() for t in pages.values()):
        return {"status": "waiting_ocr", "document_id": document_id}
    r18 = (await db.execute(_text("SELECT status FROM catalogue_risk WHERE sector = 'wod-kan' AND code = 'R18' "
                                  "ORDER BY version DESC LIMIT 1"))).scalar()
    sens = row["sensitivity"] or "confidential"
    kind_guess = _kind("\n".join(pages.values()))
    learning = await few_shot(db, kind_guess)
    facts = await document_facts({"id": row["id"], "filename": row["filename"], "sensitivity": sens, "pages": pages},
                                 sensitivity=sens, subject=f"document:{document_id}", refs=False,
                                 r18_status=r18 or "missing", learning=learning)
    facts["extracted_by"] = actor
    facts["learning"] = {"examples": learning.get("n_examples", 0), "mistakes": learning.get("n_mistakes", 0)}
    await db.execute(_text("UPDATE document SET data = coalesce(data, '{}'::jsonb) || jsonb_build_object('facts', CAST(:f AS jsonb)) "
                           "WHERE id = :i"), {"f": _json.dumps(facts, ensure_ascii=False, default=str), "i": document_id})
    return {"status": "done", "document_id": document_id, "doc_kind": facts["doc_kind"], "level": facts["level"],
            "change": {k: facts["change"].get(k) for k in ("kind", "kinds", "delta_days", "delta_months", "new_end",
                                                         "planned_end_calc", "requested_end", "value", "legal_basis")},
            "causes": [c["code"] for c in facts["causes"]], "effects": [e["code"] for e in facts["effects"]],
            "flags": [f["code"] for f in facts["flags"]], "processing": facts["processing"]}
