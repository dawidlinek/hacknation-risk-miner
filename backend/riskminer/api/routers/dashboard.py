"""Pulpit: dashboard tiles, nav badges, national headline (api_contract §2.1, §2.2). Session B.
Every tile value is a Num with provenance (calc, n = rows counted)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api.prov import Num, Prov, fmt_num, num_calc, q_ref
from riskminer.db.session import get_session

router = APIRouter(prefix="/api", tags=["dashboard"])
DB = Depends(get_session)

# "Nowe sygnały": contracts that became overdue within the last 7 days (no seen-state table, so recency is the rule).
NEW_SIGNALS_SQL = "SELECT count(*) FROM v_monitor_signal WHERE days_overdue BETWEEN 1 AND 7"
KIND_PL = {"event": "zdarzeń", "link": "powiązań", "discrepancy": "rozbieżności", "fact": "faktów", "catalogue": "propozycji do katalogu"}
SOURCE_LABELS = {
    "bzp_copy": ("BZP: kopia ogłoszeń", "ogłoszenia o zamówieniu, wyniku, zmianie i wykonaniu umowy"),
    "bzp_api": ("BZP: bieżące ogłoszenia", "ogłoszenia pobrane z API e-Zamówień"),
    "xlsx": ("Zestaw organizatora", "22 projekty pilotażowe z wartościami i numerami"),
    "ted": ("TED", "ogłoszenia europejskie z przyczynami zmian umów"),
    "kio": ("KIO", "orzeczenia Krajowej Izby Odwoławczej"),
    "nik": ("NIK", "kontrole Najwyższej Izby Kontroli"),
    "cru": ("Centralny Rejestr Umów", "umowy z rejestru, część ze zmianami"),
    "mapa_dotacji": ("Mapa Dotacji", "dofinansowanie projektów"),
    "docs_22": ("Dokumenty projektów", "SWZ, PPU i inne pliki z postępowań pilotażowych"),
}


def _count(value: int, n: int, method: str, ref_id: str, label: str) -> dict:
    return Num(value=value, display=fmt_num(value), unit="count",
               prov=Prov(role="calc", review_status="auto", n=n, method=method, refs=[q_ref(ref_id, label)])).model_dump(mode="json")


@router.get("/nav/counts", summary="Liczniki w nawigacji (przegląd, monitoring)")
async def nav_counts(_u: A.User = Depends(A.require_login), db: AsyncSession = DB):
    review_open = (await db.execute(text("SELECT count(*) FROM review_item WHERE status = 'open'"))).scalar() or 0
    monitoring_new = 0
    if (await db.execute(text("SELECT to_regclass('v_monitor_signal') IS NOT NULL"))).scalar():
        monitoring_new = (await db.execute(text(NEW_SIGNALS_SQL))).scalar() or 0
    return {"review_open": review_open, "monitoring_new": monitoring_new}


@router.get("/dashboard", summary="Pulpit eksperta: kafle, źródła, rozbieżności")
async def dashboard(user: A.User = Depends(A.require_login), db: AsyncSession = DB):
    kinds = {k: n for k, n in (await db.execute(text("SELECT kind, count(*) FROM review_item WHERE status='open' GROUP BY 1"))).all()}
    total = sum(kinds.values())
    sub = ", ".join(f"{n} {KIND_PL.get(k, k)}" for k, n in sorted(kinds.items(), key=lambda x: -x[1]))
    mon = 0
    if (await db.execute(text("SELECT to_regclass('v_monitor_signal') IS NOT NULL"))).scalar():
        mon = (await db.execute(text(NEW_SIGNALS_SQL))).scalar() or 0
    mine = (await db.execute(text("SELECT code, status FROM analysis WHERE owner = :o OR created_by = :o ORDER BY updated_at DESC LIMIT 5"),
                             {"o": user.actor})).all() if (await db.execute(text("SELECT to_regclass('analysis') IS NOT NULL"))).scalar() else []
    tiles = [
        {"key": "review_open", "label": "Czeka na Twoją decyzję", "value": _count(total, total, "count", "review_item:open", "kolejka"),
         "sub": sub or "kolejka jest pusta", "href": "/przeglad", "attention": total > 0},
        {"key": "monitoring_new", "label": "Nowe sygnały w monitoringu", "value": _count(mon, mon, "count", "v_monitor_signal:new7", "umowy po terminie do 7 dni, bez ogłoszenia o wykonaniu"),
         "sub": "nowe w ostatnim tygodniu: umowy po terminie bez ogłoszenia o wykonaniu", "href": "/monitoring", "attention": mon > 0},
        {"key": "my_analyses", "label": "Twoje analizy", "value": _count(len(mine), len(mine), "count", "analysis:mine", "analizy użytkownika"),
         "sub": ", ".join(f"{c} {s}" for c, s in mine[:3]) or "brak analiz", "href": "/analizy", "attention": False},
    ]
    rs = (await db.execute(text("""SELECT s.kind, count(*) AS files, count(*) FILTER (WHERE s.status='ok') AS ok, count(*) FILTER (WHERE s.status='blocked') AS blocked,
                                          max(s.retrieved_at) AS last_at FROM source s GROUP BY s.kind ORDER BY count(*) DESC"""))).mappings().all()
    recs = {k: n for k, n in (await db.execute(text("SELECT source_kind, count(*) FROM external_record GROUP BY 1"))).all()}
    recs["bzp_copy"] = (await db.execute(text("SELECT count(*) FROM notice WHERE channel='bzp_copy'"))).scalar()
    recs["bzp_api"] = (await db.execute(text("SELECT count(*) FROM notice WHERE channel='bzp_api'"))).scalar()
    recs["xlsx"] = (await db.execute(text("SELECT count(*) FROM project WHERE is_pilot"))).scalar()
    sources = []
    for r in rs:
        if r["kind"] not in SOURCE_LABELS:
            continue
        label, what = SOURCE_LABELS[r["kind"]]
        n = recs.get(r["kind"]) or r["ok"]
        sources.append({"kind": r["kind"], "label": label, "what": what, "count_label": f"{fmt_num(n)} rekordów" if r["kind"] != "bzp_copy" else f"{fmt_num(n)} ogłoszeń",
                        "last_retrieved_at": r["last_at"].isoformat() if r["last_at"] else None,
                        "state": "blocked" if r["blocked"] and not r["ok"] else ("ok" if r["ok"] else "pending")})
    issues = [dict(r) for r in (await db.execute(text("""SELECT r.id, p.rm_id, r.code, r.title FROM review_item r LEFT JOIN project p ON p.id = r.project_id
                                                          WHERE r.status='open' AND r.kind='discrepancy' ORDER BY r.severity='low', r.id LIMIT 4"""))).mappings().all()]
    return {"tiles": tiles, "sources": sources, "issues": issues}


@router.get("/national/headline", summary="Zdanie krajowe: ile umów skończyło się po terminie")
async def national_headline(sector: str = Query("wod-kan"), db: AsyncSession = DB):
    """Numbers come from the analytics engine (same case base as the reports, one source of truth); `ongoing_overdue_90` from the monitor view."""
    from riskminer.analytics.base import get_casebase
    from riskminer.analytics.headline import headline
    h = headline(await get_casebase(db))
    od90 = 0
    if (await db.execute(text("SELECT to_regclass('v_monitor_signal') IS NOT NULL"))).scalar():
        od90 = (await db.execute(text("SELECT count(*) FROM v_monitor_signal WHERE days_overdue > 90"))).scalar() or 0
    h["ongoing_overdue_90"] = num_calc(od90, fmt_num(od90), "count", n=max(od90, 10), method="count(days_overdue > 90)",
                                       refs=[q_ref("v_monitor_signal", "umowy bez ogłoszenia o wykonaniu po terminie")]).model_dump(mode="json")
    h["as_of"] = str(h.get("data_as_of") or "")[:10] or None
    return h


# ---------------------------------------------------------------------------------------------------- demo reset (admin)

class DemoResetIn(BaseModel):
    dry_run: bool = False


@router.post("/admin/demo-baseline", summary="DEMO: zapisz stan wyjściowy (admin)")
async def demo_baseline(user: A.User = Depends(A.require_admin), db: AsyncSession = DB):
    from riskminer.review import demo
    out = await demo.set_baseline(db, user.actor, A.request_id())
    await db.commit()
    return out


@router.get("/admin/demo-status", summary="DEMO: stan wyjściowy i liczba decyzji od tego czasu (admin)")
async def demo_status(user: A.User = Depends(A.require_admin), db: AsyncSession = DB):
    from riskminer.review import demo
    return await demo.status(db)


@router.post("/admin/demo-reset", summary="DEMO: cofnij decyzje podjęte po stanie wyjściowym (admin, dopisuje wpisy, niczego nie usuwa)")
async def demo_reset(body: DemoResetIn | None = None, user: A.User = Depends(A.require_admin), db: AsyncSession = DB):
    from riskminer.review import demo
    out = await demo.reset(db, user.actor, dry_run=bool(body and body.dry_run), request_id=A.request_id())
    await db.commit()
    return out
