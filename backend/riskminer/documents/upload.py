"""Document upload (api_contract §2.3 1.1, §3.3). Owner: S0.

Invariant 1: raw bytes are stored unchanged at `data/raw/upload/<sha256>.<ext>` with one `manifest.jsonl` line per upload
(the derived text gets its own line); the `source` row (kind `upload`, licence `user-upload`) carries url/sha256/path.
Dedup by sha256: the bytes and the source row are shared; a document row is reused for the same owner (or when the
existing row is public), otherwise a new document row is created so ownership and sensitivity stay per uploader.

Text: PDF via pypdfium2 (Apache-2.0/BSD-3), one `document_page` per PDF page. DOCX/DOC/ODT are converted to PDF with
LibreOffice headless (MPL-2.0, separate binary, isolated profile per call) and read the same way, so page numbers match
what the user sees. A PDF with almost no text layer is a scan: `text_status = "needs_ocr"` (no OCR in the request path).
Chunks follow `ingest/doctext.py` (same spans, `tsv = to_tsvector('simple', unaccent(text))`), so search works at once.

Sensitivity: `confidential` (default) documents must be excluded from public search/listing/exports (filters in
search.py / data.py) and their file is served only to the owner or an admin (`can_read`).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.config import REPO_ROOT, settings
from riskminer.ingest.doctext import chunk_spans

log = logging.getLogger("riskminer.upload")

SOURCE_KIND = "upload"
LICENCE = "user-upload"
ALLOWED = {".pdf": "application/pdf",
           ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
           ".doc": "application/msword",
           ".odt": "application/vnd.oasis.opendocument.text"}
MAGIC = {".pdf": (b"%PDF",), ".docx": (b"PK\x03\x04",), ".odt": (b"PK\x03\x04",), ".doc": (b"\xd0\xcf\x11\xe0",)}
MIN_CHARS_PER_PAGE = 40          # below this on average the PDF has no usable text layer (scan)
SOFFICE_TIMEOUT_S = 120
DATA_LOCATION = "PL (serwer ex ante)"


class UploadError(Exception):
    def __init__(self, status: int, detail: str, code: str):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


@dataclass
class Extracted:
    pages: list[str] = field(default_factory=list)
    method: str = ""
    error: str | None = None

    @property
    def needs_ocr(self) -> bool:
        n = max(1, len(self.pages))
        return sum(len(p.strip()) for p in self.pages) < MIN_CHARS_PER_PAGE * n


# ------------------------------------------------------------------------------------------- pure helpers

def check_file(filename: str, content: bytes, max_bytes: int) -> str:
    """-> extension; raises UploadError for size/type problems."""
    if not content:
        raise UploadError(400, "Plik jest pusty.", "empty_file")
    if len(content) > max_bytes:
        raise UploadError(413, f"Plik jest za duży (limit {max_bytes // (1024 * 1024)} MB).", "file_too_large")
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise UploadError(415, "Obsługujemy pliki PDF, DOCX, DOC i ODT.", "unsupported_type")
    if not content.startswith(MAGIC[ext]):
        raise UploadError(415, "Zawartość pliku nie zgadza się z rozszerzeniem.", "type_mismatch")
    return ext


def _clean(s: str) -> str:
    return s.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def pdf_pages(path: Path) -> list[str]:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(path))
    try:
        out = []
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            out.append(_clean(tp.get_text_range()))
            tp.close()
            page.close()
        return out
    finally:
        doc.close()


def to_pdf(src: Path, outdir: Path) -> Path:
    from riskminer.documents.convert import ConvertError
    from riskminer.documents.convert import to_pdf as _to_pdf
    try:
        return _to_pdf(src, outdir, timeout=SOFFICE_TIMEOUT_S)
    except ConvertError as e:
        if e.code == "converter_unavailable":
            raise UploadError(503, "Konwersja dokumentów Word jest chwilowo niedostępna. Wgraj PDF.", e.code) from None
        raise UploadError(422, "Nie udało się odczytać dokumentu. Zapisz go jako PDF i wgraj ponownie.", e.code) from None


def extract_pages(content: bytes, ext: str) -> Extracted:
    """Blocking (run in a thread). Never raises for broken files: returns an empty result with `error`."""
    with tempfile.TemporaryDirectory(prefix="rm_upload_") as td:
        src = Path(td) / f"in{ext}"
        src.write_bytes(content)
        try:
            if ext == ".pdf":
                return Extracted(pdf_pages(src), "pypdfium2")
            return Extracted(pdf_pages(to_pdf(src, Path(td))), "soffice->pdf+pypdfium2")
        except UploadError:
            raise
        except Exception as e:  # noqa: BLE001 - recorded, upload still stored
            log.warning("text extraction failed: %s", e)
            return Extracted([], "failed", f"{type(e).__name__}: {e}"[:200])


def guess_doc_type(filename: str, pages: list[str]) -> dict[str, Any]:
    """Reuses the platform classifier (filename, then text head). -> {code (upper), confidence, method}."""
    from riskminer.connectors.platforms import classify
    head = "\n".join(pages[:2])[:4000]
    kind, _sub, basis = classify(filename or "", "", head)
    conf = {"filename": 0.9, "context": 0.7, "text": 0.7, "heuristic": 0.5}.get(basis, 0.3)
    if kind in ("inne", "", None):
        return {"code": "INNE", "confidence": 0.3, "method": "filename+keywords"}
    return {"code": kind.upper(), "confidence": conf, "method": "filename+keywords" if basis == "filename" else f"{basis}+keywords"}


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_dir() -> Path:
    d = settings().raw_dir / SOURCE_KIND
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def append_manifest(entry: dict) -> None:
    line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
    with (raw_dir() / "manifest.jsonl").open("a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(line)
        fcntl.flock(fh, fcntl.LOCK_UN)


def store_bytes(content: bytes, sha: str, ext: str, *, note: str, content_type: str) -> Path:
    p = raw_dir() / f"{sha}{ext}"
    if not p.exists():
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(content)
        tmp.replace(p)
    append_manifest({"source": SOURCE_KIND, "fetched_at": _utc(), "method": "UPLOAD", "url": f"upload:{sha}", "params": {},
                     "http_status": None, "content_type": content_type, "bytes": len(content), "sha256": sha,
                     "path": rel(p), "licence": LICENCE, "run_id": None, "status": "ok", "note": note, "key": sha})
    return p


# ------------------------------------------------------------------------------------------- DB

async def _source_id(db: AsyncSession, sha: str, path: Path, size: int, ctype: str, note: str) -> int:
    sid = (await db.execute(text("SELECT id FROM source WHERE kind = :k AND sha256 = :s ORDER BY id LIMIT 1"),
                            {"k": SOURCE_KIND, "s": sha})).scalar()
    if sid:
        return sid
    return (await db.execute(text("""
        INSERT INTO source (kind, url, method, params, retrieved_at, content_type, bytes, sha256, path, licence, status, note, manifest_key)
        VALUES (:k, :url, 'UPLOAD', '{}'::jsonb, now(), :ct, :b, :s, :p, :lic, 'ok', :note, :s) RETURNING id"""),
        {"k": SOURCE_KIND, "url": f"upload:{sha}", "ct": ctype, "b": size, "s": sha, "p": rel(path), "lic": LICENCE,
         "note": note})).scalar_one()


async def _existing_document(db: AsyncSession, sha: str, owner_anon: str, owner_user: str | None) -> dict | None:
    r = (await db.execute(text("""
        SELECT d.id, d.filename, d.sha256, d.pages, d.doc_type, d.sensitivity, d.data, d.project_id
        FROM document d JOIN source s ON s.id = d.source_id AND s.kind = :k
        WHERE d.sha256 = :s AND (d.data->>'owner_anon' = :a OR (CAST(:u AS text) IS NOT NULL AND d.data->>'owner_user' = :u))
        ORDER BY d.id LIMIT 1"""), {"k": SOURCE_KIND, "s": sha, "a": owner_anon, "u": owner_user})).mappings().first()
    return dict(r) if r else None


async def _project_id(db: AsyncSession, rm_id: str | None) -> int | None:
    if not rm_id:
        return None
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id = :r"), {"r": rm_id})).scalar()
    if pid is None:
        raise UploadError(404, "Nie ma takiego projektu.", "project_not_found")
    return pid


async def save_pages(db: AsyncSession, document_id: int, pages: list[str]) -> int:
    """document_page + chunk rows (same spans and tsv as ingest/doctext.py). -> number of chunks."""
    if not pages:
        return 0
    await db.execute(text("INSERT INTO document_page (document_id, page_no, text, ocr) VALUES (:d, :n, :t, false)"),
                     [{"d": document_id, "n": i, "t": t} for i, t in enumerate(pages, 1)])
    rows = [{"d": document_id, "n": i, "a": a, "b": b, "t": t[a:b]}
            for i, t in enumerate(pages, 1) for a, b in chunk_spans(t)]
    if rows:
        await db.execute(text("""INSERT INTO chunk (document_id, page_no, char_start, char_end, text, tsv)
                                 VALUES (:d, :n, :a, :b, :t, to_tsvector('simple', unaccent(:t)))"""), rows)
    return len(rows)


async def handle_upload(db: AsyncSession, *, filename: str, content: bytes, sensitivity: str, actor: str, anon_id: str,
                        user_actor: str | None, analysis_code: str | None, project_rm_id: str | None,
                        max_bytes: int, request_id: str | None) -> dict[str, Any]:
    """Store, extract, insert, audit. Caller commits."""
    import asyncio

    ext = check_file(filename, content, max_bytes)
    project_id = await _project_id(db, project_rm_id)
    sha = hashlib.sha256(content).hexdigest()
    ctype = ALLOWED[ext]
    owner_anon = anon_id[:8]
    safe_name = Path(filename).name[:200]

    existing = await _existing_document(db, sha, owner_anon, user_actor)
    if existing and (project_id is None or existing["project_id"] == project_id):
        dt = existing["data"] or {}
        return {"document_id": existing["id"], "filename": existing["filename"], "sha256": sha, "pages": existing["pages"],
                "doc_type": {"code": (existing["doc_type"] or "inne").upper(), "confidence": dt.get("doc_type_confidence"),
                             "method": dt.get("doc_type_method")},
                "sensitivity": existing["sensitivity"], "text_status": dt.get("text_status", "ok"),
                "processing": {"data_location": DATA_LOCATION}, "duplicate": True, "jobs": []}

    raw = await asyncio.to_thread(store_bytes, content, sha, ext, note=f"upload by {actor}", content_type=ctype)
    ex = await asyncio.to_thread(extract_pages, content, ext)
    text_status = "failed" if ex.error else ("needs_ocr" if ex.needs_ocr else "ok")
    pages_for_search = ex.pages          # scans give near-empty pages: no chunks, page rows still mark the page count
    text_path = None
    if ex.pages:
        tbytes = "\f".join(ex.pages).encode("utf-8")
        tp = raw_dir() / f"{sha}.txt"
        if not tp.exists():
            tp.write_bytes(tbytes)
        append_manifest({"source": SOURCE_KIND, "fetched_at": _utc(), "method": "DERIVED", "url": f"upload:{sha}#text",
                         "params": {}, "http_status": None, "content_type": "text/plain; charset=utf-8", "bytes": len(tbytes),
                         "sha256": hashlib.sha256(tbytes).hexdigest(), "path": rel(tp), "licence": LICENCE, "run_id": None,
                         "status": "ok", "note": f"derived text ({ex.method}) of {sha}", "key": f"{sha}#text"})
        text_path = rel(tp)

    dtype = guess_doc_type(safe_name, ex.pages)
    sid = await _source_id(db, sha, raw, len(content), ctype, f"upload {safe_name}")
    data = {"owner_anon": owner_anon, "owner_user": user_actor, "uploaded_by": actor, "analysis_code": analysis_code,
            "text_status": text_status, "text_method": ex.method, "text_error": ex.error, "needs_ocr": text_status == "needs_ocr",
            "doc_type_confidence": dtype["confidence"], "doc_type_method": dtype["method"]}
    doc_id = (await db.execute(text("""
        INSERT INTO document (project_id, doc_type, phase, title, filename, url, sha256, path, text_path, mime, pages, ocr,
                              fetch_state, sensitivity, note, data, key, origin, review_status, source_id)
        VALUES (:pid, :dt, 'przygotowanie', :title, :fn, :url, :sha, :path, :tp, :mime, :pages, false,
                'found', :sens, :note, CAST(:data AS jsonb), :key, 'SOURCE', 'auto', :sid) RETURNING id"""),
        {"pid": project_id, "dt": dtype["code"].lower(), "title": safe_name, "fn": safe_name, "url": f"upload:{sha}", "sha": sha,
         "path": rel(raw), "tp": text_path, "mime": ctype, "pages": len(ex.pages) or None, "sens": sensitivity,
         "note": "wgrany przez użytkownika", "data": json.dumps(data, ensure_ascii=False),
         "key": f"upload:{sha}:{owner_anon}:{uuid.uuid4().hex[:8]}", "sid": sid})).scalar_one()
    n_chunks = await save_pages(db, doc_id, pages_for_search)
    await db.execute(text("""INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id)
                             VALUES (:a, 'document.upload', 'document', :id, CAST(:after AS jsonb), :rid)"""),
                     {"a": actor, "id": doc_id, "rid": request_id,
                      "after": json.dumps({"filename": safe_name, "sha256": sha, "sensitivity": sensitivity, "pages": len(ex.pages),
                                           "chunks": n_chunks, "text_status": text_status, "source_id": sid,
                                           "analysis_code": analysis_code, "project_rm_id": project_rm_id}, ensure_ascii=False)})
    return {"document_id": doc_id, "filename": safe_name, "sha256": sha, "pages": len(ex.pages), "doc_type": dtype,
            "sensitivity": sensitivity, "text_status": text_status, "processing": {"data_location": DATA_LOCATION},
            "duplicate": False, "jobs": []}


def can_read(doc: dict, *, anon_id: str, user_actor: str | None, role: str | None) -> bool:
    """Confidential documents: only the uploader (anon id or user) or an admin."""
    if (doc.get("sensitivity") or "public") == "public":
        return True
    if role == "admin":
        return True
    d = doc.get("data") or {}
    return d.get("owner_anon") == anon_id[:8] or (user_actor is not None and d.get("owner_user") == user_actor)
