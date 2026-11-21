"""Shared helpers for the review package: audit rows, expert-write scope, generic snapshot/restore."""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api.auth import ApiError

IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

# Tables whose rows an expert decision may touch (names are interpolated into SQL, so this is a whitelist).
TARGET_TABLES = {
    "risk_event", "link_candidate", "project_procedure", "contract_performance", "contract_change", "contract", "lot",
    "document", "analysis_item", "project", "organization", "procedure", "notice", "external_record",
    "change_cause_ai", "catalogue_risk", "catalogue_clause", "catalogue_entry", "catalogue_subsector", "catalogue_doc_type",
    "catalogue_checklist", "catalogue_cpv_map",
}


def jdump(v: Any) -> str:
    return orjson.dumps(v, default=_default, option=orjson.OPT_NON_STR_KEYS).decode()


def _default(o: Any):
    if isinstance(o, (Decimal,)):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def jclean(v: Any) -> Any:
    """Round-trip through JSON so Decimal/date values become plain JSON (for storing in jsonb and responses)."""
    return orjson.loads(jdump(v)) if v is not None else None


def check_table(table: str) -> str:
    if table not in TARGET_TABLES:
        raise ApiError(422, f"Tabela {table} nie podlega przeglądowi.", "bad_target")
    return table


def check_col(col: str) -> str:
    if not IDENT.match(col):
        raise ApiError(422, "Nieprawidłowa nazwa pola.", "bad_field")
    return col


@asynccontextmanager
async def expert_writes(db: AsyncSession):
    """Scope in which the rm_protect_approved trigger lets an expert change approved/edited rows."""
    await db.execute(text("SELECT set_config('riskminer.expert_write', 'on', true)"))
    try:
        yield
    finally:
        await db.execute(text("SELECT set_config('riskminer.expert_write', 'off', true)"))


@asynccontextmanager
async def operator_cleanup_writes(conn):
    """For riskminer/ingest/demo_cleanup.py only, when the user explicitly asks to remove test artefacts that carry
    approvals (e.g. auto-approved Red Pen notes of a rehearsal analysis): the same scope as expert_writes, on a raw
    asyncpg connection. The caller records every removed approved row in audit_log."""
    await conn.execute("SELECT set_config('riskminer.expert_write', 'on', true)")
    try:
        yield
    finally:
        await conn.execute("SELECT set_config('riskminer.expert_write', 'off', true)")


async def audit(db: AsyncSession, actor: str, action: str, table: str | None, row_id: int | None,
                before: Any = None, after: Any = None, request_id: str | None = None, note: str | None = None) -> int:
    r = await db.execute(text(
        """INSERT INTO audit_log (actor, action, table_name, row_id, before, after, request_id, note)
           VALUES (:actor, :action, :t, :rid, CAST(:b AS jsonb), CAST(:a AS jsonb), :req, :note) RETURNING id"""),
        {"actor": actor[:80], "action": action[:40], "t": table, "rid": row_id,
         "b": jdump(before) if before is not None else None, "a": jdump(after) if after is not None else None,
         "req": request_id, "note": note})
    return r.scalar_one()


async def fetch_row(db: AsyncSession, table: str, row_id: int, cols: list[str] | None = None) -> dict | None:
    check_table(table)
    sel = ", ".join(check_col(c) for c in cols) if cols else "*"
    r = (await db.execute(text(f"SELECT {sel} FROM {table} WHERE id = :id"), {"id": row_id})).mappings().first()
    return dict(r) if r else None


async def update_fields(db: AsyncSession, table: str, row_id: int, fields: dict[str, Any], *, expect: dict[str, Any] | None = None) -> dict:
    """UPDATE ... SET fields WHERE id, inside an expert_writes scope. Raises 409 `protected_row` when the trigger kept OLD
    (checked by re-reading the columns in `expect`, default: every changed field)."""
    check_table(table)
    if not fields:
        return {}
    sets = ", ".join(f"{check_col(c)} = r.{c}" for c in fields)
    # jsonb_populate_record casts every value to the column type (dates, numerics, arrays, jsonb)
    sql = (f"UPDATE {table} t SET {sets} FROM jsonb_populate_record(NULL::{table}, CAST(:j AS jsonb)) r "
           "WHERE t.id = :id")
    res = await db.execute(text(sql), {"j": jdump(fields), "id": row_id})
    if res.rowcount != 1:
        raise ApiError(404, "Nie znaleziono rekordu.", "not_found")
    check = expect if expect is not None else fields
    got = await fetch_row(db, table, row_id, list(check))
    for k, want in check.items():
        if _norm(got.get(k)) != _norm(want):
            raise ApiError(409, "Rekord jest chroniony przed zmianą (zatwierdzony). Zmiana nie została zapisana.", "protected_row")
    return got


def _norm(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()[:19] if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}T", v):
        return v[:19]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return v


async def insert_row(db: AsyncSession, table: str, fields: dict[str, Any]) -> int:
    check_table(table)
    cols = ", ".join(check_col(c) for c in fields)
    sel = ", ".join(f"r.{c}" for c in fields)
    r = await db.execute(text(f"INSERT INTO {table} ({cols}) SELECT {sel} FROM jsonb_populate_record(NULL::{table}, CAST(:j AS jsonb)) r RETURNING id"),
                         {"j": jdump(fields)})
    return r.scalar_one()


def pl_money(amount: Any, cur: str = "zł") -> str:
    try:
        return f"{float(amount):,.2f}".replace(",", " ").replace(".", ",") + f" {cur}"
    except Exception:
        return str(amount)
