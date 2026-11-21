"""demo-cleanup (owner D): e2e uploads and [e2e] analyses go, everything else stays; runs rolled back, backup in tmp."""
from __future__ import annotations

import json

from riskminer.db.session import raw_conn
from riskminer.ingest import demo_cleanup


async def test_cleanup_removes_only_e2e_artefacts(tmp_path):
    async with raw_conn() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            sid = await conn.fetchval("INSERT INTO source (kind, url, sha256, licence) VALUES ('upload', 'upload:t', 't', "
                                      "'user-upload') RETURNING id")
            keep = await conn.fetchval("INSERT INTO document (title, filename, fetch_state, key, origin, review_status, "
                                       "source_id) VALUES ('real', 'pismo.pdf', 'found', 'test:dc:keep', 'SOURCE', 'auto', $1) "
                                       "RETURNING id", sid)
            gone = await conn.fetchval("INSERT INTO document (title, filename, fetch_state, key, origin, review_status, "
                                       "source_id) VALUES ('e2e', '[e2e] x.pdf', 'found', 'test:dc:gone', 'SOURCE', 'auto', $1) "
                                       "RETURNING id", sid)
            await conn.execute("INSERT INTO review_item (key, kind, title, created_by) VALUES ($1, 'fact', 't', 'test')",
                               f"doc:{gone}:change_item")
            await conn.execute("INSERT INTO alert (kind, title, document_id, key) VALUES ('document_change', 't', $1, $2)",
                               gone, f"doc:{gone}:document_change:p1")
            dry = await demo_cleanup.run(conn)
            assert gone in [d["id"] for d in dry["documents"]] and keep not in [d["id"] for d in dry["documents"]]
            assert await conn.fetchval("SELECT count(*) FROM document WHERE id = $1", gone) == 1      # dry run: no change
            res = await demo_cleanup.run(conn, apply=True, actor="test", backup_dir=tmp_path)
            assert res["deleted"]["document"] >= 1 and res["deleted"]["alert"] >= 1 and res["deleted"]["review_item"] >= 1
            assert await conn.fetchval("SELECT count(*) FROM document WHERE id = $1", gone) == 0
            assert await conn.fetchval("SELECT count(*) FROM document WHERE id = $1", keep) == 1
            assert await conn.fetchval("SELECT count(*) FROM source WHERE id = $1", sid) == 1        # provenance kept
            a = await conn.fetchrow("SELECT actor, after FROM audit_log WHERE action = 'demo.cleanup' ORDER BY id DESC LIMIT 1")
            assert a["actor"] == "test" and a["after"]["deleted"]["document"] >= 1
            lines = [json.loads(x) for x in open(res["backup"], encoding="utf-8")]
            assert any(x["table"] == "document" and x["row"]["id"] == gone for x in lines)
        finally:
            await tr.rollback()


async def test_cleanup_removes_dryrun_project_but_keeps_national_events(tmp_path):
    """A dry-run project linked to a real procedure: the project and its links go; BZP-derived risk events that the
    link attached are detached (project_id NULL), never deleted."""
    async with raw_conn() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            proc = await conn.fetchval("SELECT procedure_id FROM risk_event WHERE procedure_id IS NOT NULL AND key NOT LIKE "
                                       "'doc:%' AND project_id IS NULL LIMIT 1")
            pid = await conn.fetchval("INSERT INTO project (rm_id, title, is_pilot, origin, review_status) VALUES "
                                      "('RM-DRY-2026-999', '[dryrun] test', false, 'SOURCE', 'auto') RETURNING id")
            await conn.execute("INSERT INTO project_procedure (project_id, procedure_id, method) VALUES ($1, $2, 'test')",
                               pid, proc)
            ev = await conn.fetch("UPDATE risk_event SET project_id = $1 WHERE procedure_id = $2 AND key NOT LIKE 'doc:%' "
                                  "RETURNING id", pid, proc)
            res = await demo_cleanup.run(conn, apply=True, actor="test", backup_dir=tmp_path)
            assert "RM-DRY-2026-999" in [p["rm_id"] for p in res["projects"]]
            assert res["deleted"]["project"] >= 1 and res["deleted"]["risk_event_detached"] >= len(ev)
            assert await conn.fetchval("SELECT count(*) FROM project WHERE id = $1", pid) == 0
            ids = [r["id"] for r in ev]
            assert await conn.fetchval("SELECT count(*) FROM risk_event WHERE id = ANY($1::bigint[]) AND project_id IS NULL",
                                       ids) == len(ids)
            assert await conn.fetchval("SELECT count(*) FROM project WHERE is_pilot") == 22
        finally:
            await tr.rollback()
