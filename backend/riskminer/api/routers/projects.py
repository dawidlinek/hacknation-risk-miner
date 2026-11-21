"""Projects 2.2-2.6: stats, card, similar, graph, link correction, documents view, history (api_contract §2.4). Session B.
The projects list itself is in `routers/data.py` (EXTEND with metrics)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api import project_graph as PG
from riskminer.api import project_views as PV
from riskminer.api import projects_read as PR
from riskminer.api.fixtures import fixture
from riskminer.api.prov import SimilarCase
from riskminer.api.schemas_review import LinkIn
from riskminer.db.session import get_session
from riskminer.review import service

router = APIRouter(prefix="/api", tags=["projects"])
DB = Depends(get_session)
LOGIN = Depends(A.require_login)


def _nf(what: str = "projekt"):
    return A.ApiError(404, "Nie ma takiego projektu." if what == "projekt" else "Nie znaleziono.", "not_found")


@router.get("/projects/stats", summary="Statystyki listy projektów (te same filtry co lista)")
async def projects_stats(q: str | None = None, province: str | None = None, subsector: str | None = None,
                         late: bool | None = None, has_discrepancy: bool | None = None, to_review: bool | None = None,
                         contractor_nip: str | None = None, rm_ids: str | None = None,
                         db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    return await PR.stats(db, user, q=q, province=province, subsector=subsector, late=late, has_discrepancy=has_discrepancy,
                          to_review=to_review, contractor_nip=contractor_nip, rm_ids=rm_ids)


@router.get("/projects/national", summary="Wszystkie postępowania wod-kan w Polsce (strona po stronie, filtry, sortowanie)")
async def projects_national(q: str | None = Query(None, max_length=120), woj: str | None = Query(None, pattern=r"^\d{2}$"),
                            status: Literal["all", "completed", "ongoing", "none"] = "all",
                            year_from: int | None = Query(None, ge=1990, le=2100), year_to: int | None = Query(None, ge=1990, le=2100),
                            relevance: Literal["core", "component", "all"] = "core",
                            sort: Literal["delay", "-delay", "delay_asc", "value", "-value", "value_asc", "signed", "-signed", "signed_asc"] = "-signed",
                            page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), db: AsyncSession = DB):
    from riskminer.api import projects_national as PN
    return await PN.list_national(db, q=q, woj=woj, status=status, year_from=year_from, year_to=year_to, relevance=relevance,
                                  sort=sort, page=page, page_size=page_size)


@router.get("/projects/{rm_id}/card", summary="Karta projektu: plan i wykonanie, zdarzenia, luki")
async def project_card(rm_id: str, db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    out = await PV.card(db, rm_id, user)
    if out is None:
        raise _nf()
    return out


@router.get("/projects/{rm_id}/export.{fmt}", summary="Eksport rekordu projektu: JSON, Markdown, DOCX albo PDF",
            description="Identyfikacja i finansowanie, powiązanie z BZP (metoda, wynik, cechy), plan i wykonanie z podstawą VAT, zmiany umowy, "
                        "zdarzenia ryzyka z kodami R i dowodami, propozycje AI oznaczone jako propozycje, dokumenty i „Co się zmieniło”, "
                        "lista źródeł (URL, data pobrania, sha256). Widok publiczny bez niezweryfikowanych propozycji AI.")
async def project_export(rm_id: str, fmt: Literal["json", "md", "docx", "pdf"], db: AsyncSession = DB,
                         user: A.User | None = Depends(A.current_user)):
    from fastapi.responses import Response

    from riskminer.api import project_export as PE
    try:
        data, name, media = await PE.render(db, rm_id, fmt, user)
    except PE.NotFound:
        raise _nf() from None
    except Exception as e:  # noqa: BLE001 - e.g. LibreOffice missing for PDF: say so instead of a bare 500
        from riskminer.documents.convert import ConvertError
        if isinstance(e, ConvertError):
            raise A.ApiError(503, "Nie udało się przygotować PDF (konwerter niedostępny). Pobierz DOCX albo Markdown.", "convert_failed") from None
        raise
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/projects/{rm_id}/similar", response_model=list[SimilarCase], summary="Podobne przypadki")
async def project_similar(rm_id: str, k: int = Query(5, le=20), db: AsyncSession = DB):
    return await PV.similar_cases(db, rm_id, k)


@router.get("/projects/{rm_id}/graph", summary="Graf powiązań (Sankey: źródła, fakty, wnioski)")
async def project_graph(rm_id: str, include_proposed: bool = True, db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    out = await PG.graph(db, rm_id, user, include_proposed and user is not None)
    if out is None:
        raise _nf()
    return out


@router.post("/projects/{rm_id}/links", summary="Popraw powiązanie z postępowaniem BZP (ekspert)")
async def project_links(rm_id: str, body: LinkIn, user: A.User = Depends(A.require_writer), db: AsyncSession = DB):
    out = await service.link_correct(db, rm_id=rm_id, action=body.action, bzp_number=body.bzp_number, lots=body.lots or None,
                                     reason=body.reason, actor=user.actor, request_id=A.request_id())
    out.pop("_changes", None)
    await db.commit()
    return out


@router.get("/projects/{rm_id}/documents", summary="Dokumenty projektu: oczekiwane, publiczne, posiadane")
async def project_documents(rm_id: str, db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    out = await PV.documents_view(db, rm_id, user)
    if out is None:
        raise _nf()
    return out


@router.get("/notices/{object_id}/facts", summary="Fakty z ogłoszenia (pola wg kodów)")
async def notice_facts(object_id: str, db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    out = await PV.notice_facts(db, object_id, user)
    if out is None:
        raise _nf("ogłoszenie")
    return out


@router.get("/projects/{rm_id}/history", summary="Historia zmian rekordu projektu", dependencies=[LOGIN])
async def project_history(rm_id: str, actor_kind: Literal["expert", "model", "system"] | None = None, db: AsyncSession = DB):
    out = await PV.history(db, rm_id, actor_kind)
    if out is None:
        raise _nf()
    return out


@router.get("/projects/{rm_id}/history/compare", summary="Porównaj dwie wersje rekordu", dependencies=[LOGIN])
async def history_compare(rm_id: str, from_: str = Query(..., alias="from"), to: str = Query(...), db: AsyncSession = DB):
    out = await PV.history_compare(db, rm_id, from_, to)
    if out is None:
        raise _nf()
    return out


# ------------------------------------------------------------------------------------------- new documents (G3, G4, G5)

STEP_LABEL = {"upload": "Wczytanie pliku", "ocr": "Rozpoznanie tekstu (OCR)", "extraction": "Odczyt faktów", "linking": "Powiązanie z projektem i umową"}
JOB_STEP = {"doc_text": "ocr", "document_ocr": "ocr", "document_extract": "extraction", "extract_events": "extraction", "document_link": "linking"}


async def _doc_for(db: AsyncSession, document_id: int, sess: A.Session) -> dict:
    from sqlalchemy import text as _t
    from riskminer.documents.upload import can_read
    r = (await db.execute(_t("SELECT * FROM document WHERE id = :i"), {"i": document_id})).mappings().first()
    if r is None or not can_read(dict(r), anon_id=sess.anon_id, user_actor=sess.user.actor if sess.user else None, role=sess.user.role if sess.user else None):
        raise A.ApiError(404, "Nie ma takiego dokumentu.", "not_found")  # confidential documents of others look absent
    return dict(r)


@router.get("/documents/{document_id}/analysis", summary="Dokument: etapy przetwarzania, wyczytane fakty z cytatami, powiązania i sprawy do przeglądu")
async def document_analysis(document_id: int, db: AsyncSession = DB, sess: A.Session = Depends(A.session)):
    from sqlalchemy import text as _t
    doc = await _doc_for(db, document_id, sess)
    data = doc.get("data") or {}
    facts, link = data.get("facts"), data.get("link")
    jobs = [dict(r) for r in (await db.execute(_t("""SELECT id, kind, status, error, finished_at FROM job WHERE payload->>'document_id' = :d
                                                     AND kind IN ('doc_text','document_ocr','document_extract','extract_events','document_link') ORDER BY id"""),
                                              {"d": str(document_id)})).mappings().all()]

    def job_state(step: str) -> tuple[str, str | None]:
        js = [j for j in jobs if JOB_STEP[j["kind"]] == step]
        if not js:
            return "pending", None
        last = js[-1]
        return {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "cancelled": "failed"}.get(last["status"], "pending"), last["error"]
    needs_ocr = bool(data.get("needs_ocr")) and not data.get("ocr_text_path") and not doc.get("ocr")
    ocr_state, ocr_err = job_state("ocr")
    steps = [{"key": "upload", "label": STEP_LABEL["upload"], "state": "done", "detail": f"{doc.get('pages') or 0} str."},
             {"key": "ocr", "label": STEP_LABEL["ocr"], "state": ("done" if not needs_ocr else ocr_state), "detail": "dokument ma warstwę tekstu" if not needs_ocr and not doc.get("ocr") else None,
              "error": ocr_err},
             {"key": "extraction", "label": STEP_LABEL["extraction"], "state": "done" if facts else job_state("extraction")[0], "error": job_state("extraction")[1]},
             {"key": "linking", "label": STEP_LABEL["linking"], "state": "done" if link else job_state("linking")[0], "error": job_state("linking")[1]}]
    items = []
    if link:
        items = [dict(r) for r in (await db.execute(_t("SELECT id, kind, title, status FROM review_item WHERE id = ANY(:i) ORDER BY id"),
                                                    {"i": link.get("review_items") or [0]})).mappings().all()] if sess.user else []
    from riskminer.review import doclink
    growth = await doclink.growth(db, document_id) if link else None
    return {"growth": growth, "document": {"id": doc["id"], "filename": doc.get("filename"), "title": doc.get("title"), "sensitivity": doc.get("sensitivity"), "pages": doc.get("pages"),
                         "doc_kind_label": (facts or {}).get("doc_kind_label"), "doc_date": (facts or {}).get("doc_date"), "level": (facts or {}).get("level")},
            "steps": steps, "facts": (facts or {}).get("facts") or [], "causes": (facts or {}).get("causes") or [], "effects": (facts or {}).get("effects") or [],
            "change": (facts or {}).get("change"), "flags": (facts or {}).get("flags") or [], "processing": (facts or {}).get("processing") or [],
            "link": link, "review_items": [{**i, "href": f"/przeglad?sprawa={i['id']}"} for i in items],
            "project_rm_id": ((link or {}).get("project") or {}).get("rm_id")}


@router.post("/documents/{document_id}/link", summary="Powiąż dokument z projektem i umową oraz zwaliduj identyfikatory (propozycje do przeglądu)")
async def document_link(document_id: int, user: A.User = Depends(A.require_writer), db: AsyncSession = DB, sess: A.Session = Depends(A.session)):
    from riskminer.review import doclink
    await _doc_for(db, document_id, sess)
    out = await doclink.link_document(db, document_id, actor=user.actor, request_id=A.request_id())
    await db.commit()
    return out


@router.get("/projects/{rm_id}/changes-since", summary="Co się zmieniło po nowym dokumencie: potwierdzone, zmienione, nowe, zamknięte")
async def changes_since(rm_id: str, document_id: int, db: AsyncSession = DB, sess: A.Session = Depends(A.session)):
    from riskminer.review import doclink
    await _doc_for(db, document_id, sess)
    out = await doclink.changes_since(db, rm_id, document_id)
    if sess.user is None:
        out["review_items"] = []  # the queue is internal
    return out
