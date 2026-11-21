"""Fixes from the 11:00 rehearsal: a plain-text investment description uploads like a PDF (pages, chunks, red pen), a
re-upload ticked public lifts the first default-confidential upload, and regex features read long descriptions right
(months are not "mieszkańców", the title names the subsector, a secured budget beats a larger estimate, attached
documents fill features the description does not give). Transactional fixtures; raw bytes go to a temp dir."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from riskminer.analysis import features as FE
from riskminer.documents import upload as U

DESC = ("Budowa sieci kanalizacji sanitarnej wraz z przepompowniami w miejscowościach A i B, w formule zaprojektuj i wybuduj.\n\n"
        "Gmina liczy około 6 200 mieszkańców. Cel: likwidacja przydomowych oczyszczalni.\n\n"
        "Wartość szacunkowa: 9 450 000 zł netto, tj. 11 623 500 zł brutto. W budżecie gminy na zadanie zabezpieczono "
        "10 800 000 zł brutto.\n\n"
        "Sieć grawitacyjna o łącznej długości około 7,4 km, 4 przepompowni sieciowych, 210 przyłączy.\n\n"
        "Termin realizacji całości: 18 miesięcy od dnia podpisania umowy. Gwarancja jakości: 60 miesięcy.\n\n") * 3


@pytest.fixture(autouse=True)
def _tmp_raw(tmp_path, monkeypatch):
    from riskminer.jobs import worker
    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "known_kind", lambda kind: False)
    return tmp_path


def test_regex_features_long_description():
    out = FE.extract(DESC)
    assert out["podsektor"]["value"] == "SAN"                       # not OCZ from "przydomowych oczyszczalni"
    assert out["termin_mies"]["value"] == 18.0                      # not 200 from "6 200 mieszkańców", not the guarantee
    assert out["budzet"]["value"]["amount"] == "10800000.00"         # the secured amount, not the larger estimate
    assert FE.extract("Budowa oczyszczalni ścieków w Steklinie, 12 miesięcy")["podsektor"]["value"] == "OCZ"
    assert FE.extract("Termin wykonania: 10 mies., 300 mieszkańców")["termin_mies"]["value"] == 10.0


def test_text_pages_keep_paragraphs():
    pages = U.text_pages(DESC, size=600)
    assert len(pages) > 2 and all(len(p) <= 900 for p in pages)
    assert "".join(pages).replace("\n", "") == DESC.strip().replace("\n", "")
    assert U.text_pages("a\fb") == ["a", "b"]


async def test_txt_upload_then_public_reupload(expert, db):
    body = DESC.encode("cp1250")                                     # Windows-encoded text is fine too
    r = await expert.post("/api/documents/upload", files={"file": ("opis.txt", body, "text/plain")})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["sensitivity"] == "confidential" and d["text_status"] == "ok" and d["pages"] >= 1
    pages = (await db.execute(text("SELECT string_agg(text, ' ') FROM document_page WHERE document_id = :d"), {"d": d["document_id"]})).scalar()
    assert "mieszkańców" in pages
    r2 = await expert.post("/api/documents/upload", files={"file": ("opis.txt", body, "text/plain")}, data={"sensitivity": "public"})
    assert r2.status_code == 201 and r2.json()["duplicate"] is True and r2.json()["document_id"] == d["document_id"]
    assert r2.json()["sensitivity"] == "public"
    assert (await db.execute(text("SELECT sensitivity FROM document WHERE id = :d"), {"d": d["document_id"]})).scalar() == "public"


async def test_analysis_features_from_attached_document(expert, db):
    up = (await expert.post("/api/documents/upload", files={"file": ("opis.txt", DESC.encode(), "text/plain")})).json()
    r = await expert.post("/api/analyses", json={"text": "", "document_ids": [up["document_id"]], "sensitivity": "confidential"})
    assert r.status_code == 201, r.text
    chips = {f["key"]: f for f in r.json()["features"]}
    assert chips["podsektor"]["value"] == "SAN" and chips["termin_mies"]["value"] == 18.0
    assert chips["podsektor"]["source_label"] == "dokument"


async def test_reupload_after_demo_cleanup_creates_a_fresh_document(expert, db):
    """demo-cleanup removes test uploads but keeps their source row and raw bytes; the same file uploaded again (e.g.
    the jury's own upload of an organizer case file) must give a fresh, fully processed document, not a broken duplicate."""
    body = DESC.encode()
    first = (await expert.post("/api/documents/upload", files={"file": ("opis.txt", body, "text/plain")})).json()
    src = (await db.execute(text("SELECT source_id FROM document WHERE id = :d"), {"d": first["document_id"]})).scalar()
    await db.execute(text("DELETE FROM job WHERE payload->>'document_id' = :d"), {"d": str(first["document_id"])})
    await db.execute(text("DELETE FROM document WHERE id = :d"), {"d": first["document_id"]})   # what the cleanup does
    again = await expert.post("/api/documents/upload", files={"file": ("opis.txt", body, "text/plain")})
    assert again.status_code == 201, again.text
    a = again.json()
    assert a["duplicate"] is False and a["document_id"] != first["document_id"] and a["text_status"] == "ok"
    row = (await db.execute(text("SELECT source_id, pages FROM document WHERE id = :d"), {"d": a["document_id"]})).one()
    assert row[0] == src and row[1] >= 1                                   # same source reused, pages rebuilt
    n = (await db.execute(text("SELECT count(*) FROM chunk WHERE document_id = :d"), {"d": a["document_id"]})).scalar()
    assert n >= 1
