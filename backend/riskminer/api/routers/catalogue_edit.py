"""Katalog wiedzy 3.2: view, versioned edits, weights, proposals, versions (api_contract §2.6, §3.2). Session B.
Raw rows stay at `GET /api/catalogue/{table}` in `routers/data.py`; this router is included before it."""
from __future__ import annotations

from typing import Any, Literal

import yaml
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.db.session import get_session
from riskminer.review import cards, service
from riskminer.review import catalogue as K

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])
DB = Depends(get_session)
LOGIN = Depends(A.require_login)
Sector = Query("wod-kan", pattern="^[a-z0-9_-]{1,20}$", description="kod sektora, np. wod-kan")


class CataloguePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    text: str | None = None
    title: str | None = None
    phase: str | None = None
    data: dict[str, Any] | None = None


class CataloguePatchIn(BaseModel):
    patch: CataloguePatch
    comment: str | None = None


class WeightsIn(BaseModel):
    weights: dict[str, float]
    comment: str | None = None


class ProposalDecisionIn(BaseModel):
    action: Literal["approve", "merge", "reject"]
    merge_into: str | None = None
    reason: str | None = None


class RestoreIn(BaseModel):
    reason: str


@router.get("/view", summary="Katalog: ryzyka, jakość reguł, propozycje, wagi, wersje", dependencies=[LOGIN])
async def view(sector: str = Sector, db: AsyncSession = DB):
    return await K.view(db, sector)


@router.get("/versions", summary="Wersje pakietu katalogu", dependencies=[LOGIN])
async def versions(sector: str = Sector, db: AsyncSession = DB):
    return await K.versions(db, sector)


@router.get("/versions/{label}/diff", summary="Różnice między wersjami katalogu", dependencies=[LOGIN])
async def version_diff(label: str, against: str | None = None, sector: str = Sector, db: AsyncSession = DB):
    return await K.diff(db, label, against, sector)


@router.post("/versions/{label}/restore", summary="Przywróć wersję katalogu (admin, jako nowa wersja)")
async def version_restore(label: str, body: RestoreIn, sector: str = Sector, user: A.User = Depends(A.require_admin), db: AsyncSession = DB):
    out = await K.restore(db, label, body.reason, user.actor, A.request_id(), sector)
    await db.commit()
    return out


@router.get("/pack.{fmt}", summary="Eksport pakietu sektorowego (JSON lub YAML), tylko zatwierdzone wiersze")
async def pack(fmt: Literal["json", "yaml"], sector: str = Sector, db: AsyncSession = DB):
    out: dict[str, Any] = {"sector": sector, "version": await K.current_label(db, sector)}
    for short, (table, _key, _cols) in K.TABLES.items():
        rs = (await db.execute(text(f"SELECT * FROM {table} WHERE sector = :s AND status = 'approved' ORDER BY id"), {"s": sector})).mappings().all()
        out[short] = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items() if k not in ("id", "created_at", "updated_at")} for r in rs]
    if fmt == "yaml":
        return Response(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), media_type="application/yaml",
                        headers={"Content-Disposition": f'attachment; filename="katalog_{sector}_{out["version"]}.yaml"'})
    return out


@router.put("/similarity/weights", summary="Zmień wagi podobieństwa (nowa wersja katalogu)")
async def weights(body: WeightsIn, sector: str = Sector, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await K.put_weights(db, body.weights, body.comment, user.actor, A.request_id(), sector)
    await db.commit()
    return out


async def _proposal_sector(db: AsyncSession, proposal_id: int) -> str:
    return (await db.execute(text("SELECT sector FROM catalogue_risk WHERE id = :i"), {"i": proposal_id})).scalar() or "wod-kan"


@router.post("/proposals/{proposal_id}/decision", summary="Decyzja o propozycji ryzyka od modelu")
async def proposal_decision(proposal_id: int, body: ProposalDecisionIn, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    item_id = (await db.execute(text("""SELECT id FROM review_item WHERE kind='catalogue' AND target_table='catalogue_risk' AND target_id=:i
                                        AND status='open' ORDER BY id LIMIT 1"""), {"i": proposal_id})).scalar()
    if item_id is None:
        exists = (await db.execute(text("SELECT count(*) FROM catalogue_risk WHERE id=:i AND status='proposed'"), {"i": proposal_id})).scalar()
        if not exists:
            raise A.ApiError(404, "Nie ma takiej propozycji.", "not_found")
        item_id = (await db.execute(text("""INSERT INTO review_item (kind, code, target_table, target_id, title, question, severity, key, created_by)
            SELECT 'catalogue', 'catalogue_proposal', 'catalogue_risk', c.id, 'Propozycja ryzyka: ' || c.name, 'Czy dodać to ryzyko do katalogu?', 'low',
                   'cat:risk:' || c.id, :by FROM catalogue_risk c WHERE c.id = :i RETURNING id"""), {"i": proposal_id, "by": user.actor})).scalar()
    if body.action == "approve":
        opt, act = "add", "approve"
    elif body.action == "merge":
        if not body.merge_into:
            raise A.ApiError(422, "Wskaż ryzyko, z którym łączysz propozycję.", "merge_into_required")
        opt, act = f"merge:{body.merge_into}", "edit"
    else:
        opt, act = "reject", "reject"
    out = await service.decide(db, item_id, actor=user.actor, option=opt, action=act, reason=body.reason, request_id=A.request_id())
    out["catalogue_version"] = await K.current_label(db, await _proposal_sector(db, proposal_id))
    await db.commit()
    return out


@router.patch("/{table}/{code}", summary="Edytuj pozycję katalogu (nowa wersja wiersza)")
async def patch_entry(table: str, code: str, body: CataloguePatchIn, sector: str = Sector, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await K.edit(db, table, code, body.patch.model_dump(exclude_none=True), body.comment, user.actor, A.request_id(), sector)
    await db.commit()
    return out
