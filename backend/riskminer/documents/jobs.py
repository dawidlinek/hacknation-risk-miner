"""Job kinds of the documents package (owner S0). Registered by riskminer.jobs.worker (JOB_PACKAGES)."""
from __future__ import annotations

from riskminer.jobs.worker import register


@register("document_process")
async def document_process(payload: dict, job_id: int) -> dict:
    """Run the new-document pipeline (OCR, facts, linking, re-analysis) in one transaction and commit."""
    from riskminer.db.session import sessionmaker
    from riskminer.documents.pipeline import process_document

    async with sessionmaker()() as db:
        out = await process_document(db, int(payload["document_id"]), actor=payload.get("actor") or "system:pipeline",
                                     request_id=payload.get("request_id"))
        await db.commit()
    return out
