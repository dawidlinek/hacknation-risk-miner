"""JSON/CSV exports of the case base (R11: filterable, exportable records). Streamed."""
from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.db.session import get_session

router = APIRouter(prefix="/api/export", tags=["export"])

# dataset -> (SQL, filters {param: SQL condition}). Personal contact data is never part of these tables.
DATASETS: dict[str, tuple[str, dict[str, str]]] = {
    "projects": ("""SELECT p.rm_id, p.title, p.beneficiary_name, p.beneficiary_nip, p.public_id_type, p.public_id,
        p.scope_text, p.funding_programme, p.value_amount, p.value_currency, p.value_vat, p.subsidy_amount,
        p.subsector_main, array_to_string(p.subsectors_extra, ' ') subsectors_extra, p.works_type, p.delivery_model,
        p.status, p.province, p.city, p.origin, p.review_status, p.source_id,
        (SELECT string_agg(pr.ocid, ' ') FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id WHERE pp.project_id=p.id) ocids,
        (SELECT string_agg(pp.method || ':' || round(pp.score::numeric, 3), ' ') FROM project_procedure pp WHERE pp.project_id=p.id) link_methods,
        (SELECT count(*) FROM review_item r WHERE r.project_id=p.id AND r.status='open') open_issues
        FROM project p WHERE true {f} ORDER BY p.rm_id""", {"pilot": "AND p.is_pilot = :pilot", "rm_ids": "AND p.rm_id = ANY(:rm_ids)"}),
    "procedures": ("""SELECT ocid, contract_notice_no, contract_notice_missing, title, buyer_nip, buyer_name, province, city,
        cpv_main, array_to_string(cpv_all, ' ') cpv_all, mode, order_type, estimated_value_amount, estimated_value_currency,
        estimated_value_vat, below_eu, eu_funded, n_lots, platform_url, first_published_on, last_published_on,
        array_to_string(notice_types, ' ') notice_types, cancelled, relevance, subsector_main,
        array_to_string(subsectors, ' ') subsectors, scope_kind, work_type, design_build, classify_why, source_id
        FROM procedure WHERE true {f} ORDER BY first_published_on, id""",
        {"relevance": "AND relevance = :relevance", "province": "AND province = :province", "buyer_nip": "AND buyer_nip = :buyer_nip",
         "year": "AND extract(year FROM first_published_on) = :year"}),
    "contracts": ("""SELECT c.id, p.ocid, c.lot_no, c.contractor_name, c.contractor_nip, c.signed_on, c.duration_raw,
        c.planned_duration_days, c.planned_end_on, c.planned_end_computed, c.value_amount, c.value_currency, c.value_vat,
        c.terms_source, c.result_notice_no, c.origin, c.review_status, c.source_id
        FROM contract c JOIN procedure p ON p.id=c.procedure_id WHERE true {f} ORDER BY c.id""",
        {"buyer_nip": "AND p.buyer_nip = :buyer_nip", "ocid": "AND p.ocid = :ocid"}),
    "performance": ("""SELECT pf.id, p.ocid, pf.contract_id, n.notice_number, n.url, pf.executed, pf.completed_on,
        pf.on_time_declared, pf.changes_count, pf.total_paid_amount, pf.total_paid_currency, pf.total_paid_vat,
        pf.properly_performed, pf.contract_value_amount, pf.signed_on, pf.planned_end_on, pf.planned_days, pf.actual_days,
        pf.delay_days, pf.cost_dev_pct, p.subsector_main, p.relevance, p.design_build, p.province, pf.source_id
        FROM contract_performance pf JOIN procedure p ON p.id=pf.procedure_id LEFT JOIN notice n ON n.id=pf.notice_id
        WHERE true {f} ORDER BY pf.id""", {"relevance": "AND p.relevance = :relevance", "ocid": "AND p.ocid = :ocid"}),
    "changes": ("""SELECT ch.id, p.ocid, ch.contract_id, ch.kind, n.notice_number, n.url, ch.change_no, ch.changed_on,
        array_to_string(ch.legal_basis, ' ') legal_basis, ch.legal_basis_raw, array_to_string(ch.change_types, ' ') change_types,
        ch.delta_days, ch.delta_value_amount, ch.delta_value_currency, ch.delta_value_vat, ch.delta_value_pct, ch.price_increase,
        ch.cause_text, ch.description_text, array_to_string(ch.cause_codes_kw, ' ') cause_codes_kw, ch.source_id
        FROM contract_change ch JOIN procedure p ON p.id=ch.procedure_id LEFT JOIN notice n ON n.id=ch.notice_id
        WHERE true {f} ORDER BY ch.id""", {"ocid": "AND p.ocid = :ocid", "legal_basis": "AND :legal_basis = ANY(ch.legal_basis)"}),
    "notices": ("""SELECT object_id, notice_type, notice_number, bzp_number, version, is_latest, ocid, published_at,
        buyer_nip, buyer_name, province, order_object, url, channel, source_id, source_locator
        FROM notice WHERE true {f} ORDER BY published_at, id""",
        {"notice_type": "AND notice_type = :notice_type", "ocid": "AND ocid = :ocid", "buyer_nip": "AND buyer_nip = :buyer_nip"}),
    "organizations": ("""SELECT nip, regon, krs, name, array_to_string(roles, ' ') roles, province, city, teryt, vat_status,
        nip_valid, origin, review_status, source_id FROM organization WHERE true {f} ORDER BY name""",
        {"role": "AND :role = ANY(roles)"}),
    "link_candidates": ("""SELECT lc.id, p.rm_id, lc.right_table, lc.right_ref, lc.method, lc.score, lc.rank, lc.decision,
        lc.review_status, lc.reference_verdict, lc.explanation, lc.features::text features, lc.created_at
        FROM link_candidate lc LEFT JOIN project p ON lc.left_table='project' AND p.id=lc.left_id
        WHERE true {f} ORDER BY p.rm_id, lc.rank""", {"rm_id": "AND p.rm_id = :rm_id", "rm_ids": "AND p.rm_id = ANY(:rm_ids)"}),
    "review_items": ("""SELECT r.id, p.rm_id, r.kind, r.code, r.title, r.severity, r.status, r.created_by, r.detail::text detail,
        r.created_at FROM review_item r LEFT JOIN project p ON p.id=r.project_id WHERE true {f} ORDER BY p.rm_id, r.id""",
        {"status": "AND r.status = :status"}),
    "sources": ("""SELECT id, kind, url, method, retrieved_at, http_status, content_type, bytes, sha256, path, licence,
        status, note, run_id FROM source WHERE true {f} ORDER BY id""", {"kind": "AND kind = :kind"}),
    "runs": ("""SELECT id, connector, stage, started_at, finished_at, status, stats::text stats, error FROM ingestion_run
        WHERE true {f} ORDER BY started_at""", {"connector": "AND connector = :connector"}),
    "external_records": ("""SELECT source_kind, kind, external_id, title, published_on, buyer_nip, buyer_name, province,
        value_amount, value_currency, value_vat, url, data::text data, source_id FROM external_record WHERE true {f}
        ORDER BY source_kind, kind, external_id""", {"source_kind": "AND source_kind = :source_kind", "kind": "AND kind = :kind"}),
    "source_checks": ("""SELECT source_kind, subject_type, subject_key, n_hits, n_relevant, result,
        array_to_string(matched_ids, ' ') matched_ids, note, checked_at, query::text query, source_id FROM source_check
        WHERE true {f} ORDER BY subject_key, source_kind""", {"source_kind": "AND source_kind = :source_kind"}),
    "risk_events": ("""SELECT e.id, p.rm_id, pr.ocid, e.event_type, e.catalogue_code, e.summary, e.cause, e.impact_days,
        e.impact_value_amount, e.impact_value_currency, e.impact_value_vat, e.impact_pct, e.occurred_on, e.evidence_state,
        e.origin, e.review_status, e.source_id, pr.relevance, pr.subsector_main
        FROM risk_event e LEFT JOIN project p ON p.id=e.project_id LEFT JOIN procedure pr ON pr.id=e.procedure_id
        WHERE true {f} ORDER BY e.id""", {"rm_id": "AND p.rm_id = :rm_id", "rm_ids": "AND p.rm_id = ANY(:rm_ids)",
                                         "relevance": "AND pr.relevance = :relevance", "kind": "AND e.event_type = :kind"}),
    "documents": ("""SELECT d.id, p.rm_id, d.doc_type, d.title, d.filename, d.url, d.sha256, d.path, d.text_path, d.pages,
        d.fetch_state, d.note, d.source_id FROM document d LEFT JOIN project p ON p.id=d.project_id WHERE true {f}
        ORDER BY p.rm_id, d.doc_type""", {"rm_id": "AND p.rm_id = :rm_id", "rm_ids": "AND p.rm_id = ANY(:rm_ids)"}),
    "signals": ("""SELECT s.contract_id, s.ocid, s.bzp_number, s.result_notice_url AS source_url, s.lot_no, s.n_parts, s.buyer_nip, s.buyer_name,
        s.title, s.subsector_main, s.value_amount, s.value_currency, s.value_vat, s.contractor_name, s.signed_on,
        s.planned_end_on, s.planned_end_computed, s.days_overdue, s.n_change_notices, s.last_change_on,
        s.woj, s.pow, s.gmi, s.lon, s.lat, s.location_method, 'CALC' AS origin, 'auto' AS review_status
        FROM monitor_signals(coalesce(CAST(:as_of AS date), current_date)) s WHERE true {f}
        ORDER BY s.days_overdue DESC, s.contract_id""",
        {"terc": "AND (CASE CAST(:level AS text) WHEN 'woj' THEN s.woj WHEN 'pow' THEN s.pow ELSE s.gmi END) LIKE CAST(:terc AS text) || '%'",
         "level": "", "as_of": ""}),
    "review_decisions": ("""SELECT rv.id, rv.created_at, rv.target_table, rv.target_id, rv.review_item_id, rv.action, rv.option_key,
        rv.reviewer, rv.comment, rv.before::text before, rv.after::text after, rv.undo_of
        FROM review rv WHERE true {f} ORDER BY rv.id""", {"target_table": "AND rv.target_table = :target_table"}),
    "audit": ("""SELECT a.id, a.at, a.actor, a.action, a.table_name, a.row_id, a.before::text before, a.after::text after,
        a.request_id, a.note FROM audit_log a WHERE true {f} ORDER BY a.id""",
        {"table_name": "AND a.table_name = :table_name", "actor": "AND a.actor = :actor",
         "since": "AND a.at >= CAST(CAST(:since AS text) AS timestamptz)", "until": "AND a.at < CAST(CAST(:until AS text) AS timestamptz)"}),
    "catalogue_risk": ("""SELECT sector, code, parent_code, level, name, description, status, version, origin, proposed_by,
        approved_by, data::text data FROM catalogue_risk WHERE true {f} ORDER BY code, version""",
        {"status": "AND status = :status"}),
    "catalogue_versions": ("""SELECT sector, label, summary, actor, created_at, changes::text changes
        FROM catalogue_version WHERE true {f} ORDER BY id""", {}),
}

# Datasets that are visible to logged-in users only (internal process data or unreleased analyses).
LOGIN_ONLY = {"review_items", "review_decisions", "audit", "runs", "sources", "link_candidates", "analyses"}
# Extra SQL condition for anonymous callers: unverified AI rows and confidential documents never leave the system.
PUBLIC_WHERE: dict[str, str] = {
    "risk_events": "AND (e.origin <> 'AI' OR e.review_status IN ('approved','edited'))",
    "projects": "AND (p.origin <> 'AI' OR p.review_status IN ('approved','edited'))",
    "catalogue_risk": "AND status = 'approved'",
}


def _cell(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


async def _stream(db: AsyncSession, sql: str, params: dict, fmt: str, sep: str = ",") -> AsyncIterator[bytes]:
    res = await db.stream(text(sql), params)
    first = True
    cols: list[str] = list(res.keys())
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=sep)
        w.writerow(cols)
        yield ("﻿" + buf.getvalue()).encode()
        async for part in res.partitions(2000):
            buf = io.StringIO()
            w = csv.writer(buf, delimiter=sep)
            for r in part:
                w.writerow([_cell(v) for v in r])
            yield buf.getvalue().encode()
        return
    yield b"["
    async for part in res.partitions(2000):
        chunks = []
        for r in part:
            chunks.append(("" if first else ",") + json.dumps({c: _cell(v) for c, v in zip(cols, r)}, ensure_ascii=False))
            first = False
        yield "\n".join(chunks).encode()
    yield b"]"


@router.get("/{dataset}.{fmt}", summary="Eksport zbioru do JSON/CSV (filtry jak w parametrach)")
async def export(dataset: str, fmt: str, pilot: bool | None = None, relevance: str | None = None,
                 province: str | None = None, buyer_nip: str | None = None, ocid: str | None = None,
                 year: int | None = None, notice_type: str | None = None, role: str | None = None,
                 rm_id: str | None = None, status: str | None = None, kind: str | None = None,
                 connector: str | None = None, source_kind: str | None = None, legal_basis: str | None = None,
                 rm_ids: str | None = Query(None, description="lista rm_id po przecinku"),
                 sep: str = Query(",", pattern="^(comma|semicolon|,|;)$", description="separator CSV: semicolon dla polskiego Excela"),
                 target_table: str | None = None, table_name: str | None = None, actor: str | None = None,
                 terc: str | None = None, level: str | None = None, as_of: str | None = None,
                 category: str | None = None, since: str | None = None, until: str | None = None,
                 limit: int | None = Query(None, le=500000), user: A.User | None = Depends(A.current_user),
                 db: AsyncSession = Depends(get_session)):
    if dataset not in DATASETS:
        raise HTTPException(404, f"unknown dataset; available: {sorted(DATASETS)}")
    if fmt not in ("json", "csv"):
        raise HTTPException(400, "fmt must be json or csv")
    if dataset in LOGIN_ONLY and user is None:
        raise A.ApiError(401, "Ten zbiór jest dostępny po zalogowaniu.", "login_required")
    sql, filters = DATASETS[dataset]
    given = {k: v for k, v in dict(pilot=pilot, relevance=relevance, province=province, buyer_nip=buyer_nip, ocid=ocid,
                                   year=year, notice_type=notice_type, role=role, rm_id=rm_id, status=status, kind=kind,
                                   connector=connector, source_kind=source_kind, legal_basis=legal_basis,
                                   rm_ids=[x.strip() for x in rm_ids.split(",") if x.strip()] if rm_ids else None,
                                   target_table=target_table, table_name=table_name, actor=actor, terc=terc, level=level, as_of=as_of, since=since, until=until).items()
             if v is not None and k in filters}
    where = " ".join(filters[k] for k in given)
    if user is None and dataset in PUBLIC_WHERE:
        where += " " + PUBLIC_WHERE[dataset]
    if dataset == "audit" and category:
        from riskminer.api.audit_read import CATEGORY_SQL
        if category not in CATEGORY_SQL:
            raise HTTPException(422, "unknown category")
        where += " AND " + CATEGORY_SQL[category]
    if dataset == "documents":  # confidential uploads: owner and admin only, for logged-in users too
        where += " AND " + A.public_doc_filter(user, "d")
    if dataset == "signals":  # terc/level/as_of are optional; the SQL needs all three bound
        for k in ("terc", "level", "as_of"):
            given.setdefault(k, None)
        if terc and not level:
            given["level"] = "woj" if len(terc) <= 2 else ("pow" if len(terc) <= 4 else "gmi")
    q = sql.format(f=where)
    if limit:
        q += f" LIMIT {int(limit)}"
    media = "text/csv; charset=utf-8" if fmt == "csv" else "application/json"
    delim = ";" if sep in ("semicolon", ";") else ","
    return StreamingResponse(_stream(db, q, given, fmt, delim), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="riskminer_{dataset}.{fmt}"'})


@router.get("", summary="Lista dostępnych zbiorów do eksportu")
async def list_datasets(user: A.User | None = Depends(A.current_user)) -> dict[str, list[str]]:
    return {k: sorted(v[1]) for k, v in DATASETS.items() if user is not None or k not in LOGIN_ONLY}
