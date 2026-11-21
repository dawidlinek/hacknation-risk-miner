"""Job table + worker loop (SELECT ... FOR UPDATE SKIP LOCKED). Every connector/importer run is a job
and writes ingestion_run + source rows. Run: `uv run riskminer worker` (several workers may run)."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import traceback
from typing import Any

from riskminer.db.session import raw_conn

log = logging.getLogger("riskminer.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
KINDS_HELP = "scrape:<source>, load:<source>, import_xlsx, import_bzp_copy, derive_bzp, link_pilot, load_all, report, seed_catalogue"


def known_kind(kind: str) -> bool:
    return kind.split(":", 1)[0] in ("scrape", "load") or kind in (
        "import_xlsx", "import_bzp_copy", "derive_bzp", "derive_events", "doc_text", "link_national", "link_pilot", "load_all", "report", "seed_catalogue", "noop")


async def enqueue(kind: str, payload: dict | None = None, priority: int = 100, created_by: str = "cli") -> dict:
    async with raw_conn() as conn:
        jid = await conn.fetchval("INSERT INTO job (kind, payload, priority, created_by) VALUES ($1,$2,$3,$4) RETURNING id",
                                  kind, payload or {}, priority, created_by)
        await conn.execute("SELECT pg_notify('riskminer_jobs', $1)", str(jid))
    return {"id": jid, "kind": kind}


async def dispatch(kind: str, payload: dict[str, Any], job_id: int) -> dict:
    from riskminer.ingest import pipeline
    if kind.startswith("scrape:"):
        return await pipeline.scrape_and_load(kind.split(":", 1)[1], job_id=job_id, **payload)
    if kind.startswith("load:"):
        return await pipeline.load_source(kind.split(":", 1)[1], job_id=job_id)
    if kind == "import_xlsx":
        return await pipeline.import_xlsx(payload.get("path"), job_id=job_id)
    if kind == "import_bzp_copy":
        return await pipeline.import_bzp_copy(limit=payload.get("limit"), path=payload.get("path"), job_id=job_id)
    if kind == "derive_bzp":
        return await pipeline.derive_bzp(job_id=job_id)
    if kind == "link_pilot":
        return await pipeline.link_pilot(job_id=job_id)
    if kind == "link_national":
        return await pipeline.link_national(job_id=job_id)
    if kind == "doc_text":
        return await pipeline.doc_text(job_id=job_id, force=bool(payload.get("force")))
    if kind == "derive_events":
        return await pipeline.derive_events(job_id=job_id)
    if kind == "seed_catalogue":
        return await pipeline.seed_catalogue(job_id=job_id)
    if kind == "load_all":
        return await pipeline.load_all(limit=payload.get("limit"), skip_bzp=payload.get("skip_bzp", False), job_id=job_id)
    if kind == "report":
        from riskminer.ingest import report
        return await report.generate()
    if kind == "noop":
        return {"ok": True}
    raise ValueError(f"unknown job kind {kind}")


async def claim(conn) -> Any:
    return await conn.fetchrow("""
        UPDATE job SET status='running', locked_by=$1, locked_at=now(), started_at=coalesce(started_at, now()),
               attempts = attempts + 1
        WHERE id = (SELECT id FROM job WHERE status='queued' AND run_after <= now()
                    ORDER BY priority, id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING id, kind, payload, attempts, max_attempts""", WORKER_ID)


async def run_once() -> bool:
    async with raw_conn() as conn:
        job = await claim(conn)
    if not job:
        return False
    log.info("job %s %s (attempt %s)", job["id"], job["kind"], job["attempts"])
    try:
        result = await dispatch(job["kind"], dict(job["payload"] or {}), job["id"])
        async with raw_conn() as conn:
            await conn.execute("UPDATE job SET status='done', finished_at=now(), result=$2, error=NULL WHERE id=$1",
                               job["id"], _jsonable(result))
    except Exception as e:  # noqa: BLE001 - recorded on the job row
        log.exception("job %s failed", job["id"])
        retry = job["attempts"] < job["max_attempts"]
        async with raw_conn() as conn:
            await conn.execute(
                "UPDATE job SET status=$2, finished_at=CASE WHEN $2='failed' THEN now() END, error=$3, "
                "run_after = now() + make_interval(secs => 30 * attempts) WHERE id=$1",
                job["id"], "queued" if retry else "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}")
    return True


async def run_forever(poll_seconds: float = 3.0) -> None:
    log.info("worker %s started", WORKER_ID)
    async with raw_conn() as conn:   # release jobs a dead worker left behind
        await conn.execute("UPDATE job SET status='queued', locked_by=NULL WHERE status='running' "
                           "AND locked_at < now() - interval '6 hours'")
    while True:
        try:
            busy = await run_once()
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
            busy = False
        if not busy:
            await asyncio.sleep(poll_seconds)


def _jsonable(x: Any) -> Any:
    import json
    return json.loads(json.dumps(x, default=str))
