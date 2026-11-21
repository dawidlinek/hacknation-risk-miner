"""OCR of one document on demand (docs/impl/new_documents.md G1): job `document_ocr`.

When an upload is a scan (`data.text_status = 'needs_ocr'`), the upload path enqueues this job (`enqueue(db, id)`),
so the request returns at once. The job:
  1. renders each PDF page in-process (pypdfium2, 300 dpi, grayscale, capped at 24 Mpx like the WCSS batch);
  2. runs Tesseract `pol` (--psm 1, TSV output -> text by line + mean word confidence per page). Runtime: the
     `tesseract` binary on PATH (production image: infra/Dockerfile.backend), else, on a dev host without it,
     `docker run --rm -i --network none riskminer-ocr:local tesseract ...` (infra/Dockerfile.ocr). Local only, so it
     is allowed for confidential documents too;
  3. stores the text as a DERIVED file next to the raw data (data/raw/<source>/<date>/ocr/<sha16>.ocr.txt) with a
     manifest line (method tesseract, confidence), and sets document.ocr, data.ocr_text_path, data.ocr_confidence
     (per page), data.ocr_low_confidence (< 0.6: evidence state NIECZYTELNY), text_status 'ok';
  4. rebuilds the document's pages and chunks with ingest/doctext.py (pages with ocr = true + confidence), so search
     and quotes work;
  5. enqueues session L's `document_extract` (fact extraction) when that job kind is registered.
Nothing about the original bytes changes; re-running replaces the derived text.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import os
import shutil
import subprocess
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.connectors.base import RawStore, request_key, sha256_bytes
from riskminer.db.session import raw_conn
from riskminer.ingest import doctext

log = logging.getLogger("riskminer.ocr_doc")

LANG = "pol"
DPI = 300
MAX_PIXELS = 24_000_000
LOW_CONF = 0.6
PAGE_TIMEOUT = 300
DEFAULT_IMAGE = "riskminer-ocr:local"


class OcrUnavailable(RuntimeError):
    pass


def runtime() -> list[str]:
    """Command prefix that runs tesseract: env RISKMINER_TESSERACT, PATH, or the docker fallback image."""
    cmd = os.environ.get("RISKMINER_TESSERACT") or shutil.which("tesseract")
    if cmd:
        return [cmd]
    if shutil.which("docker"):
        image = os.environ.get("RISKMINER_OCR_IMAGE", DEFAULT_IMAGE)
        return ["docker", "run", "--rm", "-i", "--network", "none", "-e", "OMP_THREAD_LIMIT=2", image, "tesseract"]
    raise OcrUnavailable("brak programu tesseract (ani obrazu Docker z OCR) na tym serwerze")


def render_pages(pdf_path: Path) -> list[bytes]:
    """Each page as a binary PGM (grayscale), which Tesseract/Leptonica reads from stdin."""
    import numpy as np
    import pypdfium2 as pdfium

    out = []
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            w_pt, h_pt = page.get_size()
            scale = DPI / 72
            if w_pt * h_pt * scale * scale > MAX_PIXELS:
                scale = math.sqrt(MAX_PIXELS / max(1.0, w_pt * h_pt))
            bmp = page.render(scale=scale, grayscale=True)
            arr = bmp.to_numpy()
            if arr.ndim == 3:
                arr = arr[:, :, 0]
            arr = np.ascontiguousarray(arr, dtype=np.uint8)
            h, w = arr.shape
            out.append(b"P5\n%d %d\n255\n" % (w, h) + arr.tobytes())
            page.close()
    finally:
        pdf.close()
    return out


def tsv_to_text(tsv: str) -> tuple[str, float | None]:
    """Tesseract TSV -> (text with one line per OCR line, blank line between paragraphs; mean word confidence 0..1)."""
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    confs: list[float] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
        try:
            c = float(row.get("conf") or -1)
        except ValueError:
            c = -1
        if c >= 0:
            confs.append(c)
    parts, prev = [], None
    for key in order:
        if prev is not None and key[:2] != prev[:2]:
            parts.append("")
        parts.append(" ".join(lines[key]))
        prev = key
    return "\n".join(parts), (round(sum(confs) / len(confs) / 100.0, 4) if confs else None)


def ocr_page(image: bytes, cmd: list[str]) -> tuple[str, float | None]:
    env = {**os.environ, "OMP_THREAD_LIMIT": "2"}
    r = subprocess.run([*cmd, "stdin", "stdout", "-l", LANG, "--psm", "1", "tsv"], input=image, capture_output=True,
                       timeout=PAGE_TIMEOUT, env=env, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"tesseract exit {r.returncode}: {r.stderr.decode('utf-8', 'replace')[-300:]}")
    return tsv_to_text(r.stdout.decode("utf-8", "replace"))


def ocr_pdf(pdf_path: Path) -> dict[str, Any]:
    cmd = runtime()
    pages, confs, errors = [], [], []
    for i, img in enumerate(render_pages(pdf_path), 1):
        try:
            t, c = ocr_page(img, cmd)
        except Exception as e:  # noqa: BLE001 - recorded per page
            t, c = "", None
            errors.append(f"p{i}: {type(e).__name__}: {e}"[:300])
        pages.append(t)
        confs.append(c)
    return {"pages": pages, "confs": confs, "errors": errors, "runtime": "local" if len(cmd) == 1 else "docker"}


async def enqueue(db: AsyncSession, document_id: int, created_by: str = "system:upload", priority: int = 50) -> dict:
    """Queue `document_ocr` in the caller's transaction (the job only becomes visible with the document row)."""
    jid = (await db.execute(text("INSERT INTO job (kind, payload, priority, created_by) "
                                 "VALUES ('document_ocr', CAST(:p AS jsonb), :pr, :by) RETURNING id"),
                            {"p": json.dumps({"document_id": document_id}), "pr": priority, "by": created_by})).scalar_one()
    await db.execute(text("SELECT pg_notify('riskminer_jobs', :id)"), {"id": str(jid)})
    return {"id": jid, "kind": "document_ocr"}


@asynccontextmanager
async def _use(conn):
    if conn is not None:
        yield conn
    else:
        async with raw_conn() as c:
            yield c


async def ocr_document(document_id: int, *, job_id: int | None = None, actor: str = "system:ocr", extract: bool = True,
                       conn=None, raw_root: Path | None = None) -> dict[str, Any]:
    """`conn` (asyncpg, codecs set) and `raw_root` are injectable for tests; by default each step opens its own connection."""
    async with _use(conn) as c:
        d = await c.fetchrow("""SELECT d.id, d.path, d.mime, d.sha256, d.data, d.source_id, s.kind AS source_kind
                                FROM document d LEFT JOIN source s ON s.id = d.source_id WHERE d.id = $1""", document_id)
    if d is None:
        return {"document_id": document_id, "skipped": "no such document"}
    data = dict(d["data"] or {})
    src = doctext.resolve(d["path"])
    is_pdf = (d["mime"] or "").endswith("pdf") or (src is not None and src.suffix.lower() == ".pdf")
    if src is None or not src.exists() or not is_pdf:
        return {"document_id": document_id, "skipped": "no PDF file to OCR", "path": d["path"]}

    res = await asyncio.to_thread(ocr_pdf, src)
    pages, confs = res["pages"], res["confs"]
    chars = sum(len(p) for p in pages)
    known = [x for x in confs if x is not None]
    mean = round(sum(known) / len(known), 4) if known else None
    if not chars:
        data.update(text_status="failed", ocr_error="; ".join(res["errors"]) or "OCR nie odczytał tekstu")
        async with _use(conn) as c:
            await c.execute("UPDATE document SET data = $2, updated_at = now() WHERE id = $1", document_id, data)
        return {"document_id": document_id, "pages": len(pages), "chars": 0, "errors": res["errors"]}

    # derived text file + manifest line (provenance: method, job, confidence, source sha256)
    body = ("\f".join(p.strip() for p in pages) + "\n").encode("utf-8")
    store = RawStore(d["source_kind"] or "upload", root=raw_root)
    fp = store.path_for(f"ocr/{(d['sha256'] or str(document_id))[:16]}.ocr.txt")
    fp.write_bytes(body)
    rel = store.rel(fp)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    store.append({
        "source": store.source, "fetched_at": now, "method": "tesseract", "url": f"ocr:{d['path']}", "params": {},
        "http_status": None, "content_type": "text/plain; charset=utf-8", "bytes": len(body), "sha256": sha256_bytes(body),
        "path": rel, "licence": "derived (OCR)", "run_id": str(uuid.uuid4()), "status": "ok",
        "note": (f"OCR tesseract -l {LANG} --psm 1 at {DPI} dpi ({res['runtime']}); job {job_id}; pages={len(pages)} "
                 f"mean_conf={mean}; source_sha256={d['sha256']}"),
        "key": request_key("DERIVED", f"ocr:{d['path']}", {"job": job_id}),
    })
    data.update(ocr_text_path=rel, ocr_confidence=confs, ocr_low_confidence=bool(mean is not None and mean < LOW_CONF),
                needs_ocr=False, text_status="ok", text_method="tesseract", ocr_job=job_id, ocr_at=now,
                ocr_errors=res["errors"] or None)
    async with _use(conn) as c:
        async with c.transaction():
            await c.execute("UPDATE document SET ocr = true, pages = $2, data = $3, updated_at = now() WHERE id = $1",
                            document_id, len(pages), data)
        st = await doctext.run(c, str(uuid.uuid4()), force=True, document_ids=[document_id])
        await c.execute("""INSERT INTO audit_log (actor, action, table_name, row_id, after)
                           VALUES ($1, 'document.ocr', 'document', $2, $3)""", actor, document_id,
                        {"pages": len(pages), "chars": chars, "mean_conf": mean, "ocr_text_path": rel, "job_id": job_id,
                         "runtime": res["runtime"]})
    out = {"document_id": document_id, "pages": len(pages), "chars": chars, "mean_conf": mean,
           "low_confidence": data["ocr_low_confidence"], "chunks": st.get("chunks"), "ocr_text_path": rel,
           "errors": res["errors"], "runtime": res["runtime"], "next": None}
    if extract:
        from riskminer.jobs import worker
        if worker.known_kind("document_extract"):
            out["next"] = await worker.enqueue("document_extract", {"document_id": document_id}, created_by=actor)
        else:
            out["next"] = "document_extract not registered (session L)"
    return out


async def enqueue_pending(created_by: str = "cli") -> dict:
    """Queue document_ocr for uploaded scans that are still waiting (no OCR text, no queued/running job)."""
    async with raw_conn() as conn:
        ids = [r["id"] for r in await conn.fetch("""
            SELECT d.id FROM document d JOIN source s ON s.id = d.source_id
            WHERE s.kind = 'upload' AND coalesce(d.data->>'needs_ocr', '') = 'true' AND NOT d.data ? 'ocr_text_path'
              AND NOT EXISTS (SELECT 1 FROM job j WHERE j.kind = 'document_ocr' AND j.status IN ('queued', 'running')
                              AND (j.payload->>'document_id')::bigint = d.id)
            ORDER BY d.id""")]
        jobs = []
        for i in ids:
            jid = await conn.fetchval("INSERT INTO job (kind, payload, priority, created_by) VALUES ('document_ocr', $1, 50, $2) "
                                      "RETURNING id", {"document_id": i}, created_by)
            await conn.execute("SELECT pg_notify('riskminer_jobs', $1)", str(jid))
            jobs.append({"document_id": i, "job_id": jid})
    return {"queued": jobs}
