"""JSON/CSV exports of the case base (R11: filterable, exportable records). Streamed."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
        FROM project p WHERE true {f} ORDER BY p.rm_id""", {"pilot": "AND p.is_pilot = :pilot"}),
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
        WHERE true {f} ORDER BY p.rm_id, lc.rank""", {"rm_id": "AND p.rm_id = :rm_id"}),
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
        WHERE true {f} ORDER BY e.id""", {"rm_id": "AND p.rm_id = :rm_id", "relevance": "AND pr.relevance = :relevance",
                                         "kind": "AND e.event_type = :kind"}),
    "documents": ("""SELECT d.id, p.rm_id, d.doc_type, d.title, d.filename, d.url, d.sha256, d.path, d.text_path, d.pages,
        d.fetch_state, d.note, d.source_id FROM document d LEFT JOIN project p ON p.id=d.project_id WHERE true {f}
        ORDER BY p.rm_id, d.doc_type""", {"rm_id": "AND p.rm_id = :rm_id"}),
}


def _cell(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


async def _stream(db: AsyncSession, sql: str, params: dict, fmt: str) -> AsyncIterator[bytes]:
    res = await db.stream(text(sql), params)
    first = True
    cols: list[str] = list(res.keys())
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        yield ("﻿" + buf.getvalue()).encode()
        async for part in res.partitions(2000):
            buf = io.StringIO()
            w = csv.writer(buf)
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
                 limit: int | None = Query(None, le=500000), db: AsyncSession = Depends(get_session)):
    if dataset not in DATASETS:
        raise HTTPException(404, f"unknown dataset; available: {sorted(DATASETS)}")
    if fmt not in ("json", "csv"):
        raise HTTPException(400, "fmt must be json or csv")
    sql, filters = DATASETS[dataset]
    given = {k: v for k, v in dict(pilot=pilot, relevance=relevance, province=province, buyer_nip=buyer_nip, ocid=ocid,
                                   year=year, notice_type=notice_type, role=role, rm_id=rm_id, status=status, kind=kind,
                                   connector=connector, source_kind=source_kind, legal_basis=legal_basis).items()
             if v is not None and k in filters}
    q = sql.format(f=" ".join(filters[k] for k in given))
    if limit:
        q += f" LIMIT {int(limit)}"
    media = "text/csv; charset=utf-8" if fmt == "csv" else "application/json"
    return StreamingResponse(_stream(db, q, given, fmt), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="riskminer_{dataset}.{fmt}"'})


@router.get("", summary="Lista dostępnych zbiorów do eksportu")
async def list_datasets() -> dict[str, list[str]]:
    return {k: sorted(v[1]) for k, v in DATASETS.items()}
