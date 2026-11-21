"""Strict import rules (code, not model): checksums, identifier formats, money with VAT basis, personal data.
Each rule returns (ok, reason). Values in failure reports are masked."""
from __future__ import annotations

import re
from datetime import date

from riskminer.ingest import ids

RULES_PL = [
    "Każdy NIP i REGON przechodzi sumę kontrolną.",
    "Numery BZP, KPO i TED tylko w znanym formacie.",
    "Kwota zawsze z rodzajem: netto albo brutto.",
    "Ten sam plik po sha256 nie wchodzi dwa razy.",
    "Import nigdy nie nadpisuje danych zatwierdzonych przez eksperta.",
    "Kolumny z danymi osobowymi (e-mail, telefon, PESEL, osoba kontaktowa) są pomijane i nie trafiają do modelu.",
]

PII_HEADER = re.compile(r"e-?mail|telefon|\btel\b|pesel|osob\w* kontaktow|imi[eę] i nazwisko|nazwisko|imi[eę]\b|faks|fax", re.I)


def is_pii_header(h: str) -> bool:
    return bool(PII_HEADER.search(h or ""))


def mask(v) -> str:
    s = str(v or "")
    if len(s) <= 4:
        return "*" * len(s)
    return s[:3] + "***" + s[-3:]


def nip_checksum(v, answers=None) -> tuple[bool, str]:
    return (True, "") if ids.nip_valid(ids.digits(v)) else (False, "nip_checksum")


def regon_checksum(v, answers=None) -> tuple[bool, str]:
    return (True, "") if ids.regon_valid(ids.digits(v)) else (False, "regon_checksum")


def nip_or_regon(v, answers=None) -> tuple[bool, str]:
    d = ids.digits(v)
    if len(d) == 10:
        return nip_checksum(d)
    if len(d) in (9, 14):
        return regon_checksum(d)
    return False, "id_format"


def public_id_format(v, answers=None) -> tuple[bool, str]:
    s = str(v or "").strip()
    if not s:
        return False, "missing"
    if ids.norm_bzp(s) or ids.kpo_check(s)["valid_format"] or ids.ted_valid(s) or ids.ocid_valid(s):
        return True, ""
    return False, "public_id_format"


def bzp_format(v, answers=None) -> tuple[bool, str]:
    return (True, "") if ids.norm_bzp(str(v or "")) else (False, "bzp_format")


def kpo_format(v, answers=None) -> tuple[bool, str]:
    return (True, "") if ids.kpo_check(str(v or "")).get("valid_format") else (False, "kpo_format")


def money_requires_vat_basis(v, answers=None) -> tuple[bool, str]:
    if v in (None, ""):
        return True, ""
    if (answers or {}).get("value_vat_basis") not in ("net", "gross"):
        return False, "vat_basis_unknown"
    return (True, "") if parse_money(v) is not None else (False, "money_format")


def date_format(v, answers=None) -> tuple[bool, str]:
    if v in (None, ""):
        return True, ""
    return (True, "") if parse_date(v) else (False, "date_format")


def teryt_woj(v, answers=None) -> tuple[bool, str]:
    s = str(v or "").strip().zfill(2)
    return (True, "") if s in ids.WOJ else (False, "teryt_woj")


def required_text(v, answers=None) -> tuple[bool, str]:
    return (True, "") if str(v or "").strip() else (False, "missing")


def text_no_analysis(v, answers=None) -> tuple[bool, str]:
    return True, ""


RULES = {"nip_checksum": nip_checksum, "regon_checksum": regon_checksum, "nip_or_regon": nip_or_regon,
         "public_id_format": public_id_format, "bzp_format": bzp_format, "kpo_format": kpo_format,
         "money_requires_vat_basis": money_requires_vat_basis, "date_format": date_format, "teryt_woj": teryt_woj,
         "required_text": required_text, "text_no_analysis": text_no_analysis}


def check(rule: str | None, v, answers=None) -> tuple[bool, str]:
    fn = RULES.get(rule or "text_no_analysis", text_no_analysis)
    return fn(v, answers)


def parse_money(v):
    if isinstance(v, (int, float)):
        from decimal import Decimal
        return Decimal(str(v))
    return ids.pl_money(str(v))


def parse_date(v) -> date | None:
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or None
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None
