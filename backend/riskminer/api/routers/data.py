"""Read API: projects, procedures (chain/timeline), notices, contracts, changes, performance,
organizations, sources, runs, jobs, link candidates, review items, evidence, external records."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import deps as D
from riskminer.api import schemas as S
from riskminer.db.session import get_session

router = APIRouter(prefix="/api", tags=["data"])
DB = Depends(get_session)


def _page(total, limit, offset, items):
    return {"total": total or 0, "limit": limit, "offset": offset, "items": items}


# ------------------------------------------------------------------------------------------ stats

@router.get("/stats", response_model=S.StatsOut, summary="Liczniki: tabele, ogłoszenia, źródła, ostatnie przebiegi")
async def stats(db: AsyncSession = DB):
    tables = {}
    for t in ("project", "organization", "procedure", "notice", "lot", "contract", "contract_change",
              "contract_performance", "document", "document_page", "chunk", "evidence", "external_record", "source_check", "link_candidate",
              "review_item", "source", "ingestion_run", "job", "risk_event", "catalogue_risk"):
        tables[t] = await D.scalar(db, f"SELECT count(*) FROM {t}")
    by_type = {r["k"]: r["n"] for r in await D.rows(db, "SELECT notice_type k, count(*) n FROM notice GROUP BY 1")}
    by_ch = {r["k"]: r["n"] for r in await D.rows(db, "SELECT channel k, count(*) n FROM notice GROUP BY 1")}
    by_rel = {str(r["k"]): r["n"] for r in await D.rows(db, "SELECT relevance k, count(*) n FROM procedure GROUP BY 1")}
    pilot = await D.one(db, """SELECT count(*) AS projects,
        count(*) FILTER (WHERE EXISTS (SELECT 1 FROM project_procedure pp WHERE pp.project_id=p.id)) AS linked,
        (SELECT count(*) FROM review_item r WHERE r.project_id IS NOT NULL AND r.status='open') AS open_issues
        FROM project p WHERE is_pilot""")
    return S.StatsOut(tables=tables, notices_by_type=by_type, notices_by_channel=by_ch, procedures_by_relevance=by_rel,
                      pilot=pilot or {}, sources=await _source_summary(db),
                      last_runs=[S.RunOut(**r) for r in await D.rows(
                          db, "SELECT * FROM ingestion_run ORDER BY started_at DESC LIMIT 20")])


async def _source_summary(db) -> list[S.SourceSummaryOut]:
    rs = await D.rows(db, """
        SELECT s.kind, count(*) files, count(*) FILTER (WHERE status='ok') ok, count(*) FILTER (WHERE status='empty') empty,
               count(*) FILTER (WHERE status='blocked') blocked, count(*) FILTER (WHERE status='error') error,
               coalesce(sum(bytes),0)::bigint bytes, max(retrieved_at) last_retrieved_at, max(licence) licence
        FROM source s GROUP BY s.kind ORDER BY s.kind""")
    rec = {r["k"]: r["n"] for r in await D.rows(db, "SELECT source_kind k, count(*) n FROM external_record GROUP BY 1")}
    rec["bzp_copy"] = await D.scalar(db, "SELECT count(*) FROM notice WHERE channel='bzp_copy'")
    rec["bzp_api"] = await D.scalar(db, "SELECT count(*) FROM notice WHERE channel='bzp_api'")
    rec["xlsx"] = await D.scalar(db, "SELECT count(*) FROM project WHERE is_pilot")
    docs = {r["k"]: r["n"] for r in await D.rows(db, "SELECT split_part(data->>'source','|',1) k, count(*) n FROM document GROUP BY 1")}
    out = []
    for r in rs:
        out.append(S.SourceSummaryOut(**r, records=int(rec.get(r["kind"], 0) or 0) + int(docs.get(r["kind"], 0) or 0)))
    return out


@router.get("/sources/summary", response_model=list[S.SourceSummaryOut], summary="Podsumowanie per źródło")
async def sources_summary(db: AsyncSession = DB):
    return await _source_summary(db)


# --------------------------------------------------------------------------------------- projects

_PROJECT_SQL = """
SELECT p.*,
  (SELECT array_agg(pr.ocid ORDER BY pp.score DESC NULLS LAST) FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id
     WHERE pp.project_id=p.id) AS procedures,
  (SELECT pp.method FROM project_procedure pp WHERE pp.project_id=p.id ORDER BY pp.score DESC NULLS LAST LIMIT 1) AS link_method,
  (SELECT pp.score FROM project_procedure pp WHERE pp.project_id=p.id ORDER BY pp.score DESC NULLS LAST LIMIT 1) AS link_score,
  (SELECT count(*) FROM review_item r WHERE r.project_id=p.id AND r.status='open') AS open_issues
FROM project p
"""


@router.get("/projects", response_model=S.Page[S.ProjectOut], summary="Projekty (filtry: q, województwo, podsektor, pilot)")
async def list_projects(q: str | None = None, province: str | None = None, subsector: str | None = None,
                        pilot: bool | None = None, limit: int = Query(100, le=1000), offset: int = 0,
                        db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if q:
        where.append("(p.title ILIKE :q OR p.beneficiary_name ILIKE :q OR p.rm_id ILIKE :q OR p.public_id ILIKE :q)")
        params["q"] = f"%{q}%"
    if province:
        where.append("p.province = :province")
        params["province"] = province
    if subsector:
        where.append("(p.subsector_main = :sub OR :sub = ANY(p.subsectors_extra))")
        params["sub"] = subsector
    if pilot is not None:
        where.append("p.is_pilot = :pilot")
        params["pilot"] = pilot
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM project p WHERE {w}", **params)
    rs = await D.rows(db, f"{_PROJECT_SQL} WHERE {w} ORDER BY p.rm_id LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.project(r) for r in rs])


@router.get("/projects/{rm_id}", response_model=S.ProjectDetailOut,
            summary="Karta projektu: powiązania, łańcuch ogłoszeń, umowy, zmiany, wykonanie, rozbieżności, źródła")
async def get_project(rm_id: str, db: AsyncSession = DB):
    r = await D.one(db, f"{_PROJECT_SQL} WHERE p.rm_id = :rm", rm=rm_id)
    if not r:
        raise HTTPException(404, "project not found")
    base = D.project(r).model_dump()
    o = await D.one(db, "SELECT * FROM organization WHERE id = :id", id=r["beneficiary_org_id"]) if r["beneficiary_org_id"] else None
    links = await D.rows(db, """SELECT pp.*, pr.ocid FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id
                                WHERE pp.project_id=:id ORDER BY pp.score DESC NULLS LAST""", id=r["id"])
    cands = await D.rows(db, "SELECT * FROM link_candidate WHERE left_table='project' AND left_id=:id AND right_table='procedure' "
                             "ORDER BY rank NULLS LAST, score DESC", id=r["id"])
    ext_links = await D.rows(db, "SELECT * FROM link_candidate WHERE left_table='project' AND left_id=:id AND right_table<>'procedure' "
                                 "ORDER BY score DESC", id=r["id"])
    procs = [await _procedure_detail(db, l["ocid"]) for l in links]
    issues = await D.rows(db, "SELECT r.*, :rm AS rm_id FROM review_item r WHERE project_id=:id ORDER BY severity, id",
                          id=r["id"], rm=rm_id)
    checks = await D.rows(db, "SELECT * FROM source_check WHERE subject_type='project' AND subject_key=:rm ORDER BY source_kind",
                          rm=rm_id)
    docs = await D.rows(db, "SELECT * FROM document WHERE project_id=:id ORDER BY doc_type, id", id=r["id"])
    evs = await D.rows(db, "SELECT * FROM risk_event WHERE project_id=:id ORDER BY occurred_on NULLS LAST, id", id=r["id"])
    return S.ProjectDetailOut(
        risk_events=[D.risk_event(e) for e in evs],
        **base, organization=D.org(o) if o else None,
        links=[S.ProjectLinkOut(procedure_id=l["procedure_id"], ocid=l["ocid"], method=l["method"], score=l["score"],
                                explanation=l["explanation"] or {}, lots=l["lots"] or [], review_status=l["review_status"])
               for l in links],
        link_candidates=[S.LinkCandidateOut(**c) for c in cands], procedure_details=procs,
        review_items=[S.ReviewItemOut(**i) for i in issues], source_checks=[S.SourceCheckOut(**c) for c in checks],
        documents=[D.document(d) for d in docs], external_links=[S.LinkCandidateOut(**c) for c in ext_links],
        dataset_row=r.get("dataset_row"))


@router.get("/projects/{rm_id}/timeline", response_model=list[S.TimelineEvent], summary="Przebieg projektu (oś czasu)")
async def project_timeline(rm_id: str, db: AsyncSession = DB):
    p = await get_project(rm_id, db)
    ev: list[S.TimelineEvent] = []
    for pd in p.procedure_details:
        ev.extend(pd.timeline)
    return sorted(ev, key=lambda e: (str(e.date or ""), e.kind))


# ------------------------------------------------------------------------------------- procedures

@router.get("/procedures", response_model=S.Page[S.ProcedureOut],
            summary="Postępowania (krajowo): filtry zamawiający/NIP, województwo, podsektor, trafność, CPV, rok, tekst")
async def list_procedures(q: str | None = None, buyer_nip: str | None = None, province: str | None = None,
                          subsector: str | None = None, relevance: str | None = None, cpv: str | None = None,
                          year: int | None = None, has_performance: bool | None = None, design_build: bool | None = None,
                          limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if q:
        where.append("(p.title ILIKE :q OR p.buyer_name ILIKE :q OR p.ocid = :qq OR p.contract_notice_no = :qq)")
        params.update(q=f"%{q}%", qq=q)
    if buyer_nip:
        where.append("p.buyer_nip = :nip")
        params["nip"] = buyer_nip
    if province:
        where.append("p.province = :province")
        params["province"] = province
    if subsector:
        where.append("(p.subsector_main = :sub OR :sub = ANY(p.subsectors))")
        params["sub"] = subsector
    if relevance:
        where.append("p.relevance = :rel")
        params["rel"] = relevance
    if cpv:
        where.append("EXISTS (SELECT 1 FROM unnest(p.cpv_all) c WHERE c LIKE :cpv)")
        params["cpv"] = f"{cpv}%"
    if year:
        where.append("extract(year FROM p.first_published_on) = :year")
        params["year"] = year
    if has_performance is not None:
        where.append(("" if has_performance else "NOT ") + "('CP' = ANY(p.notice_types))")
    if design_build is not None:
        where.append("p.design_build = :db")
        params["db"] = design_build
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM procedure p WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM procedure p WHERE {w} ORDER BY p.first_published_on DESC NULLS LAST, p.id "
                          "LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.procedure(r) for r in rs])


async def _procedure_detail(db, ocid: str) -> S.ProcedureDetailOut:
    p = await D.one(db, "SELECT * FROM procedure WHERE ocid = :o", o=ocid)
    if not p:
        raise HTTPException(404, "procedure not found")
    lots = await D.rows(db, "SELECT * FROM lot WHERE procedure_id=:id ORDER BY lot_no", id=p["id"])
    cs = await D.rows(db, "SELECT c.*, :o AS ocid FROM contract c WHERE procedure_id=:id ORDER BY lot_no NULLS LAST, id",
                      id=p["id"], o=ocid)
    perf = await D.rows(db, """SELECT pf.*, n.notice_number, n.url AS notice_url FROM contract_performance pf
                               LEFT JOIN notice n ON n.id=pf.notice_id WHERE pf.procedure_id=:id ORDER BY pf.id""", id=p["id"])
    chs = await D.rows(db, """SELECT ch.*, n.notice_number, n.url AS notice_url FROM contract_change ch
                              LEFT JOIN notice n ON n.id=ch.notice_id WHERE ch.procedure_id=:id
                              ORDER BY ch.changed_on NULLS LAST, ch.id""", id=p["id"])
    ns = await D.rows(db, "SELECT * FROM notice WHERE ocid=:o ORDER BY published_at", o=ocid)
    contracts = [D.contract(c, [D.performance(x) for x in perf if x["contract_id"] == c["id"]],
                            [D.change(x) for x in chs if x["contract_id"] == c["id"]]) for c in cs]
    tl: list[S.TimelineEvent] = []
    for n in ns:
        tl.append(S.TimelineEvent(date=n["published_at"], kind="notice", title=f"{n['notice_type']} {n['notice_number']}"
                                  + ("" if n["is_latest"] else " (wersja zastąpiona)"),
                                  notice_type=n["notice_type"], notice_number=n["notice_number"], url=n["url"], ocid=ocid))
    for c in cs:
        lab = f"część {c['lot_no']}" if c.get("lot_no") else "umowa"
        if c["signed_on"]:
            tl.append(S.TimelineEvent(date=c["signed_on"], kind="contract_signed", ocid=ocid,
                                      title=f"Zawarcie umowy ({lab}): {c.get('contractor_name') or ''}".strip(),
                                      detail={"value": str(c["value_amount"]) if c["value_amount"] is not None else None,
                                              "vat_basis": c["value_vat"], "contract_id": c["id"]}))
        if c["planned_end_on"]:
            tl.append(S.TimelineEvent(date=c["planned_end_on"], kind="planned_end", ocid=ocid,
                                      title=f"Planowany termin zakończenia ({lab})",
                                      detail={"computed_from_duration": c["planned_end_computed"], "contract_id": c["id"]},
                                      origin="CALC" if c["planned_end_computed"] else "SOURCE"))
    for x in perf:
        if x["completed_on"]:
            tl.append(S.TimelineEvent(date=x["completed_on"], kind="completed", ocid=ocid, url=x["notice_url"],
                                      notice_number=x["notice_number"], title="Wykonanie umowy" +
                                      (f" (opóźnienie {x['delay_days']} dni)" if (x["delay_days"] or 0) > 0 else ""),
                                      detail={"delay_days": x["delay_days"], "cost_dev_pct": x["cost_dev_pct"],
                                              "on_time_declared": x["on_time_declared"]}))
    for x in chs:
        if x["changed_on"]:
            tl.append(S.TimelineEvent(date=x["changed_on"], kind="change", ocid=ocid, url=x["notice_url"],
                                      notice_number=x["notice_number"],
                                      title=f"Zmiana umowy ({', '.join(x['legal_basis'] or []) or 'podstawa?'})",
                                      detail={"cause": (x["cause_text"] or "")[:300]}))
    tl.sort(key=lambda e: str(e.date or ""))
    return D.procedure(p, S.ProcedureDetailOut, lots=[D.lot(l) for l in lots], contracts=contracts,
                       notices=[S.NoticeOut(**{k: n.get(k) for k in S.NoticeOut.model_fields}) for n in ns], timeline=tl)


@router.get("/procedures/{ocid}", response_model=S.ProcedureDetailOut,
            summary="Postępowanie: części, umowy, wykonanie, zmiany, łańcuch ogłoszeń i oś czasu")
async def get_procedure(ocid: str, db: AsyncSession = DB):
    return await _procedure_detail(db, ocid)


# ---------------------------------------------------------------------------------------- notices

@router.get("/notices", response_model=S.Page[S.NoticeOut], summary="Ogłoszenia BZP (bez treści HTML)")
async def list_notices(notice_type: str | None = None, ocid: str | None = None, bzp_number: str | None = None,
                       buyer_nip: str | None = None, q: str | None = None, date_from: date | None = None,
                       date_to: date | None = None, channel: str | None = None, latest_only: bool = True,
                       limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if latest_only:
        where.append("is_latest")
    for col, val in (("notice_type", notice_type), ("ocid", ocid), ("buyer_nip", buyer_nip), ("channel", channel)):
        if val:
            where.append(f"{col} = :{col}")
            params[col] = val
    if bzp_number:
        where.append("(bzp_number = :bzp OR notice_number = :bzp)")
        params["bzp"] = bzp_number
    if q:
        where.append("(order_object ILIKE :q OR buyer_name ILIKE :q)")
        params["q"] = f"%{q}%"
    if date_from:
        where.append("published_at >= :df")
        params["df"] = date_from
    if date_to:
        where.append("published_at < (:dt)::date + 1")
        params["dt"] = date_to
    w = " AND ".join(where)
    cols = ", ".join(S.NoticeOut.model_fields)
    total = await D.scalar(db, f"SELECT count(*) FROM notice WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT {cols} FROM notice WHERE {w} ORDER BY published_at DESC, id LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.NoticeOut(**r) for r in rs])


@router.get("/notices/{object_id}", response_model=S.NoticeDetailOut, summary="Ogłoszenie: pola wg kodów, ekstrakcja, rekord API")
async def get_notice(object_id: str, include_html: bool = False, db: AsyncSession = DB):
    r = await D.one(db, "SELECT * FROM notice WHERE object_id = :o OR notice_number = :o LIMIT 1", o=object_id)
    if not r:
        raise HTTPException(404, "notice not found")
    if not include_html:
        r["html_body"] = None
    return S.NoticeDetailOut(**{k: r.get(k) for k in S.NoticeDetailOut.model_fields})


@router.get("/notices/{object_id}/html", response_class=HTMLResponse, summary="Oficjalny formularz ogłoszenia (HTML)")
async def notice_html(object_id: str, db: AsyncSession = DB):
    h = await D.scalar(db, "SELECT html_body FROM notice WHERE object_id = :o OR notice_number = :o LIMIT 1", o=object_id)
    if h is None:
        raise HTTPException(404, "notice not found")
    return HTMLResponse(h)


# -------------------------------------------------------------------------- contracts / changes / perf

@router.get("/contracts", response_model=S.Page[S.ContractOut], summary="Umowy (z wykonaniem i zmianami)")
async def list_contracts(ocid: str | None = None, contractor_nip: str | None = None, buyer_nip: str | None = None,
                         signed_from: date | None = None, signed_to: date | None = None,
                         limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if ocid:
        where.append("p.ocid = :ocid")
        params["ocid"] = ocid
    if contractor_nip:
        where.append("c.contractor_nip = :cn")
        params["cn"] = contractor_nip
    if buyer_nip:
        where.append("p.buyer_nip = :bn")
        params["bn"] = buyer_nip
    if signed_from:
        where.append("c.signed_on >= :sf")
        params["sf"] = signed_from
    if signed_to:
        where.append("c.signed_on <= :st")
        params["st"] = signed_to
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM contract c JOIN procedure p ON p.id=c.procedure_id WHERE {w}", **params)
    cs = await D.rows(db, f"SELECT c.*, p.ocid FROM contract c JOIN procedure p ON p.id=c.procedure_id WHERE {w} "
                          "ORDER BY c.signed_on DESC NULLS LAST, c.id LIMIT :limit OFFSET :offset", **params)
    ids = [c["id"] for c in cs] or [0]
    perf = await D.rows(db, """SELECT pf.*, n.notice_number, n.url notice_url FROM contract_performance pf
                               LEFT JOIN notice n ON n.id=pf.notice_id WHERE pf.contract_id = ANY(:ids)""", ids=ids)
    chs = await D.rows(db, """SELECT ch.*, n.notice_number, n.url notice_url FROM contract_change ch
                              LEFT JOIN notice n ON n.id=ch.notice_id WHERE ch.contract_id = ANY(:ids)""", ids=ids)
    return _page(total, limit, offset, [D.contract(c, [D.performance(x) for x in perf if x["contract_id"] == c["id"]],
                                                   [D.change(x) for x in chs if x["contract_id"] == c["id"]]) for c in cs])


@router.get("/contracts/{contract_id}", response_model=S.ContractOut)
async def get_contract(contract_id: int, db: AsyncSession = DB):
    c = await D.one(db, "SELECT c.*, p.ocid FROM contract c JOIN procedure p ON p.id=c.procedure_id WHERE c.id=:id", id=contract_id)
    if not c:
        raise HTTPException(404, "contract not found")
    perf = await D.rows(db, """SELECT pf.*, n.notice_number, n.url notice_url FROM contract_performance pf
                               LEFT JOIN notice n ON n.id=pf.notice_id WHERE pf.contract_id = :id""", id=contract_id)
    chs = await D.rows(db, """SELECT ch.*, n.notice_number, n.url notice_url FROM contract_change ch
                              LEFT JOIN notice n ON n.id=ch.notice_id WHERE ch.contract_id = :id""", id=contract_id)
    return D.contract(c, [D.performance(x) for x in perf], [D.change(x) for x in chs])


@router.get("/changes", response_model=S.Page[S.ChangeOut], summary="Zmiany umów (ogłoszenia o zmianie + bloki 5.4 z ogłoszeń o wykonaniu)")
async def list_changes(ocid: str | None = None, legal_basis: str | None = None, cause_code: str | None = None,
                       kind: str | None = None, year: int | None = None, q: str | None = None,
                       limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if ocid:
        where.append("p.ocid = :ocid")
        params["ocid"] = ocid
    if legal_basis:
        where.append(":lb = ANY(ch.legal_basis)")
        params["lb"] = legal_basis
    if cause_code:
        where.append(":cc = ANY(ch.cause_codes_kw)")
        params["cc"] = cause_code
    if kind:
        where.append("ch.kind = :kind")
        params["kind"] = kind
    if year:
        where.append("extract(year FROM coalesce(ch.changed_on, n.published_at::date)) = :year")
        params["year"] = year
    if q:
        where.append("(ch.cause_text ILIKE :q OR ch.description_text ILIKE :q)")
        params["q"] = f"%{q}%"
    w = " AND ".join(where)
    j = "contract_change ch JOIN procedure p ON p.id=ch.procedure_id LEFT JOIN notice n ON n.id=ch.notice_id"
    total = await D.scalar(db, f"SELECT count(*) FROM {j} WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT ch.*, n.notice_number, n.url notice_url FROM {j} WHERE {w} "
                          "ORDER BY ch.changed_on DESC NULLS LAST, ch.id LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.change(r) for r in rs])


@router.get("/performance", response_model=S.Page[S.PerformanceOut], summary="Wykonanie umów (opóźnienia, wypłaty)")
async def list_performance(ocid: str | None = None, late: bool | None = None, overrun: bool | None = None,
                           year: int | None = None, limit: int = Query(100, le=1000), offset: int = 0,
                           db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if ocid:
        where.append("p.ocid = :ocid")
        params["ocid"] = ocid
    if late is not None:
        where.append("coalesce(pf.delay_days,0) > 0" if late else "coalesce(pf.delay_days,0) <= 0")
    if overrun is not None:
        where.append("coalesce(pf.cost_dev_pct,0) > 0.5" if overrun else "coalesce(pf.cost_dev_pct,0) <= 0.5")
    if year:
        where.append("extract(year FROM pf.completed_on) = :year")
        params["year"] = year
    w = " AND ".join(where)
    j = "contract_performance pf JOIN procedure p ON p.id=pf.procedure_id LEFT JOIN notice n ON n.id=pf.notice_id"
    total = await D.scalar(db, f"SELECT count(*) FROM {j} WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT pf.*, n.notice_number, n.url notice_url FROM {j} WHERE {w} "
                          "ORDER BY pf.completed_on DESC NULLS LAST, pf.id LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.performance(r) for r in rs])


# ---------------------------------------------------------------------------------- organizations

@router.get("/organizations", response_model=S.Page[S.OrganizationOut], summary="Zamawiający i wykonawcy")
async def list_orgs(q: str | None = None, role: str | None = None, province: str | None = None,
                    limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if q:
        where.append("(name ILIKE :q OR nip = :qq)")
        params.update(q=f"%{q}%", qq=q)
    if role:
        where.append(":role = ANY(roles)")
        params["role"] = role
    if province:
        where.append("province = :province")
        params["province"] = province
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM organization WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM organization WHERE {w} ORDER BY name LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.org(r) for r in rs])


@router.get("/organizations/{nip}", response_model=S.OrganizationOut)
async def get_org(nip: str, db: AsyncSession = DB):
    r = await D.one(db, "SELECT * FROM organization WHERE nip = :n", n=nip)
    if not r:
        raise HTTPException(404, "organization not found")
    return D.org(r)


# ------------------------------------------------------------------------------- sources & runs

@router.get("/sources", response_model=S.Page[S.SourceOut], summary="Pobrane artefakty (1 wiersz = 1 linia manifestu)")
async def list_sources(kind: str | None = None, status: str | None = None, limit: int = Query(100, le=1000),
                       offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if kind:
        where.append("kind = :kind")
        params["kind"] = kind
    if status:
        where.append("status = :status")
        params["status"] = status
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM source WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM source WHERE {w} ORDER BY id DESC LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.SourceOut(**r) for r in rs])


@router.get("/sources/{source_id}", response_model=S.SourceOut)
async def get_source(source_id: int, db: AsyncSession = DB):
    r = await D.one(db, "SELECT * FROM source WHERE id = :id", id=source_id)
    if not r:
        raise HTTPException(404, "source not found")
    return S.SourceOut(**r)


@router.get("/runs", response_model=S.Page[S.RunOut], summary="Przebiegi konektorów/importerów (ingestion_run)")
async def list_runs(connector: str | None = None, limit: int = Query(50, le=500), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if connector:
        where.append("connector = :c")
        params["c"] = connector
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM ingestion_run WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM ingestion_run WHERE {w} ORDER BY started_at DESC LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.RunOut(**r) for r in rs])


# ------------------------------------------------------------------------- links, review, evidence

@router.get("/link-candidates", response_model=S.Page[S.LinkCandidateOut], summary="Kandydaci powiązań z cechami i wynikiem")
async def list_link_candidates(rm_id: str | None = None, method: str | None = None, decision: str | None = None,
                               limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if rm_id:
        where.append("left_table='project' AND left_id = (SELECT id FROM project WHERE rm_id=:rm)")
        params["rm"] = rm_id
    if method:
        where.append("method = :m")
        params["m"] = method
    if decision:
        where.append("decision = :d")
        params["d"] = decision
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM link_candidate WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM link_candidate WHERE {w} ORDER BY left_id, rank NULLS LAST, score DESC "
                          "LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.LinkCandidateOut(**r) for r in rs])


@router.get("/review-items", response_model=S.Page[S.ReviewItemOut], summary="Kolejka eksperta: rozbieżności, powiązania, zdarzenia")
async def list_review_items(kind: str | None = None, status: str | None = "open", rm_id: str | None = None,
                            limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if kind:
        where.append("r.kind = :kind")
        params["kind"] = kind
    if status:
        where.append("r.status = :status")
        params["status"] = status
    if rm_id:
        where.append("p.rm_id = :rm")
        params["rm"] = rm_id
    w = " AND ".join(where)
    j = "review_item r LEFT JOIN project p ON p.id = r.project_id"
    total = await D.scalar(db, f"SELECT count(*) FROM {j} WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT r.*, p.rm_id FROM {j} WHERE {w} ORDER BY p.rm_id NULLS LAST, r.id "
                          "LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.ReviewItemOut(**r) for r in rs])


@router.get("/evidence", response_model=list[S.EvidenceOut], summary="Dowody dla rekordu (tabela, id)")
async def list_evidence(claim_table: str, claim_id: int, db: AsyncSession = DB):
    rs = await D.rows(db, "SELECT * FROM evidence WHERE claim_table=:t AND claim_id=:i ORDER BY id", t=claim_table, i=claim_id)
    return [S.EvidenceOut(**r) for r in rs]


@router.get("/external-records", response_model=S.Page[S.ExternalRecordOut],
            summary="Rekordy z innych źródeł (TED, KIO, NIK, CRU, Mapa Dotacji, Biała lista...)")
async def list_external(source_kind: str | None = None, kind: str | None = None, buyer_nip: str | None = None,
                        q: str | None = None, limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    for col, val in (("source_kind", source_kind), ("kind", kind), ("buyer_nip", buyer_nip)):
        if val:
            where.append(f"{col} = :{col}")
            params[col] = val
    if q:
        where.append("(title ILIKE :q OR buyer_name ILIKE :q OR external_id ILIKE :q)")
        params["q"] = f"%{q}%"
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM external_record WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM external_record WHERE {w} ORDER BY published_on DESC NULLS LAST, id "
                          "LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.external(r) for r in rs])


@router.get("/external-records/{record_id}", response_model=S.ExternalRecordOut)
async def get_external(record_id: int, db: AsyncSession = DB):
    r = await D.one(db, "SELECT * FROM external_record WHERE id=:id", id=record_id)
    if not r:
        raise HTTPException(404, "record not found")
    return D.external(r)


@router.get("/source-checks", response_model=S.Page[S.SourceCheckOut], summary="Sprawdzenia źródeł (także 'szukano, nie znaleziono')")
async def list_source_checks(source_kind: str | None = None, subject_key: str | None = None, result: str | None = None,
                             limit: int = Query(200, le=2000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    for col, val in (("source_kind", source_kind), ("subject_key", subject_key), ("result", result)):
        if val:
            where.append(f"{col} = :{col}")
            params[col] = val
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM source_check WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM source_check WHERE {w} ORDER BY subject_key, source_kind LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [S.SourceCheckOut(**r) for r in rs])


@router.get("/documents", response_model=S.Page[S.DocumentOut], summary="Dokumenty (i stany dowodowe brakujących)")
async def list_documents(rm_id: str | None = None, doc_type: str | None = None, fetch_state: str | None = None,
                         limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    if rm_id:
        where.append("project_id = (SELECT id FROM project WHERE rm_id=:rm)")
        params["rm"] = rm_id
    if doc_type:
        where.append("doc_type = :dt")
        params["dt"] = doc_type
    if fetch_state:
        where.append("fetch_state = :fs")
        params["fs"] = fetch_state
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM document WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT * FROM document WHERE {w} ORDER BY project_id, doc_type, id LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.document(r) for r in rs])


@router.get("/catalogue/{table}", summary="Katalog wiedzy (pakiet sektorowy): risk | subsector | cpv_map | doc_type | checklist | clause | entry")
async def catalogue(table: str, sector: str = "wod-kan", status: str | None = None, db: AsyncSession = DB) -> list[dict[str, Any]]:
    allowed = {"risk", "subsector", "cpv_map", "doc_type", "checklist", "clause", "entry"}
    if table not in allowed:
        raise HTTPException(404, f"unknown catalogue table; use one of {sorted(allowed)}")
    where, params = ["sector = :sector"], {"sector": sector}
    if status:
        where.append("status = :status")
        params["status"] = status
    return await D.rows(db, f"SELECT * FROM catalogue_{table} WHERE {' AND '.join(where)} ORDER BY id", **params)


@router.get("/risk-events", response_model=S.Page[S.RiskEventOut],
            summary="Zdarzenia ryzyka (deterministyczne z pól BZP = CALC; propozycje AI = AI)")
async def list_risk_events(event_type: str | None = None, catalogue_code: str | None = None, rm_id: str | None = None,
                           ocid: str | None = None, origin: str | None = None, review_status: str | None = None,
                           limit: int = Query(100, le=1000), offset: int = 0, db: AsyncSession = DB):
    where, params = ["true"], {"limit": limit, "offset": offset}
    for col, val in (("e.event_type", event_type), ("e.catalogue_code", catalogue_code), ("e.origin", origin),
                     ("e.review_status", review_status)):
        if val:
            k = col.split(".")[1]
            where.append(f"{col} = :{k}")
            params[k] = val
    if rm_id:
        where.append("e.project_id = (SELECT id FROM project WHERE rm_id=:rm)")
        params["rm"] = rm_id
    if ocid:
        where.append("e.procedure_id = (SELECT id FROM procedure WHERE ocid=:ocid)")
        params["ocid"] = ocid
    w = " AND ".join(where)
    total = await D.scalar(db, f"SELECT count(*) FROM risk_event e WHERE {w}", **params)
    rs = await D.rows(db, f"SELECT e.* FROM risk_event e WHERE {w} ORDER BY e.occurred_on DESC NULLS LAST, e.id "
                          "LIMIT :limit OFFSET :offset", **params)
    return _page(total, limit, offset, [D.risk_event(r) for r in rs])
