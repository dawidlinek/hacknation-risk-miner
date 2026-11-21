"""W10 authority/contractor memory and W17 sector lessons digest. Read-only, public (like the other analytics)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analytics import lessons as LS
from riskminer.analytics import org_memory as OM
from riskminer.db.session import get_session

router = APIRouter(prefix="/api", tags=["memory"])
DB = Depends(get_session)


@router.get("/organizations/{nip}/memory", summary="Pamięć zamawiającego i wykonawcy: historia umów z BZP")
async def organization_memory(nip: str, db: AsyncSession = DB):
    m = await OM.organization_memory(db, nip)
    if m is None:
        raise HTTPException(404, "organization not found")
    return m


@router.get("/analytics/lessons", summary="Wnioski sektorowe: ryzyka, przyczyny i środki zaradcze")
async def lessons(sector: str = Query("wod-kan", pattern="^[a-z0-9-]{2,30}$"), limit: int = Query(8, ge=1, le=30),
                  db: AsyncSession = DB):
    return await LS.sector_lessons(db, sector, limit)
