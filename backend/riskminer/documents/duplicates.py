"""Re-uploading a file that is already in the base (sha256 dedupe in documents/upload.py). Owner: S0.

A duplicate never errors and never gets stuck: the existing document row is reused (one document per file, so its facts,
proposals and review items are not duplicated) and the response says where its results are ("ten plik już był").

Per target of the new upload:
  * no project (Źródła, Nowa inwestycja): reuse; a scan whose OCR never ran is queued again (`imports/documents.start_chain`);
  * a project, and the document has none yet: attach it (`document.project_id`, audit `document.attach`) and run the
    linking for that project again (`document_link` when facts exist, else the chain from OCR or extraction);
  * a project, and the document already belongs to another one: it stays there (one `project_id`), an explicit link to the
    new project is recorded (`link_candidate` method `user_upload`, proposed, so the card lists it too) and a review item
    asks the expert which project it belongs to. Nothing is moved silently (CLAUDE.md invariant 10).
An analysis takes a document by id (`input_documents`), so the reused id is all Nowa inwestycja needs.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

LINK_METHOD = "user_upload"


async def _row(db: AsyncSession, sql: str, **p) -> dict | None:
    r = (await db.execute(text(sql), p)).mappings().first()
    return dict(r) if r else None


async def _enqueue(db: AsyncSession, kind: str, document_id: int, actor: str) -> int:
    from riskminer.imports.documents import _enqueue as enq
    return await enq(db, kind, document_id, actor)


async def previous(db: AsyncSession, document_id: int) -> dict[str, Any]:
    """What the earlier upload already produced: the linked project, facts, open review items."""
    d = await _row(db, """SELECT d.id, d.data, p.rm_id FROM document d LEFT JOIN project p ON p.id = d.project_id
                          WHERE d.id = :i""", i=document_id) or {}
    data = d.get("data") or {}
    link = data.get("link") or {}
    open_items = (await db.execute(text("SELECT count(*) FROM review_item WHERE key LIKE :k AND status = 'open'"),
                                   {"k": f"doc:{document_id}:%"})).scalar() or 0
    return {"project_rm_id": ((link.get("project") or {}).get("rm_id")) or d.get("rm_id"), "has_facts": bool(data.get("facts")),
            "linked": bool(link), "open_review_items": open_items}


async def handle(db: AsyncSession, out: dict, *, project_rm_id: str | None, actor: str, request_id: str | None) -> dict:
    """`out` is handle_upload's result with duplicate=True. Adds `jobs`, `attached` and `previous`. Caller commits."""
    from riskminer.imports.documents import start_chain
    did = out["document_id"]
    doc = await _row(db, "SELECT id, project_id, data FROM document WHERE id = :i", i=did) or {}
    target = await _row(db, "SELECT id, rm_id FROM project WHERE rm_id = :r", r=project_rm_id) if project_rm_id else None
    jobs: list[dict] = []
    attached = None
    if target is None:
        if out.get("text_status") == "needs_ocr":          # a scan that was never OCR-ed (job cancelled or never queued)
            jobs = await start_chain(db, out, actor)
    elif doc.get("project_id") in (None, target["id"]):
        if doc.get("project_id") is None:
            await db.execute(text("UPDATE document SET project_id = :p, updated_at = now() WHERE id = :d AND project_id IS NULL"),
                             {"p": target["id"], "d": did})
            await db.execute(text("""INSERT INTO audit_log (actor, action, table_name, row_id, before, after, request_id)
                                     VALUES (:a, 'document.attach', 'document', :d, CAST(:b AS jsonb), CAST(:af AS jsonb), :r)"""),
                             {"a": actor, "d": did, "b": json.dumps({"project_id": None}), "r": request_id,
                              "af": json.dumps({"project_id": target["id"], "project_rm_id": target["rm_id"], "via": "re-upload"})})
            attached = "attached"
            if (doc.get("data") or {}).get("facts"):       # facts are there: only the linking runs again, for this project
                jobs = [{"kind": "document_link", "job_id": await _enqueue(db, "document_link", did, actor)}]
        if not jobs:
            jobs = await start_chain(db, out, actor)       # never extracted (or failed): run the chain again
    else:
        bound = (await db.execute(text("SELECT rm_id FROM project WHERE id = :i"), {"i": doc["project_id"]})).scalar()
        await db.execute(text("""INSERT INTO link_candidate (left_table, left_id, right_table, right_id, right_ref, method, features,
                                                             score, rank, explanation, decision, review_status)
            VALUES ('document', :d, 'project', :p, :ref, :m, CAST(:f AS jsonb), 0.9, 1, :e, 'review', 'proposed')
            ON CONFLICT (left_table, left_id, right_table, right_ref, method) DO NOTHING"""),
            {"d": did, "p": target["id"], "ref": target["rm_id"], "m": LINK_METHOD, "f": json.dumps({"upload_bound": 1.0}),
             "e": f"Ten sam plik wgrano do projektu {target['rm_id']}; dokument jest przy projekcie {bound}."})
        await db.execute(text("""INSERT INTO review_item (kind, code, project_id, title, question, detail, severity, key, created_by)
            VALUES ('discrepancy', 'document_uploaded_twice', :p, :t, :q, CAST(:dt AS jsonb), 'medium', :k, 'system:upload')
            ON CONFLICT (key) DO NOTHING"""),
            {"p": target["id"], "k": f"doc:{did}:also:{target['rm_id']}",
             "t": f"Ten sam dokument wgrano do projektu {target['rm_id']}, a jest już przy projekcie {bound}",
             "q": f"Do którego projektu należy dokument „{out.get('filename')}”: {bound} czy {target['rm_id']}?",
             "dt": json.dumps({"sub": "Plik o tej samej sumie SHA-256 był już wczytany. Niczego nie przenosimy samodzielnie.",
                               "document_id": did, "bound": bound, "uploaded_to": target["rm_id"]}, ensure_ascii=False)})
        attached = "also_linked"
        jobs = await start_chain(db, out, actor)
    out["jobs"] = (out.get("jobs") or []) + jobs
    out["attached"] = attached
    out["previous"] = await previous(db, did)
    return out
