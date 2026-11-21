"""Job kinds of the ingest package (registry: riskminer/jobs/worker.py). Legacy kinds stay in the worker's builtins."""
from __future__ import annotations

from riskminer.ingest import pipeline
from riskminer.jobs.worker import register


@register("derive_lengths")
async def derive_lengths(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.derive_lengths(job_id=job_id)


@register("geo_buyers")
async def geo_buyers(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.geo_buyers(job_id=job_id)


@register("quality")
async def quality(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.quality(job_id=job_id)


@register("refresh_rc")
async def refresh_rc(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.refresh_rc(job_id=job_id)


@register("derive_geo")
async def derive_geo(payload: dict, job_id: int | None = None) -> dict:
    """lengths -> buyer TERYT -> quality -> refresh rc_contract (api_contract §6 order)."""
    return await pipeline.derive_geo(job_id=job_id)


@register("derive_events")
async def derive_events(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.derive_events(job_id=job_id)


@register("document_ocr")
async def document_ocr(payload: dict, job_id: int | None = None) -> dict:
    """OCR one scanned document (Tesseract pol), re-chunk it, then queue L's document_extract (new_documents.md G1)."""
    from riskminer.ingest import ocr_doc
    return await ocr_doc.ocr_document(int(payload["document_id"]), job_id=job_id,
                                      actor=payload.get("actor") or "system:ocr", extract=payload.get("extract", True))


@register("anchor_evidence")
async def anchor_evidence(payload: dict, job_id: int | None = None) -> dict:
    return await pipeline.anchor_evidence(job_id=job_id)
