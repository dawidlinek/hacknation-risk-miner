"""
bzp_parse.py - parser for BZP (e-Zamowienia) notice htmlBody + typed normalisers.

Works for the 4 notice types present in the Risk Miner offline copy:
  ContractNotice (ogloszenie o zamowieniu), TenderResultNotice (o wyniku postepowania),
  AgreementUpdateNotice (o zmianie umowy), ContractPerformingNotice (o wykonaniu umowy).

Only the standard library is used, so it can be imported anywhere (backend, scripts).

Main entry points
-----------------
parse_html(html)          -> ParsedNotice: ordered entries (code, label, value, part, section)
                             + section free texts (e.g. SEKCJA VI INFORMACJE DODATKOWE)
extract(record)           -> flat, typed dict for one API/JSONL record (dispatch by noticeType)
money(s) / duration(s) / yes_no(s) / iso_date(s) / notice_no(s) / legal_basis_455(s) / nip(s)

Design notes
------------
* The HTML is generated from one template ("<!-- Version 1.0.0 -->" in all 113k notices,
  2021-2026). Each field is an <h3> whose text starts with a numeric code such as "4.4.)",
  "1.3)", "7.3.1)" or "4.2." followed by a label; the value is either an inline
  <span class="normal"> inside the <h3> or the text that follows the </h3> (<p>, raw text,
  <div>) until the next <h2>/<h3>.
* Codes repeat: per lot ("Część N" header <h3> without a code), per award criterion
  ("Kryterium N"), per change inside a performance notice (5.4.2 ... 5.4.8 block repeated),
  per contractor. Therefore entries are kept as an ordered list with a `part` index, and
  helpers expose first/all values per code.
* Field codes are NOT stable across notice types (e.g. contract value is 4.4 in
  performance/change notices but 8.2 in result notices), so per-type extractors map codes
  to semantic names; they also match on label text as a fallback.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

# --------------------------------------------------------------------------------------
# HTML -> ordered entries
# --------------------------------------------------------------------------------------

_HEAD_RE = re.compile(r"<(h1|h2|h3)\b[^>]*>(.*?)</\1\s*>", re.S | re.I)
_SPAN_NORMAL_RE = re.compile(r'<span\s+class="normal"\s*>(.*)</span>', re.S | re.I)
_CODE_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)(?:\.\)|\)|\.(?=\s|$))\s*(.*)$", re.S)
_PART_RE = re.compile(r"^\s*(?:Cz(?:ęść|esc)|Umowa dla cz(?:ęści|esci) nr)\s+(\d+)\s*$", re.I)
_H2_PART_RE = re.compile(r"\(dla cz(?:ęści|esci)\s+(\d+)\)", re.I)
_CRIT_RE = re.compile(r"^\s*Kryterium\s+(\d+)\s*$", re.I)
_TAG_BREAK_RE = re.compile(r"<\s*(br|/p|p|/div|div|li|/li|tr|/tr)\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_STYLE_RE = re.compile(r"<style\b.*?</style>", re.S | re.I)
_WS_RE = re.compile(r"[ \t\r\f\v ]+")


def html_to_text(fragment: str) -> str:
    """Strip tags, keep line breaks for <br>/<p>/<div>, unescape entities, tidy spaces."""
    if not fragment:
        return ""
    s = _COMMENT_RE.sub(" ", fragment)
    s = _STYLE_RE.sub(" ", s)
    s = _TAG_BREAK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = _html.unescape(s)
    lines = [_WS_RE.sub(" ", ln).strip() for ln in s.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


@dataclass
class Entry:
    code: str | None       # "4.4", "5.4.2" ... (None for un-numbered h3 like "Część 1")
    label: str             # "Wartość umowy"
    value: str             # text value ("" if none)
    part: int | None       # lot number from the most recent "Część N" header
    section: str           # the enclosing <h2> title, e.g. "SEKCJA IV – ..."
    criterion: int | None = None
    seq: int = 0           # position in document
    start: int = -1        # absolute offset in the notice's htmlBody where this field's <h3> starts
    end: int = -1          # absolute offset where its value ends (next heading); html_to_text(html[start:end]) = label + value


@dataclass
class ParsedNotice:
    title: str = ""                          # <h1> text: notice type / order type / name
    entries: list[Entry] = field(default_factory=list)
    part_markers: list[int] = field(default_factory=list)   # lot numbers announced by headers
    section_texts: dict[str, str] = field(default_factory=dict)  # free text after <h2>
    template_version: str | None = None

    # ---- convenience accessors ------------------------------------------------------
    def first(self, code: str, default: str | None = None, part: int | None = None) -> str | None:
        for e in self.entries:
            if e.code == code and (part is None or e.part == part):
                return e.value
        return default

    def all(self, code: str) -> list[str]:
        return [e.value for e in self.entries if e.code == code]

    def by_label(self, pattern: str, default: str | None = None) -> str | None:
        rx = re.compile(pattern, re.I)
        for e in self.entries:
            if rx.search(e.label):
                return e.value
        return default

    def as_dict(self) -> dict[str, str]:
        """{code: value} using the first occurrence of each code (lots/changes collapse)."""
        d: dict[str, str] = {}
        for e in self.entries:
            if e.code and e.code not in d:
                d[e.code] = e.value
        return d

    def labels(self) -> dict[str, str]:
        d: dict[str, str] = {}
        for e in self.entries:
            if e.code and e.code not in d:
                d[e.code] = e.label
        return d

    def parts(self) -> list[int]:
        return sorted({e.part for e in self.entries if e.part is not None})

    def groups(self, start_code: str, within_section_prefix: str | None = None) -> list[list[Entry]]:
        """Split entries into repeated blocks that start at `start_code`
        (e.g. '5.4.2' = 'Numer zmiany' in performance notices)."""
        blocks: list[list[Entry]] = []
        cur: list[Entry] | None = None
        for e in self.entries:
            if e.code == start_code:
                cur = [e]
                blocks.append(cur)
            elif cur is not None:
                if within_section_prefix and e.code and not e.code.startswith(within_section_prefix):
                    cur = None
                    continue
                cur.append(e)
        return blocks


def parse_html(html: str) -> ParsedNotice:
    pn = ParsedNotice()
    if not html:
        return pn
    a = html.find("<main>")
    b = html.rfind("</main>")
    body = html[a + 6 : b] if a >= 0 and b > a else html
    base = a + 6 if a >= 0 and b > a else 0          # body offset inside html (for Entry.start/end)
    m = re.search(r"<!--\s*Version\s+([\d.]+)\s*-->", body)
    pn.template_version = m.group(1) if m else None

    heads = list(_HEAD_RE.finditer(body))
    section = ""
    part: int | None = None
    crit: int | None = None
    for i, h in enumerate(heads):
        tag = h.group(1).lower()
        inner = h.group(2)
        nxt = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        tail_html = body[h.end() : nxt]
        if tag == "h1":
            pn.title = html_to_text(inner).replace("\n", " / ")
            continue
        if tag == "h2":
            section = html_to_text(inner)
            hm = _H2_PART_RE.search(section)
            part = int(hm.group(1)) if hm else None   # result notices: "SEKCJA V ... (dla części 2)"
            crit = None
            tail = html_to_text(tail_html)
            if tail:
                pn.section_texts[section] = tail
            continue
        # h3
        sm = _SPAN_NORMAL_RE.search(inner)
        if sm:
            label_html, inline_val = inner[: sm.start()], html_to_text(sm.group(1))
        else:
            label_html, inline_val = inner, ""
        label_txt = html_to_text(label_html).replace("\n", " ").strip()
        tail = html_to_text(tail_html)
        value = "\n".join(v for v in (inline_val, tail) if v)
        cm = _CODE_RE.match(label_txt)
        if cm:
            code, label = cm.group(1), cm.group(2).strip()
        else:
            code, label = None, label_txt
            pm = _PART_RE.match(label_txt)
            if pm:
                part = int(pm.group(1))
                crit = None
                if part not in pn.part_markers:
                    pn.part_markers.append(part)
            km = _CRIT_RE.match(label_txt)
            if km:
                crit = int(km.group(1))
        # some h3 contain "Label: value" without a span (rare) -> split on first ': '
        if not value and ":" in label and code:
            lab, _, rest = label.partition(":")
            if rest.strip() and len(lab) < 200:
                label, value = lab.strip(), rest.strip()
        label = label.rstrip(" :").strip()
        pn.entries.append(Entry(code, label, value, part, section, crit, len(pn.entries), base + h.start(), base + nxt))
    return pn


# --------------------------------------------------------------------------------------
# Typed normalisers
# --------------------------------------------------------------------------------------

_MONEY_RE = re.compile(r"(-?\d[\d\s .]*(?:,\d+)?|-?\d+(?:\.\d{1,2})?)\s*(PLN|EUR|USD|zł|zl)?", re.I)


def money(s: str | None) -> tuple[Decimal | None, str | None]:
    """'1 234 567,89 PLN' -> (Decimal('1234567.89'), 'PLN'). Handles '129513,18', '1.234.567,89',
    '129513.18' (dot decimal), embedded NBSP. Returns (None, None) if no number."""
    if not s:
        return None, None
    s = s.strip()
    m = _MONEY_RE.search(s)
    if not m:
        return None, None
    num, cur = m.group(1), (m.group(2) or "").upper() or None
    if cur in ("ZŁ", "ZL"):
        cur = "PLN"
    if cur is None and re.search(r"\bPLN\b", s):
        cur = "PLN"
    num = re.sub(r"[\s ]", "", num)
    if "," in num:
        num = num.replace(".", "").replace(",", ".")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    elif re.fullmatch(r"-?\d{1,3}\.\d{3}", num):  # '1.234' thousand separator, ambiguous
        num = num.replace(".", "")
    try:
        return Decimal(num), cur
    except InvalidOperation:
        return None, cur


def money_f(s: str | None) -> float | None:
    v, _ = money(s)
    return float(v) if v is not None else None


_YES = {"tak", "yes", "true"}
_NO = {"nie", "no", "false"}


def yes_no(s: str | None) -> bool | None:
    if s is None:
        return None
    t = s.strip().split("\n")[0].strip().lower().rstrip(".")
    if t in _YES:
        return True
    if t in _NO:
        return False
    if t.startswith("tak"):
        return True
    if t.startswith("nie") and not t.startswith("nie dotyczy"):
        return False
    return None


_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE_PL_RE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")


def iso_date(s: str | None) -> date | None:
    if not s:
        return None
    m = _DATE_RE.search(s)
    try:
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _DATE_PL_RE.search(s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


_UNIT_DAYS = {
    "dzien": 1, "dzień": 1, "dni": 1, "dnia": 1,
    "tydzien": 7, "tydzień": 7, "tygodnie": 7, "tygodni": 7, "tygodnia": 7,
    "miesiac": 30.4375, "miesiąc": 30.4375, "miesiące": 30.4375, "miesiace": 30.4375,
    "miesięcy": 30.4375, "miesiecy": 30.4375, "miesiąca": 30.4375,
    "rok": 365.25, "lata": 365.25, "lat": 365.25, "roku": 365.25,
}
_DUR_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(dni|dnia|dzień|dzien|tygodnie|tygodni|tygodnia|tydzień|tydzien|"
    r"miesiące|miesiace|miesięcy|miesiecy|miesiąca|miesiąc|miesiac|lata|lat|roku|rok)\b",
    re.I,
)
_RANGE_RE = re.compile(r"[Oo]d\s+(\d{4}-\d{2}-\d{2})\s+do\s+(\d{4}-\d{2}-\d{2})")


@dataclass
class Duration:
    kind: str                     # 'days' | 'until' | 'range' | 'unknown'
    days: float | None = None     # for 'days' (months converted with 30.4375)
    unit: str | None = None       # original unit word ('miesiące', 'dni' ...)
    amount: float | None = None
    start: date | None = None     # for 'range'
    end: date | None = None       # for 'until' / 'range'
    raw: str = ""

    def planned_end(self, contract_date: date | None) -> date | None:
        """Planned completion date. Month/year units use calendar months from the contract date
        (Polish contracts say 'w terminie 6 miesięcy od dnia zawarcia umowy'); note that some
        contracts count from site handover, which the notice does not report."""
        if self.kind in ("until", "range"):
            return self.end
        if self.kind == "days" and contract_date and self.days is not None:
            u = (self.unit or "")
            if self.amount is not None and float(self.amount).is_integer() and (u.startswith("miesi") or u in ("rok", "lata", "lat", "roku")):
                months = int(self.amount) * (12 if not u.startswith("miesi") else 1)
                return add_months(contract_date, months)
            return contract_date + timedelta(days=round(self.days))
        return None

    def planned_days(self, contract_date: date | None) -> float | None:
        if self.kind == "days":
            pe = self.planned_end(contract_date) if contract_date else None
            return float((pe - contract_date).days) if pe else self.days
        if self.end and (self.start or contract_date):
            return float((self.end - (self.start or contract_date)).days)
        return None


def add_months(d: date, months: int) -> date:
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def duration(s: str | None) -> Duration:
    """'4 miesiące' | '330 dni' | 'do 2023-05-30' | 'Od 2021-02-09 do 2021-07-30' -> Duration."""
    raw = (s or "").strip()
    if not raw:
        return Duration("unknown", raw=raw)
    first = raw.split("\n")[0]
    m = _RANGE_RE.search(first)
    if m:
        return Duration("range", start=iso_date(m.group(1)), end=iso_date(m.group(2)), raw=raw)
    m = _DUR_RE.search(first)
    if m and not re.match(r"^\s*do\s+\d{4}-", first, re.I):
        amt = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        return Duration("days", days=amt * _UNIT_DAYS.get(unit, 1), unit=unit, amount=amt, raw=raw)
    d = iso_date(first)
    if d:
        return Duration("until", end=d, raw=raw)
    return Duration("unknown", raw=raw)


_NOTICE_RE = re.compile(r"(\d{4})\s*/\s*BZP\s*(\d{5,9})(?:\s*/\s*(\d{1,2}))?", re.I)
_TED_RE = re.compile(r"(\d{4})\s*/\s*S\s*(\d{1,3})\s*-\s*(\d{4,7})", re.I)
_TED2_RE = re.compile(r"\b(\d{5,8})\s*-\s*(\d{4})\b")


def notice_no(s: str | None) -> dict[str, Any]:
    """'2021/BZP 00005925/01' -> {'kind':'BZP','bzp':'2021/BZP 00005925','version':'01'};
    '2022/S 123-456789' or '456789-2024' -> {'kind':'TED', 'ted': ...}."""
    if not s:
        return {"kind": None}
    m = _NOTICE_RE.search(s)
    if m:
        return {"kind": "BZP", "bzp": f"{m.group(1)}/BZP {int(m.group(2)):08d}",
                "version": (m.group(3).zfill(2) if m.group(3) else None)}
    m = _TED_RE.search(s)
    if m:
        return {"kind": "TED", "ted": f"{m.group(1)}/S {int(m.group(2)):03d}-{int(m.group(3)):06d}"}
    m = _TED2_RE.search(s)
    if m:
        return {"kind": "TED", "ted": f"{m.group(1)}-{m.group(2)}"}
    return {"kind": "other", "raw": s.strip()[:80]}


_455_RE = re.compile(r"art\.?\s*455\s*ust\.?\s*(\d)(?:\s*pkt\.?\s*(\d))?", re.I)


def legal_basis_455(s: str | None) -> list[str]:
    """'art. 455 ust. 1 pkt 4 ustawy' -> ['455.1.4']; may return several; [] if none."""
    if not s:
        return []
    out = []
    for m in _455_RE.finditer(s):
        k = f"455.{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else "")
        if k not in out:
            out.append(k)
    if not out and re.search(r"\b144\b", s):
        out.append("old_144")   # Pzp 2004 basis (rare, pre-2021 contracts)
    return out


def nip(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"NIP[:\s]*([\d\s-]{10,14})", s, re.I)
    digits = re.sub(r"\D", "", m.group(1) if m else s)
    return digits if len(digits) == 10 else None


def regon(s: str | None) -> str | None:
    if not s:
        return None
    m = re.search(r"REGON[:\s]*(\d{9}|\d{14})", s, re.I)
    return m.group(1) if m else None


def cpv_codes(s: str | None) -> list[str]:
    return re.findall(r"\b(\d{8})-\d\b", s or "")


# Extension days mentioned in free text ("przedłużenie terminu o 60 dni", "do dnia 30.11.2023")
_EXT_RE = re.compile(
    r"(?:przedłuż\w*|wydłuż\w*|zmian\w*\s+termin\w*|termin\w*\s+(?:wykonania|realizacji|zakończenia)\w*"
    r"[^.]{0,60}?)\D{0,40}?o\s+(\d{1,4})\s*(dni|dzień|tygodni\w*|miesi\w+)",
    re.I,
)


def extension_days(text: str | None) -> float | None:
    """Best-effort: number of days a deadline was extended, from free text. None if not found."""
    if not text:
        return None
    m = _EXT_RE.search(text)
    if not m:
        return None
    n = float(m.group(1))
    u = m.group(2).lower()
    if u.startswith("miesi"):
        n *= 30.4375
    elif u.startswith("tydz") or u.startswith("tygod"):
        n *= 7
    return n


def dates_in(text: str | None) -> list[date]:
    out = []
    for m in _DATE_RE.finditer(text or ""):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in _DATE_PL_RE.finditer(text or ""):
        try:
            out.append(date(int(m.group(3)), int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    return out


# --------------------------------------------------------------------------------------
# Per-type extractors (record = one JSON line from notices.jsonl / API response item)
# --------------------------------------------------------------------------------------

def _common(rec: dict) -> dict[str, Any]:
    nn = notice_no(rec.get("noticeNumber"))
    return {
        "objectId": rec.get("objectId"),
        "noticeType": rec.get("noticeType"),
        "noticeNumber": rec.get("noticeNumber"),
        "bzpNumber": rec.get("bzpNumber"),
        "noticeVersion": nn.get("version"),
        "tenderId": rec.get("tenderId") or None,
        "publicationDate": (rec.get("publicationDate") or "")[:10] or None,
        "orderObject": (rec.get("orderObject") or "").strip(),
        "cpvMain": (cpv_codes(rec.get("cpvCode")) or [None])[0],
        "cpvAll": " ".join(cpv_codes(rec.get("cpvCode"))),
        "orgName": rec.get("organizationName"),
        "orgCity": rec.get("organizationCity"),
        "orgProvince": rec.get("organizationProvince"),
        "orgNip": nip(rec.get("organizationNationalId")) or rec.get("organizationNationalId"),
        "orgId": rec.get("organizationId"),
        "belowEU": rec.get("isTenderAmountBelowEU"),
        "tenderType": rec.get("tenderType"),
        "orderType": rec.get("orderType"),
        "contractorNames": " | ".join((c.get("contractorName") or "").strip() for c in rec.get("contractors") or []),
        "contractorNips": " ".join(filter(None, (nip(c.get("contractorNationalId")) for c in rec.get("contractors") or []))),
    }


def _d(x: date | None) -> str | None:
    return x.isoformat() if x else None


def _num(x: Decimal | None) -> float | None:
    return float(x) if x is not None else None


def extract_performance(rec: dict, pn: ParsedNotice | None = None) -> dict[str, Any]:
    """ContractPerformingNotice -> one row per contract (+ list of embedded changes)."""
    pn = pn or parse_html(rec.get("htmlBody", ""))
    f = pn.as_dict()
    out = _common(rec)
    contract_date = iso_date(f.get("4.1"))
    dur = duration(f.get("4.2"))
    exec_date = iso_date(f.get("5.2"))
    val, cur = money(f.get("4.4"))
    paid, cur2 = money(f.get("5.5"))
    planned_end = dur.planned_end(contract_date)
    changes = []
    for blk in pn.groups("5.4.2", within_section_prefix="5.4"):
        g = {e.code: e.value for e in blk if e.code}
        cv, _ = money(g.get("5.4.6"))
        changes.append({
            "no": g.get("5.4.2"),
            "basis_raw": g.get("5.4.3"),
            "basis": " ".join(legal_basis_455(g.get("5.4.3"))),
            "reason": g.get("5.4.4"),
            "description": g.get("5.4.5"),
            "value_change": _num(cv),
            "currency": g.get("5.4.7"),
            "price_increase": yes_no(g.get("5.4.8")),
        })
    n_changes_raw = f.get("5.4.1")
    try:
        n_changes = int(re.sub(r"\D", "", n_changes_raw)) if n_changes_raw and re.search(r"\d", n_changes_raw) else None
    except ValueError:
        n_changes = None
    out.update({
        "procurementType": f.get("3.1"),
        "precededByNotice": yes_no(f.get("3.2")),
        "contractNoticeRef": notice_no(f.get("3.2.1")).get("bzp") or notice_no(f.get("3.2.1")).get("ted"),
        "contractNoticeRefRaw": f.get("3.2.1"),
        "euFunded": yes_no(f.get("3.3")),
        "euProject": f.get("3.4"),
        "procedure": f.get("3.5"),
        "title": f.get("3.7") or out["orderObject"],
        "description": f.get("3.8"),
        "cpvMainForm": (cpv_codes(f.get("3.9")) or [None])[0],
        "cpvAdditionalForm": " ".join(cpv_codes(f.get("3.10"))),
        "contractDate": _d(contract_date),
        "durationRaw": f.get("4.2"),
        "durationKind": dur.kind,
        "durationUnit": dur.unit,
        "plannedDays": dur.planned_days(contract_date),
        "plannedEnd": _d(planned_end),
        "contractorName": f.get("4.3.1"),
        "contractorNip": nip(f.get("4.3.2")),
        "contractValue": _num(val),
        "contractCurrency": cur,
        "resultNoticeRef": notice_no(f.get("4.5")).get("bzp") or notice_no(f.get("4.5")).get("ted"),
        "resultNoticeRefRaw": f.get("4.5"),
        "executed": yes_no(f.get("5.1")),
        "notExecutedReason": pn.by_label(r"przyczyn\w* niewykonania") if yes_no(f.get("5.1")) is False else None,
        "execDate": _d(exec_date),
        "onTimeDeclared": yes_no(f.get("5.3")),
        "nChanges": n_changes,
        "nChangeBlocks": len(changes),
        "paid": _num(paid),
        "paidCurrency": cur2,
        "properlyPerformed": yes_no(f.get("5.6")),
        "improperReason": pn.by_label(r"nienależyt|przyczyn\w* nienależyt") if yes_no(f.get("5.6")) is False else None,
        "controlledRequirements": f.get("5.7"),
        "additionalInfo": next(iter(pn.section_texts.values()), None) if pn.section_texts else None,
    })
    # derived
    if contract_date and exec_date:
        out["actualDays"] = (exec_date - contract_date).days
    else:
        out["actualDays"] = None
    if planned_end and exec_date:
        out["delayDays"] = (exec_date - planned_end).days
    else:
        out["delayDays"] = None
    if val and paid is not None and val > 0:
        out["costDevPct"] = float((paid - val) / val * 100)
    else:
        out["costDevPct"] = None
    out["changes"] = changes
    return out


def extract_change(rec: dict, pn: ParsedNotice | None = None) -> dict[str, Any]:
    """AgreementUpdateNotice -> one row per change notice."""
    pn = pn or parse_html(rec.get("htmlBody", ""))
    f = pn.as_dict()
    out = _common(rec)
    contract_date = iso_date(f.get("4.1"))
    dur = duration(f.get("4.2"))
    val, cur = money(f.get("4.4"))
    cv, ccur = money(f.get("5.5.1"))
    reason = f.get("5.3") or ""
    desc = f.get("5.4") or ""
    out.update({
        "changeOf": f.get("2.1"),
        "precededByNotice": yes_no(f.get("3.1")),
        "contractNoticeRef": notice_no(f.get("3.1.1")).get("bzp") or notice_no(f.get("3.1.1")).get("ted"),
        "euFunded": yes_no(f.get("3.2")),
        "procedure": f.get("3.4"),
        "title": f.get("3.6") or out["orderObject"],
        "description": f.get("3.7"),
        "contractDate": _d(contract_date),
        "durationRaw": f.get("4.2"),
        "durationKind": dur.kind,
        "plannedDays": dur.planned_days(contract_date),
        "plannedEnd": _d(dur.planned_end(contract_date)),
        "contractorName": f.get("4.3.1"),
        "contractorNip": nip(f.get("4.3.2")),
        "contractValue": _num(val),
        "resultNoticeRef": notice_no(f.get("4.5")).get("bzp") or notice_no(f.get("4.5")).get("ted"),
        "changeDate": _d(iso_date(f.get("5.1"))),
        "basisRaw": f.get("5.2"),
        "basis": " ".join(legal_basis_455(f.get("5.2"))),
        "reason": reason,
        "changeDescription": desc,
        "valueChange": _num(cv),
        "valueChangeCurrency": f.get("5.5.2") or ccur,
        "priceIncrease": yes_no(f.get("5.5.3")),
        "earlierChanges": yes_no(f.get("5.6")),
        "additionalInfo": next(iter(pn.section_texts.values()), None) if pn.section_texts else None,
    })
    out["valueChangePct"] = (out["valueChange"] / out["contractValue"] * 100) if out["valueChange"] is not None and out["contractValue"] else None
    out["extensionDays"] = extension_days(desc) or extension_days(reason)
    return out


def extract_result(rec: dict, pn: ParsedNotice | None = None) -> list[dict[str, Any]]:
    """TenderResultNotice -> one row per lot (part); single-lot notices -> one row (part=None).
    Values of section V-VIII repeat per part when the procedure has lots."""
    pn = pn or parse_html(rec.get("htmlBody", ""))
    common = _common(rec)
    f = pn.as_dict()
    parts = pn.parts() or [None]
    rows = []
    for p in parts:
        def g(code: str, _p=p) -> str | None:
            v = pn.first(code, part=_p) if _p is not None else None
            return v if v is not None else f.get(code)
        contract_date = iso_date(g("8.1"))
        dur = duration(g("8.3"))
        val, _ = money(g("8.2"))
        est, _ = money(g("4.5.5") if p is not None else (g("4.3") or g("4.3.1")))
        rows.append({
            **common,
            "part": p,
            "nParts": len(parts) if parts != [None] else 1,
            "procedure": f.get("3.1"),
            "referenceNo": f.get("4.1"),
            "separateProcedures": yes_no(f.get("4.2")),
            "estimatedValueNet": _num(est),
            "shortDescription": g("4.5.1"),
            "cpvMainForm": (cpv_codes(g("4.5.3")) or [None])[0],
            "outcome": g("5.1"),
            "cancelled": bool(re.search(r"unieważ", g("5.1") or "", re.I)),
            "cancelBasis": g("5.2") if re.search(r"unieważ", g("5.1") or "", re.I) else None,
            "cancelBasis255": (re.search(r"255\s*pkt\.?\s*(\d+)", g("5.2") or "") or [None, None])[1] if re.search(r"unieważ", g("5.1") or "", re.I) else None,
            "cancelReason": g("5.2.1") if re.search(r"unieważ", g("5.1") or "", re.I) else None,
            "nOffers": _int(g("6.1")),
            "nOffersSME": _int(g("6.1.3")),
            "nRejected": _int(g("6.1.6")),
            "minOffer": _num(money(g("6.2"))[0]),
            "maxOffer": _num(money(g("6.3"))[0]),
            "winningOffer": _num(money(g("6.4"))[0]),
            "contractorSize": g("7.2"),
            "contractorName": g("7.3.1"),
            "contractorNip": nip(g("7.3.2")),
            "subcontracting": yes_no(g("7.4")),
            "contractDate": _d(contract_date),
            "contractValue": _num(val),
            "durationRaw": g("8.3"),
            "durationKind": dur.kind,
            "plannedDays": dur.planned_days(contract_date),
            "plannedEnd": _d(dur.planned_end(contract_date)),
        })
    return rows


def _int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r"-?\d+", s.replace(" ", ""))
    return int(m.group(0)) if m else None


def extract_contract_notice(rec: dict, pn: ParsedNotice | None = None) -> list[dict[str, Any]]:
    """ContractNotice -> one row per lot with planned duration, CPV, EU funding, options, changes."""
    pn = pn or parse_html(rec.get("htmlBody", ""))
    common = _common(rec)
    f = pn.as_dict()
    parts = pn.parts() or [None]
    rows = []
    for p in parts:
        def g(code: str, _p=p) -> str | None:
            v = pn.first(code, part=_p) if _p is not None else None
            return v if v is not None else f.get(code)
        dur = duration(g("4.2.10"))
        est, _ = money(g("4.1.5") or g("4.2.5"))
        rows.append({
            **common,
            "part": p,
            "nParts": len(parts) if parts != [None] else 1,
            "title": f.get("2.3") or common["orderObject"],
            "euFunded": yes_no(f.get("2.14")),
            "euProject": f.get("2.15"),
            "procedure": f.get("2.16"),
            "referenceNo": f.get("4.1.2"),
            "partialOffers": yes_no(f.get("4.1.8")),
            "estimatedValueNet": _num(est),
            "shortDescription": g("4.2.2"),
            "cpvMainForm": (cpv_codes(g("4.2.6")) or [None])[0],
            "cpvAdditionalForm": " ".join(cpv_codes(g("4.2.7"))),
            "options": yes_no(g("4.2.8")),
            "durationRaw": g("4.2.10"),
            "durationKind": dur.kind,
            "durationDays": dur.days if dur.kind == "days" else None,
            "durationUntil": _d(dur.end),
            "deposit": yes_no(f.get("6.4")),
            "performanceBond": yes_no(f.get("6.5")),
            "advancePayments": yes_no(f.get("7.1")),
            "changesProvided": yes_no(f.get("7.3")),
            "changesText": f.get("7.4"),
            "offersDeadline": f.get("8.1"),
        })
    return rows


EXTRACTORS = {
    "ContractPerformingNotice": extract_performance,
    "AgreementUpdateNotice": extract_change,
    "TenderResultNotice": extract_result,
    "ContractNotice": extract_contract_notice,
}


def extract(rec: dict) -> Any:
    fn = EXTRACTORS.get(rec.get("noticeType"))
    return fn(rec) if fn else None


def iter_jsonl(path: str) -> Iterable[dict]:
    import json
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


if __name__ == "__main__":  # quick smoke test: python3 -I bzp_parse.py notices.jsonl [N]
    import json
    import sys
    path = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    seen: dict[str, int] = {}
    for rec in iter_jsonl(path):
        t = rec["noticeType"]
        if seen.get(t, 0) >= n:
            continue
        seen[t] = seen.get(t, 0) + 1
        res = extract(rec)
        print(t, json.dumps(res, ensure_ascii=False, default=str)[:1500])
        if all(v >= n for v in seen.values()) and len(seen) == 4:
            break
