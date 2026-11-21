"""Network length mentioned in notice text (verbatim port of research/bzp_corpus/07_wow_features.lengths()).

Fallback only: the data session owns `procedure.length_km` (migration 0010, `derive_lengths`); CaseBase prefers that
column when it exists. Pure, no DB.
"""
from __future__ import annotations

import re

_LEN_RX = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[,.](\d+))?\s*(km|mb|m\.?\s?b\.?|mtr|metr\w*|m)(?![\w²³2-3])"
    r"(?!\s*n\.?\s*p\.?\s*m)",
    re.IGNORECASE)
_CONN_RX = re.compile(r"przyłącz|podłącz|przykanalik|odgałęzie|sięgacz", re.IGNORECASE)
_SKIP_RX = re.compile(r"głęboko|zagłębie|wysokoś|szerokoś|średnic|grubo|odległoś|promie|wysięg|nad\s+poziom|poniżej|"
                      r"powyżej", re.IGNORECASE)
_TOTAL_RX = re.compile(r"łączn\w*\s+długoś|o\s+długości\s+całkowitej|długość\s+całkowita|razem", re.IGNORECASE)


def lengths(text: str | None) -> dict:
    """{net_km, conn_km, n_mentions, used_total}. Units m/mb/km; values < 5 m or > 200 km dropped; a mention is a
    connection if 'przyłącz…' occurs within 60 chars before it; an explicit total wins over the sum."""
    if not isinstance(text, str):
        return {"net_km": None, "conn_km": None, "n_mentions": 0, "used_total": False}
    net, conn, n, total = [], [], 0, None
    for m in _LEN_RX.finditer(text):
        num = float(re.sub(r"[  ]", "", m.group(1)) + ("." + m.group(2) if m.group(2) else ""))
        unit = m.group(3).lower()
        km = num if unit == "km" else num / 1000
        if km < 0.005 or km > 200:
            continue
        ctx = text[max(0, m.start() - 60): m.start()]
        if _SKIP_RX.search(text[max(0, m.start() - 35): m.start()]):
            continue
        n += 1
        if _CONN_RX.search(ctx):
            conn.append(km)
        else:
            net.append(km)
            if total is None and _TOTAL_RX.search(ctx):
                total = km
    net_km = total if total is not None else (sum(net) if net else None)
    return {"net_km": net_km, "conn_km": sum(conn) if conn else None, "n_mentions": n, "used_total": total is not None}
