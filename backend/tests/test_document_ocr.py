"""document_ocr (new_documents.md G1, owner D) on the organizer's scanned Grodzisko letter.

Runs inside one asyncpg transaction that is rolled back; derived files go to a temp dir, so neither the main DB nor
data/raw changes. Skipped when the case file (gitignored) or an OCR runtime (tesseract or the riskminer-ocr image) is
missing."""
from __future__ import annotations

import subprocess

import pytest

from riskminer import validators
from riskminer.config import REPO_ROOT
from riskminer.db.session import raw_conn
from riskminer.ingest import ocr_doc

LETTER = REPO_ROOT / "materials" / "organizer_cases" / "Risk_Miner_pismo_termin_grodzisko.pdf"


def _ocr_ready() -> bool:
    try:
        cmd = ocr_doc.runtime()
    except ocr_doc.OcrUnavailable:
        return False
    try:
        return subprocess.run([*cmd, "--version"], capture_output=True, timeout=60).returncode == 0
    except Exception:  # noqa: BLE001
        return False


needs_ocr = pytest.mark.skipif(not (LETTER.exists() and _ocr_ready()), reason="case file or OCR runtime missing")


def test_nip_rule_is_shared():
    from riskminer.connectors import gus_bir, ted, vat_whitelist
    from riskminer.imports import rules
    from riskminer.ingest import ids
    bad, good = "8161571014", "8161570014"
    for f in (validators.nip_valid, ids.nip_valid, ted.nip_ok, vat_whitelist.nip_valid, gus_bir.nip_valid):
        assert f(good) and not f(bad)
    assert rules.nip_checksum(bad) == (False, "nip_checksum") and rules.nip_checksum(good) == (True, "")
    c = validators.nip_check(bad)
    assert (c["valid"], c["expected"], c["got"], c["reason"]) == (False, 9, 4, "checksum")


def test_tsv_to_text_lines_and_confidence():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tNIP\n5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t80\t8161571014\n"
           "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t70\tDotyczy\n4\t1\t2\t1\t1\t0\t0\t0\t1\t1\t-1\t\n")
    t, c = ocr_doc.tsv_to_text(tsv)
    assert t == "NIP 8161571014\n\nDotyczy" and c == 0.8


@needs_ocr
async def test_document_ocr_grodzisko_scan(tmp_path):
    rel = str(LETTER.relative_to(REPO_ROOT))
    async with raw_conn() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            doc_id = await conn.fetchval("""
                INSERT INTO document (title, filename, path, mime, sha256, pages, ocr, fetch_state, sensitivity, data, key,
                                      origin, review_status)
                VALUES ('pismo Grodzisko (test)', 'Risk_Miner_pismo_termin_grodzisko.pdf', $1, 'application/pdf',
                        'test-grodzisko-ocr', 1, false, 'found', 'confidential', $2, 'test:ocr:grodzisko', 'SOURCE', 'auto')
                RETURNING id""", rel, {"text_status": "needs_ocr", "needs_ocr": True})
            res = await ocr_doc.ocr_document(doc_id, conn=conn, raw_root=tmp_path, extract=False, actor="test")
            assert res["pages"] == 1 and res["chars"] > 800 and res["mean_conf"] > 0.6, res
            d = await conn.fetchrow("SELECT ocr, data FROM document WHERE id = $1", doc_id)
            assert d["ocr"] is True and d["data"]["text_status"] == "ok" and d["data"]["needs_ocr"] is False
            assert d["data"]["ocr_text_path"].endswith(".ocr.txt") and isinstance(d["data"]["ocr_confidence"], list)
            pg = await conn.fetchrow("SELECT ocr, ocr_confidence, text FROM document_page WHERE document_id = $1 AND page_no = 1",
                                     doc_id)
            assert pg["ocr"] is True and pg["ocr_confidence"] > 0.6
            assert "8161571014" in pg["text"] and "KPOD.03.15-IW.21-0025/25" in pg["text"] and "31.12.2025" in pg["text"]
            hits = await conn.fetchval("SELECT count(*) FROM chunk WHERE document_id = $1 AND tsv @@ "
                                       "websearch_to_tsquery('simple', unaccent('kanalizacji Grodzisko'))", doc_id)
            assert hits >= 1
            assert (tmp_path / "upload" / "manifest.jsonl").read_text().count('"method": "tesseract"') == 1
        finally:
            await tr.rollback()
