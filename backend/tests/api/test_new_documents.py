"""G6 (docs/impl/new_documents.md §1, §3): the organizers' three new case documents, from upload to "Co się zmieniło".

Uploads each file to its project as the expert, runs the whole pipeline (riskminer/documents/pipeline.py: OCR → facts →
linking → re-analysis) on the request session inside the rolled-back transaction, with the LLM in fake/replay mode, and
checks the golden expectations. Skipped when materials/organizer_cases/ is absent (it is gitignored) or while a pipeline
step is not implemented yet (the skip reason names the missing step and its owner).

Assertions are made on everything the pipeline produced for the document (its extracted facts, risk events and contract
changes with evidence on it, review items mentioning it, and the changes-since diff), so they hold whatever table a step
chose, as long as the golden values are there. Flag `new_document_reanalysis` goes on only when this passes."""
from __future__ import annotations

import json
import re

import pytest
from sqlalchemy import text

from riskminer.config import REPO_ROOT

pytestmark = pytest.mark.fulldb

CASES = REPO_ROOT / "materials" / "organizer_cases"
FILES = {
    "zagrodno": ("Risk_Miner_protokol_koniecznosci_aneksowania_zagrodno.pdf", "RM-2026-002", "application/pdf"),
    "zlawies": ("Risk_Miner_protokol_koniecznosci_zlawies.docx", "RM-2026-005",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "grodzisko": ("Risk_Miner_pismo_termin_grodzisko.pdf", "RM-2026-010", "application/pdf"),
}


def _norm(s: str) -> str:
    """Lower-case, Polish number formats collapsed: '151 481,54' / '151481.54' -> '151481.54'."""
    s = s.lower().replace(" ", " ")
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)
    s = re.sub(r"(?<=\d),(?=\d{2}\b)", ".", s)
    return s


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    if not CASES.is_dir():
        pytest.skip(f"{CASES} not present (organizer case files are gitignored)")
    from riskminer.documents import pipeline
    missing = pipeline.missing_steps()
    if missing:
        pytest.skip("pipeline steps not implemented yet: " + "; ".join(missing))
    from riskminer.documents import upload as U
    from riskminer.jobs import worker

    async def no_enqueue(kind, payload=None, priority=100, created_by="cli"):
        return {"id": -1, "kind": kind}

    monkeypatch.setattr(U, "raw_dir", lambda: tmp_path)
    monkeypatch.setattr(worker, "enqueue", no_enqueue)
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")


async def _run(expert, db, key: str) -> tuple[int, str, dict]:
    """Upload + pipeline; returns (document_id, normalised text of everything produced, raw bundle)."""
    from riskminer.documents.pipeline import process_document
    name, rm_id, mime = FILES[key]
    up = await expert.post("/api/documents/upload", files={"file": (name, (CASES / name).read_bytes(), mime)},
                           data={"project_rm_id": rm_id, "sensitivity": "public"})
    assert up.status_code == 201, up.text
    doc = up.json()["document_id"]
    result = await process_document(db, doc, actor="user:test")
    bundle: dict = {"upload": up.json(), "pipeline": result}
    q = lambda sql: db.execute(text(sql), {"d": doc})
    bundle["document"] = dict((await q("SELECT doc_type, phase, pages, ocr, data FROM document WHERE id = :d")).mappings().one())
    bundle["pages"] = [dict(r) for r in (await q("SELECT page_no, ocr, left(text, 4000) AS text FROM document_page "
                                                 "WHERE document_id = :d ORDER BY page_no")).mappings().all()]
    bundle["evidence"] = [dict(r) for r in (await q("SELECT claim_table, claim_id, page_no, quote FROM evidence "
                                                    "WHERE document_id = :d")).mappings().all()]
    claims = {(e["claim_table"], e["claim_id"]) for e in bundle["evidence"]}
    bundle["risk_events"] = [dict(r) for r in (await db.execute(text(
        "SELECT * FROM risk_event WHERE id = ANY(:ids)"), {"ids": [i for t, i in claims if t == "risk_event"] or [-1]})).mappings().all()]
    bundle["changes"] = [dict(r) for r in (await db.execute(text(
        "SELECT * FROM contract_change WHERE id = ANY(:ids)"), {"ids": [i for t, i in claims if t == "contract_change"] or [-1]})).mappings().all()]
    bundle["review_items"] = [dict(r) for r in (await db.execute(text(
        "SELECT kind, code, title, question, detail FROM review_item WHERE detail::text ~ :pat "
        "OR (target_table = 'document' AND target_id = :d)"), {"d": doc, "pat": rf"\m{doc}\M"})).mappings().all()]
    bundle["alerts"] = [dict(r) for r in (await q("SELECT * FROM alert WHERE document_id = :d")).mappings().all()]
    diff = await expert.get(f"/api/projects/{rm_id}/changes-since", params={"document_id": doc})
    assert diff.status_code == 200, f"changes-since: {diff.status_code} {diff.text[:300]}"
    bundle["diff"] = diff.json()
    blob = _norm(json.dumps(bundle, ensure_ascii=False, default=str))
    return doc, blob, bundle


def _codes(bundle: dict) -> set[str]:
    out = {str(e.get("catalogue_code") or "") for e in bundle["risk_events"]}
    facts = (bundle["document"].get("data") or {}).get("facts") or {}
    for c in facts.get("causes", []) if isinstance(facts, dict) else []:
        out.add(str(c.get("risk_code") or c.get("code") or ""))
    return {c for c in out if c}


def _assert_diff(bundle: dict) -> None:
    d = json.dumps(bundle["diff"], ensure_ascii=False).lower()
    assert any(k in d for k in ("nowe", "zmienione", "potwierdzone", "zamknięte", "new", "changed")), "empty 'Co się zmieniło'"


async def test_zagrodno(expert, db):
    _doc, blob, b = await _run(expert, db, "zagrodno")
    assert "kpod.03.15-iw.13-0004/25" in blob, "KPO number not extracted"
    assert re.search(r"\+?1 (miesiąc|mies)|delta_months\W+1\b|months\W+1\b", blob), "term +1 month not found"
    assert "2026-06-05" in blob or "05.06.2026" in blob, "new planned end 05.06.2026 not computed"
    codes = _codes(b)
    assert {"R03", "R02"} <= codes, f"expected causes R03 + R02, got {codes}"
    assert "r18" in blob, "R18 (linked investment dependency) proposal missing"
    assert "pompown" in blob and "kolizj" in blob, "verified quotes for the causes missing"
    assert any(a.get("contract_id") for a in b["alerts"]), "no monitoring alert for the ongoing contract (step 8)"
    _assert_diff(b)


async def test_zlawies(expert, db):
    _doc, blob, b = await _run(expert, db, "zlawies")
    assert "151481.54" in blob, "+151 481,54 zł not extracted"
    assert "gross" in blob or "brutto" in blob, "VAT basis of the amount missing"
    assert re.search(r"\b36\b", blob) and ("2025-12-05" in blob or "05.12.2025" in blob), "term 30.10 -> 05.12.2025 (+36 d) missing"
    assert re.search(r"art\.?\s*455\s*ust\.?\s*1\s*pkt\.?\s*3", blob), "legal basis art. 455 ust. 1 pkt 3 missing"
    assert "wimax" in blob, "contractor WIMAX not extracted"
    assert "R02" in _codes(b), f"cause R02 missing: {_codes(b)}"
    _assert_diff(b)


async def test_grodzisko(expert, db):
    _doc, blob, b = await _run(expert, db, "grodzisko")
    assert any(p["ocr"] and len((p["text"] or "").strip()) > 200 for p in b["pages"]), "scan was not OCR-ed into page text"
    assert "kpod.03.15-iw.21-0025/25" in blob, "KPO number not extracted"
    assert "2025-12-31" in blob or "31.12.2025" in blob, "requested project end 31.12.2025 missing"
    assert not b["changes"], "grant-agreement term must not be stored as a contract_change"
    nip_items = [r for r in b["review_items"] if "8161571014" in json.dumps(r, ensure_ascii=False, default=str)]
    assert nip_items, "no review item for the NIP that fails the checksum (8161571014 vs 8161570014)"
    assert any(a.get("project_id") for a in b["alerts"]), "no project-level alert for the grant term change (step 8)"
    _assert_diff(b)
