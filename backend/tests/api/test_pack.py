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
    for head in ("Najważniejsze wnioski", "Werdykt: ryzyko", "1. Opis inwestycji", "2. Klasa odniesienia i podobne przypadki",
                 "3. Szanse na termin i budżet", "4. Symulacja", "5. Czerwony długopis", "6. Rejestr ryzyk", "7. Podział ryzyk",
                 "8. Zalecane zapisy umowne i lista działań", "9. Jakość danych, luki i rozbieżności", "10. Metoda, źródła i ograniczenia",
                 "Załącznik A. Źródła i cytaty", "Jak czytać oznaczenia pochodzenia"):
        assert head in text, head
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


def _text(docx_bytes: bytes) -> str:
    doc = Document(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs) + "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)


def _sim():
    cdf_t = [[10.0, 0.0], [12.0, 0.3], [14.0, 0.5], [16.0, 0.8], [18.0, 0.9], [20.0, 1.0]]
    cdf_c = [[6.0, 0.0], [7.0, 0.5], [7.5, 0.8], [8.0, 0.9], [9.0, 1.0]]
    return {"n": 82, "runs": 20000, "seed": 7, "insufficient": False, "plan_x": 14.0,
            "metrics": {"time": {"n": 77, "curves": {"": cdf_t}, "drivers": {"": {"rows": [{"label": "R07 roboty dodatkowe", "display": "+19 d", "n_r": 17}]}}},
                        "cost": {"n": 81, "eval_x": 7.7, "markers": [{"x": 7.0, "label": "budżet 7,0", "tone": "ink"}], "curves": {"": cdf_c},
                                 "drivers": {"": {"rows": []}}},
                        "comp": {"n": 168, "curves": {"": [[1, 1.0], [2, 0.95], [3, 0.8]]}, "extras": {"": {"cancel_pct": 8.0}}}},
            "options": [{"key": "geo", "label": "Badania gruntu przed przetargiem", "detail": "Dokumentacja geotechniczna.", "risk_code": "R02",
                         "effect_label": {"time": "bez zmian", "cost": "P90 -0,7 pp"}, "clause_refs": ["R02.1-K1"]}],
            "per_risk": [{"risk": "R02", "p_r": 0.1074, "n_r": 139, "n": 1294, "impact_days": {"p50": 24.3, "p80": 84.5},
                          "impact_cost_pct": {"p50": 1.15, "p80": 4.55}}],
            "limitations": ["Krzywe bazowe z umów klasy porównawczej."], "honesty_note": "Efekt liczony tylko z umów z rozpoznaną przyczyną."}


def test_simulation_quantiles_and_section():
    s = PK.sim_summary(_sim())
    assert (s["time"]["p50"], s["time"]["p80"], s["time"]["p90"]) == (14.0, 16.0, 18.0)
    assert (s["cost"]["p50"], s["cost"]["p80"], s["cost"]["p90"]) == (7.0, 7.5, 8.0)
    assert s["time"]["p_plan"] == 0.5 and s["cost"]["p_budget"] == 0.5 and s["comp"]["p_ge2"] == 0.95
    rep = _report()
    rep["allocation"] = {"risks": [{"code": "R02", "title": "Grunt", "impact_label": "P80 +28 dni", "chosen": 0, "recommended": 0,
                                    "expected_cost": {"money": {"amount": "28335.23", "currency": "PLN", "vat_basis": "gross"}}}]}
    text = _text(PK.build_docx(rep, PK.collect_refs(PK.pack_view(rep)), {}, _sim()))
    assert "P50" in text and "P80" in text and "P90" in text and "20\u00a0000 losowań" in text
    assert "11% (139 z 1\u00a0294 umów)" in text                    # register: probability with n from the simulation
    assert "czas: P50 +24, P80 +84 dni" in text and "28\u00a0335,23 zł brutto" in text
    assert "Badania gruntu przed przetargiem" in text and "ZAŁOŻENIE EKSPERTA" in text   # mitigation marked as expert assumption
    assert "Lista działań dla inwestora" in text


def test_feature_discrepancy_and_uncertain_marks():
    rep = _report()
    rep["features"] = [{"key": "dlugosc_km", "label": "długość", "value": 4.085, "display": "ok. 4,08 km", "unsure": True, "source_label": "pfu s. 6",
                        "origin": "AI", "review_status": "proposed",
                        "prov": {"role": "ai", "review_status": "proposed", "refs": [{"kind": "document", "id": "1", "page_no": 6, "quote": "ok. 4085m"}]}}]
    rep["features_used"] = {"length_km": 6.0}
    rows, diffs = PK.feature_rows(rep)
    assert diffs and "6,00 km" in diffs[0]
    text = _text(PK.build_docx(rep, PK.collect_refs(rep), {}))
    assert "niepewne" in text and "inna niż odczyt" in text and "PROPOZYCJA AI" in text and "„ok. 4085m”" in text
    level, why, pts = PK.verdict(rep, PK.split_flags(rep)[0])
    assert level in ("WYSOKIE", "PODWYŻSZONE", "UMIARKOWANE") and why


def test_annex_leaves_out_unapproved_ai_refs():
    rep = _report()
    inc, exc = PK.split_flags(rep)
    view_refs = PK.collect_refs(PK.pack_view(rep))
    exc_refs = PK.collect_refs({"flags": exc})
    only_exc = [r for r in exc_refs if r not in view_refs]
    text = _text(PK.build_docx(rep, view_refs, {}))
    for r in only_exc:
        if r.get("quote"):
            assert r["quote"] not in text


def test_pack_pdf_text_layer():
    import shutil
    import pytest
    if not shutil.which("soffice"):
        pytest.skip("soffice not installed")
    import pypdfium2 as pdfium
    rep = _report()
    pdf = PK.to_pdf_bytes(PK.build_docx(rep, PK.collect_refs(PK.pack_view(rep)), {}, _sim()))
    doc = pdfium.PdfDocument(pdf)
    text = "".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    assert "Najważniejsze wnioski" in text and "Strona 1 z" in text and "exante.linek.dev" in text and "Czerwony długopis" in text
    assert "\u2014" not in text and "\u00b7" not in text
    assert not any("\ue000" <= ch <= "\uf8ff" for ch in text)
