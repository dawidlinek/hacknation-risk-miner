"""Shared identifier checksums (NIP, REGON). Pure functions, no I/O, importable from every layer
(connectors, ingest, imports, documents, review) so one rule decides whether an identifier is valid.

`nip_check` explains a failure for review items, e.g. the organizer's Grodzisko letter: NIP 8161571014 gives
weighted sum mod 11 = 9 but check digit 4 (invalid); the register has 8161570014 (valid).
"""
from __future__ import annotations

import re

NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
REGON9_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)
REGON14_WEIGHTS = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)


def digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def nip_check(n) -> dict:
    """{"digits", "valid", "expected", "got"}: expected = weighted sum mod 11 (10 means no valid NIP has this prefix)."""
    d = digits(n)
    if len(d) != 10:
        return {"digits": d, "valid": False, "expected": None, "got": None, "reason": "length"}
    s = sum(int(a) * b for a, b in zip(d, NIP_WEIGHTS)) % 11
    got = int(d[9])
    return {"digits": d, "valid": s != 10 and s == got, "expected": s, "got": got,
            "reason": None if s != 10 and s == got else "checksum"}


def nip_valid(n) -> bool:
    return nip_check(n)["valid"]


def regon_valid(r) -> bool:
    r = digits(r)
    if len(r) == 9:
        w = REGON9_WEIGHTS
    elif len(r) == 14:
        w = REGON14_WEIGHTS
    else:
        return False
    return sum(int(a) * b for a, b in zip(r, w)) % 11 % 10 == int(r[-1])
