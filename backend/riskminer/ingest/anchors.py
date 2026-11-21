"""Anchor structured-field evidence to the exact field occurrence in the notice (CLAUDE.md invariant 1).

`notice.parsed_fields` keeps one value per field code, but some codes repeat inside one notice: section 8 (contract
date, value, term) once per part in multi-part result notices, and 5.4.x once per change block in performance notices.
An evidence row that cites field "8.1" of an 11-part notice is ambiguous: parsed_fields shows part 5's date while the
contract is part 9's (session L's source test: 3,669 contracts, all multi-part). This stage re-parses only notices where
a cited code repeats and sets, on each such evidence row:
  char_start / char_end : the field's span in notice.html_body (html_to_text(html_body[start:end]) = "8.1.) Data
                          zawarcia umowy: 2022-07-11"), so a checker or the UI can show exactly that occurrence;
  note                  : "8.1, część 9 (wystąpienie 3 z 5)" / "5.4.4, zmiana 2 (wystąpienie 2 z 4)";
  quote                 : the field value at that occurrence, only when the row had no quote.
When a row carries a quote that is not in the cited field, the field that does contain it (same part / change block
first) is cited instead and field_code follows ("recoded"). Contract claims whose anchored value disagrees with the
contract row are counted and become one review_item.
Runs after write_evidence (derive) and derive_events, which recreate these evidence rows.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

from riskminer.ingest.dbutil import upsert_copy
from riskminer.parsing import bzp_parse as bp

BATCH_NOTICES = 300

_TARGETS_SQL = """
WITH tr_multi AS (
  SELECT id FROM notice WHERE notice_type = 'TenderResultNotice' AND (extracted->'data'->0->>'nParts')::int > 1),
cp_multi AS (
  SELECT notice_id AS id FROM contract_change WHERE kind = 'performance_block' GROUP BY notice_id HAVING count(*) > 1)
SELECT e.id, e.notice_id, e.field_code, 'part' AS mode, c.lot_no AS idx, e.claim_field, e.quote IS NULL AS no_quote,
       c.signed_on::text AS claimed, e.quote
FROM evidence e JOIN contract c ON c.id = e.claim_id
WHERE e.claim_table = 'contract' AND e.verification = 'structured_field' AND e.notice_id IN (SELECT id FROM tr_multi)
UNION ALL
SELECT e.id, e.notice_id, e.field_code, 'block', split_part(ch.key, '|', 3)::int, e.claim_field, e.quote IS NULL, NULL, e.quote
FROM evidence e JOIN contract_change ch ON ch.id = e.claim_id
WHERE e.claim_table = 'contract_change' AND e.verification = 'structured_field' AND ch.kind = 'performance_block'
  AND ch.key LIKE 'cp|%' AND e.notice_id IN (SELECT id FROM cp_multi)
UNION ALL
SELECT e.id, e.notice_id, e.field_code, 'block', split_part(ch.key, '|', 3)::int, e.claim_field, e.quote IS NULL, NULL, e.quote
FROM evidence e JOIN risk_event r ON r.id = e.claim_id JOIN contract_change ch ON ch.id = r.change_id
WHERE e.claim_table = 'risk_event' AND e.verification = 'structured_field' AND ch.kind = 'performance_block'
  AND ch.key LIKE 'cp|%' AND e.notice_id = ch.notice_id AND e.notice_id IN (SELECT id FROM cp_multi)
UNION ALL
SELECT e.id, e.notice_id, e.field_code, 'part', l.lot_no, e.claim_field, e.quote IS NULL, NULL, e.quote
FROM evidence e JOIN risk_event r ON r.id = e.claim_id
JOIN lot l ON r.key LIKE '%|lot|%' AND l.id = split_part(r.key, '|', 3)::bigint
WHERE e.claim_table = 'risk_event' AND e.verification = 'structured_field' AND e.notice_id IN (SELECT id FROM tr_multi)
"""


def _norm(t: str | None) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def find_quote(pn: bp.ParsedNotice, quote: str, mode: str, idx: int | None) -> bp.Entry | None:
    """The field whose value contains the quote: first within the same part / change block, then the whole notice."""
    q = _norm(quote)[:120]
    if not q:
        return None
    scope: list[bp.Entry] = []
    if mode == "part":
        scope = [e for e in pn.entries if e.part == idx]
    elif mode == "block":
        blocks = pn.groups("5.4.2", within_section_prefix="5.4")
        scope = blocks[idx] if idx is not None and 0 <= idx < len(blocks) else []
    for pool in (scope, pn.entries):
        for e in pool:
            if e.code and q in _norm(e.value):
                return e
    return None


def anchor(pn: bp.ParsedNotice, code: str, mode: str, idx: int | None) -> tuple[bp.Entry | None, int, int]:
    """-> (entry, occurrence number 1-based, total occurrences of the code)."""
    occ = [e for e in pn.entries if e.code == code]
    if not occ:
        return None, 0, 0
    hit = None
    if mode == "part":
        hit = next((e for e in occ if e.part == idx), None)
        if hit is None and len(occ) == 1:
            hit = occ[0]
    else:
        blocks = pn.groups("5.4.2", within_section_prefix="5.4")
        if idx is not None and 0 <= idx < len(blocks):
            hit = next((e for e in blocks[idx] if e.code == code), None)
    if hit is None:
        return None, 0, len(occ)
    return hit, occ.index(hit) + 1, len(occ)


async def run(conn, rid, *, limit_notices: int | None = None) -> dict[str, Any]:
    t0 = time.time()
    rows = await conn.fetch(_TARGETS_SQL)
    by_notice: dict[int, list] = defaultdict(list)
    for r in rows:
        by_notice[r["notice_id"]].append(r)
    notice_ids = sorted(by_notice)[: limit_notices or None]
    st = {"evidence_targets": len(rows), "notices": len(notice_ids), "anchored": 0, "unanchored": 0,
          "value_mismatch": 0, "recoded": 0, "mismatch_examples": []}
    updates: list[tuple] = []
    for i in range(0, len(notice_ids), BATCH_NOTICES):
        chunk = notice_ids[i:i + BATCH_NOTICES]
        for n in await conn.fetch("SELECT id, html_body FROM notice WHERE id = ANY($1::bigint[])", chunk):
            pn = bp.parse_html(n["html_body"] or "")
            for r in by_notice[n["id"]]:
                code = r["field_code"]
                e, k, tot = anchor(pn, code, r["mode"], r["idx"])
                if r["quote"] and (e is None or _norm(r["quote"])[:120] not in _norm(e.value)):
                    alt = find_quote(pn, r["quote"], r["mode"], r["idx"])     # quote lives in another field: cite that one
                    if alt is not None:
                        code = alt.code
                        occ = [x for x in pn.entries if x.code == code]
                        e, k, tot = alt, occ.index(alt) + 1, len(occ)
                        st["recoded"] += 1
                if e is None:
                    st["unanchored"] += 1
                    continue
                where = f"część {r['idx']}" if r["mode"] == "part" else f"zmiana {(r['idx'] or 0) + 1}"
                note = f"{code}, {where} (wystąpienie {k} z {tot})"
                quote = re.sub(r"\s+", " ", e.value or "").strip()[:500] if r["no_quote"] else None
                updates.append((r["id"], e.start, e.end, note, quote, code))
                st["anchored"] += 1
                at = bp.iso_date(e.value)
                if r["claim_field"] == "signed_on" and r["claimed"] and at is not None and at.isoformat() != r["claimed"]:
                    st["value_mismatch"] += 1
                    if len(st["mismatch_examples"]) < 10:
                        st["mismatch_examples"].append({"evidence_id": r["id"], "claimed": r["claimed"], "at_anchor": e.value})
    async with conn.transaction():
        await conn.execute("CREATE TEMP TABLE tmp_anchor (id bigint, s int, e int, note text, quote text, code text) "
                           "ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_anchor", records=updates)
        await conn.execute("""UPDATE evidence ev SET char_start = t.s, char_end = t.e, note = t.note,
                                  quote = coalesce(ev.quote, t.quote), field_code = t.code
                              FROM tmp_anchor t WHERE ev.id = t.id""")
        key = "dq|national|evidence_anchor_mismatch"
        if st["value_mismatch"]:
            await upsert_copy(conn, "review_item", ("key", "kind", "code", "target_table", "title", "detail", "severity",
                                                    "created_by"),
                              [(key, "discrepancy", "evidence_anchor_mismatch", "evidence",
                                (f"Data zawarcia umowy różni się od pola 8.1 właściwej części ogłoszenia o wyniku: "
                                 f"{st['value_mismatch']} umów. Do sprawdzenia."),
                                {"n": st["value_mismatch"], "examples": st["mismatch_examples"]}, "low", "quality:anchors")],
                              ("key",), update=["title", "detail"])
        else:
            await conn.execute("UPDATE review_item SET status = 'resolved', resolved_by = 'system:anchors', "
                               "resolved_at = now() WHERE key = $1 AND status = 'open'", key)
    st["seconds"] = round(time.time() - t0, 1)
    return st
