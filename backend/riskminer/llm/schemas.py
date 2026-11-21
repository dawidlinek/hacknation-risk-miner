"""Output models per task (docs/impl/llm.md §2). Field names English, values/keys Polish where they reach the UI."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- extract_features ---------------------------------------------------------------------------------------------
ChipKey = Literal["podsektor", "formula", "rodzaj_robot", "dlugosc_km", "przepompownie", "przylacza", "budzet",
                  "termin_mies", "finansowanie", "wojewodztwo", "wynagrodzenie", "technologie"]


class Chip(BaseModel):
    key: ChipKey
    value_code: str | None = Field(None, description="kod dla cech wyboru (SAN, design_build, FENIKS, ...)")
    value_text: str = Field(description="wartość tak, jak jest napisana, np. 'ok. 6 km'")
    value_num: float | None = None
    unit: str | None = None
    vat_basis: Literal["net", "gross", "unknown"] | None = None
    source: Literal["opis", "dokument"]
    document_id: int | None = None
    page: int | None = None
    pkt: str | None = None
    quote: str
    uncertain: bool = False
    uncertain_reason: str | None = None


class QuantityRow(BaseModel):
    key: Literal["dlugosc_km", "przylacza", "przepompownie"]
    label: str
    value_text: str
    value_num: float | None = None
    unit: str | None = None
    document_id: int | None = None
    page: int | None = None
    quote: str


class Features(BaseModel):
    chips: list[Chip] = []
    rows: list[QuantityRow] = []
    missing: list[str] = []


# --- redpen_scan --------------------------------------------------------------------------------------------------
class Note(BaseModel):
    code: str = Field(description="kod ryzyka z katalogu, np. R08 albo R01.2")
    page: int
    pkt: str | None = None
    quote: str
    title: str = Field(description="po polsku, maks. 60 znaków, zwykłe stwierdzenie")
    why: str = Field(description="jedno zdanie: dlaczego to sygnał ryzyka")
    strength: Literal["słaby", "średni", "silny"] = "średni"
    clause_hint: str | None = None


class RedPenWindow(BaseModel):
    notes: list[Note] = []


# --- classify_causes ----------------------------------------------------------------------------------------------
class CauseItem(BaseModel):
    id: str
    primary: str
    secondary: str | None = None
    quote: str
    confidence: float = Field(ge=0, le=1)


class CauseBatch(BaseModel):
    items: list[CauseItem] = []


# --- chat ---------------------------------------------------------------------------------------------------------
class WhatIf(BaseModel):
    metric: Literal["termin", "koszt", "konkurencja"]
    param: str
    value: float | str | bool


class ChatAnswer(BaseModel):
    answer: str
    role: Literal["calc", "ai", "no_data"]
    fact_ids: list[str] = []
    missing: list[str] = []
    apply: WhatIf | None = None
    follow_ups: list[str] = Field(default_factory=list, max_length=2)


# --- nl2sql -------------------------------------------------------------------------------------------------------
class BarSpec(BaseModel):
    label_col: str
    value_col: str


class SqlPlan(BaseModel):
    sql: str | None = None
    answer_template: str | None = None
    bars: BarSpec | None = None
    title: str
    cannot_answer: str | None = None


# --- import_mapping -----------------------------------------------------------------------------------------------
class MappingRow(BaseModel):
    column: str
    field: str | None = Field(None, description="pole docelowe z rejestru albo null, gdy kolumna nie pasuje")
    transform: Literal["none", "strip", "parse_pln", "parse_date", "nip_normalise", "split"] = "none"
    vat_basis: Literal["net", "gross", "unknown"] | None = None
    confidence: float = Field(0.5, ge=0, le=1)
    why: str | None = None


class ImportQuestion(BaseModel):
    key: str
    question: str
    options: list[str]


class ImportMapping(BaseModel):
    target: str = Field(description="rodzaj rekordów: project | procedure | contract | payment | other")
    mapping: list[MappingRow] = []
    questions: list[ImportQuestion] = []
    summary: str


# --- catalogue_proposals ------------------------------------------------------------------------------------------
class Proposal(BaseModel):
    name: str
    definition: str
    example_ids: list[str] = Field(default_factory=list)
    merge_with: str | None = None
    rationale: str | None = None


class ProposalBatch(BaseModel):
    proposals: list[Proposal] = Field(default_factory=list, max_length=5)
