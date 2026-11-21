"""Przegląd 3.1: review queue (api_contract §2.5, §3.1). Login only. Decisions go through `riskminer/review/service.py`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api import schemas as S
from riskminer.api.schemas_review import BulkDecisionIn, DecisionIn, ReviewItemRow
from riskminer.db.session import get_session
from riskminer.review import cards, service

router = APIRouter(prefix="/api", tags=["review"], dependencies=[Depends(A.require_login)])
DB = Depends(get_session)

# frontend tab names (plural) and contract kinds (singular) both work
KIND_ALIASES = {"events": "event", "links": "link", "discrepancies": "discrepancy", "facts": "fact", "catalogue": "catalogue",
                "imports": "import", "cases": "case_candidate"}


def _kind(k: str | None) -> str | None:
    return KIND_ALIASES.get(k, k) if k else None


def _row(r: dict) -> ReviewItemRow:
    return ReviewItemRow(
        **{k: r.get(k) for k in ("id", "kind", "code", "rm_id", "title", "question", "target_table", "target_id", "project_id", "detail",
                                 "severity", "status", "model_pick", "confidence", "created_by", "created_at", "resolved_by", "resolved_at")},
        kind_label=cards.KIND_LABEL.get(r["kind"], r["kind"]),
        context={"label": (r.get("rm_id") or "") + (f", {r['project_title']}" if r.get("project_title") else "") or None,
                 "href": f"/projekty/{r['rm_id']}" if r.get("rm_id") else None})


@router.get("/review-items", response_model=S.Page[ReviewItemRow], summary="Kolejka eksperta (login)")
async def list_review_items(kind: str | None = None, status: str | None = "open", code: str | None = None, rm_id: str | None = None,
                            id: int | None = Query(None, description="pozycja, która ma być pierwsza"),
                            limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    for col, val, key in (("r.kind", _kind(kind), "kind"), ("r.status", status, "status"), ("r.code", code, "code"), ("p.rm_id", rm_id, "rm")):
        if val:
            where.append(f"{col} = :{key}")
            params[key] = val
    w = " AND ".join(where)
    j = "review_item r LEFT JOIN project p ON p.id = r.project_id"
    total = (await db.execute(text(f"SELECT count(*) FROM {j} WHERE {w}"), params)).scalar()
    order = "(r.id = :first) DESC, " if id else ""
    if id:
        params["first"] = id
    rs = (await db.execute(text(f"""SELECT r.*, p.rm_id, p.title AS project_title FROM {j} WHERE {w}
                                    ORDER BY {order}(r.detail ? 'skipped_at'), r.severity = 'low', r.id LIMIT :limit OFFSET :offset"""), params)).mappings().all()
    return {"total": total or 0, "limit": limit, "offset": offset, "items": [_row(dict(r)) for r in rs]}


@router.get("/review-items/counts", summary="Liczniki kolejki wg rodzaju")
async def review_counts(db: AsyncSession = DB):
    rs = (await db.execute(text("SELECT kind, count(*) AS n FROM review_item WHERE status='open' GROUP BY kind"))).all()
    out = {k: 0 for k in ("event", "link", "discrepancy", "fact", "catalogue")}
    out.update({k: n for k, n in rs})
    out["total"] = sum(n for _, n in rs)
    return out


@router.post("/review-items/bulk-decision", summary="Zatwierdź wiele pozycji naraz (tylko dowody dokładne)")
async def bulk_decision(body: BulkDecisionIn, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    done, refused = [], []
    for i in body.ids:
        item = await cards.load_item(db, i)
        if item is None or item["status"] != "open":
            refused.append({"id": i, "reason": "sprawa nie jest otwarta"})
            continue
        card = await cards.build_card(db, item)
        ev = card.get("evidence") or {}
        if item["kind"] not in ("event", "fact") or ev.get("verification") not in ("exact", "structured_field"):
            refused.append({"id": i, "reason": "cytat niezweryfikowany"})
            continue
        pick = next((o for o in card["options"] if o.get("model_pick")), None)
        if pick is None:
            refused.append({"id": i, "reason": "brak propozycji modelu"})
            continue
        try:
            async with db.begin_nested():
                await service.decide(db, i, actor=user.actor, option=pick["key"], action="approve", request_id=A.request_id())
            done.append(i)
        except A.ApiError as e:
            refused.append({"id": i, "reason": e.detail})
    await db.commit()
    return {"done": done, "refused": refused}


@router.get("/review-items/{item_id}", summary="Pozycja kolejki: pytanie, dowód, opcje, skutki")
async def review_item(item_id: int, db: AsyncSession = DB):
    item = await cards.load_item(db, item_id)
    if item is None:
        raise A.ApiError(404, "Nie ma takiej sprawy.", "not_found")
    return await cards.build_card(db, item)


@router.post("/review-items/{item_id}/decision", summary="Decyzja eksperta (zatwierdź, popraw, odrzuć)")
async def decision(item_id: int, body: DecisionIn, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await service.decide(db, item_id, actor=user.actor, option=body.option, action=body.action, value=body.value,
                               reason=body.reason, gold=body.gold, request_id=A.request_id())
    await db.commit()
    return out


@router.post("/review-items/{item_id}/skip", summary="Pomiń pozycję (wróci na koniec kolejki)")
async def skip(item_id: int, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await service.skip(db, item_id, actor=user.actor, request_id=A.request_id())
    await db.commit()
    return out


@router.post("/reviews/{review_id}/undo", summary="Cofnij własną decyzję (15 minut)")
async def undo(review_id: int, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await service.undo(db, review_id, actor=user.actor, request_id=A.request_id())
    await db.commit()
    return out


@router.get("/reviews", summary="Decyzje ekspertów")
async def reviews(target_table: str | None = None, target_id: int | None = None, reviewer: str | None = None,
                  limit: int = Query(50, le=500), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    for col, val in (("target_table", target_table), ("target_id", target_id), ("reviewer", reviewer)):
        if val is not None:
            where.append(f"{col} = :{col}")
            params[col] = val
    w = " AND ".join(where)
    total = (await db.execute(text(f"SELECT count(*) FROM review WHERE {w}"), params)).scalar()
    rs = (await db.execute(text(f"""SELECT id, action, option_key, before, after, reviewer, comment, created_at, review_item_id, undo_of,
                                    target_table, target_id FROM review WHERE {w} ORDER BY id DESC LIMIT :limit OFFSET :offset"""), params)).mappings().all()
    return {"total": total or 0, "limit": limit, "offset": offset, "items": [dict(r) for r in rs]}
