"""extract_features and redpen_scan from hand-written cassettes: verification, number check, unverified handling."""
import json

import pytest

from riskminer.llm.tasks.extract_features import extract_features, feature_items
from riskminer.llm.tasks.redpen_scan import note_items, redpen_scan, windows

pytestmark = pytest.mark.unit

DESC = "Budowa kanalizacji sanitarnej ok. 6 km z 3 przepompowniami, zaprojektuj i wybuduj. 7 mln zł brutto, 14 miesięcy."
DOC = {"id": 901, "doc_type": "PFU", "filename": "pfu.pdf", "sensitivity": "public",
       "pages": {1: "Program funkcjonalno-użytkowy. Budowa sieci kanalizacji sanitarnej.",
                 2: "Wynagrodzenie ma charakter ryczałtowy. Długość sieci wyniesie ok. 6 km, ostateczna długość wynikać "
                    "będzie z dokumentacji projektowej.",
                 3: "Zamawiający nie posiada prawa do dysponowania nieruchomością na cele budowlane dla działek prywatnych."}}


@pytest.fixture
def cassettes(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKMINER_LLM_REPLAY_DIR", str(tmp_path))

    def put(task, match, obj):
        d = tmp_path / task
        d.mkdir(exist_ok=True)
        (d / f"{abs(hash(match))}.json").write_text(json.dumps({"match": match, "text": obj}), encoding="utf-8")
    return put


def chip(key, quote, **kw):
    return {"key": key, "value_text": kw.pop("value_text", quote), "source": "opis", "quote": quote, **kw}


async def test_extract_features_verifies_and_flags(cassettes):
    cassettes("extract_features_text", "Budowa kanalizacji sanitarnej ok. 6 km", {"chips": [
        chip("podsektor", "Budowa kanalizacji sanitarnej", value_code="SAN"),
        chip("dlugosc_km", "ok. 6 km", value_num=6, unit="km", value_text="ok. 6 km"),
        chip("przepompownie", "z 3 przepompowniami", value_num=4),                        # wrong number
        chip("budzet", "7 mln zł brutto", value_num=7000000, vat_basis="gross"),
        chip("termin_mies", "w terminie 18 miesięcy", value_num=18),                       # fabricated quote
        chip("finansowanie", "FEnIKS", value_code="NIEZNANY"),                             # bad code: dropped
    ], "rows": [], "missing": ["przylacza"]})
    res = await extract_features(DESC, [], docs={})
    c = res.chips
    assert c["podsektor"]["value"] == "SAN" and c["podsektor"]["origin"] == "AI" and c["podsektor"]["review_status"] == "proposed"
    assert c["dlugosc_km"]["unsure"] and c["dlugosc_km"]["verification"] == "exact"
    assert c["przepompownie"]["needs_review"] and c["przepompownie"]["unsure"]
    assert c["budzet"]["value"]["amount"] == "7000000.00" and not c["budzet"]["needs_review"]
    assert c["termin_mies"]["verification"] == "unverified" and c["termin_mies"]["unsure"]
    assert "finansowanie" not in c and res.missing == ["przylacza"]
    assert all(i["review_status"] == "proposed" for i in feature_items(res))


async def test_table_total_computed_by_code(cassettes):
    doc = {**DOC, "pages": {1: "W1 | sieć | 335,0 mb\nW2 | sieć | 130,0 mb"}}
    cassettes("extract_features", "335,0 mb", {"chips": [
        {"key": "dlugosc_km", "value_text": "945 mb", "value_num": 0.945, "source": "dokument", "page": 1,
         "quote": "W1 | sieć | 335,0 mb"}],
        "rows": [{"key": "dlugosc_km", "label": "W1", "value_text": "335,0 mb", "value_num": 335, "unit": "mb", "page": 1, "quote": "W1 | sieć | 335,0 mb"},
                 {"key": "dlugosc_km", "label": "W2", "value_text": "130,0 mb", "value_num": 130, "unit": "mb", "page": 1, "quote": "W2 | sieć | 130,0 mb"}],
        "missing": []})
    res = await extract_features(None, [901], docs={901: doc})
    assert not res.errors, res.errors
    L = res.chips["dlugosc_km"]
    assert L["origin"] == "CALC" and L["value"] == 0.465 and L["method"] == "calc:sum_rows(ai)"


def test_windows():
    assert windows(list(range(1, 27))) == [[1, 2, 3, 4, 5, 6], [6, 7, 8, 9, 10, 11], [11, 12, 13, 14, 15, 16],
                                           [16, 17, 18, 19, 20, 21], [21, 22, 23, 24, 25, 26]]
    assert windows([1, 2, 3]) == [[1, 2, 3]]


async def test_redpen_notes(cassettes):
    cassettes("redpen_scan", "Program funkcjonalno", {"notes": [
        {"code": "R01.2", "page": 2, "pkt": None, "quote": "Długość sieci wyniesie ok. 6 km, ostateczna długość wynikać będzie z dokumentacji projektowej.",
         "title": "Ryczałt przy „ok. 6 km” sieci — ryzyko", "why": "Długość ustali projekt wykonawcy.", "strength": "silny",
         "clause_hint": "R01.2-K1"},
        {"code": "R03", "page": 2, "quote": "Zamawiający nie posiada prawa do dysponowania nieruchomością na cele budowlane",
         "title": "Brak prawa do terenu", "why": "Opóźni pozwolenie.", "strength": "silny", "clause_hint": "R08.1-K1"},
        {"code": "R05", "page": 3, "quote": "Wykonawca ponosi pełne ryzyko geologiczne bez dodatkowego wynagrodzenia.",
         "title": "Ryzyko geologiczne", "why": "x", "strength": "średni"},
        {"code": "R99", "page": 2, "quote": "Wynagrodzenie ma charakter ryczałtowy.", "title": "x", "why": "x"}]})
    res = await redpen_scan(DOC)
    by = {n["code"]: n for n in res.notes}
    assert set(by) == {"R01.2", "R03", "R05"}                      # unknown code dropped
    assert by["R01.2"]["verification"] == "exact" and by["R01.2"]["suggested_clause"] == "R01.2-K1"
    assert "—" not in by["R01.2"]["title"]
    assert by["R03"]["page_no"] == 3 and by["R03"]["page_mismatch"]   # page corrected
    assert by["R03"]["suggested_clause"] is None                     # clause of another risk removed
    assert by["R05"]["verification"] == "unverified"                 # fabricated, re-quote did not fix it
    assert res.notes[-1]["code"] == "R05"                            # unverified last
    items = note_items(res, DOC)
    assert all(i["origin"] == "AI" and i["review_status"] == "proposed" for i in items)
    assert next(i for i in items if i["catalogue_code"] == "R05")["body"]["bulk_approvable"] is False


async def test_import_mapping_only_registry_fields(cassettes):
    from riskminer.llm.tasks.import_mapping import propose
    cassettes("import_mapping", "Kwota dotacji", {"target": "project", "summary": "Dwie kolumny pasują.", "questions": [],
              "mapping": [{"column": "Kwota dotacji", "field": "project.subsidy", "confidence": 0.9},
                          {"column": "Kolor", "field": "project.colour", "confidence": 0.9},
                          {"column": "Nr BZP", "field": "procedure.bzp_number", "confidence": 0.4}]})
    out = await propose(headers=["Kwota dotacji", "Kolor", "Nr BZP"],
                        sample={"headers": ["Kwota dotacji", "Kolor", "Nr BZP"], "rows": [["100 000", "zielony", "2024/BZP 1"]]},
                        fields=["project.subsidy", "procedure.bzp_number"])
    assert out == {"Kwota dotacji": "project.subsidy"}       # invented field dropped, low confidence dropped


async def test_non_latin_note_is_dropped_and_logged(cassettes):
    from riskminer.llm import calllog
    doc = {**DOC, "id": 902}
    cassettes("redpen_scan", "Program funkcjonalno", {"notes": [
        {"code": "R08", "page": 2, "quote": "Wynagrodzenie ma charakter ryczałtowy.", "title": "Ryczałt",
         "why": "Ryzyko моноpolu dostawcy.", "strength": "średni"},
        {"code": "R01.2", "page": 2, "quote": "Długość sieci wyniesie ok. 6 km", "title": "Długość orientacyjna",
         "why": "Długość ustali projekt wykonawcy.", "strength": "silny"}]})
    res = await redpen_scan(doc)
    assert [n["code"] for n in res.notes] == ["R01.2"]
    assert "non-Latin" in (calllog.MEMORY[-1]["error"] or "")
