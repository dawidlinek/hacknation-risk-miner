"""Document text stage (pure helpers) + search / pages API against the loaded DB (in-process ASGI).
Run: uv run pytest -q tests/test_search.py"""
import itertools

import httpx
import pytest

from riskminer.api.main import app
from riskminer.api.routers import search
from riskminer.ingest.doctext import CHUNK_SIZE, TAIL_SLACK, chunk_spans, split_pages, text_hash

if not any(getattr(r, "path", None) == "/api/search" for r in app.routes):
    app.include_router(search.router)   # until main.py includes it


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


# ------------------------------------------------------------------------------------------- pure

def test_split_pages_form_feed():
    assert split_pages("a\fb\f") == ["a", "b"]          # pdftotext: every page ends with \f
    assert split_pages("a\f\fc\n") == ["a", "", "c\n"]  # blank page kept, OCR join without trailing \f
    assert split_pages("no pages") == ["no pages"]
    assert text_hash(["a", "b"]) == text_hash(split_pages("a\fb\f"))


def test_chunk_spans_bounded_and_overlapping():
    text = " ".join(f"słowo{i}" for i in range(2000)) + "\n\n" + "x" * 5000
    spans = chunk_spans(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    for a, b in spans:
        assert b - a <= CHUNK_SIZE + TAIL_SLACK
        assert not text[a].isspace() and not text[b - 1].isspace()
    for (a1, b1), (a2, _) in itertools.pairwise(spans):
        assert a1 < a2 <= b1                              # overlapping, always progressing
    assert chunk_spans("   \n ") == []


def test_snippet_keeps_diacritics_and_marks_unaccented_query():
    text = "Budowa oczyszczalni ścieków w Gminie <Test> & kanalizacji sanitarnej."
    s = search.snippet(text, search.query_terms('oczyszczalni sciekow -gmina or "kanalizacji"'))
    assert "<mark>oczyszczalni</mark> <mark>ścieków</mark>" in s
    assert "<mark>kanalizacji</mark>" in s and "&lt;Test&gt; &amp;" in s
    assert "Gminie" in s and "<mark>Gminie</mark>" not in s
    assert len(search.fold("Łódź żółć")) == len("Łódź żółć") and search.fold("Łódź żółć") == "lodz zolc"


def test_prefix_query_and_snippet():
    assert search.prefix_tsquery("kara umowna -aneks") == "kar:* & umow:* & !aneks"
    assert search.prefix_tsquery('"oczyszczalnia ścieków" or 2024') == "oczyszczaln:* & sciek:* & 2024:*"
    assert search.prefix_tsquery("-tylko -wykluczenia") == ""
    terms = [search.stem(t) for t in search.query_terms("kara umowna")]
    s = search.snippet("Wykonawca zapłaci karę umowną za opóźnienie.", terms, prefix=True)
    assert "<mark>karę</mark> <mark>umowną</mark>" in s


# ------------------------------------------------------------------------------------------- API

async def _any_chunk(client):
    from riskminer.api import deps as D
    from riskminer.db.session import sessionmaker
    async with sessionmaker()() as s:
        return await D.one(s, """SELECT c.document_id, c.page_no, d.doc_type FROM chunk c JOIN document d ON d.id = c.document_id
                                 WHERE c.document_id IS NOT NULL ORDER BY c.id LIMIT 1""")


async def test_search_finds_ranked_chunks(client):
    if not await _any_chunk(client):
        pytest.skip("chunk table empty: run the doctext stage first")
    r = await client.get("/api/search", params={"q": "oczyszczalnia sciekow", "limit": 5})
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    assert body["total"] > 0 and 0 < len(body["items"]) <= 5
    ranks = [h["rank"] for h in body["items"]]
    assert ranks == sorted(ranks, reverse=True)
    h = body["items"][0]
    assert h["document_id"] and h["page_no"] >= 1 and h["char_end"] > h["char_start"]
    assert "<mark>" in h["snippet"]
    # accented and unaccented queries hit the same index entries
    r2 = (await client.get("/api/search", params={"q": "oczyszczalnia ścieków", "limit": 1})).json()
    assert r2["total"] == body["total"]
    # prefix mode reaches inflected forms (oczyszczalni, ściekowej, ...)
    r3 = (await client.get("/api/search", params={"q": "oczyszczalnia sciekow", "prefix": True, "limit": 1})).json()
    assert r3["total"] > body["total"] and "<mark>" in r3["items"][0]["snippet"]


async def test_search_filters_and_paging(client):
    c = await _any_chunk(client)
    if not c:
        pytest.skip("chunk table empty: run the doctext stage first")
    r = (await client.get("/api/search", params={"q": "umowa", "source": "docs_sample", "limit": 3, "offset": 3})).json()
    assert r["offset"] == 3 and all(h["source"] == "docs_sample" for h in r["items"])
    r = (await client.get("/api/search", params={"q": "umowa", "rm_id": "RM-2026-001", "limit": 50})).json()
    assert all(h["rm_id"] == "RM-2026-001" for h in r["items"])
    r = (await client.get("/api/search", params={"q": "zzzqqqnieistniejace"})).json()
    assert r["total"] == 0 and r["items"] == []
    assert (await client.get("/api/search")).status_code == 422


async def test_document_pages(client):
    c = await _any_chunk(client)
    if not c:
        pytest.skip("chunk table empty: run the doctext stage first")
    doc_id, page_no = c["document_id"], c["page_no"]
    r = await client.get(f"/api/documents/{doc_id}/pages")
    assert r.status_code == 200, r.text[:500]
    d = r.json()
    assert d["document_id"] == doc_id and d["items"]
    assert [p["page_no"] for p in d["items"]] == list(range(1, len(d["items"]) + 1))
    slim = (await client.get(f"/api/documents/{doc_id}/pages", params={"include_text": False})).json()
    assert all(p["text"] is None for p in slim["items"])
    p = (await client.get(f"/api/documents/{doc_id}/pages/{page_no}")).json()
    assert p["page_no"] == page_no and p["chars"] == len(p["text"])
    assert (await client.get(f"/api/documents/{doc_id}/pages/99999")).status_code == 404
    assert (await client.get("/api/documents/999999999/pages")).status_code == 404


async def test_search_hit_offsets_match_page_text(client):
    c = await _any_chunk(client)
    if not c:
        pytest.skip("chunk table empty: run the doctext stage first")
    h = (await client.get("/api/search", params={"q": "zamawiający", "limit": 1})).json()["items"][0]
    page = (await client.get(f"/api/documents/{h['document_id']}/pages/{h['page_no']}")).json()
    excerpt = page["text"][h["char_start"]:h["char_end"]]
    assert excerpt and not excerpt[0].isspace()
