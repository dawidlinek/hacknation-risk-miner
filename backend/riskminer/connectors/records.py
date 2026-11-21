"""Normalised record shapes that connectors emit from raw files (`parse()`), loaded by
riskminer.ingest.external into the DB. Connectors never write to the DB directly: the DB tables are
derived from data/raw and can be rebuilt (`riskminer load <source>`).

Every record points back to its raw file (`raw_path` + `raw_sha256`), which maps to exactly one
manifest line -> one `source` row. RODO: never put personal contact fields (person names, phones,
e-mails of natural persons) into `data`/`text` of these records.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExternalRecord(BaseModel):
    record_type: Literal["external_record"] = "external_record"
    source: str                                   # connector id, e.g. "ted"
    kind: str                                     # ted_notice | kio_ruling | nik_audit | cru_agreement | kpo_project | vat_entity | ...
    external_id: str                              # stable id within (source, kind)
    title: str | None = None
    published_on: date | None = None
    buyer_nip: str | None = None
    buyer_regon: str | None = None
    buyer_name: str | None = None
    teryt: str | None = None                      # TERC code if known (woj 2 / pow 4 / gmina 7 digits)
    province: str | None = None                   # PL02..PL32 or name
    value_amount: Decimal | None = None
    value_currency: str | None = None
    value_vat_basis: Literal["net", "gross", "unknown"] | None = None
    url: str | None = None                        # human citation link
    raw_path: str | None = None                   # data/raw/<source>/... file this record was parsed from
    raw_sha256: str | None = None
    text: str | None = None                       # long text for search (e.g. ruling/audit text)
    data: dict[str, Any] = Field(default_factory=dict)


class SourceCheck(BaseModel):
    """'We searched X for subject Y' record - also when nothing was found (jury: completeness)."""
    record_type: Literal["source_check"] = "source_check"
    source: str
    subject_type: Literal["project", "organization", "procedure"]
    subject_key: str                              # rm_id (RM-2026-001) | NIP | OCID
    query: Any = None
    n_hits: int = 0
    n_relevant: int = 0
    result: Literal["found", "not_found", "blocked", "error", "partial"]
    matched_ids: list[str] = Field(default_factory=list)    # external_ids of matched ExternalRecords
    note: str = ""
    checked_at: datetime | None = None
    raw_path: str | None = None


class DocumentRecord(BaseModel):
    """A file (PDF/DOCX/...) fetched for a procedure/project/audit, or the evidence state of an
    expected document that could not be fetched."""
    record_type: Literal["document"] = "document"
    source: str
    subject_type: Literal["project", "procedure", "external_record"]
    subject_key: str                              # rm_id | OCID | "<kind>:<external_id>"
    doc_type: str | None = None                   # catalogue doc_type code guess (swz, pfu, opz, ppu, qa, ...)
    title: str | None = None
    filename: str | None = None
    url: str | None = None
    raw_path: str | None = None
    raw_sha256: str | None = None
    text_path: str | None = None                  # derived text (pdftotext) path
    pages: int | None = None
    fetch_state: Literal["found", "not_in_package", "blocked", "link_dead", "not_applicable"] = "found"
    note: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class LinkHint(BaseModel):
    """Proposed link between a pilot project / organization and an external record."""
    record_type: Literal["link_hint"] = "link_hint"
    source: str
    left_type: Literal["project", "organization", "procedure"]
    left_key: str
    right_type: str                               # e.g. "external_record"
    right_key: str                                # "<kind>:<external_id>"
    method: str                                   # exact_id | normalised_id | exact_value+beneficiary | fuzzy
    score: float
    features: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


AnyRecord = ExternalRecord | SourceCheck | DocumentRecord | LinkHint
