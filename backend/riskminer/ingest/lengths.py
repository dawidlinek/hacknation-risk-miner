"""Network length (km) per water/sewage procedure and lot, for the unit-cost benchmark (PLN per km).

Port of research/bzp_corpus/07_wow_features.py `lengths()`: m/mb/km mentions in the title and descriptions,
'przyłącz/przykanalik' mentions counted as connections, a 'łączna długość' total preferred over summing
segments, depths/diameters/heights skipped, values < 5 m or > 200 km dropped.

Text per procedure: title + completion-notice description (field 3.8, as in the research), else title + the
contract-notice part descriptions (4.2.2). Per lot: the lot's own 4.2.2 description. length_method = 'regex'
(the LLM/expert can later write 'ai'/'expert'; rows with those methods are never overwritten here).
"""
from __future__ import annotations

import re

from riskminer.ingest.dbutil import upsert_copy  # noqa: F401  (kept for symmetry with other stages)

_LEN_RX = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:[  ]\d{3})+|\d+)(?:[,.](\d+))?\s*(km|mb|m\.?\s?b\.?|mtr|metr\w*|m)(?![\w²³2-3])(?!\s*n\.?\s*p\.?\s*m)",
    re.I)
_CONN_RX = re.compile(r"przyłącz|podłącz|przykanalik|odgałęzie|sięgacz", re.I)
_SKIP_RX = re.compile(r"głęboko|zagłębie|wysokoś|szerokoś|średnic|grubo|odległoś|promie|wysięg|nad\s+poziom|poniżej|powyżej", re.I)
_TOTAL_RX = re.compile(r"łączn\w*\s+długoś|o\s+długości\s+całkowitej|długość\s+całkowita|razem", re.I)


def lengths(text: str | None) -> dict:
    """-> {net_km, conn_km, n_mentions, used_total} (km; None when no length is mentioned)."""
    if not isinstance(text, str) or not text:
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


def _r(x: float | None) -> float | None:
    return round(x, 3) if x is not None else None


async def run(conn, rid) -> dict:
    rows = await conn.fetch("""
        SELECT p.id, p.title, p.length_method,
               (SELECT string_agg(n.extracted->'data'->>'description', E'\\n')
                  FROM notice n WHERE n.procedure_id = p.id AND n.is_latest
                   AND n.notice_type = 'ContractPerformingNotice') AS cp_desc,
               (SELECT string_agg(l.description, E'\\n' ORDER BY l.lot_no) FROM lot l WHERE l.procedure_id = p.id) AS lot_desc
        FROM procedure p WHERE p.sector = 'wod-kan'""")
    proc_upd, stats = [], {"procedures": len(rows), "with_length": 0, "with_conn": 0, "used_total": 0, "kept_manual": 0}
    for r in rows:
        if r["length_method"] in ("ai", "expert"):
            stats["kept_manual"] += 1
            continue
        title = r["title"] or ""
        res = lengths(title + "\n" + r["cp_desc"]) if r["cp_desc"] else {"net_km": None}
        if res["net_km"] is None:
            res = lengths(title + "\n" + (r["lot_desc"] or ""))
        if res["net_km"] is not None:
            stats["with_length"] += 1
        if res.get("conn_km") is not None:
            stats["with_conn"] += 1
        if res.get("used_total"):
            stats["used_total"] += 1
        proc_upd.append((r["id"], _r(res["net_km"]), _r(res.get("conn_km")),
                         "regex" if res["net_km"] is not None or res.get("conn_km") is not None else None))
    lots = await conn.fetch("""SELECT l.id, l.description FROM lot l JOIN procedure p ON p.id = l.procedure_id
                               WHERE p.sector = 'wod-kan' AND l.lot_no > 0 AND l.description IS NOT NULL""")
    lot_upd = []
    for r in lots:
        res = lengths(r["description"])
        lot_upd.append((r["id"], _r(res["net_km"]), _r(res["conn_km"])))
    stats["lots"] = len(lot_upd)
    stats["lots_with_length"] = sum(1 for x in lot_upd if x[1] is not None)
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE tmp_len (id bigint, length_km numeric, conn_km numeric, method text) ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_len", records=proc_upd)
        await conn.execute("""UPDATE procedure p SET length_km = t.length_km, conn_km = t.conn_km, length_method = t.method
                              FROM tmp_len t WHERE p.id = t.id
                                AND (p.length_km, p.conn_km, p.length_method) IS DISTINCT FROM (t.length_km, t.conn_km, t.method)""")
        await conn.execute("CREATE TEMP TABLE tmp_lot_len (id bigint, length_km numeric, conn_km numeric) ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_lot_len", records=lot_upd)
        await conn.execute("""UPDATE lot l SET length_km = t.length_km, conn_km = t.conn_km FROM tmp_lot_len t
                              WHERE l.id = t.id AND (l.length_km, l.conn_km) IS DISTINCT FROM (t.length_km, t.conn_km)""")
    return stats
