"""POST /api/documents/upload + GET /api/documents/{id}/file (api_contract §2.3 1.1, §3.3). Transactional (rolled back);
raw bytes go to a temp dir, never to data/raw/upload."""
from __future__ import annotations

import io
import json

import pytest
from sqlalchemy import text

from riskminer.documents import upload as U

pytestmark = pytest.mark.fulldb


def make_pdf(pages: list[str]) -> bytes:
    """Minimal valid PDF with one Helvetica text line per page (ASCII only)."""
    objs: list[bytes] = []
    kids = []
    n = len(pages)
    # 1 catalog, 2 pages, 3 font, then per page: page obj + content obj
    for i, t in enumerate(pages):
        kids.append(f"{4 + 2 * i} 0 R")
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {n} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, t in enumerate(pages):
        stream = f"BT /F1 12 Tf 50 700 Td ({t}) Tj ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R "
                    f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for k, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{k} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


PFU = make_pdf(["Program funkcjonalno-uzytkowy. Budowa sieci kanalizacji sanitarnej w formule zaprojektuj i wybuduj.",
                "Siec o dlugosci ok. 6 km, ostateczna dlugosc wynikac bedzie z dokumentacji projektowej. " * 3])


@pytest.fixture(autouse=True)
def _tmp_raw(tmp_path, monkeypatch):
    from riskminer.jobs import worker
    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "known_kind", lambda kind: False)   # enqueue() uses its own connection: never in tests
    return tmp_path


async def _up(c, content=PFU, name="PFU_kanalizacja.pdf", **form):
    return await c.post("/api/documents/upload", files={"file": (name, content, "application/pdf")}, data=form)


def test_pdf_pages():
    ex = U.extract_pages(PFU, ".pdf")
    assert ex.method == "pypdfium2" and len(ex.pages) == 2 and "zaprojektuj i wybuduj" in ex.pages[0]
    assert not ex.needs_ocr


def test_doc_type_guess():
    assert U.guess_doc_type("PFU_kanalizacja.pdf", [])["code"] == "PFU"
    assert U.guess_doc_type("Zalacznik.pdf", ["Projektowane postanowienia umowy"])["code"] in ("PPU", "INNE")


async def test_upload_public_pdf(client, db, _tmp_raw):
    r = await _up(client, sensitivity="public")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["pages"] == 2 and out["text_status"] == "ok" and out["doc_type"]["code"] == "PFU" and out["sensitivity"] == "public"
    did = out["document_id"]
    d = (await db.execute(text("SELECT d.*, s.kind, s.licence, s.sha256 AS s_sha FROM document d JOIN source s ON s.id = d.source_id "
                               "WHERE d.id = :id"), {"id": did})).mappings().one()
    assert d["origin"] == "SOURCE" and d["kind"] == "upload" and d["licence"] == "user-upload" and d["s_sha"] == out["sha256"]
    assert (await db.execute(text("SELECT count(*) FROM document_page WHERE document_id = :id"), {"id": did})).scalar() == 2
    assert (await db.execute(text("SELECT count(*) FROM chunk WHERE document_id = :id AND tsv IS NOT NULL"), {"id": did})).scalar() >= 2
    a = (await db.execute(text("SELECT actor, request_id FROM audit_log WHERE action = 'document.upload' AND row_id = :id"),
                          {"id": did})).one()
    assert a[0].startswith("anon:") and a[1]
    lines = [json.loads(x) for x in (_tmp_raw / "manifest.jsonl").read_text().splitlines()]
    assert {x["method"] for x in lines} == {"UPLOAD", "DERIVED"} and all(x["licence"] == "user-upload" for x in lines)
    assert (_tmp_raw / f"{out['sha256']}.pdf").read_bytes() == PFU
    f = await client.get(f"/api/documents/{did}/file")
    # the file lives in a tmp dir outside data/: the route refuses paths outside data_dir
    assert f.status_code == 404


async def test_duplicate_same_owner(client):
    a = (await _up(client)).json()
    b = (await _up(client)).json()
    assert b["duplicate"] is True and b["document_id"] == a["document_id"]


async def test_confidential_default_hidden_from_others(client, expert, db):
    out = (await _up(client)).json()
    assert out["sensitivity"] == "confidential"
    doc = dict((await db.execute(text("SELECT sensitivity, data FROM document WHERE id = :id"),
                                 {"id": out["document_id"]})).mappings().one())
    assert not U.can_read(doc, anon_id="ffffffff", user_actor=None, role=None)
    assert not U.can_read(doc, anon_id="ffffffff", user_actor="user:test", role="expert")
    assert U.can_read(doc, anon_id="ffffffff", user_actor="user:boss", role="admin")
    r = await expert.get(f"/api/documents/{out['document_id']}/file")
    assert r.status_code == 404


async def test_rejects(client):
    r = await _up(client, content=b"hello", name="x.xlsx")
    assert r.status_code == 415 and r.json()["code"] == "unsupported_type"
    r = await _up(client, content=b"\x00\x01binary", name="x.txt")          # plain text accepted, binary named .txt is not
    assert r.status_code == 415 and r.json()["code"] == "type_mismatch"
    r = await _up(client, content=b"not a pdf", name="x.pdf")
    assert r.status_code == 415 and r.json()["code"] == "type_mismatch"
    r = await _up(client, project_rm_id="RM-2026-003")
    assert r.status_code == 401
    r = await client.post("/api/documents/upload", files={"file": ("a.pdf", PFU, "application/pdf")},
                          headers={"X-Requested-With": ""})
    assert r.status_code == 403


async def test_project_upload_expert(expert, db):
    r = await _up(expert, project_rm_id="RM-2026-003", sensitivity="public")
    assert r.status_code == 201, r.text
    pid = (await db.execute(text("SELECT p.rm_id FROM document d JOIN project p ON p.id = d.project_id WHERE d.id = :id"),
                            {"id": r.json()["document_id"]})).scalar()
    assert pid == "RM-2026-003"
