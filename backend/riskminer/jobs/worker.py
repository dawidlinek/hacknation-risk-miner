"""Job table + worker loop (SELECT ... FOR UPDATE SKIP LOCKED). Every connector/importer run is a job
and writes ingestion_run + source rows. Run: `uv run riskminer worker` (several workers may run)."""
from __future__ import annotations

import asyncio
import importlib
import logging
import os
import socket
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from riskminer.db.session import raw_conn

log = logging.getLogger("riskminer.worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
# ---- job registry ------------------------------------------------------------------------------------------------
# Each package registers its own kinds in `<package>/jobs.py` (never edit this file for that):
#
#     from riskminer.jobs.worker import register
#
#     @register("analysis_redpen")                 # exact kind
#     async def analysis_redpen(payload: dict, job_id: int) -> dict: ...
#
#     JOBS = {"review_sync": review_sync}         # or a module-level dict (exact kinds)
#
#     @register("scrape", prefix=True)             # kind "scrape:<arg>": handler gets payload["_arg"] = "<arg>"
#
# Handlers return a JSON-able dict (stored in job.result). Enqueue with `await enqueue(kind, payload, created_by=...)`.
Handler = Callable[[dict[str, Any], int], Awaitable[dict]]
REGISTRY: dict[str, Handler] = {}
PREFIXES: dict[str, Handler] = {}
JOB_PACKAGES = ("riskminer.ingest.jobs", "riskminer.analysis.jobs", "riskminer.llm.jobs", "riskminer.review.jobs",
                "riskminer.monitoring.jobs", "riskminer.imports.jobs", "riskminer.analytics.jobs",
                "riskminer.documents.jobs")
_loaded = False


def register(kind: str, *, prefix: bool = False) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        (PREFIXES if prefix else REGISTRY)[kind] = fn
        return fn
    return deco


_last_rescan = 0.0
RESCAN_EVERY_S = 30.0


def load_registry(*, rescan: bool = False) -> None:
    """Import every package's jobs.py once (a missing module is fine; a broken one is logged, not fatal).
    `rescan=True` re-executes already imported jobs.py modules too, so a kind registered after the worker started is found
    without a restart (only the jobs.py module is reloaded; changed service code still needs a worker restart)."""
    global _loaded
    if _loaded and not rescan:
        return
    _loaded = True
    _register_builtin()
    for mod in JOB_PACKAGES:
        try:
            m = importlib.reload(sys.modules[mod]) if rescan and mod in sys.modules else importlib.import_module(mod)
            for kind, fn in (getattr(m, "JOBS", None) or {}).items():   # alternative to @register: JOBS = {kind: fn}
                REGISTRY.setdefault(kind, fn)
        except ModuleNotFoundError as e:
            if e.name != mod and not mod.startswith(e.name or "\0"):
                log.exception("job module %s failed to import", mod)
        except Exception:
            log.exception("job module %s failed to import", mod)


def _lookup(kind: str) -> tuple[Handler, str | None] | None:
    if kind in REGISTRY:
        return REGISTRY[kind], None
    head, _, arg = kind.partition(":")
    if arg and head in PREFIXES:
        return PREFIXES[head], arg
    return None


def resolve(kind: str) -> tuple[Handler, str | None] | None:
    """Handler for a kind. On a miss the job modules are rescanned (at most every RESCAN_EVERY_S seconds)."""
    global _last_rescan
    load_registry()
    hit = _lookup(kind)
    if hit is None and time.monotonic() - _last_rescan > RESCAN_EVERY_S:
        _last_rescan = time.monotonic()
        load_registry(rescan=True)
        hit = _lookup(kind)
    return hit


def known_kind(kind: str) -> bool:
    return resolve(kind) is not None


def kinds_help() -> str:
    load_registry()
    return ", ".join(sorted([f"{p}:<arg>" for p in PREFIXES] + list(REGISTRY)))


KINDS_HELP = "see GET /api/jobs/kinds or riskminer.jobs.worker.kinds_help()"


def _register_builtin() -> None:
    """Legacy ingest kinds (were an if-chain). The data session may move these into riskminer/ingest/jobs.py."""
    from riskminer.ingest import pipeline

    def put(kind: str, fn: Handler, prefix: bool = False) -> None:
        (PREFIXES if prefix else REGISTRY).setdefault(kind, fn)

    put("scrape", lambda p, j: pipeline.scrape_and_load(p.pop("_arg"), job_id=j, **p), True)
    put("load", lambda p, j: pipeline.load_source(p["_arg"], job_id=j), True)
    put("import_xlsx", lambda p, j: pipeline.import_xlsx(p.get("path"), job_id=j))
    put("import_bzp_copy", lambda p, j: pipeline.import_bzp_copy(limit=p.get("limit"), path=p.get("path"), job_id=j))
    put("derive_bzp", lambda p, j: pipeline.derive_bzp(job_id=j))
    put("link_pilot", lambda p, j: pipeline.link_pilot(job_id=j))
    put("link_national", lambda p, j: pipeline.link_national(job_id=j))
    put("doc_text", lambda p, j: pipeline.doc_text(job_id=j, force=bool(p.get("force"))))
    put("derive_events", lambda p, j: pipeline.derive_events(job_id=j))
    put("seed_catalogue", lambda p, j: pipeline.seed_catalogue(job_id=j))
    put("load_all", lambda p, j: pipeline.load_all(limit=p.get("limit"), skip_bzp=p.get("skip_bzp", False), job_id=j))

    async def _report(p: dict, j: int) -> dict:
        from riskminer.ingest import report
        return await report.generate()

    async def _noop(p: dict, j: int) -> dict:
        return {"ok": True}

    put("report", _report)
    put("noop", _noop)


async def enqueue(kind: str, payload: dict | None = None, priority: int = 100, created_by: str = "cli") -> dict:
    async with raw_conn() as conn:
        jid = await conn.fetchval("INSERT INTO job (kind, payload, priority, created_by) VALUES ($1,$2,$3,$4) RETURNING id",
                                  kind, payload or {}, priority, created_by)
        await conn.execute("SELECT pg_notify('riskminer_jobs', $1)", str(jid))
    return {"id": jid, "kind": kind}


async def dispatch(kind: str, payload: dict[str, Any], job_id: int) -> dict:
    hit = resolve(kind)
    if hit is None:
        raise ValueError(f"unknown job kind {kind}")
    fn, arg = hit
    payload = dict(payload)
    if arg is not None:
        payload["_arg"] = arg
    return await fn(payload, job_id)


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
    except Exception as e:
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
        except Exception:
            log.exception("worker loop error")
            busy = False
        if not busy:
            await asyncio.sleep(poll_seconds)


def _jsonable(x: Any) -> Any:
    import json
    return json.loads(json.dumps(x, default=str))
