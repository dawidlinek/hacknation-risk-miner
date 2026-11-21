"""Per-project record export GET /api/projects/{rm_id}/export.{fmt} (reads only; transactional fixtures, no main-DB change)."""
from __future__ import annotations

import io
import json
import shutil
import zipfile

import pytest

from riskminer.api import project_export as PE

PILOT = "RM-2026-001"           # organizer pilot: BZP number, linked exact_id, contract + performance notice


async def test_json_has_every_section(expert):
    r = await expert.get(f"/api/projects/{PILOT}/export.json")
    assert r.status_code == 200, r.text
    assert 'filename="rekord_RM-2026-001.json"' in r.headers["content-disposition"]
    x = r.json()
    for key in ("meta", "record", "links", "contracts", "plan_vs_actual", "changes", "risk_events", "ai_proposals", "review_items",
                "documents", "whats_changed", "notices", "sources"):
        assert key in x, key
    assert x["meta"]["view"] == "ekspert" and x["record"]["rm_id"] == PILOT
    lk = x["links"][0]
    assert lk["method"] and lk["score"] is not None and lk["ocid"].startswith("ocds-")
    # money is a value object with its VAT basis; plan vs actual compares gross with gross
    for c in x["contracts"]:
        if c["value"]:
            assert set(c["value"]) == {"amount", "currency", "vat_basis"} and c["value"]["vat_basis"] == "gross"
    assert "netto" in x["plan_vs_actual"]["vat_note"]
    # every source has url/path, retrieved date and sha256
    assert x["sources"] and all(s.get("sha256") and (s.get("url") or s.get("path")) for s in x["sources"])
    # risk events carry their R-code (or none) and evidence rows with field code / page and quote
    for e in x["risk_events"]:
        assert "risk_code" in e and isinstance(e["evidence"], list)
    # AI proposals are flagged as proposals, never as facts
    assert all(a["proposal"] is True for a in x["ai_proposals"])


async def test_markdown_and_docx(expert):
    md = await expert.get(f"/api/projects/{PILOT}/export.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    t = md.text
    for h in ("# Rekord projektu RM-2026-001", "## 1. Identyfikacja i finansowanie", "## 2. Powiązanie z postępowaniem",
              "## 4. Plan i wykonanie", "## 5. Zmiany umowy", "## 6. Zdarzenia ryzyka", "## 7. Propozycje AI (do weryfikacji)",
              "„Co się zmieniło”", "## 10. Źródła"):
        assert h in t, h
    dx = await expert.get(f"/api/projects/{PILOT}/export.docx")
    assert dx.status_code == 200 and dx.content[:2] == b"PK"
    body = zipfile.ZipFile(io.BytesIO(dx.content)).read("word/document.xml").decode()
    assert "Rekord projektu RM-2026-001" in body and "Zdarzenia ryzyka" in body


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
async def test_pdf_has_text(expert):
    r = await expert.get(f"/api/projects/{PILOT}/export.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(r.content)
    text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    assert "Rekord projektu" in text and "Źródła" in text


async def test_public_view_hides_unverified_ai(client):
    r = await client.get(f"/api/projects/{PILOT}/export.json")
    assert r.status_code == 200
    x = r.json()
    assert x["meta"]["view"] == "publiczny"
    assert x["ai_proposals"] == [] and x["review_items"] == []
    assert all(not (e["origin"] == "AI" and e["review_status"] not in ("approved", "edited")) for e in x["risk_events"])


async def test_unknown_project_and_format(client):
    assert (await client.get("/api/projects/RM-NIE-MA-TAKIEGO/export.json")).status_code == 404
    assert (await client.get(f"/api/projects/{PILOT}/export.xml")).status_code == 422


def test_markdown_render_marks_ai_and_vat():
    x = {"meta": {"generated_at": "2026-11-21T10:00:00+00:00", "view": "ekspert", "unverified_ai_hidden": 0},
         "record": {"rm_id": "RM-T-1", "title": "Test", "description": None, "beneficiary": {"name": "Gmina T", "nip": "9121715754",
                    "nip_valid": True}, "location": {"teryt_woj": "02", "city": "T"}, "public_id_type": "Projekt KPO",
                    "public_id": "KPOD.03.15-IW.13-0004/25", "scope": "całe postępowanie", "status": "Zakończone",
                    "subsector_main": "SAN", "delivery_model": "build", "record_date": "2026-11-21", "record_version": "2.0",
                    "funding": {"programme": "KPO", "value": PE.money(100, "unknown"), "subsidy": None, "note": "n"},
                    "origin": "SOURCE", "review_status": "auto", "source": None},
         "links": [], "link_alternatives": [], "contracts": [],
         "plan_vs_actual": {"summary": "s", "dates": [], "values": {"estimate_bzp": PE.money(80, "net")}, "vat_note": "v"},
         "changes": [], "risk_events": [{"risk_code": "R07", "risk_name": "Roboty dodatkowe", "summary": "zmiana", "occurred_on": None,
                                          "impact_days": None, "impact_value": None, "impact_pct": None, "evidence": [
                                              {"notice_number": "2025/BZP 1/01", "field_code": "5.3", "quote": "Konieczność"}],
                                          "origin": "AI", "review_status": "proposed", "proposal": True}],
         "ai_proposals": [{"what": "zdarzenie ryzyka", "risk_code": "R07", "quote": "Konieczność", "proposal": True}],
         "review_items": [], "documents": [], "whats_changed": [], "notices": [], "sources": []}
    md = PE.to_markdown(x)
    assert "[PROPOZYCJA AI] zmiana" in md and "PROPOZYCJA, czeka na eksperta" in md
    assert "80,00 zł (netto)" in md and "pole 5.3: „Konieczność”" in md
    assert "\u2014" not in md and "\u00b7" not in md                 # our own copy (source quotes stay verbatim)
    json.dumps(x)                                                    # the JSON shape is plain data
