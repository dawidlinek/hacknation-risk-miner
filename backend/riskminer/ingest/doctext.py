"""Document text -> `document_page` + `chunk` (full-text search), idempotently.

Text source per document (repo-relative paths): `data.ocr_text_path` (OCR output, preferred) else `text_path`
(pdftotext / docx / odt / soffice ...). Pages are split on form feed: pdftotext ends every page with `\\f` and the
OCR batch (scripts/wcss/ocr_batch.py) joins pages with `\\f`; text without `\\f` is stored as page 1. Scanned PDFs
flagged `data.needs_ocr` that have no OCR text yet are skipped and counted, so the stage is simply re-run after
`riskminer import-ocr`.

Chunks: about CHUNK_SIZE chars with about CHUNK_OVERLAP chars of overlap, never crossing a page, cut at paragraph /
line / sentence / word boundaries. Offsets are relative to the stored page text, i.e.
`chunk.text == document_page.text[char_start:char_end]`. `tsv = to_tsvector('simple', unaccent(text))` is computed
in SQL (Postgres ships no Polish config); `embedding` stays NULL (computed elsewhere).

Idempotent: a document is rebuilt (one transaction per batch) only when its page text, OCR flag or chunk count
changed, so re-runs are cheap. On a rebuild the pages are replaced and the document's existing chunk rows are reused
in place (ids kept, embedding kept only where the chunk text is identical); only surplus chunks are deleted, because
every chunk delete costs a full scan of `evidence` (FK evidence.chunk_id ON DELETE SET NULL has no index yet). If the
text is unchanged (`force=True` or new chunk parameters), evidence rows that pointed at the document's chunks are
re-anchored by (document, page, offset). If the text itself changed (e.g. OCR replaced an empty text layer), such
evidence keeps document/page/offsets/quote and only loses `chunk_id`; this is counted in the stats, never silent.

Not chunked here: KIO rulings and NIK audits in `external_record.text` (`chunk` has no `external_record_id`). NIK audit
PDFs are already `document` rows linked by `document.external_record_id`, so they are covered; KIO rulings would need
the kio connector to emit `document` rows with `text_path` (as nik does), after which this stage picks them up.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from riskminer.config import REPO_ROOT

log = logging.getLogger("riskminer.doctext")

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MIN_CUT = 900                 # a boundary-aware cut is searched in [start + MIN_CUT, start + CHUNK_SIZE]
TAIL_SLACK = CHUNK_SIZE // 5  # a remainder up to CHUNK_SIZE + TAIL_SLACK becomes one last chunk (no tiny tails)
BATCH_DOCS = 200
BATCH_CHARS = 20_000_000      # keeps memory bounded when a batch hits several multi-MB texts

GARBLED = 0.3                 # control-garbage share above which a text is reported as an OCR candidate
_BREAKS = ("\n\n", "\n", ". ", "; ", ", ", " ", "\t")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


# ------------------------------------------------------------------------------------------- pure helpers

def resolve(rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def read_text(path: Path) -> tuple[str, float]:
    """UTF-8 (lossy), BOM dropped, NUL and the other C0 control characters stripped (Postgres text cannot hold NUL;
    the rest is glyph garbage from PDFs with broken font encodings). Tab, newline, CR and the form-feed page
    separator are kept. Returns (text, share of non-whitespace characters that were control garbage)."""
    raw = path.read_bytes().decode("utf-8", errors="replace").removeprefix("﻿")
    n_ctrl = len(_CTRL.findall(raw))
    if not n_ctrl:
        return raw, 0.0
    text = _CTRL.sub("", raw)
    return text, n_ctrl / max(1, n_ctrl + sum(1 for c in text if not c.isspace()))


def split_pages(text: str) -> list[str]:
    """Form-feed pagination; the empty piece after pdftotext's final `\\f` is not a page."""
    parts = text.split("\f")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    return parts


def text_hash(pages: list[str]) -> str:
    """Same value as md5(string_agg(text, E'\\f' ORDER BY page_no)) over the stored pages."""
    return hashlib.md5("\f".join(pages).encode("utf-8")).hexdigest()


def _skip_ws(text: str, i: int, n: int) -> int:
    while i < n and text[i].isspace():
        i += 1
    return i


def _cut(text: str, start: int, limit: int) -> int:
    """Best end position in [start + MIN_CUT, limit]: after a paragraph, line, sentence, clause or word break."""
    lo = start + MIN_CUT
    for sep in _BREAKS:
        j = text.rfind(sep, lo, limit)
        if j >= 0:
            return j + len(sep)
    return limit


def chunk_spans(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[tuple[int, int]]:
    """Page-local (char_start, char_end) spans; stretches without a letter or digit produce no chunk."""
    n = len(text)
    spans: list[tuple[int, int]] = []
    start = _skip_ws(text, 0, n)
    while start < n:
        end = n if n - start <= size + TAIL_SLACK else _cut(text, start, start + size)
        e = end
        while e > start and text[e - 1].isspace():
            e -= 1
        if e > start and any(ch.isalnum() for ch in text[start:e]):   # punctuation-only stretches are no chunk
            spans.append((start, e))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        if nxt > 0 and not text[nxt - 1].isspace():      # do not start mid-word: jump to the next word
            k = nxt
            while k < end and not text[k].isspace():
                k += 1
            if k < end:
                nxt = k
        start = _skip_ws(text, nxt, n)
    return spans


def _confidences(raw: Any, n_pages: int) -> list[float | None]:
    """data.ocr_confidence: one mean value for the document (ocr_load) or a per-page list."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return [float(raw)] * n_pages
    if isinstance(raw, list):
        out = [float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None for x in raw[:n_pages]]
        return out + [None] * (n_pages - len(out))
    return [None] * n_pages


# ------------------------------------------------------------------------------------------- stage

@dataclass
class _Doc:
    id: int
    pages: list[str]
    ocr: bool
    conf: list[float | None]
    paginated: bool
    db_pages: int | None
    spans: list[list[tuple[int, int]]] = field(default_factory=list)
    hash: str = ""

    @property
    def n_chunks(self) -> int:
        return sum(len(s) for s in self.spans)


_DOCS_SQL = """
SELECT id, text_path, data->>'ocr_text_path' AS ocr_text_path, data->'ocr_confidence' AS ocr_confidence,
       coalesce(data->>'needs_ocr', '') = 'true' AS needs_ocr, pages
FROM document
WHERE (text_path IS NOT NULL OR data ? 'ocr_text_path') {extra}
ORDER BY id
"""


def _load(row) -> tuple[str, _Doc | None, str | None, float]:
    """-> (outcome, doc, missing_path, garbled share). outcome: ok | missing | needs_ocr | empty."""
    if row["ocr_text_path"]:
        rel, ocr = row["ocr_text_path"], True
    elif row["needs_ocr"]:
        return "needs_ocr", None, None, 0.0
    else:
        rel, ocr = row["text_path"], False
    p = resolve(rel)
    if p is None or not p.is_file():
        return "missing", None, rel, 0.0
    text, garbled = read_text(p)
    if not text.strip():
        return "empty", None, None, garbled
    pages = split_pages(text)
    d = _Doc(id=row["id"], pages=pages, ocr=ocr, conf=_confidences(row["ocr_confidence"], len(pages)) if ocr
             else [None] * len(pages), paginated=ocr or "\f" in text, db_pages=row["pages"])
    d.spans = [chunk_spans(t) for t in pages]
    d.hash = text_hash(pages)
    return "ok", d, None, garbled


async def run(conn, rid, *, force: bool = False, limit: int | None = None,
              document_ids: list[int] | None = None) -> dict:
    t0 = time.time()
    st: dict[str, Any] = {k: 0 for k in (
        "documents_with_text_source", "documents_processed", "documents_unchanged", "pages", "chunks",
        "ocr_documents", "missing_files", "no_text_needs_ocr", "empty_text", "pages_set", "page_count_mismatch",
        "evidence_relinked", "evidence_unlinked", "garbled_text", "chunks_deleted")}
    st["missing_examples"], st["ocr_candidates"] = [], []
    extra, args = "", []
    if document_ids:
        extra, args = "AND id = ANY($1::bigint[])", [list(document_ids)]
    sql = _DOCS_SQL.format(extra=extra) + (f" LIMIT {int(limit)}" if limit else "")
    rows = await conn.fetch(sql, *args)
    st["documents_with_text_source"] = len(rows)
    # Re-anchoring is only needed once evidence points at chunks; skip the (unindexed) lookups otherwise.
    relink = bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM evidence WHERE chunk_id IS NOT NULL)"))

    batch: list[_Doc] = []
    no_text: list[int] = []       # no usable text now (empty / waiting for OCR): earlier pages+chunks are cleared
    chars = 0
    for i, row in enumerate(rows, 1):
        outcome, doc, missing, garbled = _load(row)
        if garbled > GARBLED:          # text layer is mostly glyph garbage: OCR candidate (reported, not changed)
            st["garbled_text"] += 1
            if len(st["ocr_candidates"]) < 20:
                st["ocr_candidates"].append(row["id"])
        if outcome == "missing":
            st["missing_files"] += 1
            if len(st["missing_examples"]) < 5:
                st["missing_examples"].append({"document_id": row["id"], "path": missing})
        elif outcome == "needs_ocr":
            st["no_text_needs_ocr"] += 1
            no_text.append(row["id"])
        elif outcome == "empty":
            st["empty_text"] += 1
            no_text.append(row["id"])
        else:
            batch.append(doc)
            chars += sum(len(t) for t in doc.pages)
        if len(batch) >= BATCH_DOCS or chars >= BATCH_CHARS:
            await _flush(conn, batch, st, force, relink)
            batch, chars = [], 0
            log.info("doctext %d/%d documents, %d rebuilt, %d chunks", i, len(rows), st["documents_processed"],
                     st["chunks"])
    if batch:
        await _flush(conn, batch, st, force, relink)
    st["documents_cleared"] = await _clear(conn, no_text, st, relink) if no_text else 0

    if st["documents_processed"] or st["documents_cleared"]:
        await conn.execute("ANALYZE document_page")
        await conn.execute("ANALYZE chunk")
    tot = await conn.fetchrow("""
        SELECT (SELECT count(DISTINCT document_id) FROM document_page) AS documents_with_pages,
               (SELECT count(*) FROM document_page) AS pages, (SELECT count(*) FROM chunk WHERE document_id IS NOT NULL) AS chunks,
               (SELECT count(*) FROM document WHERE coalesce(data->>'needs_ocr', '') = 'true'
                                                AND NOT data ? 'ocr_text_path') AS needs_ocr_without_text""")
    st["totals"] = dict(tot)
    st["chunk_params"] = {"size": CHUNK_SIZE, "overlap": CHUNK_OVERLAP, "tsv": "to_tsvector('simple', unaccent(text))"}
    st["seconds"] = round(time.time() - t0, 1)
    return st


async def _clear(conn, doc_ids: list[int], st: dict, relink: bool) -> int:
    """Drop pages/chunks of documents that no longer have usable text (so search never serves stale text)."""
    stale = [r["document_id"] for r in await conn.fetch("""
        SELECT document_id FROM document_page WHERE document_id = ANY($1::bigint[])
        UNION SELECT document_id FROM chunk WHERE document_id = ANY($1::bigint[])""", doc_ids)]
    if not stale:
        return 0
    async with conn.transaction():
        if relink:
            st["evidence_unlinked"] += await conn.fetchval(
                "SELECT count(*) FROM evidence e JOIN chunk c ON c.id = e.chunk_id WHERE c.document_id = ANY($1::bigint[])",
                stale)
        r = await conn.execute("DELETE FROM chunk WHERE document_id = ANY($1::bigint[])", stale)
        st["chunks_deleted"] += int(r.split()[-1])
        await conn.execute("DELETE FROM document_page WHERE document_id = ANY($1::bigint[])", stale)
    return len(stale)


async def _flush(conn, batch: list[_Doc], st: dict, force: bool, relink: bool) -> None:
    ids = [d.id for d in batch]
    old = {r["document_id"]: r for r in await conn.fetch(r"""
        SELECT p.document_id, md5(string_agg(coalesce(p.text, ''), E'\f' ORDER BY p.page_no)) AS h, bool_or(p.ocr) AS ocr,
               (SELECT count(*) FROM chunk c WHERE c.document_id = p.document_id) AS n_chunks
        FROM document_page p WHERE p.document_id = ANY($1::bigint[]) GROUP BY p.document_id""", ids)}
    todo: list[_Doc] = []
    same_text: list[int] = []
    new_text: list[int] = []
    for d in batch:
        o = old.get(d.id)
        if o is not None and o["h"] == d.hash:
            if not force and o["ocr"] == d.ocr and o["n_chunks"] == d.n_chunks:
                st["documents_unchanged"] += 1
                continue
            same_text.append(d.id)
        elif o is not None:
            new_text.append(d.id)
        todo.append(d)
    if not todo:
        return

    page_recs, set_pages = [], []
    for d in todo:
        page_recs.extend((d.id, no, t, d.ocr, d.conf[no - 1]) for no, t in enumerate(d.pages, 1))
        if d.db_pages is None and d.paginated:
            set_pages.append((d.id, len(d.pages)))
        elif d.db_pages is not None and d.paginated and d.db_pages != len(d.pages):
            st["page_count_mismatch"] += 1
        st["ocr_documents"] += d.ocr

    rebuild = [d.id for d in todo]
    async with conn.transaction():
        # Existing chunk rows are reused in place (UPDATE keeps their ids) and only the surplus is deleted: each
        # deleted chunk costs a sequential scan of `evidence` (FK evidence.chunk_id ON DELETE SET NULL, no index).
        old_ids: dict[int, list[int]] = {r["document_id"]: r["ids"] for r in await conn.fetch(
            "SELECT document_id, array_agg(id ORDER BY page_no, char_start, id) AS ids FROM chunk "
            "WHERE document_id = ANY($1::bigint[]) GROUP BY document_id", rebuild)}
        chunk_recs, surplus = [], []
        for d in todo:
            reuse = old_ids.get(d.id, [])
            k = 0
            for no, (t, spans) in enumerate(zip(d.pages, d.spans), 1):
                for a, b in spans:
                    chunk_recs.append((reuse[k] if k < len(reuse) else None, d.id, no, a, b, t[a:b]))
                    k += 1
            surplus += reuse[k:]
        anchors = []
        if relink and same_text:
            anchors = await conn.fetch("""
                SELECT e.id, c.document_id, c.page_no, coalesce(e.char_start, c.char_start) AS off
                FROM evidence e JOIN chunk c ON c.id = e.chunk_id WHERE c.document_id = ANY($1::bigint[])""", same_text)
        if relink and new_text:    # text changed: old chunk ids no longer point at the quoted text
            r = await conn.execute("UPDATE evidence SET chunk_id = NULL WHERE chunk_id = ANY($1::bigint[])",
                                   [i for d in new_text for i in old_ids.get(d, [])])
            st["evidence_unlinked"] += int(r.split()[-1])
        if surplus:
            await conn.execute("DELETE FROM chunk WHERE id = ANY($1::bigint[])", surplus)
        await conn.execute("DELETE FROM document_page WHERE document_id = ANY($1::bigint[])", rebuild)
        await conn.copy_records_to_table("document_page", records=page_recs,
                                         columns=["document_id", "page_no", "text", "ocr", "ocr_confidence"])
        await conn.execute("CREATE TEMP TABLE tmp_doctext_chunk (id bigint, document_id bigint, page_no int, "
                           "char_start int, char_end int, text text) ON COMMIT DROP")
        await conn.copy_records_to_table("tmp_doctext_chunk", records=chunk_recs)
        await conn.execute("""
            UPDATE chunk c SET page_no = t.page_no, char_start = t.char_start, char_end = t.char_end,
                   embedding = CASE WHEN c.text = t.text THEN c.embedding END,
                   embed_model = CASE WHEN c.text = t.text THEN c.embed_model END,
                   text = t.text, tsv = to_tsvector('simple', unaccent(t.text))
            FROM tmp_doctext_chunk t WHERE c.id = t.id AND t.id IS NOT NULL""")
        await conn.execute("""
            INSERT INTO chunk (document_id, page_no, char_start, char_end, text, tsv)
            SELECT document_id, page_no, char_start, char_end, text, to_tsvector('simple', unaccent(text))
            FROM tmp_doctext_chunk WHERE id IS NULL ORDER BY document_id, page_no, char_start""")
        if set_pages:
            r = await conn.execute("""
                UPDATE document d SET pages = v.n FROM unnest($1::bigint[], $2::int[]) AS v(id, n)
                WHERE d.id = v.id AND d.pages IS NULL""", [x[0] for x in set_pages], [x[1] for x in set_pages])
            st["pages_set"] += int(r.split()[-1])
        if anchors:
            r = await conn.execute("""
                UPDATE evidence e SET chunk_id = (
                    SELECT c.id FROM chunk c WHERE c.document_id = a.document_id AND c.page_no = a.page_no
                      AND c.char_start <= a.off AND a.off < c.char_end ORDER BY c.char_start DESC LIMIT 1)
                FROM unnest($1::bigint[], $2::bigint[], $3::int[], $4::int[]) AS a(id, document_id, page_no, off)
                WHERE e.id = a.id""", [a["id"] for a in anchors], [a["document_id"] for a in anchors],
                [a["page_no"] for a in anchors], [a["off"] for a in anchors])
            st["evidence_relinked"] += int(r.split()[-1])
        st["chunks_deleted"] += len(surplus)
    st["documents_processed"] += len(todo)
    st["pages"] += len(page_recs)
    st["chunks"] += len(chunk_recs)
