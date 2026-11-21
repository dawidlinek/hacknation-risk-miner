"""Document pages for prompts (document_page is the page-tagged text every backend can read, Bielik included)."""
from __future__ import annotations

import re

from riskminer.db.session import raw_conn

RELEVANT = re.compile(r"opis przedmiotu|parametr|długoś|dlugos|przepompown|przyłącz|przylacz|termin|wynagrodz|ryczałt|"
                      r"zaprojektuj|\bkm\b|\bmb\b|\brlm\b|spis treści|zakres|kanalizac|wodociąg|oczyszczal|"
                      r"waloryzac|kar\w* umown|odbior|gwarancj|geotechn|uzgodni|decyzj|harmonogram", re.IGNORECASE)


async def load_documents(doc_ids: list[int]) -> dict[int, dict]:
    """{doc_id: {id, filename, doc_type, sensitivity, pages: {page_no: text}}}"""
    out: dict[int, dict] = {}
    if not doc_ids:
        return out
    async with raw_conn() as conn:
        for r in await conn.fetch("SELECT id, filename, doc_type, sensitivity FROM document WHERE id = ANY($1::bigint[])",
                                  doc_ids):
            out[r["id"]] = {"id": r["id"], "filename": r["filename"], "doc_type": r["doc_type"] or "dokument",
                            "sensitivity": r["sensitivity"] or "confidential", "pages": {}}
        for r in await conn.fetch("SELECT document_id, page_no, text FROM document_page WHERE document_id = ANY($1::bigint[]) "
                                  "ORDER BY document_id, page_no", doc_ids):
            if r["document_id"] in out:
                out[r["document_id"]]["pages"][r["page_no"]] = r["text"] or ""
    return out


def pick_pages(pages: dict[int, str], max_pages: int = 40, always_first: int = 3) -> list[int]:
    """All pages when they fit; otherwise the first pages plus the most chip-relevant ones, in page order."""
    if len(pages) <= max_pages:
        return sorted(pages)
    keep = set(sorted(pages)[:always_first])
    scored = sorted(((len(RELEVANT.findall(t or "")), -p) for p, t in pages.items() if p not in keep), reverse=True)
    for _, negp in scored:
        if len(keep) >= max_pages:
            break
        keep.add(-negp)
    return sorted(keep)
