"""Data-quality stage (docs/impl/verification.md §0, §2.3). Nothing is fixed silently. Only published BZP changes
(kind change_notice | performance_block) are compared; proposals from uploaded documents (document_change) are not.

1. Double-counted changes: a contract can have the same change twice, once as an AgreementUpdateNotice
   (kind change_notice) and once as a block 5.4.x in its ContractPerformingNotice (kind performance_block).
   When a contract's change rows outnumber the count the buyer declared in field 5.4.1, each change notice
   whose legal basis matches a not-yet-paired performance block is marked is_duplicate with duplicate_of_id
   (row kept, visible, excluded from rc_contract aggregates).
2. Pilot contracts whose change rows still differ from the declared count get a review_item
   (kind discrepancy, code change_count_mismatch) for the expert.
3. Impossible dates (planned end before signing, non-positive planned duration, negative actual duration) are
   flagged in rc_contract.dq_flags and excluded from statistics there and from monitoring signals; this stage
   writes one aggregated review_item per check (code dates_inconsistent, contract list in detail) plus one per
   affected pilot contract.
"""
from __future__ import annotations

from collections import defaultdict

from riskminer.ingest.dbutil import audit, upsert_copy


async def run(conn, rid) -> dict:
    stats: dict = {}
    rows = await conn.fetch("""
        WITH cnt AS (
          SELECT ch.contract_id, count(*) n_rows, max(pf.changes_count) declared
          FROM contract_change ch JOIN contract_performance pf ON pf.contract_id = ch.contract_id AND NOT pf.is_duplicate
          WHERE ch.contract_id IS NOT NULL AND ch.kind IN ('change_notice', 'performance_block') GROUP BY ch.contract_id)
        SELECT ch.id, ch.contract_id, ch.kind, ch.legal_basis, ch.changed_on, cnt.n_rows, cnt.declared
        FROM contract_change ch JOIN cnt ON cnt.contract_id = ch.contract_id
        WHERE cnt.declared IS NOT NULL AND cnt.n_rows > cnt.declared AND ch.kind IN ('change_notice', 'performance_block')
        ORDER BY ch.contract_id, ch.kind, ch.id""")
    by_contract: dict[int, dict[str, list]] = defaultdict(lambda: {"change_notice": [], "performance_block": []})
    meta = {}
    for r in rows:
        by_contract[r["contract_id"]][r["kind"]].append(r) if r["kind"] in ("change_notice", "performance_block") else None
        meta[r["contract_id"]] = (r["n_rows"], r["declared"])
    pairs = []
    for cid, k in by_contract.items():
        n_rows, declared = meta[cid]
        excess = n_rows - declared
        free = list(k["performance_block"])
        for au in k["change_notice"]:
            if excess <= 0:
                break
            hit = next((b for b in free if set(b["legal_basis"] or []) & set(au["legal_basis"] or [])), None)
            if hit is None and len(k["change_notice"]) + len(free) - declared > 0 and len(free) == declared and free:
                hit = free[0]       # all declared changes are listed in the performance notice: the notice repeats one
            if hit is not None:
                free.remove(hit)
                pairs.append((au["id"], hit["id"]))
                excess -= 1
    async with conn.transaction():
        await conn.execute("UPDATE contract_change SET is_duplicate = false, duplicate_of_id = NULL WHERE is_duplicate")
        if pairs:
            await conn.execute("CREATE TEMP TABLE tmp_dup (id bigint, dup_of bigint) ON COMMIT DROP")
            await conn.copy_records_to_table("tmp_dup", records=pairs)
            await conn.execute("UPDATE contract_change c SET is_duplicate = true, duplicate_of_id = t.dup_of "
                               "FROM tmp_dup t WHERE c.id = t.id")
        stats["contracts_over_declared"] = len(by_contract)
        stats["change_notices_marked_duplicate"] = len(pairs)
        # pilot contracts still not matching the declared count -> review items
        mism = await conn.fetch("""
            SELECT pr.id project_id, pr.rm_id, c.id contract_id, c.lot_no, c.contractor_name,
                   count(ch.id) FILTER (WHERE NOT ch.is_duplicate) n_rows,
                   count(ch.id) FILTER (WHERE ch.is_duplicate) n_dup, max(pf.changes_count) declared
            FROM project pr JOIN project_procedure pp ON pp.project_id = pr.id AND pp.method <> 'cross_reference_related'
            JOIN contract c ON c.procedure_id = pp.procedure_id
            JOIN contract_performance pf ON pf.contract_id = c.id AND NOT pf.is_duplicate
            LEFT JOIN contract_change ch ON ch.contract_id = c.id AND ch.kind IN ('change_notice', 'performance_block')
            WHERE pr.is_pilot GROUP BY pr.id, pr.rm_id, c.id, c.lot_no, c.contractor_name""")
        items, deduped = [], []
        for m in mism:
            if m["n_dup"]:
                deduped.append(m["rm_id"])
            if m["declared"] is not None and m["n_rows"] != m["declared"]:
                items.append((f"dq|{m['rm_id']}|change_count|{m['contract_id']}", "discrepancy", "change_count_mismatch",
                              "contract", m["contract_id"], m["project_id"],
                              (f"Umowa ({m['contractor_name'] or 'wykonawca nieznany'}): w ogłoszeniach jest {m['n_rows']} "
                               f"zmian, a w ogłoszeniu o wykonaniu zadeklarowano {m['declared']}"),
                              {"rows": m["n_rows"], "declared": m["declared"], "marked_duplicate": m["n_dup"],
                               "lot_no": m["lot_no"]}, "low", "quality:change_count"))
        await conn.execute("UPDATE review_item SET status = 'resolved', resolved_by = 'system:quality', resolved_at = now() "
                           "WHERE code = 'change_count_mismatch' AND status = 'open' AND NOT (key = ANY($1::text[]))",
                           [i[0] for i in items])
        if items:
            await upsert_copy(conn, "review_item", ("key", "kind", "code", "target_table", "target_id", "project_id",
                                                    "title", "detail", "severity", "created_by"),
                              items, ("key",), update=["title", "detail", "severity"])
        stats["pilot_contracts_deduped"] = sorted(set(deduped))
        stats["pilot_change_count_review_items"] = len(items)
        dq = await conn.fetchrow("""SELECT count(*) FILTER (WHERE planned_end_on < signed_on) end_before_sign,
                                    (SELECT count(*) FROM rc_contract WHERE NOT dq_ok) rc_flagged FROM contract""")
        stats.update(dict(dq))
        stats["date_review_items"] = await _date_items(conn)
        stats["future_date_items"] = await _future_items(conn)
        await audit(conn, "system:quality", "derive.quality", "contract_change", None, None,
                    {"marked_duplicate": len(pairs), "review_items": len(items)},
                    "change notices repeating performance-notice change blocks marked is_duplicate")
    return stats


DATE_CHECKS = (
    ("planned_end_before_signed", "contract",
     """SELECT c.id, c.planned_end_on < c.signed_on AS bad FROM contract c WHERE c.planned_end_on < c.signed_on""",
     "Umowy z planowanym końcem przed datą podpisania: {n}. Wyłączone ze statystyk klasy referencyjnej i z sygnałów monitoringu."),
    ("rc_dates_flagged", "rc_contract",
     """SELECT contract_id AS id, true AS bad FROM rc_contract WHERE NOT dq_ok""",
     ("Umowy klasy referencyjnej z niemożliwymi datami (koniec przed podpisaniem, czas planowany 0 dni lub mniej, "
      "czas faktyczny ujemny): {n}. Opóźnienie i czas trwania nie są liczone dla tych umów.")),
)


async def _date_items(conn) -> int:
    """One aggregated review_item per impossible-date check (national scope), listing the contracts, so the expert
    sees what was excluded from statistics; per-pilot rows get their own item. Resolved automatically when the
    count drops to 0 after a reload."""
    n_items = 0
    for code, table, sql, title in DATE_CHECKS:
        rows = await conn.fetch(sql)
        ids = sorted({r["id"] for r in rows})
        key = f"dq|national|{code}"
        if not ids:
            await conn.execute("UPDATE review_item SET status = 'resolved', resolved_by = 'system:quality', resolved_at = now() "
                               "WHERE key = $1 AND status = 'open'", key)
            continue
        pilots = await conn.fetch("""
            SELECT DISTINCT pr.id project_id, pr.rm_id, c.id contract_id FROM contract c
            JOIN project_procedure pp ON pp.procedure_id = c.procedure_id AND pp.method <> 'cross_reference_related'
            JOIN project pr ON pr.id = pp.project_id AND pr.is_pilot WHERE c.id = ANY($1::bigint[])""", ids)
        items = [(key, "discrepancy", "dates_inconsistent", table, None, None, title.format(n=len(ids)),
                  {"check": code, "n": len(ids), "contract_ids": ids[:500], "truncated": len(ids) > 500,
                   "pilot_rm_ids": sorted({p["rm_id"] for p in pilots}),
                   "rule": "excluded from rc_contract statistics (dq_flags) and from monitor_signals"},
                  "low", "quality:dates")]
        items += [(f"dq|{p['rm_id']}|{code}|{p['contract_id']}", "discrepancy", "dates_inconsistent", "contract",
                   p["contract_id"], p["project_id"], ("Umowa ma niemożliwe daty (koniec przed podpisaniem lub czas 0 dni); "
                                                       "wyłączona ze statystyk"), {"check": code}, "low", "quality:dates")
                  for p in pilots]
        await upsert_copy(conn, "review_item", ("key", "kind", "code", "target_table", "target_id", "project_id",
                                                "title", "detail", "severity", "created_by"),
                          items, ("key",), update=["title", "detail", "severity"])
        n_items += len(items)
    return n_items


async def _future_items(conn) -> int:
    """Dates in the future copied from BZP fields (e.g. completion 2029-08-03 in field 5.2 of 2024/BZP 00496727): the
    buyer's typo, kept as published. One review_item lists every affected risk event, performance notice and change."""
    ev = await conn.fetch("""SELECT r.id, r.event_type, r.occurred_on, r.procedure_id, r.contract_id FROM risk_event r
                             WHERE r.occurred_on > current_date ORDER BY r.id""")
    pf = await conn.fetch("""SELECT pf.id, pf.completed_on, n.bzp_number, (rc.late IS NOT NULL) AS in_stats
                             FROM contract_performance pf JOIN notice n ON n.id = pf.notice_id
                             LEFT JOIN rc_contract rc ON rc.performance_id = pf.id
                             WHERE NOT pf.is_duplicate AND pf.completed_on > current_date ORDER BY pf.id""")
    ch = await conn.fetch("SELECT id, changed_on FROM contract_change WHERE changed_on > current_date ORDER BY id")
    key = "dq|national|future_dates"
    if not (ev or pf or ch):
        await conn.execute("UPDATE review_item SET status = 'resolved', resolved_by = 'system:quality', resolved_at = now() "
                           "WHERE key = $1 AND status = 'open'", key)
        return 0
    in_stats = sum(1 for r in pf if r["in_stats"])
    title = (f"Daty z przyszłości w ogłoszeniach BZP: zdarzeń ryzyka {len(ev)}, ogłoszeń o wykonaniu {len(pf)} "
             f"(w statystykach klasy referencyjnej {in_stats}), zmian umów {len(ch)}. Prawdopodobnie błąd zamawiającego "
             "w ogłoszeniu; pozostawione tak, jak opublikowano. Do sprawdzenia.")
    detail = {"risk_events": [{"id": r["id"], "event_type": r["event_type"], "occurred_on": r["occurred_on"],
                               "contract_id": r["contract_id"]} for r in ev],
              "performance": [{"id": r["id"], "completed_on": r["completed_on"], "bzp_number": r["bzp_number"],
                               "in_rc_statistics": r["in_stats"]} for r in pf],
              "changes": [{"id": r["id"], "changed_on": r["changed_on"]} for r in ch],
              "rule": "date later than the load date; source value kept (invariant 10), flagged for the expert"}
    await upsert_copy(conn, "review_item", ("key", "kind", "code", "target_table", "title", "detail", "severity",
                                            "created_by"),
                      [(key, "discrepancy", "future_date", "risk_event", title, detail, "low", "quality:dates")],
                      ("key",), update=["title", "detail"])
    return 1
