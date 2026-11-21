"""`llm_call` rows (one per backend attempt) in their own short transaction, cost computation and the daily budget.

Sink: RISKMINER_LLM_LOG = db (default) | memory (default in fake mode, keeps tests off the main DB) | off."""
from __future__ import annotations

import os
import time
from typing import Any

from riskminer.llm.config import LLMConfig, fake_mode
from riskminer.llm.sanitize import redact_secrets

MEMORY: list[dict[str, Any]] = []
_spent_cache: dict[str, tuple[float, float]] = {}
MAX_PAYLOAD_CHARS = 60_000


def sink() -> str:
    s = os.environ.get("RISKMINER_LLM_LOG")
    if s:
        return s
    return "memory" if fake_mode() else "db"


def cost_usd(cfg: LLMConfig, model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0,
             tokens_thought: int = 0, batch: bool = False) -> float:
    pr = cfg.price(model)
    pin = (pr.batch_in if batch and pr.batch_in is not None else pr.in_)
    pout = (pr.batch_out if batch and pr.batch_out is not None else pr.out)
    pcached = pr.cached if pr.cached is not None else pin
    fresh = max(tokens_in - tokens_cached, 0)
    # Gemini reports thoughts separately from candidates; both are billed as output
    return round((fresh * pin + tokens_cached * pcached + (tokens_out + tokens_thought) * pout) / 1e6, 6)


def _cap(v: Any) -> Any:
    if isinstance(v, str) and len(v) > MAX_PAYLOAD_CHARS:
        return v[:MAX_PAYLOAD_CHARS] + f"…[+{len(v) - MAX_PAYLOAD_CHARS} znaków]"
    return v


async def log_call(row: dict[str, Any]) -> int | None:
    """Insert one llm_call row; returns its id (None when not logged to the DB)."""
    row = dict(row)
    row["error"] = redact_secrets(row.get("error"))
    for k in ("request", "response"):
        if isinstance(row.get(k), dict):
            row[k] = {kk: _cap(vv) for kk, vv in row[k].items()}
    s = sink()
    if s == "off":
        return None
    if s == "memory":
        row["id"] = None
        row["created_at"] = time.time()
        MEMORY.append(row)
        return None
    from riskminer.db.session import raw_conn

    cols = ["task", "provider", "model", "alias", "data_location", "sensitivity", "request_hash", "tokens_in",
            "tokens_out", "cost_usd", "latency_ms", "status", "error", "request", "response", "prompt_version",
            "tokens_cached", "tokens_thought", "attempt", "fallback_from", "batch_ref", "subject", "price_basis"]
    vals = [row.get(c) for c in cols]
    async with raw_conn() as conn:
        rid = await conn.fetchval(
            f"INSERT INTO llm_call ({', '.join(cols)}) VALUES ({', '.join(f'${i + 1}' for i in range(len(cols)))}) RETURNING id",
            *vals)
    _spent_cache.pop("today", None) if row.get("cost_usd") else None
    return rid


async def spent_today() -> float:
    """Sum of cost_usd today (cached 60 s in process)."""
    hit = _spent_cache.get("today")
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    if sink() != "db":
        day0 = time.time() - (time.time() % 86400)
        v = sum(r.get("cost_usd") or 0 for r in MEMORY if r.get("created_at", 0) >= day0)
    else:
        from riskminer.db.session import raw_conn

        async with raw_conn() as conn:
            v = float(await conn.fetchval(
                "SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE created_at >= date_trunc('day', now())") or 0)
    _spent_cache["today"] = (time.time(), v)
    return v


def add_spent(v: float) -> None:
    hit = _spent_cache.get("today")
    if hit:
        _spent_cache["today"] = (hit[0], hit[1] + v)


async def spent_run(subject_prefix: str) -> float:
    if sink() != "db":
        return sum(r.get("cost_usd") or 0 for r in MEMORY if (r.get("subject") or "").startswith(subject_prefix))
    from riskminer.db.session import raw_conn

    async with raw_conn() as conn:
        return float(await conn.fetchval("SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE subject LIKE $1",
                                         subject_prefix + "%") or 0)
