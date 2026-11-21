"""Declarative base, naming convention, shared column mixins and enums (as CHECK-constrained text)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# ---- enums (kept as text + CHECK so adding a value is a one-line migration) --------------
ORIGIN = ("SOURCE", "CALC", "AI")
REVIEW_STATUS = ("auto", "proposed", "approved", "edited", "rejected")
VAT_BASIS = ("net", "gross", "unknown")
# docs/research/03_domain_methodology.md §6.1
EVIDENCE_STATE = (
    "JESZCZE_NIEWYMAGALNY", "BRAK_W_PACZCE", "NIECZYTELNY", "DOKUMENT_NIE_WSPOMINA",
    "BRAK_POTWIERDZENIA", "POTWIERDZONO", "POTWIERDZONO_NIE_WYKONANO", "SPRZECZNOSC",
)
# docs/scrape.md §4 (document acquisition state)
FETCH_STATE = ("found", "not_in_package", "blocked", "link_dead", "not_applicable")
VERIFICATION = ("exact", "fuzzy", "unverified", "structured_field")
JOB_STATUS = ("queued", "running", "done", "failed", "cancelled")
RUN_STATUS = ("running", "ok", "partial", "error")
CATALOGUE_STATUS = ("approved", "proposed", "rejected", "retired")


def check_in(col: str, values: tuple[str, ...], name: str | None = None) -> CheckConstraint:
    vals = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} IS NULL OR {col} IN ({vals})", name=name or f"{col}_enum")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProvenanceMixin(TimestampMixin):
    """Every fact row: where it came from, how it was produced, and its review state."""

    @declared_attr
    def source_id(cls) -> Mapped[int | None]:  # noqa: N805
        return mapped_column(BigInteger, ForeignKey("source.id", ondelete="SET NULL"), index=True)

    origin: Mapped[str] = mapped_column(String(8), server_default="SOURCE")
    review_status: Mapped[str] = mapped_column(String(10), server_default="auto")



def prov_checks() -> tuple:
    """CHECK constraints for ProvenanceMixin columns; include in each model's __table_args__."""
    return (check_in("origin", ORIGIN), check_in("review_status", REVIEW_STATUS))
