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
    for h in ("# Rekord projektu RM-2026-001", "## Najważniejsze wnioski", "## 1. Identyfikacja i finansowanie", "## 2. Powiązanie z postępowaniem",
              "## 3. Umowy i przebieg", "## 4. Plan i wykonanie", "## 5. Zmiany umowy", "## 6. Zdarzenia ryzyka", "### Podobne przypadki",
              "## 7. Propozycje AI (do weryfikacji)", "## 8. Jakość danych", "„Co się zmieniło”", "## 10. Źródła, metoda i ograniczenia",
              "### Metoda", "### Ograniczenia", "https://exante.linek.dev"):
        assert h in t, h
    assert "\u2014" not in t and "\u00b7" not in t
    dx = await expert.get(f"/api/projects/{PILOT}/export.docx")
    assert dx.status_code == 200 and dx.content[:2] == b"PK"
    z = zipfile.ZipFile(io.BytesIO(dx.content))
    body = z.read("word/document.xml").decode()
    assert "Rekord projektu RM-2026-001" in body and "Zdarzenia ryzyka" in body and "Najważniejsze wnioski" in body
    hf = "".join(z.read(n).decode() for n in z.namelist() if n.startswith(("word/header", "word/footer")))
    assert "ex ante" in hf and "NUMPAGES" in hf and "exante.linek.dev" in hf and "RM-2026-001" in hf


@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice not installed")
async def test_pdf_has_text(expert):
    r = await expert.get(f"/api/projects/{PILOT}/export.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(r.content)
    text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    assert "Rekord projektu" in text and "Źródła" in text and "Najważniejsze wnioski" in text
    assert "Strona 1 z" in text and "exante.linek.dev" in text and "zł" in text      # footer fields resolved, Polish glyphs extractable
    assert "\u2014" not in text and "\u00b7" not in text
    assert not any("\ue000" <= ch <= "\uf8ff" for ch in text)                    # no symbol-font glyphs in the text layer


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
    assert "## Najważniejsze wnioski" in md and "## Załącznik B. Propozycje AI (niezatwierdzone)" in md
    assert "[PROPOZYCJA AI]" in md and "nie wchodzi do statystyk" in md            # legend explains the AI tag
    assert "80,00 zł netto" in md and "100,00 zł (podstawa VAT nieznana)" in md     # money always with its VAT basis
    assert "pole 5.3: „Konieczność”" in md                                          # evidence: notice, field code, verbatim quote
    assert "Nie znaleziono postępowania w BZP" in md                                # gap reported, not hidden
    assert "\u2014" not in md and "\u00b7" not in md                 # our own copy (source quotes stay verbatim)
    json.dumps(x)                                                    # the JSON shape is plain data


def _x_with_repeats():
    x = {"meta": {"generated_at": "2026-11-21T10:00:00+00:00", "view": "ekspert", "unverified_ai_hidden": 0},
         "record": {"rm_id": "RM-T-2", "title": "Test \u2014 kanalizacja", "beneficiary": {"name": "Gmina T", "nip": "1", "nip_valid": False},
                    "location": {"teryt_woj": "02"}, "funding": {"value": PE.money(100, "gross"), "subsidy": None}, "origin": "SOURCE",
                    "review_status": "auto"},
         "links": [{"ocid": "ocds-1", "contract_notice_no": "2025/BZP 1", "method": "exact_id", "method_label": "numer", "score": 1.0}],
         "link_alternatives": [], "contracts": [],
         "plan_vs_actual": {"summary": "s", "dates": [{"lot_no": 0, "signed_on": "2025-01-02", "planned_days": 100, "planned_end_on": "2025-04-12",
                                                      "completed_on": "2025-05-01", "actual_days": 119, "delay_days": 19,
                                                      "contract_value": PE.money(1000, "gross"), "paid": PE.money(1100, "gross"), "cost_dev_pct": 10.0}],
                            "values": {"contracts_total": PE.money(1000, "gross"), "paid_total": PE.money(1100, "gross"), "cost_dev_pct": 10.0},
                            "vat_note": "v"},
         "changes": [{"change_id": 1, "kind": "change_notice", "kind_label": "ogłoszenie o zmianie umowy (BZP)", "notice": "2025/BZP 2/01", "changed_on": "2025-03-01",
                      "legal_basis": ["455.1.3"], "change_types": ["price"], "delta_value": PE.money(100, "unknown"), "cause": "roboty dodatkowe",
                      "origin": "SOURCE", "review_status": "auto"},
                     {"change_id": 2, "kind": "performance_block", "kind_label": "ogłoszenie o wykonaniu umowy, sekcja zmian (BZP)", "notice": "2025/BZP 3/01",
                      "changed_on": None, "legal_basis": ["455.1.3"], "change_types": ["price"], "delta_value": PE.money(100, "unknown"),
                      "cause": "roboty dodatkowe", "origin": "SOURCE", "review_status": "auto"}],
         "risk_events": [], "ai_proposals": [], "review_items": [],
         "documents": [{"id": 10, "title": "a.pdf", "filename": "a.pdf", "pages": 1, "sha256": "ab"},
                       {"id": 11, "title": "a.pdf", "filename": "a.pdf", "pages": 1, "sha256": "cd"}],
         "whats_changed": [], "notices": [], "sources": [], "timeline": [], "similar_cases": []}
    return x


def test_quality_reports_repeats_and_never_fixes():
    x = _x_with_repeats()
    kinds = {q["kind"] for q in PE.quality(x)}
    assert {"powtórzony dokument", "powtórzona zmiana", "podstawa VAT", "rozbieżność danych"} <= kinds
    md = PE.to_markdown(x)
    assert "Powtórzenie: powtarza zmianę z ogłoszenia 2025/BZP 2/01" in md       # the repeated row stays, marked
    assert "+19 dni" in md and "+10,0%" in md                                     # page-1 tiles: plan vs actual
    assert "art. 455 ust. 1 pkt 3 Pzp (roboty dodatkowe)" in md                   # legal basis in words
    assert "\u2014" not in md                                                     # even a title with an em dash is cleaned


def test_docx_layout_pure():
    x = _x_with_repeats()
    z = zipfile.ZipFile(io.BytesIO(PE.to_docx(x)))
    body = z.read("word/document.xml").decode()
    assert "Najważniejsze wnioski" in body and "Jak czytać oznaczenia pochodzenia" in body
    assert "Liberation Sans" in z.read("word/styles.xml").decode()                 # a font with Polish glyphs, installed in the image
    assert "\u2014" not in body and "\u00b7" not in body
