"""Monitoring 4.1-4.1c: map regions, signals, contract detail, watches (api_contract §2.7). Owner: D (data-db).
SQL lives in `riskminer/monitoring/service.py` and `riskminer/monitoring/alerts.py`. Reads are public (alerts from
confidential documents only for those who may see the document); watches, case reports and alert status need a writer."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.db.session import get_session
from riskminer.monitoring import alerts as AL
from riskminer.monitoring import service as M

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])
DB = Depends(get_session)
log = logging.getLogger("riskminer.monitoring")


async def _warm() -> None:
    try:
        from riskminer.db.session import sessionmaker
        async with sessionmaker()() as s:
            log.info("monitoring warm-up: %s", await M.warm(s))
    except Exception:
        log.exception("monitoring warm-up failed")


@router.on_event("startup")
async def _startup() -> None:
    """Background, non-blocking: warms the as_of path so the first time-slider step is fast (RISKMINER_WARM=0 skips)."""
    if os.environ.get("RISKMINER_WARM", "1") != "0":
        asyncio.get_event_loop().create_task(_warm())

Level = Literal["woj", "pow", "gmi"]
Metric = Literal["late", "delay", "over", "chg", "imp", "sig"]


class WatchIn(BaseModel):
    contract_id: int
    reason: str | None = None


class ReportCaseIn(BaseModel):
    note: str


def _as_of(as_of: str | None) -> date | None:
    if not as_of:
        return None
    try:
        return date.fromisoformat(as_of[:10])
    except ValueError:
        raise A.ApiError(422, "Nieprawidłowa data (oczekiwano RRRR-MM-DD).", "bad_date")


def _filters(subsector, value_min, value_max, year_from, year_to, q, as_of) -> M.Filters:
    return M.Filters(subsector=subsector, value_min=value_min, value_max=value_max, year_from=year_from, year_to=year_to,
                     q=q, as_of=_as_of(as_of))


@router.get("/regions", summary="Mapa: wartości dla regionów (województwa, powiaty, gminy)")
async def regions(level: Level = "woj", parent: str | None = None, mode: Literal["done", "open"] = "done", metric: Metric = "late",
                  subsector: str | None = None, value_min: float | None = None, value_max: float | None = None,
                  year_from: int | None = None, year_to: int | None = None, q: str | None = None, as_of: str | None = None,
                  db: AsyncSession = DB):
    return await M.regions(db, level, parent, mode, metric,
                           _filters(subsector, value_min, value_max, year_from, year_to, q, as_of))


@router.get("/regions/{terc}", summary="Region: wskaźniki, podregiony, sygnały")
async def region(terc: str, mode: Literal["done", "open"] = "done", metric: Metric = "late", subsector: str | None = None,
                 value_min: float | None = None, value_max: float | None = None, year_from: int | None = None,
                 year_to: int | None = None, q: str | None = None, as_of: str | None = None, db: AsyncSession = DB):
    res = await M.region(db, terc, mode, metric, _filters(subsector, value_min, value_max, year_from, year_to, q, as_of))
    if res is None:
        raise A.ApiError(404, "Nie ma takiego regionu (kod TERYT).", "region_not_found")
    return res


@router.get("/signals", summary="Sygnały: umowy po terminie bez ogłoszenia o wykonaniu")
async def signals(terc: str | None = None, level: Level | None = None, limit: int = Query(50, le=500), offset: int = 0,
                  sort: str = "-days_overdue", geo: bool = False, as_of: str | None = None,
                  subsector: str | None = None, value_min: float | None = None, value_max: float | None = None,
                  year_from: int | None = None, year_to: int | None = None, q: str | None = None, db: AsyncSession = DB):
    page = await M.signals(db, terc, level, _filters(subsector, value_min, value_max, year_from, year_to, q, as_of),
                           limit, offset, sort, geo)
    page["items"] = [s.model_dump() for s in page["items"]]
    return page


@router.get("/contracts/{contract_id}", summary="Jedna umowa w monitoringu")
async def contract(contract_id: int, user: A.User | None = Depends(A.current_user), db: AsyncSession = DB):
    res = await M.contract_detail(db, contract_id, can_write=user is not None and not user.read_only)
    if res is None:
        raise A.ApiError(404, "Nie ma takiej umowy.", "contract_not_found")
    res["alerts"] = (await AL.list_alerts(db, A.public_doc_filter(user, "d"), contract_id=contract_id, limit=20))["items"]
    return res


class AlertStatusIn(BaseModel):
    status: Literal["new", "seen", "closed"]


@router.get("/alerts", summary="Alerty: nowe dokumenty zmieniające umowy i projekty w realizacji")
async def alerts(status: Literal["new", "seen", "closed"] | None = None, contract_id: int | None = None,
                 project_id: int | None = None, rm_id: str | None = None, document_id: int | None = None,
                 limit: int = Query(50, le=500), offset: int = 0, user: A.User | None = Depends(A.current_user),
                 db: AsyncSession = DB):
    return await AL.list_alerts(db, A.public_doc_filter(user, "d"), status=status, contract_id=contract_id,
                                project_id=project_id, rm_id=rm_id, document_id=document_id, limit=limit, offset=offset)


@router.post("/alerts/{alert_id}/status", summary="Oznacz alert (przejrzany, zamknięty)", dependencies=[Depends(A.csrf_guard)])
async def alert_status(alert_id: int, body: AlertStatusIn, request: Request, user: A.User = Depends(A.require_writer),
                       db: AsyncSession = DB):
    res = await AL.set_status(db, alert_id, body.status, user.actor, A.request_id(request))
    if res is None:
        raise A.ApiError(404, "Nie ma takiego alertu.", "alert_not_found")
    await db.commit()
    return res


async def _audit(db: AsyncSession, actor: str, action: str, table: str, row_id: int | None, after: dict, request: Request):
    await db.execute(text("INSERT INTO audit_log (actor, action, table_name, row_id, after, request_id) "
                          "VALUES (:a, :ac, :t, :r, CAST(:after AS jsonb), :rid)"),
                     {"a": actor, "ac": action, "t": table, "r": row_id, "after": json.dumps(after, ensure_ascii=False, default=str),
                      "rid": A.request_id(request)})


@router.post("/watches", status_code=201, summary="Obserwuj umowę", dependencies=[Depends(A.csrf_guard)])
async def watch(body: WatchIn, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    c = (await db.execute(text("SELECT c.id, c.procedure_id FROM contract c WHERE c.id = :id"), {"id": body.contract_id})).first()
    if not c:
        raise A.ApiError(404, "Nie ma takiej umowy.", "contract_not_found")
    existing = (await db.execute(text("SELECT id FROM monitor_watch WHERE contract_id = :c AND active"),
                                 {"c": body.contract_id})).scalar()
    if existing:
        return {"id": existing, "contract_id": body.contract_id, "active": True}
    wid = (await db.execute(text("INSERT INTO monitor_watch (contract_id, procedure_id, reason, active) "
                                 "VALUES (:c, :p, :r, true) RETURNING id"),
                            {"c": body.contract_id, "p": c[1], "r": body.reason})).scalar()
    await _audit(db, user.actor, "monitoring.watch", "monitor_watch", wid, {"contract_id": body.contract_id, "reason": body.reason},
                 request)
    await db.commit()
    return {"id": wid, "contract_id": body.contract_id, "active": True}


@router.delete("/watches/{watch_id}", summary="Przestań obserwować", dependencies=[Depends(A.csrf_guard)])
async def unwatch(watch_id: int, request: Request, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    row = (await db.execute(text("UPDATE monitor_watch SET active = false, updated_at = now() WHERE id = :id "
                                 "RETURNING id, contract_id"), {"id": watch_id})).first()
    if not row:
        raise A.ApiError(404, "Nie ma takiej obserwacji.", "watch_not_found")
    await _audit(db, user.actor, "monitoring.unwatch", "monitor_watch", watch_id, {"active": False}, request)
    await db.commit()
    return {"id": row[0], "contract_id": row[1], "active": False}


@router.post("/contracts/{contract_id}/report-case", status_code=201, summary="Zgłoś przypadek do przeglądu",
             dependencies=[Depends(A.csrf_guard)])
async def report_case(contract_id: int, body: ReportCaseIn, request: Request, user: A.User = Depends(A.require_writer),
                      db: AsyncSession = DB):
    c = (await db.execute(text("""SELECT c.id, p.ocid, p.title, coalesce(p.buyer_name, '') buyer FROM contract c
                                  JOIN procedure p ON p.id = c.procedure_id WHERE c.id = :id"""), {"id": contract_id})).mappings().first()
    if not c:
        raise A.ApiError(404, "Nie ma takiej umowy.", "contract_not_found")
    detail = {"contract_id": contract_id, "ocid": c["ocid"], "note": body.note, "reported_by": user.actor}
    rid = (await db.execute(text("""
        INSERT INTO review_item (key, kind, code, target_table, target_id, title, detail, severity, created_by)
        VALUES (:key, 'case_candidate', 'monitoring_report', 'contract', :cid, :title, CAST(:detail AS jsonb), 'medium', :by)
        ON CONFLICT (key) DO UPDATE SET detail = EXCLUDED.detail, status = 'open', updated_at = now()
        RETURNING id"""),
        {"key": f"case|contract:{contract_id}|{user.actor}", "cid": contract_id,
         "title": f"Zgłoszony przypadek z monitoringu: {c['title'][:150] if c['title'] else c['ocid']} ({c['buyer']})",
         "detail": json.dumps(detail, ensure_ascii=False), "by": user.actor})).scalar()
    await _audit(db, user.actor, "monitoring.report_case", "review_item", rid, detail, request)
    await db.commit()
    return {"review_item_id": rid}
