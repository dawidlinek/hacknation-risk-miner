"""Pipeline invariants against the loaded DB (run after `riskminer load-all`)."""
import asyncpg
import pytest

from riskminer.db.session import raw_conn
from riskminer.ingest import ids
from riskminer.ingest.xlsx_import import parse_annotation


def test_ids():
    assert ids.nip_valid("9121715754") and not ids.nip_valid("9121715755")
    assert ids.norm_bzp("2022/BZP 58537/1") == ("2022/BZP 00058537", "01")
    k = ids.kpo_check("KPOD.03.15-IW.13-0004/25", "02")
    assert k["valid_format"] and k["iw_matches_woj"]
    assert ids.regon_valid("910866761")


def test_annotation():
    a = parse_annotation("KPO, inwestycja B3.1.1. Wartość przedsięwzięcia: 5 350 782,65 zł; dofinansowanie: 4 333 677,17 zł. Opis: „X”")
    assert str(a["value"]) == "5350782.65" and str(a["subsidy"]) == "4333677.17" and a["description"] == "X"


async def test_bzp_copy_counts():
    async with raw_conn() as c:
        by = {r["notice_type"]: r["n"] for r in await c.fetch(
            "SELECT notice_type, count(*) n FROM notice WHERE channel='bzp_copy' GROUP BY 1")}
    assert by == {"ContractNotice": 40904, "TenderResultNotice": 40453, "AgreementUpdateNotice": 5079,
                  "ContractPerformingNotice": 26842}


async def test_pilot_linked_22_and_discrepancies():
    async with raw_conn() as c:
        linked = await c.fetchval("SELECT count(DISTINCT project_id) FROM project_procedure WHERE method <> 'cross_reference_related'")
        correct = await c.fetchval("SELECT count(*) FROM link_candidate WHERE reference_verdict='correct' "
                                   "AND left_table='project' AND right_table='procedure'")
        codes = {(r["rm_id"], r["code"]) for r in await c.fetch(
            "SELECT p.rm_id, r.code FROM review_item r JOIN project p ON p.id=r.project_id WHERE r.kind='discrepancy'")}
    assert linked == 22 and correct == 22
    assert ("RM-2026-009", "part_mismatch") in codes            # Zakrzew część
    assert ("RM-2026-008", "part_scope_wider") in codes         # Biecz część
    assert ("RM-2026-007", "value_deviation") in codes and ("RM-2026-014", "value_deviation") in codes
    assert ("RM-2026-022", "contract_notice_missing") in codes  # Wolin


async def test_audit_log_append_only():
    """Runs inside a transaction that is rolled back: no permanent audit row (api_contract §8)."""
    async with raw_conn() as c:
        tr = c.transaction()
        await tr.start()
        try:
            await c.execute("INSERT INTO audit_log (actor, action, note) VALUES ('test', 'test', 'append-only check')")
            with pytest.raises(asyncpg.RaiseError):           # the DELETE must raise; savepoint rolls back
                async with c.transaction():
                    await c.execute("DELETE FROM audit_log WHERE actor='test'")
        finally:
            await tr.rollback()


async def test_approved_rows_protected():
    """Approved rows survive a non-expert UPDATE (trigger keeps OLD). Rolled back at the end."""
    async with raw_conn() as c:
        tr = c.transaction()
        await tr.start()
        try:
            pid = await c.fetchval("SELECT id FROM project WHERE rm_id='RM-2026-001'")
            await c.execute("SET LOCAL riskminer.expert_write = 'on'")
            await c.execute("UPDATE project SET review_status='approved' WHERE id=$1", pid)
            await c.execute("SET LOCAL riskminer.expert_write = 'off'")
            await c.execute("UPDATE project SET title='AI overwrite' WHERE id=$1", pid)   # pipeline/AI write: ignored
            title = await c.fetchval("SELECT title FROM project WHERE id=$1", pid)
            assert title != "AI overwrite"
        finally:
            await tr.rollback()
