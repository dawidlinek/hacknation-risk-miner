"""Import agent -> document pipeline (docs/impl/new_documents.md §2). Owner: S0.

A file dropped on the Import screen (`/zrodla`) that the agent did not recognise as a dataset or a project record (inspect
did not mark it `tabular`) is a case document: a protocol, an annex, a letter, a scan. Such files are handed over to the
same pipeline as the project card's Dokumenty drop zone, with no project bound, so the project is found from the document
itself (KPO number, NIP, buyer and task title, contract number and date: `review/doclink.py`).

Per file: `documents/upload.handle_upload` (raw bytes in data/raw/upload/ with a manifest line, `source` row, pages,
chunks; sensitivity `public`, so the LLM pass may run), then the job chain in the SAME transaction as the document row:
scan -> `document_ocr` -> `document_extract` -> `document_link`; text layer -> `document_extract` -> `document_link`.
A re-dropped file (sha256 dedupe) reuses its document and only queues the chain again when nothing was ever extracted.
Everything the chain writes is a proposal or a review item (invariants 1, 2, 10). The routing is recorded in the import
session (tool call + `answers._documents`) and in the audit log.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import app_config
from riskminer.documents import upload as U

NOT_DOCUMENTS = {"xlsx", "csv", "zip"}      # datasets and archives stay with the import agent
SENSITIVITY = "public"                       # execution-phase case documents (new_documents.md §4)
CHAIN = ("document_ocr", "document_extract", "document_link")


def is_document(f: dict) -> bool:
    """A session file that goes to the document pipeline: not a table/record found by inspect, a type the upload takes."""
    return not f.get("tabular") and f.get("kind") not in NOT_DOCUMENTS and Path(f.get("name") or "").suffix.lower() in U.ALLOWED


def _max_bytes() -> int:
    return int((app_config().get("api") or {}).get("upload_max_mb", 50)) * 1024 * 1024


async def _enqueue(db: AsyncSession, kind: str, document_id: int, actor: str) -> int:
    """Job row in the caller's transaction: the worker sees it only together with the document row."""
    jid = (await db.execute(text("INSERT INTO job (kind, payload, priority, created_by) VALUES (:k, CAST(:p AS jsonb), 50, :by) "
                                 "RETURNING id"), {"k": kind, "p": json.dumps({"document_id": document_id}), "by": actor})).scalar_one()
    await db.execute(text("SELECT pg_notify('riskminer_jobs', :id)"), {"id": str(jid)})
    return jid


async def _chain_started(db: AsyncSession, document_id: int) -> bool:
    n = (await db.execute(text("SELECT count(*) FROM job WHERE payload->>'document_id' = :d AND kind = ANY(:k) "
                               "AND status IN ('queued', 'running', 'done')"), {"d": str(document_id), "k": list(CHAIN)})).scalar()
    return bool(n)


async def start_chain(db: AsyncSession, out: dict, actor: str) -> list[dict]:
    """Queue OCR or extraction for an uploaded document (also a re-upload that was never extracted). -> [{kind, job_id}]."""
    did = out["document_id"]
    if out.get("duplicate"):
        data = (await db.execute(text("SELECT data FROM document WHERE id = :d"), {"d": did})).scalar() or {}
        if data.get("facts") or await _chain_started(db, did):
            return []
    if out.get("text_status") == "needs_ocr":
        return [{"kind": "document_ocr", "job_id": await _enqueue(db, "document_ocr", did, actor)}]
    if out.get("text_status") == "ok":
        return [{"kind": "document_extract", "job_id": await _enqueue(db, "document_extract", did, actor)}]
    return []


async def route(db: AsyncSession, code: str, *, actor: str, anon_id: str, user_actor: str | None,
                request_id: str | None) -> dict | None:
    """Hand the session's non-tabular document files to the document pipeline. Caller commits. None = no such import."""
    from riskminer.imports import service as S
    s = await S._load(db, code)
    if not s:
        return None
    if not s["tool_calls"]:
        return {"error": "Najpierw uruchom przegląd plików (inspect)."}
    answers = dict(s["answers"] or {})
    done = {d["name"]: d for d in answers.get("_documents") or [] if d.get("document_id")}
    docs, calls = [], list(s["tool_calls"])
    for f in s["files"]:
        if not is_document(f):
            continue
        if f["name"] in done:                       # the agent already routed this file: idempotent
            docs.append(done[f["name"]])
            continue
        row: dict[str, Any] = {"name": f["name"], "document_id": None, "duplicate": False, "text_status": None, "jobs": [],
                               "error": None}
        try:
            content = Path(f["path"]).read_bytes()
            out = await U.handle_upload(db, filename=f["name"], content=content, sensitivity=SENSITIVITY, actor=actor,
                                        anon_id=anon_id, user_actor=user_actor, analysis_code=None, project_rm_id=None,
                                        max_bytes=_max_bytes(), request_id=request_id)
            jobs = await start_chain(db, out, actor)
            row.update(document_id=out["document_id"], duplicate=out["duplicate"], text_status=out["text_status"], jobs=jobs,
                       pages=out.get("pages"))
            if out["duplicate"]:
                from riskminer.documents.duplicates import previous
                row["previous"] = await previous(db, out["document_id"])
            what = "skan, najpierw OCR" if out["text_status"] == "needs_ocr" else "warstwa tekstu"
            res = f"dokument #{out['document_id']} ({what}), {'był już wczytany' if out['duplicate'] else 'przekazany do analizy'}"
        except U.UploadError as e:
            row["error"] = e.detail
            res = f"błąd: {e.detail}"
        except OSError as e:
            row["error"] = "Nie udało się odczytać pliku z piaskownicy."
            res = f"błąd: {type(e).__name__}"
        calls.append({"call": f'route_document("{f["name"]}")', "out": res, "ms": 0, "llm": False,
                      "data": {k: row[k] for k in ("document_id", "duplicate", "text_status", "error")}})
        docs.append(row)
    tables = sum(1 for f in s["files"] if f.get("tabular") or f.get("kind") in ("xlsx", "csv"))
    answers["_documents"] = docs
    await S._save(db, code, tool_calls=calls, answers=answers)
    await S._audit(db, actor, "import.route_documents", s["id"],
                   {"documents": [{k: d.get(k) for k in ("name", "document_id", "duplicate", "error")} for d in docs]}, request_id)
    return {"code": code, "documents": docs, "tables": tables}
