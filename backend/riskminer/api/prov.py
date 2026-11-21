"""Shared provenance types for every new endpoint (docs/impl/api_contract.md §2.0). FROZEN at 20:45 Sat 21.11.

Owned by the lead (S0). Do not edit: ask the lead for additions. Area models go in `api/schemas_<area>.py`
and reuse these types.

Rules (tested):
1. Every metric is a `Num` (or `Range` / `Money` inside an object that carries `prov`). Bare numbers only for ids, ranks,
   page numbers, offsets, versions, pagination and chart coordinates inside a series that has its own `prov`.
2. `role` maps from DB `origin`: SOURCE -> source, CALC -> calc, AI -> ai. `case` = a fact of another project/procedure
   shown as evidence (keeps the underlying refs).
3. `calc` requires `n` and `method` and a `query` ref; `n < analytics.insufficient_n` (10) -> value None,
   insufficient True, display "za mało danych" (use `num_calc`, it applies the rule).
4. `source` requires a ref with notice number + field code, document + page, or URL with retrieved_at.
5. `ai` requires `llm` and a `review_status`; quotes carry `verification`.
6. Expert assumptions are role `source` with a `catalogue` ref and `assumption=True` (UI: "założenie eksperta").
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from riskminer.api.schemas import Money, Page  # re-exported: Money value object, Page[T]

__all__ = [
    "INSUFFICIENT_DISPLAY",
    "INSUFFICIENT_N",
    "Answer",
    "AnswerAction",
    "AnswerMethod",
    "Bar",
    "Contribution",
    "ErrorOut",
    "LLMInfo",
    "Money",
    "MoneyProv",
    "Num",
    "Page",
    "Processing",
    "Prov",
    "Range",
    "Ref",
    "RefKind",
    "ReviewStatus",
    "Role",
    "Signal",
    "SimilarCase",
    "SimilarOutcome",
    "Unit",
    "Verification",
    "fmt_num",
    "num_ai",
    "num_calc",
    "num_case",
    "num_source",
    "q_ref",
    "role_from_origin",
]

INSUFFICIENT_N = 10
INSUFFICIENT_DISPLAY = "za mało danych"

Role = Literal["source", "calc", "case", "ai"]
ReviewStatus = Literal["auto", "proposed", "approved", "edited", "rejected"]
RefKind = Literal["notice", "document", "query", "project", "procedure", "contract", "catalogue", "llm_call", "source",
                  "input_text", "file"]
Verification = Literal["exact", "fuzzy", "unverified", "structured_field"]
Unit = Literal["days", "months", "pct", "share", "pln", "mln_pln_per_km", "count", "offers", "score"]


class Ref(BaseModel):
    """Pointer to the evidence behind a value (notice field, document page, query filter, catalogue entry...)."""
    kind: RefKind
    id: str
    label: str
    url: str | None = None
    page_no: int | None = None
    field_code: str | None = None
    quote: str | None = None
    verification: Verification | None = None
    retrieved_at: datetime | None = None


class LLMInfo(BaseModel):
    provider: str
    model: str
    data_location: str
    llm_call_id: int | None = None


class Prov(BaseModel):
    role: Role
    review_status: ReviewStatus
    n: int | None = None
    method: str | None = None
    refs: list[Ref] = Field(default_factory=list)
    ci90: tuple[float, float] | None = None
    insufficient: bool | None = None
    assumption: bool | None = None
    llm: LLMInfo | None = None


class Num(BaseModel):
    value: float | None
    display: str
    unit: Unit
    prov: Prov


class Range(BaseModel):
    """Distribution summary for a range bar. `you` = the user's value, `marker` = e.g. programme end."""
    unit: Unit
    axis: tuple[float, float]
    p10: float | None = None
    p25: float | None = None
    p50: float
    p75: float | None = None
    p80: float | None = None
    p90: float | None = None
    you: float | None = None
    marker: dict[str, Any] | None = None   # {x, label}
    n: int
    plain: str


class MoneyProv(BaseModel):
    """Money with provenance (expected cost, overpaid total)."""
    money: Money
    prov: Prov


class Bar(BaseModel):
    label: str
    value: float
    display: str
    highlight: bool = False


class AnswerMethod(BaseModel):
    kind: Literal["sql", "template", "llm"]
    sql: str | None = None
    view: str | None = None
    template: str | None = None


class Processing(BaseModel):
    provider: str
    model: str
    data_location: str


class AnswerAction(BaseModel):
    kind: str
    label: str
    href: str | None = None


class Answer(BaseModel):
    """Chat / ask answer (pattern 13). `role` calc when SQL or a template ran, ai for explanations, no_data names the gap."""
    id: str
    code: str | None = None
    role: Literal["calc", "ai", "no_data"]
    role_label: Literal["obliczenie", "wniosek AI", "brak danych"]
    text: str
    bars: list[Bar] = Field(default_factory=list)
    numbers: list[Num] = Field(default_factory=list)
    method: AnswerMethod
    sources: list[Ref] = Field(default_factory=list)
    n: int | None = None
    missing: list[str] = Field(default_factory=list)
    actions: list[AnswerAction] = Field(default_factory=list)
    apply: dict[str, Any] | None = None
    processing: Processing | None = None


class Contribution(BaseModel):
    feature: str
    label: str
    value: float


class SimilarOutcome(BaseModel):
    delay_days: Num
    cost_dev_pct: Num


class SimilarCase(BaseModel):
    rank: int
    score: Num
    rm_id: str | None = None
    ocid: str
    title: str
    why: str
    contributions: list[Contribution]
    outcome: SimilarOutcome
    href: str
    buyer_name: str | None = None
    year: int | None = None
    changes_count: int | None = None


class Signal(BaseModel):
    """Monitoring signal: a core contract past its planned end with no performance notice."""
    contract_id: int
    ocid: str
    bzp_number: str | None = None
    lot_no: int | None = None
    n_parts: int | None = None
    buyer_name: str | None = None
    title: str | None = None
    value: Money
    signed_on: str | None = None
    planned_end_on: str | None = None
    days_overdue: Num
    n_change_notices: int = 0
    has_performance: bool = False
    woj: str | None = None
    pow: str | None = None
    gmi: str | None = None
    lon: float | None = None
    lat: float | None = None
    location_method: str | None = None
    watched: bool = False


class ErrorOut(BaseModel):
    detail: str          # Polish message
    code: str            # machine code, e.g. protected_row, sovereign_unavailable, csrf_header_missing


# ---- helpers ---------------------------------------------------------------------------------------------------------

_ORIGIN_ROLE = {"SOURCE": "source", "CALC": "calc", "AI": "ai", "CASE": "case"}


def role_from_origin(origin: str | None) -> Role:
    return _ORIGIN_ROLE.get((origin or "").upper(), "source")  # type: ignore[return-value]


def fmt_num(x: float | None, decimals: int = 0) -> str:
    """Polish number format: no-break space thousands separator (U+00A0), decimal comma. 11574 -> '11 574', 0.5 -> '0,5'."""
    if x is None:
        return ""
    s = f"{x:,.{decimals}f}"
    return s.replace(",", " ").replace(".", ",")


def q_ref(query_id: str, label: str) -> Ref:
    return Ref(kind="query", id=query_id, label=label)


def num_calc(value: float | None, display: str, unit: Unit, *, n: int, method: str, refs: list[Ref],
             ci90: tuple[float, float] | None = None, min_n: int = INSUFFICIENT_N) -> Num:
    """Calculated number; applies the insufficient-n rule (value None, display 'za mało danych')."""
    if n < min_n:
        return Num(value=None, display=INSUFFICIENT_DISPLAY, unit=unit,
                   prov=Prov(role="calc", review_status="auto", n=n, method=method, refs=refs, insufficient=True))
    return Num(value=value, display=display, unit=unit,
               prov=Prov(role="calc", review_status="auto", n=n, method=method, refs=refs, ci90=ci90))


def num_source(value: float | None, display: str, unit: Unit, refs: list[Ref], review_status: ReviewStatus = "auto",
               assumption: bool | None = None) -> Num:
    return Num(value=value, display=display, unit=unit,
               prov=Prov(role="source", review_status=review_status, refs=refs, assumption=assumption))


def num_ai(value: float | None, display: str, unit: Unit, refs: list[Ref], llm: LLMInfo,
           review_status: ReviewStatus = "proposed") -> Num:
    return Num(value=value, display=display, unit=unit,
               prov=Prov(role="ai", review_status=review_status, refs=refs, llm=llm))


def num_case(value: float | None, display: str, unit: Unit, refs: list[Ref], review_status: ReviewStatus = "auto",
             n: int | None = None) -> Num:
    return Num(value=value, display=display, unit=unit, prov=Prov(role="case", review_status=review_status, n=n, refs=refs))

