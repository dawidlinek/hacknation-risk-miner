"""Bulk helpers on raw asyncpg: COPY into a temp table, then INSERT ... ON CONFLICT upsert."""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import asyncpg


async def upsert_copy(conn: asyncpg.Connection, table: str, columns: Sequence[str], records: Iterable[Sequence[Any]],
                      conflict: Sequence[str], update: Sequence[str] | None = None,
                      returning: Sequence[str] | None = None) -> list[asyncpg.Record]:
    """COPY records into a temp clone of `table`, then upsert. `update=None` updates every non-conflict
    column; `update=[]` means DO NOTHING. Approved/edited rows are protected by the DB trigger."""
    async with conn.transaction():   # temp table lives until commit (savepoint if already in a transaction)
        return await _upsert_copy(conn, table, columns, records, conflict, update, returning)


async def _upsert_copy(conn, table, columns, records, conflict, update, returning) -> list[asyncpg.Record]:
    tmp = f"tmp_{table}_{uuid.uuid4().hex[:8]}"
    await conn.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    recs = list(records)
    if not recs:
        return []
    await conn.copy_records_to_table(tmp, records=recs, columns=list(columns))
    cols = ", ".join(columns)
    if update is None:
        update = [c for c in columns if c not in conflict]
    if update:
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in update)
        if "updated_at" not in update and await _has_col(conn, table, "updated_at"):
            sets += ", updated_at = now()"
        action = f"DO UPDATE SET {sets}"
    else:
        action = "DO NOTHING"
    ret = f" RETURNING {', '.join(returning)}" if returning else ""
    sql = (f"INSERT INTO {table} ({cols}) SELECT DISTINCT ON ({', '.join(conflict)}) {cols} FROM {tmp} "
           f"ORDER BY {', '.join(conflict)} ON CONFLICT ({', '.join(conflict)}) {action}{ret}")
    return await conn.fetch(sql)


_COLS: dict[tuple[str, str], bool] = {}


async def _has_col(conn: asyncpg.Connection, table: str, col: str) -> bool:
    k = (table, col)
    if k not in _COLS:
        _COLS[k] = bool(await conn.fetchval(
            "SELECT 1 FROM information_schema.columns WHERE table_name=$1 AND column_name=$2", table, col))
    return _COLS[k]


async def start_run(conn: asyncpg.Connection, connector: str, stage: str, params: dict | None = None,
                    run_id: str | None = None, job_id: int | None = None) -> uuid.UUID:
    rid = uuid.UUID(run_id) if run_id else uuid.uuid4()
    await conn.execute(
        "INSERT INTO ingestion_run (id, connector, stage, params, status, job_id) VALUES ($1,$2,$3,$4,'running',$5) "
        "ON CONFLICT (id) DO UPDATE SET status='running', stage=EXCLUDED.stage",
        rid, connector, stage, params or {}, job_id)
    return rid


async def finish_run(conn: asyncpg.Connection, rid: uuid.UUID, status: str, stats: dict, error: str | None = None) -> None:
    await conn.execute("UPDATE ingestion_run SET finished_at=now(), status=$2, stats=$3, error=$4 WHERE id=$1",
                       rid, status, stats, error)


async def audit(conn: asyncpg.Connection, actor: str, action: str, table: str | None = None, row_id: int | None = None,
                before: dict | None = None, after: dict | None = None, note: str | None = None) -> None:
    await conn.execute(
        "INSERT INTO audit_log (actor, action, table_name, row_id, before, after, note) VALUES ($1,$2,$3,$4,$5,$6,$7)",
        actor, action, table, row_id, before, after, note)


def now() -> datetime:
    return datetime.now(UTC)
