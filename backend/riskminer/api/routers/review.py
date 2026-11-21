"""Przegląd 3.1: review queue (api_contract §2.5, §3.1). Login only. Decisions go through `riskminer/review/service.py`."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api import schemas as S
from riskminer.api.schemas_review import BulkDecisionIn, DecisionIn, ReviewItemRow
from riskminer.db.session import get_session
from riskminer.review import card_read, cards, service

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
        type=r.get("itype"), type_label=card_read.type_label(r.get("itype")) if r.get("itype") else None,
        strength=card_read.strength(r.get("verification"), r.get("confidence")),
        context={"label": (r.get("rm_id") or "") + (f", {r['project_title']}" if r.get("project_title") else "") or None,
                 "href": f"/projekty/{r['rm_id']}" if r.get("rm_id") else None})


# review_item + project + the event type and the first evidence row of the target claim (read-only joins)
_FROM = """review_item r LEFT JOIN project p ON p.id = r.project_id
    LEFT JOIN risk_event e ON r.target_table = 'risk_event' AND e.id = r.target_id
    LEFT JOIN LATERAL (SELECT ev.verification FROM evidence ev WHERE ev.claim_table = r.target_table AND ev.claim_id = r.target_id
                       ORDER BY (ev.quote IS NULL), ev.id LIMIT 1) v ON true"""
_TYPE = "(CASE WHEN r.kind = 'event' AND e.event_type IS NOT NULL THEN e.event_type ELSE r.code END)"
_RANK = f"""(CASE WHEN v.verification IN ('exact','structured_field') AND (r.confidence IS NULL OR r.confidence >= {card_read.READY_CONF}) THEN 0
              WHEN v.verification IN ('exact','structured_field') THEN 1 WHEN v.verification = 'fuzzy' THEN 2 ELSE 3 END)"""
_LEVEL = {0: "ready", 1: "check", 2: "check", 3: "weak"}
_LEVEL_LABEL = {"ready": "gotowe do akceptacji", "check": "do sprawdzenia", "weak": "bez cytatu ze źródła"}


def _where(kind: str | None, status: str | None, code: str | None, rm_id: str | None, type_: str | None,
           skip: set[str] = frozenset()) -> tuple[str, dict]:
    where, params = ["true"], {}
    if _kind(kind) and "kind" not in skip:
        where.append("r.kind = :kind")
        params["kind"] = _kind(kind)
    if status:
        where.append("r.status = :status")
        params["status"] = status
    if code:  # a review code (ai_event) or a risk code from the catalogue (R02 also matches R02.1)
        where.append("(r.code = :code OR r.model_pick = :code OR r.model_pick LIKE :code_sub)")
        params.update(code=code, code_sub=f"{code}.%")
    if rm_id and "rm_id" not in skip:
        if rm_id == "none":
            where.append("p.rm_id IS NULL")
        else:
            where.append("p.rm_id = :rm")
            params["rm"] = rm_id
    if type_ and "type" not in skip:
        where.append(f"{_TYPE} = :itype")
        params["itype"] = type_
    return " AND ".join(where), params


@router.get("/review-items", response_model=S.Page[ReviewItemRow], summary="Kolejka eksperta (login)")
async def list_review_items(kind: str | None = None, status: str | None = "open", code: str | None = None,
                            rm_id: str | None = Query(None, description="projekt (RM-...), `none` = sprawy bez projektu"),
                            type: str | None = Query(None, description="rodzaj: event_type zdarzenia (EV_DOC_SIGNAL) albo kod sprawy"),
                            sort: str = Query("queue", description="`queue` (kolejność kolejki) albo `strength` (najpierw gotowe do akceptacji)"),
                            id: int | None = Query(None, description="pozycja, która ma być pierwsza"),
                            limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    w, params = _where(kind, status, code, rm_id, type)
    params.update(limit=limit, offset=offset)
    total = (await db.execute(text(f"SELECT count(*) FROM {_FROM} WHERE {w}"), params)).scalar()
    order = "(r.id = :first) DESC, " if id else ""
    if id:
        params["first"] = id
    rest = f"{_RANK}, r.confidence DESC NULLS LAST, r.id" if sort == "strength" else "r.severity = 'low', r.id"
    rs = (await db.execute(text(f"""SELECT r.*, p.rm_id, p.title AS project_title, {_TYPE} AS itype, v.verification FROM {_FROM} WHERE {w}
                                    ORDER BY {order}(r.detail ? 'skipped_at'), {rest} LIMIT :limit OFFSET :offset"""), params)).mappings().all()
    return {"total": total or 0, "limit": limit, "offset": offset, "items": [_row(dict(r)) for r in rs]}


@router.get("/review-items/counts", summary="Liczniki kolejki wg rodzaju")
async def review_counts(db: AsyncSession = DB):
    rs = (await db.execute(text("SELECT kind, count(*) AS n FROM review_item WHERE status='open' GROUP BY kind"))).all()
    out = {k: 0 for k in ("event", "link", "discrepancy", "fact", "catalogue")}
    out.update({k: n for k, n in rs})
    out["total"] = sum(n for _, n in rs)
    return out


@router.get("/review-items/facets", summary="Filtry kolejki: rodzaje, projekty i siła dowodu z liczbami, które się sumują")
async def review_facets(kind: str | None = None, status: str | None = "open", code: str | None = None, rm_id: str | None = None,
                        type: str | None = None, db: AsyncSession = DB):
    """Each facet is counted with the other filters applied (not its own), so the numbers of one dropdown add up to `total`
    of the list without that filter."""
    async def grouped(expr: str, skip: set[str], extra: str = "") -> list[dict]:
        w, p = _where(kind, status, code, rm_id, type, skip)
        return [dict(r) for r in (await db.execute(text(f"""SELECT {expr} AS key{extra}, count(*) AS n FROM {_FROM} WHERE {w}
                                                            GROUP BY 1 ORDER BY n DESC, 1"""), p)).mappings().all()]

    types = await grouped(_TYPE, {"type"})
    projects = await grouped("coalesce(p.rm_id, 'none')", {"rm_id"}, ", min(p.title) AS title")
    ranks = await grouped(_RANK, set())
    w, p = _where(kind, status, code, rm_id, type)
    total = (await db.execute(text(f"SELECT count(*) FROM {_FROM} WHERE {w}"), p)).scalar() or 0
    levels: dict[str, int] = {}
    for r in ranks:
        levels[_LEVEL[r["key"]]] = levels.get(_LEVEL[r["key"]], 0) + r["n"]
    return {
        "total": total,
        "types": [{"key": t["key"], "label": card_read.type_label(t["key"]), "n": t["n"]} for t in types if t["key"]],
        "projects": [{"key": x["key"], "label": "Bez projektu (dokumenty i dane krajowe)" if x["key"] == "none"
                      else f"{x['key']}, {x['title'] or ''}".strip(", "), "n": x["n"]} for x in projects],
        "strength": [{"key": k, "label": _LEVEL_LABEL[k], "n": levels[k]} for k in ("ready", "check", "weak") if k in levels],
    }


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
    return await card_read.enrich(db, item, await cards.build_card(db, item))


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
