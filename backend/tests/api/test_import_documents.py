"""Źródła (/zrodla) -> document pipeline (riskminer/imports/documents.py): a case document dropped on the Import screen is
recognised as a document (not a dataset or a project record) and handed to the same pipeline as the project card's drop
zone, with no project bound, so linking finds the project from the document itself.

Transactional fixtures (tests/api/conftest.py): nothing persists in the main DB; uploaded and raw files go to temp dirs;
the LLM runs in fake mode; job rows are written inside the rolled-back transaction, so the worker never sees them.
The organizer-case test is skipped when materials/organizer_cases/ is absent (it is gitignored)."""
from __future__ import annotations

import io
import json

import openpyxl
import pytest
from sqlalchemy import text

from riskminer.config import REPO_ROOT
from riskminer.imports import documents as D
from riskminer.imports import registry, service

CASES = REPO_ROOT / "materials" / "organizer_cases"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# a short case document in plain text, with the Zagrodno KPO number (RM-2026-002) and no record columns
CASE_TXT = """KPOD.03.15-IW.13-0004/25
PROTOKÓŁ KONIECZNOŚCI ANEKSOWANIA UMOWY
sporządzony dnia 05.05.2026 w Zagrodnie
Dotyczy umowy nr: IR.271.1.2026 z dnia: 05.03.2026
W związku z koniecznością przedłużenia terminu realizacji przedmiotu umowy o okres 1 miesiąca, stwierdza się potrzebę
zawarcia aneksu. Przyczyną jest wystąpienie kolizji z siecią wodociągową uniemożliwiające posadowienie pompowni numer PM2.
""".encode()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    from riskminer.documents import upload as U
    from riskminer.jobs import worker

    async def no_enqueue(kind, payload=None, priority=100, created_by="cli"):
        return {"id": -1, "kind": kind}

    monkeypatch.setattr(service, "imports_dir", lambda: tmp_path / "imports")
    monkeypatch.setattr(service, "raw_root", lambda: tmp_path / "raw")
    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "enqueue", no_enqueue)
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(registry.KNOWN_FORMATS["zestaw organizatora"]["headers"])
    ws.append([1, "TEST-DOCROUTE-001", "NIP", "9121715754", "Gmina Oława", "JST", "Polska", "02", "dolnośląskie", "Oława",
               "Budowa kanalizacji testowej", "całe postępowanie", "Ogłoszenie BZP", "2022/BZP 00058537/01", "wod-kan",
               "Roboty budowlane", "Pzp", "PLN", "Zakończone", "test", "2026-11-21", "1.0", None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_is_document():
    assert D.is_document({"name": "protokol.pdf", "kind": "pdf"})
    assert D.is_document({"name": "pismo_zławieś.docx", "kind": "docx"})
    assert not D.is_document({"name": "rekord.pdf", "kind": "pdf", "tabular": True})    # a project record printed to PDF
    assert not D.is_document({"name": "projekty.xlsx", "kind": "xlsx"})
    assert not D.is_document({"name": "paczka.zip", "kind": "zip"})
    assert not D.is_document({"name": "dane.json", "kind": "json"})                      # not a type the document upload takes


async def _session(expert, files) -> str:
    r = await expert.post("/api/imports", files=files)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert (await expert.post(f"/api/imports/{code}/inspect")).status_code == 200
    return code


async def test_route_needs_inspect(expert):
    r = await expert.post("/api/imports", files={"files": ("protokol.txt", CASE_TXT, "text/plain")})
    code = r.json()["code"]
    r = await expert.post(f"/api/imports/{code}/documents")
    assert r.status_code == 409 and "inspect" in r.json()["detail"]


async def test_mixed_drop_routes_document_and_keeps_dataset(expert, db):
    code = await _session(expert, [("files", ("projekty.xlsx", _xlsx(), "application/vnd.ms-excel")),
                                   ("files", ("protokół_zagrodno.txt", CASE_TXT, "text/plain"))])
    r = await expert.post(f"/api/imports/{code}/documents")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["tables"] == 1
    assert [d["name"] for d in out["documents"]] == ["protokół_zagrodno.txt"]
    doc = out["documents"][0]
    assert doc["document_id"] and doc["text_status"] == "ok" and not doc["error"]
    assert [j["kind"] for j in doc["jobs"]] == ["document_extract"]
    row = (await db.execute(text("SELECT project_id, sensitivity, data FROM document WHERE id = :d"),
                            {"d": doc["document_id"]})).mappings().one()
    assert row["project_id"] is None and row["sensitivity"] == "public"     # no project bound: linking finds it
    job = (await db.execute(text("SELECT kind, status FROM job WHERE id = :j"), {"j": doc["jobs"][0]["job_id"]})).mappings().one()
    assert dict(job) == {"kind": "document_extract", "status": "queued"}

    st = (await expert.get(f"/api/imports/{code}")).json()
    assert st["documents"][0]["document_id"] == doc["document_id"]
    assert any(c["call"].startswith("route_document(") for c in st["tool_calls"])
    # the dataset still goes through the mapping step
    st = (await expert.post(f"/api/imports/{code}/propose-mapping")).json()
    assert any(m["field"] == "project.rm_id" for m in st["mapping"])
    # idempotent: a second call reuses the routed document and queues nothing new
    again = (await expert.post(f"/api/imports/{code}/documents")).json()
    assert again["documents"][0]["document_id"] == doc["document_id"]
    n = (await db.execute(text("SELECT count(*) FROM job WHERE payload->>'document_id' = :d"), {"d": str(doc["document_id"])})).scalar()
    assert n == 1


async def test_duplicate_without_facts_requeues_once(expert, db):
    code = await _session(expert, {"files": ("protokol.txt", CASE_TXT, "text/plain")})
    first = (await expert.post(f"/api/imports/{code}/documents")).json()["documents"][0]
    # the same bytes again in a new drop: same document; its extraction is already queued, so nothing new
    code2 = await _session(expert, {"files": ("protokol.txt", CASE_TXT, "text/plain")})
    second = (await expert.post(f"/api/imports/{code2}/documents")).json()["documents"][0]
    assert second["document_id"] == first["document_id"] and second["duplicate"] and second["jobs"] == []
    # an earlier run that never started (job cancelled): the re-drop queues the chain again
    await db.execute(text("UPDATE job SET status = 'cancelled' WHERE payload->>'document_id' = :d"), {"d": str(first["document_id"])})
    code3 = await _session(expert, {"files": ("protokol.txt", CASE_TXT, "text/plain")})
    third = (await expert.post(f"/api/imports/{code3}/documents")).json()["documents"][0]
    assert [j["kind"] for j in third["jobs"]] == ["document_extract"]


@pytest.mark.fulldb
async def test_routed_text_document_links_by_kpo(expert, db):
    """Rules alone (fake LLM) find the KPO number and link the project-less document to RM-2026-002 (exact, 1.0)."""
    from riskminer.documents.pipeline import process_document
    code = await _session(expert, {"files": ("protokol_zagrodno.txt", CASE_TXT, "text/plain")})
    did = (await expert.post(f"/api/imports/{code}/documents")).json()["documents"][0]["document_id"]
    await process_document(db, did, actor="user:test")
    a = (await expert.get(f"/api/documents/{did}/analysis")).json()
    assert a["link"]["project"]["rm_id"] == "RM-2026-002" and a["link"]["project"]["method"] == "exact_id"
    pid = (await db.execute(text("SELECT project_id FROM document WHERE id = :d"), {"d": did})).scalar()
    assert pid == (await db.execute(text("SELECT id FROM project WHERE rm_id = 'RM-2026-002'"))).scalar()


@pytest.mark.fulldb
async def test_card_upload_of_other_projects_document_asks(expert, db):
    """Dropped on RM-2026-005's card, but the KPO number names RM-2026-002: a review item, the document is not moved."""
    from riskminer.documents.pipeline import process_document
    up = await expert.post("/api/documents/upload", files={"file": ("protokol_zagrodno.txt", CASE_TXT, "text/plain")},
                           data={"project_rm_id": "RM-2026-005", "sensitivity": "public"})
    assert up.status_code == 201, up.text
    did = up.json()["document_id"]
    await process_document(db, did, actor="user:test")
    item = (await db.execute(text("SELECT title FROM review_item WHERE key = :k"), {"k": f"doc:{did}:project_mismatch"})).scalar()
    assert item and "RM-2026-005" in item and "RM-2026-002" in item
    bound = (await db.execute(text("SELECT p.rm_id FROM document d JOIN project p ON p.id = d.project_id WHERE d.id = :d"),
                              {"d": did})).scalar()
    assert bound == "RM-2026-005"


GOLDEN = {
    "Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf": ("application/pdf", "RM-2026-002"),
    "Risk_Miner_protokol_koniecznosci_zlawies.docx": (DOCX, "RM-2026-005"),
    "Risk_Miner_pismo_termin_grodzisko.pdf": ("application/pdf", "RM-2026-010"),
}


@pytest.mark.fulldb
async def test_organizer_cases_from_zrodla(expert, db):
    """The three organizer documents in ONE drop on /zrodla (no project chosen): all routed as documents, the scan OCR-ed,
    each linked to its golden project, Grodzisko's NIP flagged for review, and "Co się zmieniło" filled."""
    if not CASES.is_dir():
        pytest.skip(f"{CASES} not present (organizer case files are gitignored)")
    from riskminer.documents.pipeline import process_document
    # modified bytes: the real files (and any earlier local upload of them) keep their own sha256
    files = [("files", (n.replace("zlawies", "zławieś"), (CASES / n).read_bytes() + b"\n%rm-test-zrodla\n", m)) for n, (m, _rm) in GOLDEN.items()]
    code = await _session(expert, files)
    out = (await expert.post(f"/api/imports/{code}/documents")).json()
    assert out["tables"] == 0 and len(out["documents"]) == 3, out
    by_name = {d["name"]: d for d in out["documents"]}
    scan = by_name["Risk_Miner_pismo_termin_grodzisko.pdf"]
    assert scan["text_status"] == "needs_ocr" and [j["kind"] for j in scan["jobs"]] == ["document_ocr"]
    for name, (_m, rm) in GOLDEN.items():
        d = by_name[name.replace("zlawies", "zławieś")]
        assert d["document_id"] and not d["error"], d
        await process_document(db, d["document_id"], actor="user:test")
        a = (await expert.get(f"/api/documents/{d['document_id']}/analysis")).json()
        assert a["project_rm_id"] == rm, (name, a["link"])
        assert all(s["state"] == "done" for s in a["steps"]), (name, a["steps"])
        assert a["review_items"], f"{name}: no proposals for review"
        diff = (await expert.get(f"/api/projects/{rm}/changes-since", params={"document_id": d["document_id"]})).json()
        assert sum(diff["counts"].values()) > 0, f"{name}: empty 'Co się zmieniło'"
        if "grodzisko" in name:
            bad = [c for c in a["link"]["checks"] if c["kind"] == "nip" and not c["ok"]]
            assert bad and bad[0]["value"] == "8161571014" and bad[0]["expected"] == "8161570014"
            assert any("8161570014" in i["title"] for i in a["review_items"])
            assert not a["growth"]["contract_changes"], "grant term change must not be a contract_change"
            regon = [i for i in a["review_items"] if "REGON" in i["title"]]
            assert len(regon) <= 1, f"duplicate REGON review items: {json.dumps(regon, ensure_ascii=False)}"
        else:
            assert a["growth"]["contract_changes"] == 1, (name, a["growth"])


# ---- duplicates: the same file again never errors, never gets stuck, never makes a second document (documents/duplicates.py)

async def _card_upload(expert, rm_id: str | None, name: str = "protokol.txt", body: bytes = CASE_TXT, **extra):
    data = {"sensitivity": "public", **({"project_rm_id": rm_id} if rm_id else {}), **extra}
    r = await expert.post("/api/documents/upload", files={"file": (name, body, "text/plain")}, data=data)
    assert r.status_code == 201, r.text
    return r.json()


async def _project_id(db, rm_id: str) -> int:
    return (await db.execute(text("SELECT id FROM project WHERE rm_id = :r"), {"r": rm_id})).scalar()


@pytest.mark.fulldb
async def test_duplicate_same_card_reuses_and_shows_previous(expert, db):
    a = await _card_upload(expert, "RM-2026-002")
    b = await _card_upload(expert, "RM-2026-002", name="kopia.txt")
    assert b["duplicate"] and b["document_id"] == a["document_id"]
    assert b["previous"]["project_rm_id"] == "RM-2026-002" and b["attached"] is None
    # worker.enqueue is faked here, so the first upload left no job row: the re-upload queues the extraction once ...
    assert [j["kind"] for j in b["jobs"]] == ["document_extract"]
    # ... and a third upload, with that job queued, queues nothing
    c = await _card_upload(expert, "RM-2026-002")
    assert c["document_id"] == a["document_id"] and c["jobs"] == []


@pytest.mark.fulldb
async def test_duplicate_from_zrodla_then_card_attaches_and_relinks(expert, db):
    code = await _session(expert, {"files": ("protokol.txt", CASE_TXT, "text/plain")})
    did = (await expert.post(f"/api/imports/{code}/documents")).json()["documents"][0]["document_id"]
    await db.execute(text("UPDATE document SET data = data || '{\"facts\": {\"identifiers\": {}}}'::jsonb WHERE id = :d"), {"d": did})
    b = await _card_upload(expert, "RM-2026-005")
    assert b["duplicate"] and b["document_id"] == did and b["attached"] == "attached"
    assert [j["kind"] for j in b["jobs"]] == ["document_link"]          # facts exist: only the linking runs again
    assert (await db.execute(text("SELECT project_id FROM document WHERE id = :d"), {"d": did})).scalar() == await _project_id(db, "RM-2026-005")
    act = (await db.execute(text("SELECT action FROM audit_log WHERE table_name = 'document' AND row_id = :d ORDER BY id DESC LIMIT 1"),
                            {"d": did})).scalar()
    assert act == "document.attach"


@pytest.mark.fulldb
async def test_duplicate_on_another_projects_card_links_and_asks(expert, db):
    a = await _card_upload(expert, "RM-2026-002")
    b = await _card_upload(expert, "RM-2026-005")
    assert b["duplicate"] and b["document_id"] == a["document_id"] and b["attached"] == "also_linked"
    did = a["document_id"]
    # stays on RM-2026-002, nothing moved silently; the expert is asked
    assert (await db.execute(text("SELECT project_id FROM document WHERE id = :d"), {"d": did})).scalar() == await _project_id(db, "RM-2026-002")
    title = (await db.execute(text("SELECT title FROM review_item WHERE key = :k"), {"k": f"doc:{did}:also:RM-2026-005"})).scalar()
    assert title and "RM-2026-005" in title and "RM-2026-002" in title
    # both cards list the document
    for rm in ("RM-2026-002", "RM-2026-005"):
        docs = (await expert.get(f"/api/projects/{rm}/documents")).json()["public"]
        assert any(d["key"] == f"doc:{did}" for d in docs), rm
    # a third upload to the same card is idempotent
    c = await _card_upload(expert, "RM-2026-005")
    assert c["document_id"] == did
    n = (await db.execute(text("SELECT count(*) FROM review_item WHERE key = :k"), {"k": f"doc:{did}:also:RM-2026-005"})).scalar()
    assert n == 1


async def test_duplicate_in_new_analysis_reuses_and_requeues_a_stuck_scan(expert, db):
    a = await _card_upload(expert, None, analysis_code="AN-TEST-DUP")
    b = await _card_upload(expert, None, analysis_code="AN-TEST-DUP-2")
    assert b["duplicate"] and b["document_id"] == a["document_id"]
    # a scan whose OCR job was cancelled: the next upload of the same file queues OCR again instead of staying stuck
    await db.execute(text("UPDATE document SET data = data || '{\"text_status\": \"needs_ocr\", \"needs_ocr\": true}'::jsonb "
                          "WHERE id = :d"), {"d": a["document_id"]})
    c = await _card_upload(expert, None, analysis_code="AN-TEST-DUP-3")
    assert c["document_id"] == a["document_id"] and [j["kind"] for j in c["jobs"]] == ["document_ocr"]
