"""Full-text search over document chunks + page text of a document.

Index: chunk.tsv = to_tsvector('simple', unaccent(text)) (built by ingest/doctext.py); queries use
websearch_to_tsquery('simple', unaccent(q)), so "oczyszczalnia sciekow", "oczyszczalnia ścieków", quoted phrases,
`or` and `-wykluczenie` all work; `prefix=true` also matches inflected forms (crude stem + prefix, since the
'simple' config does not stem Polish). Snippets are cut from the original chunk text (Polish diacritics kept) with
the matched words wrapped in <mark>; the rest of the snippet is HTML-escaped.
"""
from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.api import deps as D
from riskminer.api import schemas as S
from riskminer.db.session import get_session

router = APIRouter(prefix="/api", tags=["search"])
DB = Depends(get_session)

_TSQ = "websearch_to_tsquery('simple', unaccent(CAST(:q AS text)))"
_TSQ_PREFIX = "to_tsquery('simple', unaccent(CAST(:q AS text)))"


# ------------------------------------------------------------------------------------------- models

class SearchHitOut(BaseModel):
    chunk_id: int
    document_id: int
    doc_type: str | None = None
    title: str | None = None
    filename: str | None = None
    source: str | None = Field(None, description="document source (docs_22, docs_sample, bip_22, nik, ...)")
    rm_id: str | None = Field(None, description="pilot project id via document.project_id")
    ocid: str | None = Field(None, description="procedure OCID via document.procedure_id (or the document's own OCID)")
    page_no: int | None = None
    char_start: int | None = Field(None, description="chunk start offset within the page text")
    char_end: int | None = Field(None, description="chunk end offset within the page text (exclusive)")
    ocr: bool = Field(False, description="page text comes from OCR")
    rank: float
    snippet: str = Field(description="HTML-escaped excerpt; matched words wrapped in <mark>")
    url: str | None = None
    path: str | None = None


class DocumentPageOut(BaseModel):
    document_id: int
    page_no: int
    chars: int
    text: str | None = None
    ocr: bool
    ocr_confidence: float | None = None


class DocumentPagesOut(BaseModel):
    document_id: int
    title: str | None = None
    filename: str | None = None
    url: str | None = None
    path: str | None = None
    pages: int | None = Field(None, description="page count of the original file (NULL when unknown, e.g. DOCX)")
    paginated: bool = Field(description="text is split into real pages; otherwise the whole text is page 1")
    needs_ocr: bool = Field(description="scanned document still waiting for OCR (no usable text yet)")
    ocr: bool
    items: list[DocumentPageOut]


# ------------------------------------------------------------------------------------------- snippet

_FOLD = {"ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ø": "o", "Ø": "o", "ß": "s", "æ": "a", "Æ": "a", "œ": "o",
         "Œ": "o", "ı": "i"}


@lru_cache(maxsize=8192)
def _fold_char(c: str) -> str:
    if c.isascii():
        return c.lower()
    if c in _FOLD:
        return _FOLD[c]
    base = "".join(ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch))
    return (base[:1] or c).lower()[:1] or c


def fold(s: str) -> str:
    """Lower-case, accent-free copy with the SAME length (positions map 1:1 back to the original)."""
    return "".join(_fold_char(c) for c in s)


def query_terms(q: str, negated: bool = False) -> list[str]:
    """Folded words of a websearch query: the positive ones (default; `or` skipped) or the `-negated` ones."""
    out = []
    for m in re.finditer(r'(^|[\s"(])(-?)([^\s"()]+)', q):
        if bool(m.group(2)) != negated:
            continue
        for w in re.findall(r"\w+", fold(m.group(3))):
            if w != "or" and w not in out:
                out.append(w)
    return out


def stem(w: str) -> str:
    """Crude Polish stem for prefix search: drop the inflectional ending (umowna -> umow, kara -> kar)."""
    if w.isdigit() or len(w) <= 3:
        return w
    return w[:-1] if len(w) <= 5 else w[:-2]


def prefix_tsquery(q: str) -> str:
    """'kara umowna -aneks' -> 'kar:* & umow:* & !aneks' (words are \\w+ only, so no tsquery syntax injection)."""
    pos = [f"{stem(w)}:*" for w in query_terms(q)]
    return " & ".join(pos + [f"!{w}" for w in query_terms(q, negated=True)]) if pos else ""


def snippet(text: str, terms: list[str], width: int = 300, prefix: bool = False) -> str:
    folded = fold(text)
    hits: list[tuple[int, int, int]] = []           # (start, end, term index)
    tail = r"\w*" if prefix else r"(?!\w)"
    for k, t in enumerate(terms):
        hits += [(m.start(), m.end(), k) for m in re.finditer(rf"(?<!\w){re.escape(t)}{tail}", folded)]
    hits.sort()
    spans = [(s, e) for s, e, _ in hits]
    a = 0
    if hits:
        # anchor on the match whose following 2/3 window covers the most distinct query terms
        best = max(range(len(hits)), key=lambda i: (
            len({k for s, _, k in hits[i:] if s < hits[i][0] + 2 * width // 3}), -i))
        a = max(0, hits[best][0] - width // 3)
        if a > 0:
            sp = text.find(" ", a, hits[best][0])
            a = sp + 1 if sp >= 0 else a
    b = min(len(text), a + width)
    if b < len(text):
        sp = text.rfind(" ", a + width // 2, b)
        b = sp if sp > 0 else b
    parts, pos = [], a
    for s, e in spans:
        if s < pos or e > b:
            continue
        parts.append(html.escape(text[pos:s]))
        parts.append(f"<mark>{html.escape(text[s:e])}</mark>")
        pos = e
    parts.append(html.escape(text[pos:b]))
    out = re.sub(r"\s+", " ", "".join(parts)).strip()
    return ("… " if a > 0 else "") + out + (" …" if b < len(text) else "")


# ------------------------------------------------------------------------------------------- search

@router.get("/search", response_model=S.Page[SearchHitOut],
            summary="Wyszukiwanie pełnotekstowe w dokumentach (fragmenty stron, ranking ts_rank)")
async def search(q: str = Query(..., min_length=1, max_length=500, description="websearch syntax: words, \"phrase\", or, -word"),
                 source: str | None = Query(None, description="document source: docs_22 | docs_sample | bip_22 | nik"),
                 doc_type: str | None = None, rm_id: str | None = None, document_id: int | None = None,
                 prefix: bool = Query(False, description="match inflected forms: every word is cut to a crude stem and "
                                                         "prefix-matched (kara umowna -> kar:* & umow:*); "
                                                         "phrases and `or` are ignored"),
                 limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0), db: AsyncSession = DB,
                 user: A.User | None = Depends(A.current_user)):
    tsq = prefix_tsquery(q) if prefix else q
    if not tsq:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    # confidential uploads are never searchable for anonymous callers (api_contract §1.6 trap 2, §3.3)
    where, params = ["c.tsv @@ x.tsq", A.public_doc_filter(user, "d")], {"q": tsq, "limit": limit, "offset": offset}
    if source:
        where.append("split_part(d.data->>'source', '|', 1) = :source")
        params["source"] = source
    if doc_type:
        where.append("d.doc_type = :doc_type")
        params["doc_type"] = doc_type
    if rm_id:
        where.append("d.project_id = (SELECT id FROM project WHERE rm_id = :rm_id)")
        params["rm_id"] = rm_id
    if document_id is not None:
        where.append("c.document_id = :document_id")
        params["document_id"] = document_id
    w = " AND ".join(where)
    base = (f"FROM chunk c JOIN document d ON d.id = c.document_id "
            f"CROSS JOIN (SELECT {_TSQ_PREFIX if prefix else _TSQ} AS tsq) x WHERE {w}")
    total = await D.scalar(db, f"SELECT count(*) {base}", **params)
    rs = await D.rows(db, f"""
        WITH hits AS (SELECT c.id, ts_rank(c.tsv, x.tsq) AS rank {base} ORDER BY rank DESC, c.id LIMIT :limit OFFSET :offset)
        SELECT c.id AS chunk_id, c.document_id, c.page_no, c.char_start, c.char_end, c.text, h.rank,
               coalesce(pg.ocr, false) AS ocr, d.doc_type, d.title, d.filename, d.url, d.path,
               split_part(d.data->>'source', '|', 1) AS source, p.rm_id, coalesce(pr.ocid, d.data->>'ocid') AS ocid
        FROM hits h JOIN chunk c ON c.id = h.id JOIN document d ON d.id = c.document_id
        LEFT JOIN document_page pg ON pg.document_id = c.document_id AND pg.page_no = c.page_no
        LEFT JOIN project p ON p.id = d.project_id LEFT JOIN procedure pr ON pr.id = d.procedure_id
        ORDER BY h.rank DESC, c.id""", **params)
    terms = [stem(t) for t in query_terms(q)] if prefix else query_terms(q)
    items = [SearchHitOut(**{k: v for k, v in r.items() if k != "text"}, snippet=snippet(r["text"], terms, prefix=prefix))
             for r in rs]
    return {"total": total or 0, "limit": limit, "offset": offset, "items": items}


# ------------------------------------------------------------------------------------------- pages

_DOC_SQL = """SELECT id, title, filename, url, path, pages, ocr, coalesce(data->>'needs_ocr', '') = 'true' AND NOT data ? 'ocr_text_path' AS needs_ocr
FROM document d WHERE id = :id AND {visible}"""


@router.get("/documents/{document_id}/pages", response_model=DocumentPagesOut, summary="Strony dokumentu (tekst)")
async def document_pages(document_id: int, include_text: bool = Query(True, description="false: only page numbers and sizes"),
                         db: AsyncSession = DB, user: A.User | None = Depends(A.current_user)):
    doc = await D.one(db, _DOC_SQL.format(visible=A.public_doc_filter(user, "d")), id=document_id)
    if not doc:
        raise HTTPException(404, "document not found")
    txt = "text" if include_text else "NULL::text AS text"
    rs = await D.rows(db, f"""SELECT document_id, page_no, coalesce(length(text), 0) AS chars, {txt}, ocr, ocr_confidence
                              FROM document_page WHERE document_id = :id ORDER BY page_no""", id=document_id)
    paginated = len(rs) > 1 or doc["pages"] is not None or any(r["ocr"] for r in rs)
    return DocumentPagesOut(document_id=doc["id"], title=doc["title"], filename=doc["filename"], url=doc["url"],
                            path=doc["path"], pages=doc["pages"], paginated=paginated, needs_ocr=doc["needs_ocr"],
                            ocr=doc["ocr"], items=[DocumentPageOut(**r) for r in rs])


@router.get("/documents/{document_id}/pages/{page_no}", response_model=DocumentPageOut, summary="Jedna strona dokumentu")
async def document_page(document_id: int, page_no: int, db: AsyncSession = DB,
                        user: A.User | None = Depends(A.current_user)):
    r = await D.one(db, f"""SELECT pg.document_id, pg.page_no, coalesce(length(pg.text), 0) AS chars, pg.text, pg.ocr, pg.ocr_confidence
                            FROM document_page pg JOIN document d ON d.id = pg.document_id
                            WHERE pg.document_id = :id AND pg.page_no = :no AND {A.public_doc_filter(user, "d")}""",
                    id=document_id, no=page_no)
    if not r:
        raise HTTPException(404, "page not found")
    return DocumentPageOut(**r)
