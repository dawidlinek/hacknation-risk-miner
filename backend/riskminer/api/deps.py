"""Query helpers + row -> schema converters shared by the routers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import schemas as S


async def rows(db: AsyncSession, sql: str, **params) -> list[dict[str, Any]]:
    res = await db.execute(text(sql), params)
    return [dict(r) for r in res.mappings().all()]


async def one(db: AsyncSession, sql: str, **params) -> dict[str, Any] | None:
    r = await rows(db, sql, **params)
    return r[0] if r else None


async def scalar(db: AsyncSession, sql: str, **params) -> Any:
    return (await db.execute(text(sql), params)).scalar()


def money(r: dict, prefix: str, vat: str | None = None) -> S.Money:
    return S.Money(amount=r.get(f"{prefix}_amount"), currency=r.get(f"{prefix}_currency"),
                   vat_basis=r.get(f"{prefix}_vat") or vat)


def prov(r: dict) -> S.Provenance:
    return S.Provenance(source_id=r.get("source_id"), origin=r.get("origin"), review_status=r.get("review_status"))


def org(r: dict) -> S.OrganizationOut:
    return S.OrganizationOut(**{k: r.get(k) for k in S.OrganizationOut.model_fields if k != "provenance"},
                             provenance=prov(r))


def project(r: dict) -> S.ProjectOut:
    base = {k: r.get(k) for k in S.ProjectOut.model_fields if k not in ("value", "subsidy", "provenance")}
    base["procedures"] = r.get("procedures") or []
    base["open_issues"] = r.get("open_issues") or 0
    base["external_ids"] = r.get("external_ids") or {}
    base["subsectors_extra"] = r.get("subsectors_extra") or []
    return S.ProjectOut(**base, value=money(r, "value"), subsidy=money(r, "subsidy"), provenance=prov(r))


def procedure(r: dict, cls=S.ProcedureOut, **extra) -> Any:
    base = {k: r.get(k) for k in cls.model_fields if k not in ("estimated_value", "provenance") and k not in extra}
    for k in ("cpv_all", "notice_types", "subsectors"):
        base[k] = base.get(k) or []
    return cls(**base, estimated_value=money(r, "estimated_value", "net"), provenance=prov(r), **extra)


def lot(r: dict) -> S.LotOut:
    return S.LotOut(id=r["id"], lot_no=r["lot_no"], description=r.get("description"), cpv_main=r.get("cpv_main"),
                    estimated_value=money(r, "estimated_value", "net"), outcome=r.get("outcome"),
                    cancelled=r.get("cancelled"), cancel_reason=r.get("cancel_reason"), n_offers=r.get("n_offers"),
                    min_offer=S.Money(amount=r.get("min_offer_amount"), currency="PLN" if r.get("min_offer_amount") else None, vat_basis="gross" if r.get("min_offer_amount") else None),
                    max_offer=S.Money(amount=r.get("max_offer_amount"), currency="PLN" if r.get("max_offer_amount") else None, vat_basis="gross" if r.get("max_offer_amount") else None),
                    winning_offer=S.Money(amount=r.get("winning_offer_amount"), currency="PLN" if r.get("winning_offer_amount") else None, vat_basis="gross" if r.get("winning_offer_amount") else None))


def performance(r: dict) -> S.PerformanceOut:
    base = {k: r.get(k) for k in S.PerformanceOut.model_fields if k not in ("total_paid", "provenance")}
    return S.PerformanceOut(**base, total_paid=money(r, "total_paid"), provenance=prov(r))


def change(r: dict) -> S.ChangeOut:
    base = {k: r.get(k) for k in S.ChangeOut.model_fields if k not in ("delta_value", "provenance")}
    for k in ("legal_basis", "change_types", "cause_codes_kw"):
        base[k] = base.get(k) or []
    return S.ChangeOut(**base, delta_value=money(r, "delta_value"), provenance=prov(r))


def contract(r: dict, perf: list | None = None, changes: list | None = None) -> S.ContractOut:
    base = {k: r.get(k) for k in S.ContractOut.model_fields if k not in ("value", "provenance", "performance", "changes")}
    return S.ContractOut(**base, value=money(r, "value"), provenance=prov(r), performance=perf or [], changes=changes or [])


def external(r: dict) -> S.ExternalRecordOut:
    base = {k: r.get(k) for k in S.ExternalRecordOut.model_fields if k not in ("value", "provenance")}
    base["data"] = r.get("data") or {}
    return S.ExternalRecordOut(**base, value=money(r, "value"), provenance=prov(r))


def document(r: dict) -> S.DocumentOut:
    base = {k: r.get(k) for k in S.DocumentOut.model_fields if k != "provenance"}
    return S.DocumentOut(**base, provenance=prov(r))


def risk_event(r: dict) -> S.RiskEventOut:
    base = {k: r.get(k) for k in S.RiskEventOut.model_fields if k not in ("impact_value", "provenance")}
    return S.RiskEventOut(**base, impact_value=money(r, "impact_value"), provenance=prov(r))
