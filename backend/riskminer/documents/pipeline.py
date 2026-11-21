"""New-document pipeline (docs/impl/new_documents.md §2): upload → OCR → facts → linking → re-analysis. Owner: S0 (orchestration).

Each step is owned by another session and plugged in by import path (STEPS). A step is

    async def step(db: AsyncSession, document_id: int, *, actor: str, request_id: str | None) -> dict

It writes only through `db` (never raw_conn, never commit), so the whole pipeline runs in one transaction: the job
`document_process` (a one-shot rerun) commits at the end, and tests (G6, tests/api/test_new_documents.py) run it in a
rolled-back transaction. Uploads use the job chain instead (see api/routers/documents.py).
Its dict result is stored per step in the job result (counts, ids, `skipped: reason`). A step that is not implemented yet
(module or function missing) is reported as {"pending": true} and the pipeline continues with the next one.

All records a step writes are proposals (origin AI or CALC, review_status proposed/auto) with evidence (document, page, quote);
discrepancies become review_item rows; nothing approved is overwritten (CLAUDE.md invariants 1, 2, 10).
"""
from __future__ import annotations

import importlib
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("riskminer.documents.pipeline")

# (step key, "module:function", owner, what it does). Production runs the same steps as a job chain
# (upload -> document_ocr (D) -> document_extract (L) -> document_link (B)); this module runs them on one session.
STEPS: list[tuple[str, str, str, str]] = [
    ("ocr", "riskminer.documents.pipeline:ocr_step", "S0 over D's ocr_doc.ocr_pdf",
     "scans (data.text_status needs_ocr): Tesseract pol via D's ocr_pdf, document_page rows with ocr=true + confidence, chunks"),
    ("facts", "riskminer.llm.tasks.document_facts:extract_document", "L",
     "rules + LLM (sensitivity routing): document.data.facts (kind, level, change, causes with quotes, flags)"),
    ("link", "riskminer.review.doclink:link_document", "B",
     "identifiers -> project/contract (score, features), checksum checks, proposals with evidence, discrepancy review_items"),
]


async def ocr_step(db: AsyncSession, document_id: int, *, actor: str, request_id: str | None = None) -> dict:
    """Session-based OCR for the pipeline (the standalone job is D's riskminer/ingest/ocr_doc.py: same Tesseract call)."""
    import asyncio
    import hashlib
    import json

    from sqlalchemy import text

    from riskminer.documents import upload as U
    from riskminer.ingest.doctext import resolve
    from riskminer.ingest.ocr_doc import ocr_pdf
    d = (await db.execute(text("SELECT id, path, mime, sha256, data FROM document WHERE id = :i"), {"i": document_id})).mappings().first()
    if d is None:
        return {"skipped": "no such document"}
    data = dict(d["data"] or {})
    if data.get("text_status") != "needs_ocr":
        return {"skipped": f"text_status {data.get('text_status')!r}"}
    src = resolve(d["path"])
    if src is None or not src.exists() or not (d["mime"] or "").endswith("pdf"):
        return {"skipped": "no PDF file to OCR"}
    res = await asyncio.to_thread(ocr_pdf, src)
    pages, confs = res["pages"], res["confs"]
    if not sum(len(p) for p in pages):
        return {"pages": len(pages), "chars": 0, "errors": res["errors"]}
    body = ("\f".join(p.strip() for p in pages) + "\n").encode("utf-8")
    tp = U.raw_dir() / f"{d['sha256'] or document_id}.ocr.txt"
    tp.write_bytes(body)
    U.append_manifest({"source": U.SOURCE_KIND, "fetched_at": U._utc(), "method": "tesseract", "url": f"upload:{d['sha256']}#ocr",
                       "params": {}, "http_status": None, "content_type": "text/plain; charset=utf-8", "bytes": len(body),
                       "sha256": hashlib.sha256(body).hexdigest(), "path": U.rel(tp), "licence": "derived (OCR)", "run_id": None,
                       "status": "ok", "note": f"OCR tesseract pol ({res['runtime']}) of {d['sha256']}", "key": f"{d['sha256']}#ocr"})
    await db.execute(text("DELETE FROM chunk WHERE document_id = :i"), {"i": document_id})
    await db.execute(text("DELETE FROM document_page WHERE document_id = :i"), {"i": document_id})
    await db.execute(text("INSERT INTO document_page (document_id, page_no, text, ocr, ocr_confidence) VALUES (:d, :n, :t, true, :c)"),
                     [{"d": document_id, "n": i, "t": t, "c": c} for i, (t, c) in enumerate(zip(pages, confs), 1)])
    n_chunks = 0
    from riskminer.ingest.doctext import chunk_spans
    rows = [{"d": document_id, "n": i, "a": a, "b": b, "t": t[a:b]} for i, t in enumerate(pages, 1) for a, b in chunk_spans(t)]
    if rows:
        await db.execute(text("INSERT INTO chunk (document_id, page_no, char_start, char_end, text, tsv) "
                              "VALUES (:d, :n, :a, :b, :t, to_tsvector('simple', unaccent(:t)))"), rows)
        n_chunks = len(rows)
    known = [c for c in confs if c is not None]
    data.update(text_status="ok", text_method="tesseract", needs_ocr=False, ocr_confidence=confs, ocr_text_path=U.rel(tp))
    await db.execute(text("UPDATE document SET ocr = true, pages = :p, data = CAST(:data AS jsonb), updated_at = now() WHERE id = :i"),
                     {"i": document_id, "p": len(pages), "data": json.dumps(data, ensure_ascii=False)})
    await db.execute(text("INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id) "
                          "VALUES (:a, 'document.ocr', 'document', :i, CAST(:after AS jsonb), :r)"),
                     {"a": actor, "i": document_id, "r": request_id,
                      "after": json.dumps({"pages": len(pages), "chunks": n_chunks, "runtime": res["runtime"]})})
    return {"pages": len(pages), "chars": sum(len(p) for p in pages), "chunks": n_chunks,
            "mean_conf": round(sum(known) / len(known), 4) if known else None, "runtime": res["runtime"]}


def _resolve(target: str):
    mod, _, fn = target.partition(":")
    try:
        m = importlib.import_module(mod)
    except ModuleNotFoundError as e:
        if e.name and mod.startswith(e.name):
            return None
        raise
    return getattr(m, fn, None)


def missing_steps() -> list[str]:
    return [f"{key} ({owner}: {target})" for key, target, owner, _ in STEPS if _resolve(target) is None]


async def process_document(db: AsyncSession, document_id: int, *, actor: str = "system:pipeline",
                           request_id: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"document_id": document_id, "steps": {}}
    for key, target, owner, _ in STEPS:
        fn = _resolve(target)
        if fn is None:
            out["steps"][key] = {"pending": True, "owner": owner}
            continue
        t0 = time.monotonic()
        res = await fn(db, document_id, actor=actor, request_id=request_id)
        out["steps"][key] = {**(res or {}), "ms": int((time.monotonic() - t0) * 1000)}
    return out
