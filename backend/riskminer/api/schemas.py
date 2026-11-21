"""Pydantic v2 response models (the OpenAPI contract for the frontend and analytics)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Money(BaseModel):
    """Money value object. Compare only like with like (net vs gross)."""
    amount: Decimal | None = None
    currency: str | None = None
    vat_basis: Literal["net", "gross", "unknown"] | None = None


class Provenance(BaseModel):
    source_id: int | None = None
    origin: Literal["SOURCE", "CALC", "AI"] | None = None
    review_status: Literal["auto", "proposed", "approved", "edited", "rejected"] | None = None


class Page(BaseModel, Generic[T]):
    total: int
    limit: int
    offset: int
    items: list[T]


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationOut(Base):
    id: int
    nip: str | None
    regon: str | None = None
    krs: str | None = None
    name: str
    roles: list[str] = []
    province: str | None = None
    city: str | None = None
    teryt: str | None = None
    vat_status: str | None = None
    nip_valid: bool | None = None
    provenance: Provenance


class ProjectOut(Base):
    id: int
    rm_id: str
    title: str
    description: str | None = None
    beneficiary_name: str | None = None
    beneficiary_nip: str | None = None
    public_id_type: str | None = None
    public_id: str | None = None
    external_ids: dict[str, Any] = {}
    scope_text: str | None = None
    scope_part: int | None = None
    funding_programme: str | None = None
    value: Money
    subsidy: Money
    subsector_main: str | None = None
    subsectors_extra: list[str] = []
    works_type: str | None = None
    delivery_model: str | None = None
    status: str | None = None
    province: str | None = None
    city: str | None = None
    sector: str
    is_pilot: bool
    # summary
    procedures: list[str] = []          # OCIDs (main link first)
    link_method: str | None = None
    link_score: float | None = None
    open_issues: int = 0
    provenance: Provenance


class LotOut(Base):
    id: int
    lot_no: int
    description: str | None = None
    cpv_main: str | None = None
    estimated_value: Money
    outcome: str | None = None
    cancelled: bool | None = None
    cancel_reason: str | None = None
    n_offers: int | None = None
    min_offer: Money
    max_offer: Money
    winning_offer: Money


class PerformanceOut(Base):
    id: int
    contract_id: int | None
    notice_id: int | None
    notice_number: str | None = None
    notice_url: str | None = None
    executed: bool | None
    completed_on: date | None
    on_time_declared: bool | None
    changes_count: int | None
    total_paid: Money
    properly_performed: bool | None
    not_executed_reason: str | None = None
    improper_reason: str | None = None
    planned_end_on: date | None = None
    actual_days: int | None = None
    delay_days: int | None = None
    cost_dev_pct: float | None = None
    provenance: Provenance


class ChangeOut(Base):
    id: int
    contract_id: int | None
    procedure_id: int
    notice_id: int | None
    notice_number: str | None = None
    notice_url: str | None = None
    kind: str
    change_no: str | None = None
    changed_on: date | None = None
    legal_basis: list[str] = []
    legal_basis_raw: str | None = None
    change_types: list[str] = []
    delta_days: float | None = None
    delta_value: Money
    delta_value_pct: float | None = None
    price_increase: bool | None = None
    cause_text: str | None = None
    description_text: str | None = None
    cause_codes_kw: list[str] = []
    provenance: Provenance


class ContractOut(Base):
    id: int
    procedure_id: int
    ocid: str | None = None
    lot_no: int | None = None
    contractor_name: str | None = None
    contractor_nip: str | None = None
    signed_on: date | None = None
    duration_raw: str | None = None
    planned_duration_days: float | None = None
    planned_end_on: date | None = None
    planned_end_computed: bool | None = None
    value: Money
    terms_source: str
    result_notice_no: str | None = None
    performance: list[PerformanceOut] = []
    changes: list[ChangeOut] = []
    provenance: Provenance


class NoticeOut(Base):
    id: int
    object_id: str
    notice_type: str
    notice_number: str
    bzp_number: str | None = None
    version: int | None = None
    is_latest: bool
    ocid: str | None = None
    published_at: datetime | None = None
    buyer_nip: str | None = None
    buyer_name: str | None = None
    province: str | None = None
    order_object: str | None = None
    url: str | None = None
    channel: str
    source_id: int | None = None
    source_locator: str | None = None


class NoticeDetailOut(NoticeOut):
    cpv_raw: str | None = None
    refs: list[str] = []
    raw_json: dict[str, Any] = {}
    parsed_fields: dict[str, Any] | None = None
    extracted: Any = None
    html_body: str | None = None


class ProcedureOut(Base):
    id: int
    ocid: str
    contract_notice_no: str | None = None
    contract_notice_missing: bool = False
    title: str | None = None
    buyer_nip: str | None = None
    buyer_name: str | None = None
    province: str | None = None
    city: str | None = None
    cpv_main: str | None = None
    cpv_all: list[str] = []
    mode: str | None = None
    order_type: str | None = None
    estimated_value: Money
    below_eu: bool | None = None
    eu_funded: bool | None = None
    n_lots: int | None = None
    platform_url: str | None = None
    first_published_on: date | None = None
    last_published_on: date | None = None
    notice_types: list[str] = []
    cancelled: bool | None = None
    relevance: str | None = None
    subsector_main: str | None = None
    subsectors: list[str] = []
    scope_kind: str | None = None
    work_type: str | None = None
    design_build: bool | None = None
    classify_why: str | None = None
    provenance: Provenance


class TimelineEvent(BaseModel):
    date: date | datetime | None
    kind: str                     # notice | contract_signed | planned_end | completed | change
    title: str
    notice_type: str | None = None
    notice_number: str | None = None
    url: str | None = None
    ocid: str | None = None
    detail: dict[str, Any] = {}
    origin: str = "SOURCE"


class ProcedureDetailOut(ProcedureOut):
    lots: list[LotOut] = []
    contracts: list[ContractOut] = []
    notices: list[NoticeOut] = []
    timeline: list[TimelineEvent] = []


class LinkCandidateOut(Base):
    id: int
    left_table: str
    left_id: int
    right_table: str
    right_id: int | None
    right_ref: str | None
    method: str
    features: dict[str, Any] = {}
    score: float | None
    rank: int | None
    explanation: str | None
    decision: str
    review_status: str
    reference_verdict: str | None = None
    created_at: datetime


class ProjectLinkOut(Base):
    procedure_id: int
    ocid: str
    method: str
    score: float | None
    explanation: dict[str, Any] = {}
    lots: list[int] = []
    review_status: str


class ReviewItemOut(Base):
    id: int
    kind: str
    code: str | None
    target_table: str | None
    target_id: int | None
    project_id: int | None
    rm_id: str | None = None
    title: str
    detail: dict[str, Any] = {}
    severity: str
    status: str
    created_by: str | None
    created_at: datetime


class SourceOut(Base):
    id: int
    kind: str
    url: str | None
    method: str | None
    retrieved_at: datetime | None
    http_status: int | None
    content_type: str | None
    bytes: int | None
    sha256: str | None
    path: str | None
    licence: str | None
    status: str
    note: str | None
    run_id: Any = None


class SourceSummaryOut(BaseModel):
    kind: str
    files: int
    ok: int
    empty: int
    blocked: int
    error: int
    bytes: int
    last_retrieved_at: datetime | None
    records: int
    licence: str | None


class RunOut(Base):
    id: Any
    connector: str
    stage: str
    params: dict[str, Any] = {}
    started_at: datetime
    finished_at: datetime | None
    status: str
    stats: dict[str, Any] = {}
    error: str | None
    job_id: int | None


class JobOut(Base):
    id: int
    kind: str
    payload: dict[str, Any] = {}
    status: str
    priority: int
    attempts: int
    run_after: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime


class JobIn(BaseModel):
    kind: str = Field(description="scrape:<source> | load:<source> | import_xlsx | import_bzp_copy | derive_bzp | "
                                  "link_pilot | load_all | report")
    payload: dict[str, Any] = {}
    priority: int = 100


class ExternalRecordOut(Base):
    id: int
    source_kind: str
    kind: str
    external_id: str
    title: str | None
    published_on: date | None
    buyer_nip: str | None
    buyer_name: str | None
    province: str | None
    value: Money
    url: str | None
    data: dict[str, Any] = {}
    procedure_id: int | None = None
    provenance: Provenance


class SourceCheckOut(Base):
    id: int
    source_kind: str
    subject_type: str
    subject_key: str
    query: Any = None
    n_hits: int
    n_relevant: int
    result: str
    matched_ids: list[str] = []
    note: str | None
    checked_at: datetime | None
    source_id: int | None


class EvidenceOut(Base):
    id: int
    claim_table: str
    claim_id: int
    claim_field: str | None
    source_id: int | None
    notice_id: int | None
    field_code: str | None
    document_id: int | None
    page_no: int | None
    quote: str | None
    url: str | None
    retrieved_at: datetime | None
    verification: str
    evidence_state: str | None


class DocumentOut(Base):
    id: int
    project_id: int | None
    procedure_id: int | None
    doc_type: str | None
    title: str | None
    filename: str | None
    url: str | None
    sha256: str | None
    path: str | None
    text_path: str | None
    pages: int | None
    fetch_state: str
    note: str | None
    provenance: Provenance


class RiskEventOut(Base):
    id: int
    project_id: int | None
    procedure_id: int | None
    contract_id: int | None
    change_id: int | None
    event_type: str | None
    catalogue_code: str | None
    summary: str
    cause: str | None = None
    impact_days: float | None = None
    impact_value: Money
    impact_pct: float | None = None
    occurred_on: date | None = None
    evidence_state: str | None = None
    conf_data_quality: float | None = None
    conf_completeness: float | None = None
    conf_link_strength: float | None = None
    provenance: Provenance


class ProjectDetailOut(ProjectOut):
    organization: OrganizationOut | None = None
    links: list[ProjectLinkOut] = []
    link_candidates: list[LinkCandidateOut] = []
    procedure_details: list[ProcedureDetailOut] = []
    review_items: list[ReviewItemOut] = []
    source_checks: list[SourceCheckOut] = []
    documents: list[DocumentOut] = []
    external_links: list[LinkCandidateOut] = []
    risk_events: list[RiskEventOut] = []
    dataset_row: dict[str, Any] | None = None


class StatsOut(BaseModel):
    tables: dict[str, int]
    notices_by_type: dict[str, int]
    notices_by_channel: dict[str, int]
    procedures_by_relevance: dict[str, int]
    pilot: dict[str, Any]
    sources: list[SourceSummaryOut]
    last_runs: list[RunOut]
