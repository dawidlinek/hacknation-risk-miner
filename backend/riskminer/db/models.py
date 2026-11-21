"""Schema v1 (docs/PLAN.md §5). Money = (<x>_amount, <x>_currency, <x>_vat ∈ net|gross|unknown).

Invariants (see root CLAUDE.md): every fact row cites `source_id` (+ evidence rows), carries
`origin` ∈ SOURCE|CALC|AI and `review_status`; AI never overwrites approved rows; `audit_log` is
append-only (DB trigger); personal contact data never enters normalised tables.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from riskminer.db.base import (
    CATALOGUE_STATUS,
    EVIDENCE_STATE,
    FETCH_STATE,
    JOB_STATUS,
    RUN_STATUS,
    VAT_BASIS,
    VERIFICATION,
    Base,
    ProvenanceMixin,
    TimestampMixin,
    check_in,
    prov_checks,
)

Money = Numeric(18, 2)
EMBED_DIM = 1024  # BAAI/bge-m3


# ======================================================================================
# Provenance: runs, sources, jobs, LLM calls
# ======================================================================================

class IngestionRun(Base):
    __tablename__ = "ingestion_run"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector: Mapped[str] = mapped_column(String(40), index=True)
    stage: Mapped[str] = mapped_column(String(20), server_default="fetch")   # fetch|load|derive|link|report
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), server_default="running")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("job.id", ondelete="SET NULL"))
    __table_args__ = (check_in("status", RUN_STATUS),)


class Source(Base):
    """One fetched artefact (= one manifest line) or one imported file. Every record cites one."""
    __tablename__ = "source"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)              # connector id: bzp_copy, ted, xlsx...
    url: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(10))
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(120))
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    path: Mapped[str | None] = mapped_column(Text)                         # data/raw/... relative to repo root
    licence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="ok")   # ok|empty|blocked|error
    note: Mapped[str | None] = mapped_column(Text)
    manifest_key: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ingestion_run.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("kind", "manifest_key", "retrieved_at", name="uq_source_manifest"),
        check_in("status", ("ok", "empty", "blocked", "error")),
    )


class Job(Base):
    __tablename__ = "job"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)              # scrape:ted | import_xlsx | ...
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(10), server_default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, server_default="100")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(80))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        check_in("status", JOB_STATUS),
        Index("ix_job_queue", "status", "priority", "run_after"),
    )


class LlmCall(Base):
    __tablename__ = "llm_call"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task: Mapped[str] = mapped_column(String(60), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    alias: Mapped[str | None] = mapped_column(String(40))
    data_location: Mapped[str | None] = mapped_column(String(80))
    sensitivity: Mapped[str] = mapped_column(String(20), server_default="public")   # public|confidential
    request_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), server_default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ======================================================================================
# Core case base
# ======================================================================================

class Organization(ProvenanceMixin, Base):
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    nip: Mapped[str | None] = mapped_column(String(10), unique=True)
    regon: Mapped[str | None] = mapped_column(String(14), index=True)
    krs: Mapped[str | None] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str | None] = mapped_column(Text, index=True)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(20)), server_default="{}")     # buyer|contractor
    org_type: Mapped[str | None] = mapped_column(String(80))                             # e.g. JST, spółka
    teryt: Mapped[str | None] = mapped_column(String(7), index=True)
    province: Mapped[str | None] = mapped_column(String(4), index=True)                  # PL02..PL32
    city: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    vat_status: Mapped[str | None] = mapped_column(String(40))
    bzp_org_ids: Mapped[list[str]] = mapped_column(ARRAY(String(20)), server_default="{}")
    nip_valid: Mapped[bool | None] = mapped_column(Boolean)
    verified_by_source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")             # no personal contacts
    __table_args__ = (*prov_checks(),)


class Project(ProvenanceMixin, Base):
    __tablename__ = "project"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rm_id: Mapped[str] = mapped_column(String(20), unique=True)                          # RM-2026-001
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    beneficiary_org_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organization.id"), index=True)
    beneficiary_name: Mapped[str | None] = mapped_column(Text)
    beneficiary_nip: Mapped[str | None] = mapped_column(String(10), index=True)
    external_ids: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")    # {kpo, bzp, cst, ted}
    public_id_type: Mapped[str | None] = mapped_column(String(40))
    public_id: Mapped[str | None] = mapped_column(String(60), index=True)
    scope_text: Mapped[str | None] = mapped_column(Text)                                 # "całe postępowanie" / "część 2"
    scope_part: Mapped[int | None] = mapped_column(Integer)
    funding_programme: Mapped[str | None] = mapped_column(Text)
    value_amount: Mapped[Decimal | None] = mapped_column(Money)
    value_currency: Mapped[str | None] = mapped_column(String(3))
    value_vat: Mapped[str | None] = mapped_column(String(7))
    subsidy_amount: Mapped[Decimal | None] = mapped_column(Money)
    subsidy_currency: Mapped[str | None] = mapped_column(String(3))
    subsidy_vat: Mapped[str | None] = mapped_column(String(7))
    subsector_main: Mapped[str | None] = mapped_column(String(8))
    subsectors_extra: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default="{}")
    works_type: Mapped[str | None] = mapped_column(String(20))                           # build|renovation|mixed
    delivery_model: Mapped[str | None] = mapped_column(String(20))                       # build|design_build
    quantities: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")      # {km, connections, pe, m3d}
    status: Mapped[str | None] = mapped_column(String(40))
    sector: Mapped[str] = mapped_column(String(20), server_default="wod-kan", index=True)
    teryt_woj: Mapped[str | None] = mapped_column(String(2))
    province: Mapped[str | None] = mapped_column(String(4))
    city: Mapped[str | None] = mapped_column(Text)
    record_version: Mapped[str | None] = mapped_column(String(20))
    record_date: Mapped[date | None] = mapped_column(Date)
    annotation: Mapped[str | None] = mapped_column(Text)
    dataset_row: Mapped[dict[str, Any] | None] = mapped_column(JSONB)                    # verbatim organizer row
    is_pilot: Mapped[bool] = mapped_column(Boolean, server_default="false")
    __table_args__ = (*prov_checks(),)


class Procedure(ProvenanceMixin, Base):
    """One procurement procedure (= BZP tenderId / OCID)."""
    __tablename__ = "procedure"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ocid: Mapped[str] = mapped_column(String(80), unique=True)
    contract_notice_no: Mapped[str | None] = mapped_column(String(30), index=True)      # 2024/BZP 00349631
    contract_notice_missing: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ted_no: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(Text)
    buyer_org_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organization.id"), index=True)
    buyer_nip: Mapped[str | None] = mapped_column(String(10), index=True)
    buyer_name: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(4), index=True)
    city: Mapped[str | None] = mapped_column(Text)
    cpv_main: Mapped[str | None] = mapped_column(String(10), index=True)
    cpv_all: Mapped[list[str]] = mapped_column(ARRAY(String(10)), server_default="{}")
    mode: Mapped[str | None] = mapped_column(Text)
    order_type: Mapped[str | None] = mapped_column(String(20))
    tender_type: Mapped[str | None] = mapped_column(String(20))
    client_type: Mapped[str | None] = mapped_column(String(20))
    estimated_value_amount: Mapped[Decimal | None] = mapped_column(Money)
    estimated_value_currency: Mapped[str | None] = mapped_column(String(3))
    estimated_value_vat: Mapped[str | None] = mapped_column(String(7))                  # net (art. 28 Pzp)
    below_eu: Mapped[bool | None] = mapped_column(Boolean)
    eu_funded: Mapped[bool | None] = mapped_column(Boolean)
    eu_project: Mapped[str | None] = mapped_column(Text)
    n_lots: Mapped[int | None] = mapped_column(Integer)
    platform_url: Mapped[str | None] = mapped_column(Text)
    first_published_on: Mapped[date | None] = mapped_column(Date, index=True)
    last_published_on: Mapped[date | None] = mapped_column(Date)
    notice_types: Mapped[list[str]] = mapped_column(ARRAY(String(4)), server_default="{}")   # CN TR AU CP
    cancelled: Mapped[bool | None] = mapped_column(Boolean)
    # classification (wodkan_classify; explainable)
    relevance: Mapped[str | None] = mapped_column(String(12), index=True)               # core|component|cpv_only|none
    subsector_main: Mapped[str | None] = mapped_column(String(8), index=True)
    subsectors: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default="{}")
    scope_kind: Mapped[str | None] = mapped_column(String(20))
    work_type: Mapped[str | None] = mapped_column(String(20))
    design_build: Mapped[bool | None] = mapped_column(Boolean)
    classify_why: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str] = mapped_column(String(20), server_default="wod-kan", index=True)
    __table_args__ = (*prov_checks(),)


class ProjectProcedure(ProvenanceMixin, Base):
    __tablename__ = "project_procedure"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), index=True)
    procedure_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(60))
    score: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    link_candidate_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("link_candidate.id", ondelete="SET NULL"))
    lots: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")         # parts the project covers
    __table_args__ = (UniqueConstraint("project_id", "procedure_id", name="uq_project_procedure"), *prov_checks())


class Notice(ProvenanceMixin, Base):
    __tablename__ = "notice"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    object_id: Mapped[str] = mapped_column(String(80), unique=True)
    notice_type: Mapped[str] = mapped_column(String(40), index=True)
    notice_number: Mapped[str] = mapped_column(String(40), index=True)                  # 2024/BZP 00349631/01
    bzp_number: Mapped[str | None] = mapped_column(String(30), index=True)              # 2024/BZP 00349631
    version: Mapped[int | None] = mapped_column(Integer)
    is_latest: Mapped[bool] = mapped_column(Boolean, server_default="true", index=True)
    superseded_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="SET NULL"), index=True)
    ocid: Mapped[str | None] = mapped_column(String(80), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    buyer_nip: Mapped[str | None] = mapped_column(String(20), index=True)
    buyer_name: Mapped[str | None] = mapped_column(Text)
    buyer_city: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(4))
    order_object: Mapped[str | None] = mapped_column(Text)
    cpv_raw: Mapped[str | None] = mapped_column(Text)
    refs: Mapped[list[str]] = mapped_column(ARRAY(String(30)), server_default="{}")     # BZP numbers cited in body
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB)                              # API record minus htmlBody
    html_body: Mapped[str | None] = mapped_column(Text)                                  # official form (lz4 TOAST)
    parsed_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)                  # {code: value} first occurrence
    extracted: Mapped[Any | None] = mapped_column(JSONB)                                 # typed extract (bzp_parse)
    url: Mapped[str | None] = mapped_column(Text)                                        # citation link
    source_locator: Mapped[str | None] = mapped_column(Text)                                 # line:12345 | file:<raw path>
    channel: Mapped[str] = mapped_column(String(12), server_default="bzp_copy")          # bzp_copy|bzp_api
    __table_args__ = (*prov_checks(),)


class Lot(ProvenanceMixin, Base):
    __tablename__ = "lot"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    procedure_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    lot_no: Mapped[int] = mapped_column(Integer, server_default="0")                     # 0 = not divided
    description: Mapped[str | None] = mapped_column(Text)
    cpv_main: Mapped[str | None] = mapped_column(String(10))
    duration_raw: Mapped[str | None] = mapped_column(Text)
    estimated_value_amount: Mapped[Decimal | None] = mapped_column(Money)
    estimated_value_currency: Mapped[str | None] = mapped_column(String(3))
    estimated_value_vat: Mapped[str | None] = mapped_column(String(7))
    outcome: Mapped[str | None] = mapped_column(Text)
    cancelled: Mapped[bool | None] = mapped_column(Boolean)
    cancel_basis: Mapped[str | None] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    n_offers: Mapped[int | None] = mapped_column(Integer)
    n_offers_sme: Mapped[int | None] = mapped_column(Integer)
    n_rejected: Mapped[int | None] = mapped_column(Integer)
    min_offer_amount: Mapped[Decimal | None] = mapped_column(Money)
    max_offer_amount: Mapped[Decimal | None] = mapped_column(Money)
    winning_offer_amount: Mapped[Decimal | None] = mapped_column(Money)
    offers_vat: Mapped[str | None] = mapped_column(String(7), server_default="gross")
    contract_notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    result_notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    __table_args__ = (UniqueConstraint("procedure_id", "lot_no", name="uq_lot_procedure_lot"), *prov_checks())


class Offer(ProvenanceMixin, Base):
    __tablename__ = "offer"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lot_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lot.id", ondelete="CASCADE"), index=True)
    contractor_org_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organization.id"))
    contractor_name: Mapped[str | None] = mapped_column(Text)
    price_amount: Mapped[Decimal | None] = mapped_column(Money)
    price_currency: Mapped[str | None] = mapped_column(String(3))
    price_vat: Mapped[str | None] = mapped_column(String(7))
    is_winner: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    __table_args__ = (*prov_checks(),)


class Contract(ProvenanceMixin, Base):
    __tablename__ = "contract"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    procedure_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    lot_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lot.id", ondelete="SET NULL"), index=True)
    lot_no: Mapped[int | None] = mapped_column(Integer)
    contractor_org_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organization.id"), index=True)
    contractor_name: Mapped[str | None] = mapped_column(Text)
    contractor_nip: Mapped[str | None] = mapped_column(String(10), index=True)
    contractor_id_raw: Mapped[str | None] = mapped_column(Text)
    signed_on: Mapped[date | None] = mapped_column(Date, index=True)
    duration_raw: Mapped[str | None] = mapped_column(Text)
    planned_duration_days: Mapped[float | None] = mapped_column(Float)
    planned_end_on: Mapped[date | None] = mapped_column(Date)
    planned_end_computed: Mapped[bool | None] = mapped_column(Boolean)                  # from a duration, not a date
    value_amount: Mapped[Decimal | None] = mapped_column(Money)
    value_currency: Mapped[str | None] = mapped_column(String(3))
    value_vat: Mapped[str | None] = mapped_column(String(7))
    remuneration_type: Mapped[str | None] = mapped_column(String(40))
    terms_source: Mapped[str] = mapped_column(String(40), server_default="result_notice")
    # result_notice | performance_notice | change_notice | signed | reconstructed_from_PPU
    result_notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    result_notice_no: Mapped[str | None] = mapped_column(String(30), index=True)
    key: Mapped[str | None] = mapped_column(String(200), unique=True)                    # derivation key (idempotent)
    __table_args__ = (*prov_checks(),)


class ContractChange(ProvenanceMixin, Base):
    __tablename__ = "contract_change"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    procedure_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"), index=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30))                     # change_notice | performance_block | cru_annex
    change_no: Mapped[str | None] = mapped_column(String(40))
    changed_on: Mapped[date | None] = mapped_column(Date, index=True)
    legal_basis: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default="{}")   # 455.1.4 ...
    legal_basis_raw: Mapped[str | None] = mapped_column(Text)
    change_types: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default="{}")  # term|value|scope|...
    delta_days: Mapped[float | None] = mapped_column(Float)
    delta_value_amount: Mapped[Decimal | None] = mapped_column(Money)
    delta_value_currency: Mapped[str | None] = mapped_column(String(3))
    delta_value_vat: Mapped[str | None] = mapped_column(String(7))
    delta_value_pct: Mapped[float | None] = mapped_column(Float)
    price_increase: Mapped[bool | None] = mapped_column(Boolean)
    cause_text: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    cause_codes_kw: Mapped[list[str]] = mapped_column(ARRAY(String(40)), server_default="{}")  # keyword pre-classifier
    field_code: Mapped[str | None] = mapped_column(String(20))       # 5.3 / 5.4.4 ...
    key: Mapped[str | None] = mapped_column(String(200), unique=True)
    __table_args__ = (*prov_checks(),)


class ContractPerformance(ProvenanceMixin, Base):
    __tablename__ = "contract_performance"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    procedure_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"), unique=True)
    executed: Mapped[bool | None] = mapped_column(Boolean)
    completed_on: Mapped[date | None] = mapped_column(Date, index=True)
    on_time_declared: Mapped[bool | None] = mapped_column(Boolean)
    changes_count: Mapped[int | None] = mapped_column(Integer)
    total_paid_amount: Mapped[Decimal | None] = mapped_column(Money)
    total_paid_currency: Mapped[str | None] = mapped_column(String(3))
    total_paid_vat: Mapped[str | None] = mapped_column(String(7))
    properly_performed: Mapped[bool | None] = mapped_column(Boolean)
    not_executed_reason: Mapped[str | None] = mapped_column(Text)
    improper_reason: Mapped[str | None] = mapped_column(Text)
    # contract terms as restated in the performance notice
    contract_value_amount: Mapped[Decimal | None] = mapped_column(Money)
    signed_on: Mapped[date | None] = mapped_column(Date)
    planned_end_on: Mapped[date | None] = mapped_column(Date)
    planned_days: Mapped[float | None] = mapped_column(Float)
    # CALC
    actual_days: Mapped[int | None] = mapped_column(Integer)
    delay_days: Mapped[int | None] = mapped_column(Integer)
    cost_dev_pct: Mapped[float | None] = mapped_column(Float)
    # the same contract re-published under another notice number (research: 213) -> keep the latest
    is_duplicate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    duplicate_of_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract_performance.id", ondelete="SET NULL"))
    __table_args__ = (*prov_checks(),)


# ======================================================================================
# Documents, evidence, risk
# ======================================================================================

class Document(ProvenanceMixin, Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="SET NULL"), index=True)
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="SET NULL"), index=True)
    external_record_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("external_record.id", ondelete="SET NULL"), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(30), index=True)
    phase: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    path: Mapped[str | None] = mapped_column(Text)
    text_path: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(120))
    pages: Mapped[int | None] = mapped_column(Integer)
    ocr: Mapped[bool] = mapped_column(Boolean, server_default="false")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    fetch_state: Mapped[str] = mapped_column(String(20), server_default="found")
    sensitivity: Mapped[str] = mapped_column(String(20), server_default="public")       # public|confidential
    note: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    key: Mapped[str | None] = mapped_column(String(200), unique=True)
    __table_args__ = (check_in("fetch_state", FETCH_STATE), *prov_checks())


class DocumentPage(Base):
    __tablename__ = "document_page"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text)
    ocr: Mapped[bool] = mapped_column(Boolean, server_default="false")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("document_id", "page_no", name="uq_document_page"),)


class Chunk(Base):
    __tablename__ = "chunk"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="CASCADE"), index=True)
    page_no: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    tsv: Mapped[Any | None] = mapped_column(TSVECTOR)
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBED_DIM))
    embed_model: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index("ix_chunk_tsv", "tsv", postgresql_using="gin"),)


class Evidence(Base):
    """Claim (table,id,field) -> where it is proven: notice field code, document page span, or URL."""
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    claim_table: Mapped[str] = mapped_column(String(40))
    claim_id: Mapped[int] = mapped_column(BigInteger)
    claim_field: Mapped[str | None] = mapped_column(String(60))
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"), index=True)
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    field_code: Mapped[str | None] = mapped_column(String(20))
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="SET NULL"))
    chunk_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("chunk.id", ondelete="SET NULL"))
    page_no: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification: Mapped[str] = mapped_column(String(20), server_default="structured_field")
    evidence_state: Mapped[str | None] = mapped_column(String(30))
    state_reason: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_evidence_claim", "claim_table", "claim_id"),
        check_in("verification", VERIFICATION),
        check_in("evidence_state", EVIDENCE_STATE),
    )


class RiskEvent(ProvenanceMixin, Base):
    __tablename__ = "risk_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), index=True)
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    contract_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    change_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract_change.id", ondelete="SET NULL"))
    event_type: Mapped[str | None] = mapped_column(String(40), index=True)    # late_completion|overrun|change|...
    catalogue_code: Mapped[str | None] = mapped_column(String(12), index=True) # R01..R18 / R02.1
    summary: Mapped[str] = mapped_column(Text)
    cause: Mapped[str | None] = mapped_column(Text)
    impact_days: Mapped[float | None] = mapped_column(Float)
    impact_value_amount: Mapped[Decimal | None] = mapped_column(Money)
    impact_value_currency: Mapped[str | None] = mapped_column(String(3))
    impact_value_vat: Mapped[str | None] = mapped_column(String(7))
    impact_pct: Mapped[float | None] = mapped_column(Float)
    mitigation: Mapped[str | None] = mapped_column(Text)
    mitigation_effectiveness: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(String(30))
    occurred_on: Mapped[date | None] = mapped_column(Date)
    evidence_state: Mapped[str | None] = mapped_column(String(30))
    conf_data_quality: Mapped[float | None] = mapped_column(Float)
    conf_completeness: Mapped[float | None] = mapped_column(Float)
    conf_link_strength: Mapped[float | None] = mapped_column(Float)
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_call.id", ondelete="SET NULL"))
    key: Mapped[str | None] = mapped_column(String(200), unique=True)
    __table_args__ = (check_in("evidence_state", EVIDENCE_STATE), *prov_checks())


class RiskSignal(ProvenanceMixin, Base):
    __tablename__ = "risk_signal"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), index=True)
    analysis_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("analysis.id", ondelete="CASCADE"), index=True)
    catalogue_code: Mapped[str | None] = mapped_column(String(12), index=True)
    signal_code: Mapped[str | None] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    strength: Mapped[float | None] = mapped_column(Float)
    suggested_clause: Mapped[str | None] = mapped_column(Text)
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_call.id", ondelete="SET NULL"))
    __table_args__ = (*prov_checks(),)


# ======================================================================================
# Other public sources (generic) and linking
# ======================================================================================

class ExternalRecordRow(ProvenanceMixin, Base):
    """Normalised record from a non-BZP connector (TED, KIO, NIK, CRU, Mapa Dotacji, VAT...)."""
    __tablename__ = "external_record"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(40), index=True)     # connector id
    kind: Mapped[str] = mapped_column(String(40), index=True)            # ted_notice, kio_ruling, ...
    external_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(Text)
    published_on: Mapped[date | None] = mapped_column(Date, index=True)
    buyer_nip: Mapped[str | None] = mapped_column(String(10), index=True)
    buyer_regon: Mapped[str | None] = mapped_column(String(14))
    buyer_name: Mapped[str | None] = mapped_column(Text)
    buyer_org_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("organization.id", ondelete="SET NULL"))
    teryt: Mapped[str | None] = mapped_column(String(7))
    province: Mapped[str | None] = mapped_column(String(40))
    value_amount: Mapped[Decimal | None] = mapped_column(Money)
    value_currency: Mapped[str | None] = mapped_column(String(3))
    value_vat: Mapped[str | None] = mapped_column(String(7))
    url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="SET NULL"), index=True)
    __table_args__ = (UniqueConstraint("kind", "external_id", name="uq_external_record_kind_id"), *prov_checks())


class SourceCheckRow(TimestampMixin, Base):
    """'Searched source X for subject Y', recorded also when nothing was found."""
    __tablename__ = "source_check"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_kind: Mapped[str] = mapped_column(String(40), index=True)
    subject_type: Mapped[str] = mapped_column(String(20))
    subject_key: Mapped[str] = mapped_column(String(100), index=True)
    query: Mapped[Any | None] = mapped_column(JSONB)
    n_hits: Mapped[int] = mapped_column(Integer, server_default="0")
    n_relevant: Mapped[int] = mapped_column(Integer, server_default="0")
    result: Mapped[str] = mapped_column(String(12))
    matched_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    note: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"))
    __table_args__ = (
        UniqueConstraint("source_kind", "subject_type", "subject_key", name="uq_source_check_subject"),
        check_in("result", ("found", "not_found", "blocked", "error", "partial")),
    )


class LinkCandidate(TimestampMixin, Base):
    __tablename__ = "link_candidate"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    left_table: Mapped[str] = mapped_column(String(40))
    left_id: Mapped[int] = mapped_column(BigInteger)
    right_table: Mapped[str] = mapped_column(String(40))
    right_id: Mapped[int | None] = mapped_column(BigInteger)
    right_ref: Mapped[str | None] = mapped_column(Text)                # e.g. OCID / external key
    method: Mapped[str] = mapped_column(String(60))                    # exact_id|normalised_id|cross_reference|fuzzy|exact_value+beneficiary
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    explanation: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(12), server_default="review")     # accept|review|reject (automatic)
    review_status: Mapped[str] = mapped_column(String(10), server_default="proposed")
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ingestion_run.id", ondelete="SET NULL"))
    reference_verdict: Mapped[str | None] = mapped_column(String(12))  # correct|uncertain|wrong (vs reference set)
    __table_args__ = (
        Index("ix_link_candidate_left", "left_table", "left_id"),
        UniqueConstraint("left_table", "left_id", "right_table", "right_ref", "method", name="uq_link_candidate"),
    )


# ======================================================================================
# Review, audit, catalogue, gold
# ======================================================================================

class ReviewItem(TimestampMixin, Base):
    """Queue entry for the expert: data discrepancies, links, events, facts, catalogue proposals."""
    __tablename__ = "review_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)          # discrepancy|link|event|fact|catalogue
    code: Mapped[str | None] = mapped_column(String(60), index=True)   # e.g. part_mismatch, kpo_value_deviation
    target_table: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)                           # Polish, user-facing
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    severity: Mapped[str] = mapped_column(String(10), server_default="medium")    # low|medium|high
    status: Mapped[str] = mapped_column(String(12), server_default="open", index=True)  # open|resolved|dismissed
    created_by: Mapped[str | None] = mapped_column(String(60))
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"))
    key: Mapped[str | None] = mapped_column(String(200), unique=True)


class Review(Base):
    __tablename__ = "review"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_table: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int] = mapped_column(BigInteger)
    review_item_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("review_item.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(20))                    # approve|edit|reject|mark_gold|comment
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reviewer: Mapped[str] = mapped_column(String(80))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_review_target", "target_table", "target_id"),
        check_in("action", ("approve", "edit", "reject", "mark_gold", "comment")),
    )


class AuditLog(Base):
    """Append-only (UPDATE/DELETE rejected by trigger)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor: Mapped[str] = mapped_column(String(80))                     # user / system:<component>
    action: Mapped[str] = mapped_column(String(40))
    table_name: Mapped[str | None] = mapped_column(String(40))
    row_id: Mapped[int | None] = mapped_column(BigInteger)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_audit_log_row", "table_name", "row_id"),)


class _CatalogueMixin(TimestampMixin):
    sector: Mapped[str] = mapped_column(String(20), server_default="wod-kan", index=True)
    status: Mapped[str] = mapped_column(String(10), server_default="approved")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    origin: Mapped[str] = mapped_column(String(8), server_default="SOURCE")    # SOURCE (expert pack) | AI (proposal)
    proposed_by: Mapped[str | None] = mapped_column(String(80))
    approved_by: Mapped[str | None] = mapped_column(String(80))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class CatalogueRisk(_CatalogueMixin, Base):
    __tablename__ = "catalogue_risk"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(12))                      # R01, R02.1, R16
    parent_code: Mapped[str | None] = mapped_column(String(12))
    level: Mapped[int] = mapped_column(Integer, server_default="1")
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("sector", "code", "version", name="uq_catalogue_risk"), check_in("status", CATALOGUE_STATUS))


class CatalogueSubsector(_CatalogueMixin, Base):
    __tablename__ = "catalogue_subsector"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("sector", "code", "version", name="uq_catalogue_subsector"), check_in("status", CATALOGUE_STATUS))


class CatalogueCpvMap(_CatalogueMixin, Base):
    __tablename__ = "catalogue_cpv_map"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cpv: Mapped[str] = mapped_column(String(10))
    label: Mapped[str | None] = mapped_column(Text)
    subsector_code: Mapped[str | None] = mapped_column(String(12))
    strength: Mapped[str | None] = mapped_column(String(10))           # strong|weak
    __table_args__ = (UniqueConstraint("sector", "cpv", "version", name="uq_catalogue_cpv_map"), check_in("status", CATALOGUE_STATUS))


class CatalogueDocType(_CatalogueMixin, Base):
    __tablename__ = "catalogue_doc_type"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(String(30))
    __table_args__ = (UniqueConstraint("sector", "code", "version", name="uq_catalogue_doc_type"), check_in("status", CATALOGUE_STATUS))


class CatalogueChecklist(_CatalogueMixin, Base):
    __tablename__ = "catalogue_checklist"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    phase: Mapped[str | None] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("sector", "code", "version", name="uq_catalogue_checklist"), check_in("status", CATALOGUE_STATUS))


class CatalogueClause(_CatalogueMixin, Base):
    __tablename__ = "catalogue_clause"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(30))
    risk_code: Mapped[str | None] = mapped_column(String(12), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("sector", "code", "version", name="uq_catalogue_clause"), check_in("status", CATALOGUE_STATUS))


class CatalogueEntry(_CatalogueMixin, Base):
    """Other sector-pack tables (event types, red flags, phases, similarity weights, price index...)."""
    __tablename__ = "catalogue_entry"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    table_name: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("sector", "table_name", "code", "version", name="uq_catalogue_entry"), check_in("status", CATALOGUE_STATUS))


class GoldExample(TimestampMixin, Base):
    __tablename__ = "gold_example"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task: Mapped[str] = mapped_column(String(60), index=True)
    catalogue_code: Mapped[str | None] = mapped_column(String(12), index=True)
    input_text: Mapped[str] = mapped_column(Text)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    target_table: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    review_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("review.id", ondelete="SET NULL"))
    created_by: Mapped[str | None] = mapped_column(String(80))


# ======================================================================================
# Analysis, monitoring, reference data
# ======================================================================================

class Analysis(TimestampMixin, Base):
    __tablename__ = "analysis"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    input_text: Mapped[str | None] = mapped_column(Text)
    input_documents: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    reference_class: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")   # definition + n
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    sensitivity: Mapped[str] = mapped_column(String(20), server_default="public")
    status: Mapped[str] = mapped_column(String(20), server_default="draft")
    created_by: Mapped[str | None] = mapped_column(String(80))
    sector: Mapped[str] = mapped_column(String(20), server_default="wod-kan")


class AnalysisItem(ProvenanceMixin, Base):
    __tablename__ = "analysis_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    analysis_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("analysis.id", ondelete="CASCADE"), index=True)
    section: Mapped[str] = mapped_column(String(40))      # similar_case|forecast|red_flag|checklist_gap|recommendation|clause|limitation
    rank: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    catalogue_code: Mapped[str | None] = mapped_column(String(12))
    llm_call_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_call.id", ondelete="SET NULL"))
    __table_args__ = (*prov_checks(),)


class MonitorWatch(TimestampMixin, Base):
    __tablename__ = "monitor_watch"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("contract.id", ondelete="CASCADE"), index=True)
    procedure_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("procedure.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("project.id", ondelete="CASCADE"))
    reason: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class Alert(TimestampMixin, Base):
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    watch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("monitor_watch.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"))
    notice_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notice.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), server_default="new")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FetchQueue(TimestampMixin, Base):
    """Rate-capped backlogs (e.g. VAT whitelist 100 req/day)."""
    __tablename__ = "fetch_queue"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    connector: Mapped[str] = mapped_column(String(40), index=True)
    item_key: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, server_default="100")
    status: Mapped[str] = mapped_column(String(12), server_default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    next_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("connector", "item_key", name="uq_fetch_queue_item"),)


class RefTeryt(Base):
    __tablename__ = "ref_teryt"
    terc: Mapped[str] = mapped_column(String(7), primary_key=True)      # woj(2)+pow(2)+gmi(2)+rodz(1), shorter for woj/pow
    level: Mapped[str] = mapped_column(String(10))                      # woj|pow|gmi
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)
    woj: Mapped[str] = mapped_column(String(2), index=True)
    pow: Mapped[str | None] = mapped_column(String(2))
    gmi: Mapped[str | None] = mapped_column(String(2))
    rodz: Mapped[str | None] = mapped_column(String(1))
    source_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"))


VAT_BASIS_VALUES = VAT_BASIS
