"""Job kinds of the imports package (registry: riskminer/jobs/worker.py)."""
from __future__ import annotations

from sqlalchemy import text

from riskminer.db.session import sessionmaker
from riskminer.imports import service
from riskminer.jobs.worker import register


@register("import_mapped")
async def import_mapped(payload: dict, job_id: int | None = None) -> dict:
    code = payload["import_code"]
    async with sessionmaker()() as db:
        try:
            res = await service.full_run(db, code, payload.get("run_id"))
            await db.commit()
            return res
        except Exception:
            await db.rollback()
            await db.execute(text("UPDATE import_session SET status = 'failed', updated_at = now() WHERE code = :c"), {"c": code})
            await db.commit()
            raise
