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
Every deleted row is first written as JSON lines to data/snapshots/demo_cleanup_<ts>.jsonl (manual restore possible).
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
    ("analysis", "id = ANY($1::bigint[])", "an"),
    ("document", "id = ANY($1::bigint[])", "doc"),
]


async def find(conn, *, include_raw_named: bool = False) -> dict[str, Any]:
    hashes = case_hashes()
    docs = await conn.fetch("""
        SELECT d.id, d.filename, d.sha256, d.project_id, d.created_at, d.data->>'uploaded_by' AS uploaded_by
        FROM document d JOIN source s ON s.id = d.source_id WHERE s.kind = 'upload' ORDER BY d.id""")
    picked, skipped = [], []
    for d in docs:
        fn = d["filename"] or ""
        reason = ("e2e_name" if fn.startswith("[e2e]") else "organizer_case" if d["sha256"] in hashes else
                  "raw_store_name" if len(fn) > 17 and fn[16] == "_" and all(c in "0123456789abcdef" for c in fn[:16])
                  else None)
        row = {"id": d["id"], "filename": fn, "reason": reason, "uploaded_by": d["uploaded_by"],
               "created_at": d["created_at"].isoformat() if d["created_at"] else None}
        if reason in ("e2e_name", "organizer_case") or (reason == "raw_store_name" and include_raw_named):
            picked.append(row)
        else:
            skipped.append(row)
    analyses = [dict(r) for r in await conn.fetch(
        "SELECT id, code, title FROM analysis WHERE title LIKE '[e2e]%' ORDER BY id")]
    return {"documents": picked, "documents_kept": skipped, "analyses": analyses}


async def run(conn, *, apply: bool = False, include_raw_named: bool = False, actor: str = "system:demo-cleanup",
              backup_dir: Path | None = None) -> dict:
    sel = await find(conn, include_raw_named=include_raw_named)
    doc_ids = [d["id"] for d in sel["documents"]]
    an_ids = [a["id"] for a in sel["analyses"]]
    counts: dict[str, int] = {}
    backup_rows: list[dict] = []
    for table, where, which in _ROWS:
        ids = doc_ids if which == "doc" else an_ids
        rows = await conn.fetch(f"SELECT to_jsonb(t) AS j FROM {table} t WHERE {where}", ids) if ids else []
        counts[table] = len(rows)
        backup_rows += [{"table": table, "row": r["j"]} for r in rows]
    out = {"apply": apply, "documents": sel["documents"], "documents_kept": sel["documents_kept"],
           "analyses": sel["analyses"], "rows": counts}
    if not apply or not backup_rows:
        return out
    snap = backup_dir or Path(settings().data_dir) / "snapshots"
    snap.mkdir(parents=True, exist_ok=True)
    bfile = snap / f"demo_cleanup_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    with bfile.open("w", encoding="utf-8") as fh:
        for b in backup_rows:
            fh.write(json.dumps(b, ensure_ascii=False, default=str) + "\n")
    async with conn.transaction():
        await conn.execute("SET LOCAL riskminer.expert_write = 'on'")     # operator cleanup: approved rows too
        deleted = {}
        for table, where, which in _ROWS:
            ids = doc_ids if which == "doc" else an_ids
            r = await conn.execute(f"DELETE FROM {table} WHERE {where}", ids) if ids else "DELETE 0"
            deleted[table] = int(r.split()[-1])
        await conn.execute("""INSERT INTO audit_log (actor, action, table_name, row_id, after)
                              VALUES ($1, 'demo.cleanup', 'document', NULL, $2)""", actor,
                           {"deleted": deleted, "documents": sel["documents"], "analyses": sel["analyses"],
                            "backup": str(bfile.relative_to(REPO_ROOT)) if bfile.is_relative_to(REPO_ROOT) else str(bfile),
                            "rule": "e2e/test artefacts removed before the demo snapshot; raw files and sources kept"})
    out.update(deleted=deleted, backup=str(bfile))
    return out
