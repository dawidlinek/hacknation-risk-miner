"""Historia: global audit log and restore (api_contract §2.4 2.6, §2.8). Login only."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import audit_read as AR
from riskminer.api import auth as A
from riskminer.api.schemas_review import RestoreIn
from riskminer.db.session import get_session
from riskminer.review import service

router = APIRouter(prefix="/api/audit", tags=["audit"], dependencies=[Depends(A.require_login)])
DB = Depends(get_session)


@router.get("", summary="Dziennik zmian (ekspert, import, katalog, model, system)")
async def audit(category: Literal["expert", "import", "catalogue", "model", "system"] | None = None,
                table: str | None = None, row_id: int | None = None, actor: str | None = None, since: str | None = None,
                until: str | None = None, hide_login: bool = False,
                limit: int = Query(50, le=500), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if category:
        where.append(AR.CATEGORY_SQL[category])
    if hide_login:
        where.append("a.action <> 'auth.login'")
    if table:
        where.append("a.table_name = :table")
        params["table"] = table
    if row_id is not None:
        where.append("a.row_id = :row_id")
        params["row_id"] = row_id
    if actor:
        where.append("a.actor = :actor")
        params["actor"] = actor
    if since:
        where.append("a.at >= CAST(CAST(:since AS text) AS timestamptz)")
        params["since"] = since
    if until:
        where.append("a.at < CAST(CAST(:until AS text) AS timestamptz)")
        params["until"] = until
    w = " AND ".join(where)
    total = (await db.execute(text(f"SELECT count(*) FROM audit_log a WHERE {w}"), params)).scalar() or 0
    rs = (await db.execute(text(f"SELECT a.* FROM audit_log a WHERE {w} ORDER BY a.id DESC LIMIT :limit OFFSET :offset"), params)).mappings().all()
    items = []
    for r in rs:
        r = dict(r)
        items.append(AR.entry(r, obj=await AR.object_ref(db, r["table_name"], r["row_id"])))
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.post("/{audit_id}/restore", summary="Przywróć wartość sprzed decyzji (jako nowa edycja)")
async def restore(audit_id: int, body: RestoreIn, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await service.restore_from_audit(db, audit_id, reason=body.reason, actor=user.actor, request_id=A.request_id())
    await db.commit()
    return out
