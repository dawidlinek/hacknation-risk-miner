"""Analysis pack: manifest, exclusion of unapproved AI, DOCX/CSV/JSON/PDF content, annex (api_contract §4). Pure, no DB writes."""
import io
import json

from docx import Document

from riskminer.analysis import pack as PK
from riskminer.api.fixtures import fixture_data


def _report():
    rep = fixture_data("analysis")
    rep["code"] = "AN-2026-0099"
    return rep


def test_manifest_excludes_unapproved_ai():
    m = PK.manifest(_report())
    assert any(x["key"] == "annex" for x in m["items"])
    assert m["excluded"] and all(x["reason"] == "wniosek AI niezatwierdzony" for x in m["excluded"])
    assert m["formats"] == ["docx", "pdf", "csv", "json"]


def test_docx_has_sections_and_no_excluded_flag():
    rep = _report()
    inc, exc = PK.split_flags(rep)
    refs = PK.collect_refs(rep)
    doc = Document(io.BytesIO(PK.build_docx(rep, refs, {})))
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    for head in ("Podsumowanie", "Klasa odniesienia i prognozy", "Sygnały ryzyka", "Załącznik: źródła i cytaty", "Metoda"):
        assert head in text
    assert rep["summary"]["sentence"] in text
    for f in exc:
        assert f["title"] not in text
    assert "—" not in text and "·" not in text


def test_csv_and_json():
    rep = _report()
    csv_b = PK.build_csv(rep)
    assert csv_b.startswith("﻿".encode()) and b"kod;ryzyko" in csv_b
    j = json.loads(PK.build_json(rep, PK.collect_refs(rep)))
    assert j["excluded"] and all(f.get("review_status") != "proposed" or f.get("origin") != "AI" for f in j["flags"])


def test_pdf_conversion():
    import shutil
    import pytest
    if not shutil.which("soffice"):
        pytest.skip("soffice not installed")
    rep = _report()
    pdf = PK.to_pdf_bytes(PK.build_docx(rep, PK.collect_refs(rep), {}))
    assert pdf.startswith(b"%PDF-") and len(pdf) > 5000


def test_allocation_index_and_missing_in_pack():
    rep = _report()
    rep["allocation"] = {"risks": [{"code": "R02", "title": "Grunt", "impact_label": "P80 +28 dni", "chosen": 1,
                                    "expected_cost": {"money": {"amount": "210000.00", "currency": "PLN", "vat_basis": "gross"}, "prov": {"n": 82}}}],
                         "balance": {"note": "1 ryzyko podzielone inaczej niż zalecamy."}}
    rep["missing"] = [{"title": "Brak: dokumentacja geotechniczna", "evidence_state": "BRAK_W_PACZCE", "limits": "Ogranicza ocenę ryzyka R02."}]
    doc = Document(io.BytesIO(PK.build_docx(rep, PK.collect_refs(rep), {})))
    text = "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
    assert "Wspólnie" in text and "P80 +28 dni" in text and "nie ma w paczce" in text and "Rejestr ryzyk" in text
    assert b"Wsp\xc3\xb3lnie" in PK.build_csv(rep)
