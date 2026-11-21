"""Identifier normalisation and validation (PLAN §6.1). Pure functions."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

WOJ = {
    "02": "dolnośląskie", "04": "kujawsko-pomorskie", "06": "lubelskie", "08": "lubuskie", "10": "łódzkie",
    "12": "małopolskie", "14": "mazowieckie", "16": "opolskie", "18": "podkarpackie", "20": "podlaskie",
    "22": "pomorskie", "24": "śląskie", "26": "świętokrzyskie", "28": "warmińsko-mazurskie", "30": "wielkopolskie",
    "32": "zachodniopomorskie",
}

_BZP = re.compile(r"(\d{4})\s*[/\-_ ]\s*BZP\s*[/\-_ ]?\s*0*(\d{1,8})(?:\s*[/\-_ ]\s*(\d{1,2}))?", re.I)
_BZP_ALT = re.compile(r"BZP\s*[/\-_ ]?\s*(\d{4})\s*[/\-_ ]\s*0*(\d{1,8})(?:\s*[/\-_ ]\s*(\d{1,2}))?", re.I)
_KPO = re.compile(r"^KPOD\.(\d{2})\.(\d{2})-IW\.(\d{2})-(\d{4})/(\d{2})$")
_OCID = re.compile(r"^ocds-148610-[0-9a-f-]{20,}$", re.I)
_TED = re.compile(r"^\d{1,8}-\d{4}$")


def digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def nip_valid(n: str | None) -> bool:
    n = digits(n)
    if len(n) != 10:
        return False
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    s = sum(int(a) * b for a, b in zip(n, w)) % 11
    return s != 10 and s == int(n[9])


def regon_valid(r: str | None) -> bool:
    r = digits(r)
    if len(r) == 9:
        w = (8, 9, 2, 3, 4, 5, 6, 7)
    elif len(r) == 14:
        w = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    else:
        return False
    return sum(int(a) * b for a, b in zip(r, w)) % 11 % 10 == int(r[-1])


def norm_bzp(s: str | None) -> tuple[str, str | None] | None:
    """'2022/BZP 00058537/01' -> ('2022/BZP 00058537', '01'). Accepts sloppy variants."""
    if not s:
        return None
    s = str(s).replace("–", "-").replace("\xa0", " ")
    m = _BZP.search(s) or _BZP_ALT.search(s)
    if not m:
        return None
    year, num, ver = m.groups()
    return f"{year}/BZP {int(num):08d}", (f"{int(ver):02d}" if ver else None)


def kpo_check(s: str | None, woj: str | None = None) -> dict:
    """KPO B3.1.1 number: KPOD.03.15-IW.{nn}-{nnnn}/{yy}; nn = 12 + woj TERYT / 2 (verified on the pilot set)."""
    s = (s or "").strip()
    m = _KPO.match(s)
    if not m:
        return {"valid_format": False, "value": s}
    out = {"valid_format": True, "value": s, "component": f"{m.group(1)}.{m.group(2)}", "iw": m.group(3),
           "seq": m.group(4), "year": "20" + m.group(5)}
    if woj and woj.isdigit():
        exp = 12 + int(woj) // 2
        out["iw_expected"] = f"{exp:02d}"
        out["iw_matches_woj"] = int(m.group(3)) == exp
    return out


def ocid_valid(s: str | None) -> bool:
    return bool(s and _OCID.match(s))


def ted_valid(s: str | None) -> bool:
    return bool(s and _TED.match(s))


def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").replace("ł", "l").replace("Ł", "L"))
    return "".join(c for c in s if not unicodedata.combining(c)).casefold()


def pl_money(s: str | None) -> Decimal | None:
    """'5 350 782,65 zł' -> Decimal('5350782.65')."""
    if not s:
        return None
    m = re.search(r"-?\d[\d\s\xa0.]*(?:,\d{1,2})?", s)
    if not m:
        return None
    t = re.sub(r"[\s\xa0]", "", m.group(0))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None
