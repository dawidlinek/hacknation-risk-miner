"""Document upload and original file (api_contract §2.3 1.1/1.3, §2.4 2.5, §3.3). Owner: S0 (lead).
Logic in `riskminer/documents/upload.py`."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.config import REPO_ROOT, app_config, settings
from riskminer.db.session import get_session
from riskminer.documents import upload as U

router = APIRouter(prefix="/api/documents", tags=["documents"])
DB = Depends(get_session)


def _max_bytes() -> int:
    return int((app_config().get("api") or {}).get("upload_max_mb", 50)) * 1024 * 1024


@router.post("/upload", status_code=201, summary="Wgraj dokument (PDF, DOCX, DOC, ODT) z etykietą poufności")
async def upload(file: UploadFile = File(...),
                 sensitivity: Literal["confidential", "public"] = Form("confidential"),
                 analysis_code: str | None = Form(None), project_rm_id: str | None = Form(None),
                 s: A.Session = Depends(A.session), db: AsyncSession = DB):
    if project_rm_id and s.user is None:
        raise A.ApiError(401, "Dokument do projektu może dodać tylko zalogowany ekspert.", "login_required")
    content = await file.read(_max_bytes() + 1)
    try:
        out = await U.handle_upload(db, filename=file.filename or "", content=content, sensitivity=sensitivity, actor=s.actor,
                                    anon_id=s.anon_id, user_actor=s.user.actor if s.user else None,
                                    analysis_code=analysis_code, project_rm_id=project_rm_id, max_bytes=_max_bytes(),
                                    request_id=A.request_id())
    except U.UploadError as e:
        raise A.ApiError(e.status, e.detail, e.code) from None
    # Job chain (docs/impl/new_documents.md): scan -> document_ocr (D, same transaction as the document row) -> document_extract
    # (L) -> document_link (B). A text-layer project document starts at document_extract (enqueued after commit).
    from riskminer.jobs import worker
    if not out["duplicate"] and out["text_status"] == "needs_ocr" and worker.known_kind("document_ocr"):
        from riskminer.ingest import ocr_doc
        j = await ocr_doc.enqueue(db, out["document_id"], created_by=s.actor)
        out["jobs"].append({"kind": "document_ocr", "job_id": j["id"]})
    await db.commit()
    if project_rm_id and not out["duplicate"] and out["text_status"] == "ok" and worker.known_kind("document_extract"):
        j = await worker.enqueue("document_extract", {"document_id": out["document_id"]}, created_by=s.actor)
        out["jobs"].append({"kind": "document_extract", "job_id": j["id"]})
    return out


@router.get("/{document_id}/file", summary="Oryginalny plik dokumentu (poufny tylko dla właściciela)")
async def file(document_id: int, s: A.Session = Depends(A.session), db: AsyncSession = DB):
    r = (await db.execute(text("SELECT id, filename, path, mime, sensitivity, data FROM document WHERE id = :id"),
                          {"id": document_id})).mappings().first()
    if r is None or not U.can_read(dict(r), anon_id=s.anon_id, user_actor=s.user.actor if s.user else None,
                                   role=s.user.role if s.user else None):
        raise A.ApiError(404, "Nie ma takiego dokumentu.", "not_found")   # 404, not 403: do not reveal confidential ids
    p = Path(r["path"] or "")
    p = p if p.is_absolute() else REPO_ROOT / p
    try:
        p = p.resolve(strict=True)
        p.relative_to(Path(settings().data_dir).resolve())
    except (FileNotFoundError, ValueError):
        raise A.ApiError(404, "Plik dokumentu nie jest dostępny.", "file_missing") from None
    name = r["filename"] or p.name
    return FileResponse(p, media_type=r["mime"] or "application/octet-stream", filename=name, content_disposition_type="inline")
