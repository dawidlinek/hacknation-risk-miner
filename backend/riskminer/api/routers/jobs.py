"""Jobs: enqueue connector/importer runs and watch their status (visible in the UI)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import deps as D
from riskminer.api import schemas as S
from riskminer.db.session import get_session
from riskminer.jobs import worker

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=S.Page[S.JobOut], summary="Zadania (kolejka)")
async def list_jobs(status: str | None = None, limit: int = Query(50, le=500), offset: int = 0,
                    db: AsyncSession = Depends(get_session)):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if status:
        where.append("status = :s")
        params["s"] = status
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM job WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM job WHERE {w} ORDER BY id DESC LIMIT :limit OFFSET :offset", **params)
    return {"total": total, "limit": limit, "offset": offset, "items": [S.JobOut(**r) for r in rs]}


@router.post("", response_model=S.JobOut, status_code=201, summary="Uruchom: scrape:<źródło> | load:<źródło> | load_all | ...")
async def create_job(job: S.JobIn, db: AsyncSession = Depends(get_session)):
    if not worker.known_kind(job.kind):
        raise HTTPException(400, f"unknown job kind {job.kind!r}; known: {worker.KINDS_HELP}")
    jid = await worker.enqueue(job.kind, job.payload, priority=job.priority, created_by="api")
    r = await D.one(db, "SELECT * FROM job WHERE id = :id", id=jid["id"])
    return S.JobOut(**r)


@router.get("/{job_id}", response_model=S.JobOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_session)):
    r = await D.one(db, "SELECT * FROM job WHERE id = :id", id=job_id)
    if not r:
        raise HTTPException(404, "job not found")
    return S.JobOut(**r)
