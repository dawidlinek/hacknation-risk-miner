"""Job handlers of the review package (registered with the worker registry)."""
from __future__ import annotations

from riskminer.db.session import sessionmaker
from riskminer.jobs.worker import register
from riskminer.review import queue_sync


@register("review_sync")
async def review_sync(payload: dict, job_id: int | None = None) -> dict:
    async with sessionmaker()() as db:
        out = await queue_sync.sync(db)
        await db.commit()
    return out


@register("document_link")
async def document_link(payload: dict, job_id: int | None = None) -> dict:
    """G3: link + validate an extracted document, create proposals and review items (enqueued by the LLM session's document_extract)."""
    from riskminer.review import doclink
    async with sessionmaker()() as db:
        out = await doclink.link_document(db, int(payload["document_id"]))
        await db.commit()
    return {"project": out.get("project"), "contract": out.get("contract"), "review_items": out["review_items"], "created": out["created"],
            "checks_failed": [c for c in out["checks"] if not c["ok"]]}
