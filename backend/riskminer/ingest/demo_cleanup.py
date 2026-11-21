"""Remove e2e / test artefacts from the main DB before the demo snapshot (lead's request, freeze 07:00).

Why: the jury's own upload of an organizer case file must be the first real one. A leftover test upload of the same
file would make the jury's upload a sha256 duplicate and the review queue would already hold its proposals.

What counts as an artefact (dry run lists every row with its reason; nothing is guessed silently):
  documents (source kind 'upload') whose filename starts with "[e2e]", or whose sha256 equals one of the organizer
  case files in materials/organizer_cases/ (uploaded by e2e specs). With include_raw_named=True also uploads whose
  filename starts with a 16-hex raw-store prefix ("9cdc085eedd413b1_PFU_Kaniów.pdf": copied from data/raw by a script).
  analyses whose title starts with "[e2e]" (+ items, versions, signals by cascade).
  For those documents: pages, chunks, evidence, proposed contract changes, risk events (key doc:<id>:...), link
  candidates, review items, alerts, jobs; risk_signal / document_page / chunk go by FK cascade.
Kept: raw bytes and the `source` row (provenance; a re-upload reuses the source and creates a fresh document),
audit_log (append-only; one `demo.cleanup` row records the counts and the backup file), `review` decision rows.
Rows an expert approved or edited are kept by the rm_protect_approved trigger (this module never overrides it) and
reported as kept_protected. Every deleted row is first written as JSON lines to data/snapshots/demo_cleanup_<ts>.jsonl (manual restore possible).
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from riskminer.config import REPO_ROOT, settings

CASES_DIR = REPO_ROOT / "materials" / "organizer_cases"


def case_hashes() -> dict[str, str]:
    if not CASES_DIR.exists():
        return {}
    return {hashlib.sha256(p.read_bytes()).hexdigest(): p.name for p in sorted(CASES_DIR.iterdir()) if p.is_file()}


# (table, WHERE with $1 = the id list named in the third field); delete order respects FKs (children first)
_DOC_RE = "('^doc:(' || array_to_string($1::bigint[], '|') || '):')"
_ROWS: list[tuple[str, str, str]] = [
    ("alert", "document_id = ANY($1::bigint[])", "doc"),
    ("review_item", (f"key ~ {_DOC_RE} OR (target_table = 'document' AND target_id = ANY($1::bigint[])) "
                     "OR (detail->>'document_id') = ANY($1::bigint[]::text[])"), "doc"),
    ("evidence", (f"document_id = ANY($1::bigint[]) OR (claim_table = 'risk_event' AND claim_id IN "
                  f"(SELECT id FROM risk_event WHERE key ~ {_DOC_RE}))"), "doc"),
    ("risk_event", f"key ~ {_DOC_RE}", "doc"),
    ("contract_change", "document_id = ANY($1::bigint[])", "doc"),
    ("link_candidate", "left_table = 'document' AND left_id = ANY($1::bigint[])", "doc"),
    ("job", "(payload->>'document_id') = ANY($1::bigint[]::text[])", "doc"),
    ("job", "(payload->>'analysis_code') = ANY($1::text[])", "an_code"),
    ("analysis", "id = ANY($1::bigint[])", "an"),
    ("document", "id = ANY($1::bigint[])", "doc"),
    # dry-run projects: their own link rows and review items; national risk events are DETACHED first (see run)
    ("link_candidate", "left_table = 'project' AND left_id = ANY($1::bigint[])", "proj"),
    ("review_item", "project_id = ANY($1::bigint[])", "proj"),
    ("project_procedure", "project_id = ANY($1::bigint[])", "proj"),
    ("project", "id = ANY($1::bigint[]) AND NOT is_pilot", "proj"),
    # rehearsal imports named in dryrun_ids.md: sessions, then importers no remaining session uses, then their jobs
    ("import_session", "code = ANY($1::text[])", "imp"),
    ("importer", "id = ANY($1::bigint[]) AND NOT EXISTS (SELECT 1 FROM import_session s WHERE s.importer_id = importer.id)",
     "importer"),
    ("job", "id = ANY($1::bigint[])", "job"),
]


DRYRUN_IDS = REPO_ROOT / "docs" / "submission" / "dryrun_ids.md"


def dryrun_listed() -> dict[str, list]:
    """Ids the live-test rehearsal wrote down (docs/submission/dryrun_ids.md): RM-DRY-... projects, AN-... analyses,
    document ids ("document 34001", "document_id: 34001"). Absent file: nothing listed."""
    import re
    if not DRYRUN_IDS.exists():
        return {"projects": [], "analyses": [], "documents": []}
    t = DRYRUN_IDS.read_text(encoding="utf-8")
    return {"projects": sorted(set(re.findall(r"\bRM-DRY-\d{4}-\d{3}\b", t))),
            "analyses": sorted(set(re.findall(r"\bAN-\d{4}-\d{4}\b", t))),
            "documents": sorted({int(x) for x in re.findall(r"\bdoc(?:ument)?(?:_id)?[\s:=#]*(\d{3,})", t, re.IGNORECASE)})}


async def find(conn, *, include_raw_named: bool = False, anon_analyses_since: str | None = None,
               analysis_codes: list[str] | None = None, include_approved: bool = False) -> dict[str, Any]:
    listed = dryrun_listed()
    hashes = case_hashes()
    docs = await conn.fetch("""
        SELECT d.id, d.filename, d.sha256, d.project_id, d.created_at, d.data->>'uploaded_by' AS uploaded_by
        FROM document d JOIN source s ON s.id = d.source_id WHERE s.kind = 'upload' ORDER BY d.id""")
    picked, skipped = [], []
    for d in docs:
        fn = d["filename"] or ""
        reason = ("e2e_name" if fn.startswith("[e2e]") else "dryrun" if fn.startswith("[dryrun]")
                  or d["id"] in listed["documents"] else "organizer_case" if d["sha256"] in hashes else
                  "raw_store_name" if len(fn) > 17 and fn[16] == "_" and all(c in "0123456789abcdef" for c in fn[:16])
                  else None)
        row = {"id": d["id"], "filename": fn, "reason": reason, "uploaded_by": d["uploaded_by"],
               "created_at": d["created_at"].isoformat() if d["created_at"] else None}
        if reason in ("e2e_name", "dryrun", "organizer_case") or (reason == "raw_store_name" and include_raw_named):
            picked.append(row)
        else:
            skipped.append(row)
    # "[e2e]" titles always; with anon_analyses_since also analyses created by anonymous visitors since that time
    # (tooling: e2e specs, deck screenshots, headless checks), judged by the current owner, so analyses handed
    # to a demo demo user (owner user:Ekspert (demo)) stay. Seeded system:* analyses are never selected.
    analyses = [dict(r) for r in await conn.fetch("""
        SELECT id, code, title, created_by,
               CASE WHEN title LIKE '[e2e]%' THEN 'e2e_title' WHEN title LIKE '[dryrun]%' THEN 'dryrun_title'
                    WHEN code = ANY($2::text[]) THEN 'named' ELSE 'anonymous_tooling' END AS reason
        FROM analysis WHERE title LIKE '[e2e]%' OR title LIKE '[dryrun]%'
           OR ($1::timestamptz IS NOT NULL AND owner LIKE 'anon:%' AND created_at >= $1::timestamptz)
           OR code = ANY($2::text[])
        ORDER BY id""", anon_analyses_since, list(analysis_codes or []) + listed["analyses"])]
    # analyses holding expert-approved/edited items are protected (rm_protect_approved): only an expert undo in
    # Przegląd may change those approvals, so they are reported, never removed here
    approved = {r["analysis_id"] for r in await conn.fetch(
        "SELECT DISTINCT analysis_id FROM analysis_item WHERE analysis_id = ANY($1::bigint[]) "
        "AND review_status IN ('approved', 'edited')", [a["id"] for a in analyses])} if analyses else set()
    protected = [a for a in analyses if a["id"] in approved]
    if not include_approved:
        analyses = [a for a in analyses if a["id"] not in approved]
    # dry-run projects (never a pilot): RM-DRY-... ids, "[dryrun]" titles, or listed in dryrun_ids.md
    projects = [dict(r) for r in await conn.fetch("""
        SELECT id, rm_id, title FROM project
        WHERE NOT is_pilot AND (rm_id LIKE 'RM-DRY-%' OR title LIKE '[dryrun]%' OR rm_id = ANY($1::text[]))
        ORDER BY id""", listed["projects"])]
    return {"documents": picked, "documents_kept": skipped, "analyses": analyses, "analyses_protected": protected,
            "projects": projects, "listed_file": DRYRUN_IDS.exists()}


async def run(conn, *, apply: bool = False, include_raw_named: bool = False, actor: str = "system:demo-cleanup",
              backup_dir: Path | None = None, anon_analyses_since: str | None = None,
              analysis_codes: list[str] | None = None, document_ids: list[int] | None = None,
              import_sessions: list[str] | None = None, importer_ids: list[int] | None = None,
              job_ids: list[int] | None = None, include_approved: bool = False) -> dict:
    from datetime import datetime as _dt
    since = _dt.fromisoformat(anon_analyses_since) if anon_analyses_since else None
    sel = await find(conn, include_raw_named=include_raw_named, anon_analyses_since=since, analysis_codes=analysis_codes,
                     include_approved=include_approved)
    extra_docs = [dict(r) for r in await conn.fetch(
        "SELECT id, filename, data->>'uploaded_by' AS uploaded_by FROM document WHERE id = ANY($1::bigint[])",
        list(document_ids or []))] if document_ids else []
    sel["documents"] += [{"id": d["id"], "filename": d["filename"], "reason": "named", "uploaded_by": d["uploaded_by"]}
                         for d in extra_docs if d["id"] not in {x["id"] for x in sel["documents"]}]
    doc_ids = [d["id"] for d in sel["documents"]]
    an_ids = [a["id"] for a in sel["analyses"]]
    an_codes = [a["code"] for a in sel["analyses"]]
    proj_ids = [p["id"] for p in sel["projects"]]
    pick = {"doc": doc_ids, "an": an_ids, "an_code": an_codes, "proj": proj_ids,
            "imp": list(import_sessions or []), "importer": list(importer_ids or []), "job": list(job_ids or [])}
    counts: dict[str, int] = {}
    backup_rows: list[dict] = []
    for table, where, which in _ROWS:
        ids = pick[which]
        rows = await conn.fetch(f"SELECT to_jsonb({table}) AS j FROM {table} WHERE {where}", ids) if ids else []
        counts[table] = counts.get(table, 0) + len(rows)
        backup_rows += [{"table": table, "row": r["j"]} for r in rows]
    # national risk events (BZP-derived) that a dry-run project's link attached: detached, never deleted
    detach = [dict(r) for r in await conn.fetch(
        "SELECT id, project_id FROM risk_event WHERE project_id = ANY($1::bigint[]) AND key NOT LIKE 'doc:%'",
        proj_ids)] if proj_ids else []
    counts["risk_event_detached"] = len(detach)
    backup_rows += [{"table": "risk_event.project_id", "row": d} for d in detach]
    out = {"apply": apply, "documents": sel["documents"], "documents_kept": sel["documents_kept"],
           "analyses": sel["analyses"], "analyses_protected": sel["analyses_protected"], "projects": sel["projects"],
           "listed_file": sel["listed_file"], "rows": counts}
    if not apply or not backup_rows:
        return out
    snap = backup_dir or Path(settings().data_dir) / "snapshots"
    snap.mkdir(parents=True, exist_ok=True)
    bfile = snap / f"demo_cleanup_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    with bfile.open("w", encoding="utf-8") as fh:
        for b in backup_rows:
            fh.write(json.dumps(b, ensure_ascii=False, default=str) + "\n")
    async with conn.transaction():
        deleted = {}
        if detach:
            r = await conn.execute("UPDATE risk_event SET project_id = NULL WHERE id = ANY($1::bigint[])",
                                   [d["id"] for d in detach])
            deleted["risk_event_detached"] = int(r.split()[-1])
        approved_removed = [a["code"] for a in sel["analyses_protected"]] if include_approved else []

        async def _delete_all():
            for table, where, which in _ROWS:
                ids = pick[which]
                r = await conn.execute(f"DELETE FROM {table} WHERE {where}", ids) if ids else "DELETE 0"
                deleted[table] = deleted.get(table, 0) + int(r.split()[-1])

        if approved_removed:
            # the user explicitly asked to remove test analyses that carry (auto-)approved items: lifted only through
            # the review package, and every such analysis is named in the audit row below
            from riskminer.review.common import operator_cleanup_writes
            async with operator_cleanup_writes(conn):
                await _delete_all()
        else:
            await _delete_all()
        # rm_protect_approved keeps approved/edited rows (only the review package may override it): report, never force
        kept = {}
        for table, where, which in _ROWS:
            ids = pick[which]
            n = await conn.fetchval(f"SELECT count(*) FROM {table} WHERE {where}", ids) if ids else 0
            if n:
                kept[table] = kept.get(table, 0) + n
        await conn.execute("""INSERT INTO audit_log (actor, action, table_name, row_id, after)
                              VALUES ($1, 'demo.cleanup', 'document', NULL, $2)""", actor,
                           {"deleted": deleted, "kept_protected": kept, "approved_removed": approved_removed,
                            "documents": sel["documents"],
                            "analyses": sel["analyses"], "projects": sel["projects"],
                            "backup": str(bfile.relative_to(REPO_ROOT)) if bfile.is_relative_to(REPO_ROOT) else str(bfile),
                            "rule": "e2e/test artefacts removed before the demo snapshot; raw files and sources kept"})
    out.update(deleted=deleted, kept_protected=kept, backup=str(bfile))
    return out
