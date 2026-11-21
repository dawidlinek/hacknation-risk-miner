"""Pydantic models for the review, catalogue-edit, projects and audit routers (session B)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ReviewItemRow(BaseModel):
    id: int
    kind: str
    kind_label: str
    code: str | None = None
    rm_id: str | None = None
    title: str
    question: str | None = None
    context: dict[str, Any] = {}
    target_table: str | None = None
    target_id: int | None = None
    project_id: int | None = None
    detail: dict[str, Any] = {}
    severity: str
    status: str
    model_pick: str | None = None
    confidence: float | None = None
    created_by: str | None = None
    created_at: datetime
    resolved_by: str | None = None
    resolved_at: datetime | None = None


class DecisionIn(BaseModel):
    option: str | None = Field(None, description="klucz opcji z karty (np. R02, other, not_risk)")
    action: Literal["approve", "edit", "reject"]
    value: Any = None
    reason: str | None = None
    gold: bool = False


class BulkDecisionIn(BaseModel):
    ids: list[int] = Field(default_factory=list)
    action: Literal["approve"] = "approve"


class LinkIn(BaseModel):
    action: Literal["replace", "add", "remove"]
    bzp_number: str
    lots: list[int] = Field(default_factory=list)
    reason: str | None = None


class RestoreIn(BaseModel):
    reason: str


class ProjectRowOut(BaseModel):
    """Project list row: ProjectOut fields (extra allowed) + metrics (contract_value Money, delay_days/cost_dev_pct/changes Num,
    properly_performed, state)."""
    model_config = {"extra": "allow"}
    rm_id: str
    metrics: dict[str, Any]
