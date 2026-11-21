"""Run a connector without the DB (used by the CLI and the job worker)."""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from riskminer import connectors
from riskminer.config import settings
from riskminer.connectors.base import RawStore, ScrapeContext

log = logging.getLogger("riskminer.runner")


def make_context(source: str, run_id: str | None = None) -> ScrapeContext:
    mod = connectors.get(source)
    d = dict(getattr(mod, "DEFAULTS", {}) or {})
    ttl_h = d.pop("ttl_hours", None)
    return ScrapeContext.create(source, run_id, ttl=timedelta(hours=ttl_h) if ttl_h else None, **d)


def scrape(source: str, run_id: str | None = None, **opts: Any) -> dict[str, Any]:
    mod = connectors.get(source)
    ctx = make_context(source, run_id)
    ov = opts.pop("robots_override", None)
    if ov:
        ctx.set_robots_override(ov, opts.pop("robots_override_note", None) or "approved by the site operator",
                                float(opts.pop("override_min_interval", 5.0)))
    t0 = time.time()
    try:
        result = mod.run(ctx, **{k: v for k, v in opts.items() if v is not None}) or {}
    finally:
        ctx.close()
    stats = {**ctx.stats, **(result if isinstance(result, dict) else {})}
    stats["seconds"] = round(time.time() - t0, 1)
    stats["run_id"] = ctx.run_id
    return stats


def derived_path(source: str) -> Path:
    return Path(settings().data_dir) / "derived" / source / "records.jsonl"


def parse(source: str) -> dict[str, Any]:
    """Re-derive records from raw files and write data/derived/<source>/records.jsonl."""
    mod = connectors.get(source)
    if not hasattr(mod, "parse"):
        return {"records": 0, "note": "connector has no parse()"}
    store = RawStore(source)
    out = derived_path(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    with out.open("w", encoding="utf-8") as fh:
        for rec in mod.parse(store):
            d = rec.model_dump(mode="json") if hasattr(rec, "model_dump") else rec
            counts[f"{d.get('record_type')}:{d.get('kind') or d.get('result') or d.get('fetch_state') or ''}"] += 1
            fh.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
    return {"path": str(out), "counts": dict(counts), "records": sum(counts.values())}
