"""Flow 1, Nowa inwestycja 1.1–1.5 (api_contract §2.3, §3.3; shapes follow docs/impl/frontend.md §2 plus the
api_contract fields and `prov`). Owner: session A (analytics). Pack file handlers call B's `riskminer/analysis/pack.py`.

The analysis id in every path is its record code (`AN-2026-0001`)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.analysis import service as SV
from riskminer.api.auth import ApiError, Session, User, csrf_guard, require_login, require_writer, session
from riskminer.db.session import get_session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["analyses"])


async def _warm() -> None:
    """Load the wod-kan case base and its text index without blocking the event loop (worker threads). Other
    sectors (drogi) load lazily on their first analysis, also off the loop."""
    try:
        from riskminer.analytics import similarity as SIM
        from riskminer.analytics.base import get_casebase
        from riskminer.db.session import sessionmaker
        async with sessionmaker()() as s:
            cb = await get_casebase(s)
        await asyncio.to_thread(SIM._prep, cb, False)
    except Exception:  # noqa: BLE001 - warm-up is best effort
        log.exception("analytics warm-up failed")


@router.on_event("startup")
async def _startup() -> None:
    asyncio.get_event_loop().create_task(_warm())


# ---- request models ----------------------------------------------------------------------------------------------------

class AnalysisCreateIn(BaseModel):
    text: str | None = None                 # frontend.md
    input_text: str | None = None           # api_contract
    title: str | None = None
    document_ids: list[int] = Field(default_factory=list)
    sensitivity: Literal["public", "confidential"] = "public"


class FeaturesPatchIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)      # frontend.md: {podsektor: "SAN", dlugosc_km: 6.2}
    skipped: list[str] = Field(default_factory=list)
    features: dict[str, Any] = Field(default_factory=dict)    # api_contract alias
    answers: dict[str, Any] = Field(default_factory=dict)     # api_contract alias (follow-up answers)
    text: str | None = None
    document_ids: list[int] | None = None


class ItemDecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    value: Any = None
    reason: str | None = None
    add_clause: str | None = None


class PackClauseIn(BaseModel):
    code: str
    text: str | None = None


# ---- helpers -----------------------------------------------------------------------------------------------------------

def _nf(code: str) -> ApiError:
    return ApiError(404, f"Nie znaleziono analizy {code}.", "not_found")


async def _guard_read(db: AsyncSession, code: str, sess: Session) -> dict:
    try:
        a = await SV._load(db, code)
    except SV.NotFound:
        raise _nf(code) from None
    is_user = sess.user is not None
    if not SV.can_read(a, sess.actor, is_user, is_user and sess.user.role == "admin"):
        raise ApiError(403, "To nie jest Twoja analiza.", "forbidden")
    return a


async def _guard_write(db: AsyncSession, code: str, sess: Session) -> dict:
    a = await _guard_read(db, code, sess)
    if not SV.can_write(a, sess.actor, sess.user is not None and sess.user.role == "admin"):
        raise ApiError(403, "Tylko autor analizy może ją zmieniać.", "forbidden")
    return a


def _doc_ok(sess: Session):
    """Ownership check for confidential uploads (S0's documents.upload.can_read)."""
    from riskminer.documents.upload import can_read

    def ok(doc: dict) -> bool:
        return can_read(doc, anon_id=sess.anon_id, user_actor=sess.user.actor if sess.user else None,
                        role=sess.user.role if sess.user else None)
    return ok


def _rid(request: Request) -> str | None:
    try:
        from riskminer.api.middleware import request_id_var
        rid = request_id_var.get()
    except Exception:  # noqa: BLE001 - middleware absent or var unset
        rid = None
    return rid or request.headers.get("X-Request-ID")


# ---- 1.1 ---------------------------------------------------------------------------------------------------------------

@router.post("/analyses", status_code=201, summary="Nowa analiza: cechy z opisu (regex; AI dopisuje sesja L)",
             dependencies=[Depends(csrf_guard)])
async def create_analysis(body: AnalysisCreateIn, request: Request, sess: Session = Depends(session),
                          db: AsyncSession = Depends(get_session)):
    txt = body.text if body.text is not None else (body.input_text or "")
    try:
        out = await SV.create(db, text_in=txt, document_ids=body.document_ids, title=body.title,
                              sensitivity=body.sensitivity, owner=sess.actor, actor=sess.actor,
                              request_id=_rid(request), doc_ok=_doc_ok(sess))
    except SV.Forbidden:
        raise ApiError(403, "Nie masz dostępu do jednego z dokumentów.", "document_forbidden") from None
    await db.commit()
    return out


@router.get("/analyses", summary="Moje analizy")
async def list_analyses(mine: bool = True, status: str | None = None, limit: int = Query(50, le=500), offset: int = 0,
                        sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    is_admin = sess.user is not None and sess.user.role == "admin"
    owner = sess.actor if (mine or not is_admin) else None
    return await SV.list_analyses(db, owner, status, limit, offset)


@router.get("/analyses/{code}/draft", summary="Szkic analizy: cechy i pytania uzupełniające")
async def get_draft(code: str, sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    _, d = await SV.get_draft(db, code)
    return d


@router.patch("/analyses/{code}/features", summary="Popraw cechy (nowa wersja)", dependencies=[Depends(csrf_guard)])
async def patch_features(code: str, body: FeaturesPatchIn, request: Request, sess: Session = Depends(session),
                         db: AsyncSession = Depends(get_session)):
    await _guard_write(db, code, sess)
    values = {**body.features, **body.answers, **body.values}
    try:
        out = await SV.patch_features(db, code, values, body.skipped, sess.actor, _rid(request), text_in=body.text,
                                      document_ids=body.document_ids, doc_ok=_doc_ok(sess))
    except SV.Forbidden:
        raise ApiError(403, "Nie masz dostępu do jednego z dokumentów.", "document_forbidden") from None
    await db.commit()
    return out


@router.get("/catalogue/funding-programmes", summary="Programy finansowania (założenia eksperta)")
async def funding_programmes(active: bool = True, db: AsyncSession = Depends(get_session)):
    from riskminer.analytics import catalogue
    cat = await catalogue.load(db)
    out = []
    for code, p in cat["funding"].items():
        dls = p.get("deadlines") or []
        end = str(dls[0]["date"]) if dls and dls[0].get("date") else None
        if active and not end and code not in ("OWN",):
            continue
        out.append({"code": code, "name": p.get("name"), "family": p.get("family"), "end_date": end,
                    "deadline_kind": dls[0].get("kind") if dls else None,
                    "prov": {"role": "source", "review_status": "approved" if p.get("status") == "approved"
                             else "proposed", "assumption": True,
                             "refs": [{"kind": "catalogue", "id": f"funding_programme:{code}",
                                       "label": (dls[0].get("source") if dls else None) or "Katalog"}]}})
    return out


# ---- 1.2 ---------------------------------------------------------------------------------------------------------------

@router.post("/analyses/{code}/run", summary="Policz raport dla bieżącej wersji", dependencies=[Depends(csrf_guard)])
async def run_analysis(code: str, request: Request, sess: Session = Depends(session),
                       db: AsyncSession = Depends(get_session)):
    await _guard_write(db, code, sess)
    out = await SV.run(db, code, sess.actor, _rid(request))
    await db.commit()
    return out


@router.get("/analyses/{code}", summary="Raport analizy")
async def get_analysis(code: str, version: int | None = None, sess: Session = Depends(session),
                       db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.get_report(db, code, version)
    except SV.NotFound:
        raise ApiError(404, f"Nie ma wersji {version} analizy {code}.", "not_found") from None


@router.get("/analyses/{code}/versions", summary="Wersje analizy")
async def analysis_versions(code: str, sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    return await SV.versions(db, code)


@router.get("/analyses/{code}/reference-class/contracts", summary="Umowy klasy porównawczej")
async def reference_class_contracts(code: str, step: str = "final", limit: int = Query(50, le=500), offset: int = 0,
                                    sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.reference_class_contracts(db, code, limit, offset)
    except SV.NotFound:
        raise ApiError(409, "Najpierw uruchom analizę.", "not_run") from None


@router.post("/analyses/{code}/pack/clauses", summary="Dodaj zapis do pakietu", dependencies=[Depends(csrf_guard)])
async def add_pack_clause(code: str, body: PackClauseIn, request: Request, sess: Session = Depends(session),
                          db: AsyncSession = Depends(get_session)):
    await _guard_write(db, code, sess)
    out = await SV.add_pack_clause(db, code, body.code, body.text, sess.actor, _rid(request))
    await db.commit()
    return out


# ---- 1.3 (Red Pen data comes from session L's scan job; page text is real) ---------------------------------------------

@router.get("/analyses/{code}/redpen/{document_id}", summary="Czerwony długopis: uwagi i braki w dokumencie")
async def redpen(code: str, document_id: int, pages: Literal["with_notes", "all"] = "all",
                 sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.redpen(db, code, document_id, pages == "with_notes")
    except SV.NotFound:
        raise ApiError(404, "Ten dokument nie należy do analizy.", "not_found") from None
    except SV.SovereignUnavailable:
        raise ApiError(503, "Model w Polsce jest teraz niedostępny. Poufnych danych nie wysyłamy do chmury, więc "
                       "ta część analizy AI jest wstrzymana. Spróbuj ponownie później.",
                       "sovereign_unavailable") from None


@router.post("/analyses/{code}/items/{item_id}/decision", summary="Decyzja właściciela analizy o pozycji AI",
             dependencies=[Depends(csrf_guard)])
async def item_decision(code: str, item_id: int, body: ItemDecisionIn, request: Request,
                        sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_write(db, code, sess)
    if body.action == "reject" and not body.reason:
        raise ApiError(422, "Podaj powód odrzucenia.", "reason_required")
    try:
        out = await SV.item_decision(db, code, item_id, body.action, body.value, body.reason, body.add_clause,
                                     sess.actor, _rid(request))
    except SV.NotFound:
        raise ApiError(404, "Nie ma takiej pozycji w analizie.", "not_found") from None
    except SV.Protected:
        raise ApiError(409, "Ta pozycja została już zatwierdzona i jest chroniona.", "protected_row") from None
    await db.commit()
    return out


# ---- 1.4 / 1.5 --------------------------------------------------------------------------------------------------------

class AllocationIn(BaseModel):
    choices: dict[str, int | Literal["buyer", "shared", "contractor"]]


def _not_ready(code: str) -> ApiError:
    return ApiError(409, "Najpierw uruchom analizę.", "not_run")


@router.get("/analyses/{code}/simulation", summary="Symulacja: wszystkie kombinacje zmian, trzy miary (1.4)")
async def get_simulation(code: str, sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.simulation(db, code)
    except SV.NotReady:
        raise _not_ready(code) from None


@router.post("/analyses/{code}/simulate", summary="Symulacja Monte Carlo (alias: ten sam wynik co GET /simulation)")
async def simulate(code: str, body: dict | None = None, sess: Session = Depends(session),
                   db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.simulation(db, code)
    except SV.NotReady:
        raise _not_ready(code) from None


@router.get("/analyses/{code}/allocation", summary="Podział ryzyk")
async def get_allocation(code: str, sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    await _guard_read(db, code, sess)
    try:
        return await SV.allocation(db, code)
    except SV.NotReady:
        raise _not_ready(code) from None


@router.put("/analyses/{code}/allocation", summary="Zapisz podział ryzyk", dependencies=[Depends(csrf_guard)])
async def put_allocation(code: str, body: AllocationIn, request: Request, sess: Session = Depends(session),
                         db: AsyncSession = Depends(get_session)):
    await _guard_write(db, code, sess)
    try:
        out = await SV.put_allocation(db, code, body.choices, sess.actor, _rid(request))
    except SV.NotReady:
        raise _not_ready(code) from None
    except ValueError:
        raise ApiError(422, "Nieznana pozycja w podziale ryzyk.", "invalid_choice") from None
    await db.commit()
    return out


@router.get("/analyses/{code}/pack", summary="Zawartość pakietu do akt")
async def pack(code: str, version: int | None = None, sess: Session = Depends(session),
               db: AsyncSession = Depends(get_session)):
    from riskminer.analysis import pack as PK
    await _guard_read(db, code, sess)
    rep = await SV.get_report(db, code, version)
    if rep.get("status") != "ready":
        raise ApiError(409, "Najpierw uruchom analizę.", "not_run")
    return PK.manifest(rep)


@router.get("/analyses/{code}/pack.{fmt}", summary="Pakiet do akt: DOCX, PDF, CSV lub JSON")
async def pack_file(code: str, fmt: Literal["docx", "pdf", "csv", "json"], version: int | None = None,
                    sess: Session = Depends(session), db: AsyncSession = Depends(get_session)):
    from fastapi.responses import FileResponse

    from riskminer.analysis import pack as PK
    await _guard_read(db, code, sess)
    pf = await PK.render(db, code, fmt, version)
    return FileResponse(pf.path, filename=pf.filename, media_type=pf.media_type)


# ---- affected analyses (new documents pipeline, step 8) ------------------------------------------------------------

class AffectedIn(BaseModel):
    rm_id: str | None = None
    ocid: str | None = None
    reason: str = "nowe dane w przypadku podobnym"
    document_id: int | None = None


@router.get("/analyses-affected", summary="Analizy, w których ten przypadek jest podobny")
async def analyses_affected(rm_id: str | None = None, ocid: str | None = None, _u: User = Depends(require_login),
                            db: AsyncSession = Depends(get_session)):
    rows = await SV.affected(db, rm_id, ocid)
    return {"items": [{"code": r["code"], "title": r["title"], "case": r["case_title"]} for r in rows]}


@router.post("/analyses-affected", summary="Oznacz analizy: nowe dane w przypadku podobnym (ekspert)",
             dependencies=[Depends(csrf_guard)])
async def mark_analyses_affected(body: AffectedIn, request: Request, user: User = Depends(require_writer),
                                 db: AsyncSession = Depends(get_session)):
    marked = await SV.mark_affected(db, rm_id=body.rm_id, ocid=body.ocid, reason=body.reason, actor=user.actor,
                                    document_id=body.document_id, request_id=_rid(request))
    await db.commit()
    return {"marked": marked, "n": len(marked)}


# ---- national analytics (read-only; Pulpit, pitch, A6 chips) -----------------------------------------------------------

@router.get("/analytics/headline", summary="Liczby krajowe: opóźnienia, dopłaty, zmiany (obliczenie)")
async def analytics_headline(db: AsyncSession = Depends(get_session)):
    from riskminer.analytics.base import get_casebase
    from riskminer.analytics.headline import headline
    return headline(await get_casebase(db))


@router.get("/analytics/tenders", summary="Wyniki przetargów wod-kan według roku")
async def analytics_tenders(subsector: str | None = None, db: AsyncSession = Depends(get_session)):
    from riskminer.analytics.base import get_casebase
    from riskminer.analytics.competition import tenders_by_year
    return {"subsector": subsector, "years": tenders_by_year(await get_casebase(db), subsector)}


@router.get("/analytics/unit-cost", summary="Koszt kilometra sieci: percentyle i pozycja Twojej kwoty")
async def analytics_unit_cost(subsector: Literal["SAN", "WOD", "DESZ"] = "SAN", budget: float | None = None,
                              length_km: float | None = None, index_to: int | None = None,
                              db: AsyncSession = Depends(get_session)):
    from riskminer.analytics import unit_cost as U
    from riskminer.analytics.base import get_casebase
    u = U.unit_cost(await get_casebase(db), subsector, budget, length_km, index_to)
    if u is None:
        raise ApiError(404, "Brak danych o koszcie kilometra.", "no_data")
    return {"subsector": u.subsector, "user_ppk": u.user_ppk, "q": u.q, "user_percentile": u.user_percentile,
            "n": u.n, "coverage": u.coverage, "length_source": u.length_source, "indexed_to": u.indexed_to,
            "sample": u.sample,
            "prov": {"role": "calc", "review_status": "auto", "n": u.n, "method": "unit_cost_percentile",
                     "refs": [{"kind": "query", "id": f"rc:{subsector}|length_km", "label": "umowy z długością sieci"}]}}


@router.get("/analytics/backtest", summary="Sprawdzian prognoz na umowach zakończonych od 2024 r. (W3)")
async def analytics_backtest(db: AsyncSession = Depends(get_session)):
    from riskminer.analytics.backtest import backtest
    from riskminer.analytics.base import get_casebase
    return backtest(await get_casebase(db))
