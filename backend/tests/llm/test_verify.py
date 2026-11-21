import pytest

from riskminer.llm.verify import match_in_text, numbers_supported, parse_numbers, verify_quote

pytestmark = pytest.mark.unit

PAGES = {
    5: "Wykonawca uzyska zgody właścicieli nieruchomości na cele budowlane,\nw tym dla działek prywatnych.",
    6: "Długość sieci wyniesie ok. 6 km, ostateczna dłu-\ngość wynikać będzie z dokumentacji projektowej.",
    7: "Koniec strony siódmej. Przewody projektować w oparciu o określony w PFU zakres,",
    8: "warunki techniczne do projektowania i budowy wydane przez spółdzielnię.",
    10: "W1-W4 (sieć) | Rury PVC-U DN110 | 335,0 mb\nW5 | Rury PE | 130,0 mb",
}


def test_exact_on_stated_page_with_offsets():
    q = "zgody właścicieli nieruchomości na cele budowlane"
    r = verify_quote(q, PAGES, 5)
    assert r.status == "exact" and r.page == 5 and not r.page_mismatch
    assert PAGES[5][r.char_start:r.char_end] == q


def test_hyphenation_soft_hyphen_and_typographic_quotes():
    r = verify_quote("ostateczna długość wynikać będzie z dokumentacji projektowej", PAGES, 6)
    assert r.status == "exact"
    assert match_in_text("formule „zaprojektuj i wybuduj”", 'w formule "zaprojektuj i wybuduj" zadania').status == "exact"
    assert match_in_text("dłu­gość sieci", "Długość sieci").status == "exact"


def test_page_correction():
    r = verify_quote("zgody właścicieli nieruchomości na cele budowlane", PAGES, 9)
    assert r.status == "exact" and r.page == 5 and r.page_mismatch


def test_fuzzy_and_fabricated():
    r = verify_quote("Wykonawca uzyska zgody wlascicieli nieruchomosci na cele budowlane", PAGES, 5)
    assert r.status == "fuzzy" and r.score >= 90
    assert verify_quote("Zamawiający zapłaci zaliczkę w wysokości 30 procent wynagrodzenia", PAGES, 5).status == "unverified"


def test_cross_page():
    q = "Przewody projektować w oparciu o określony w PFU zakres, warunki techniczne do projektowania"
    r = verify_quote(q, PAGES, 7)
    assert r.ok and r.reason == "cross_page" and r.pages == [7, 8]


def test_table_cells_out_of_order():
    r = verify_quote("W1-W4 (sieć) 335,0 mb Rury PVC-U DN110", PAGES, 10)
    assert r.ok


def test_short_quote_cannot_be_fuzzy():
    assert match_in_text("ok 7 km", "ok. 6 km").status == "unverified"


def test_polish_numbers():
    vals = {t.text.strip(): (t.value, t.unit) for t in parse_numbers("1 234 567,89 zł oraz 7 mln zł i ok. 6 km, 14 miesięcy")}
    assert vals["1 234 567,89"] == (1234567.89, "pln")
    assert vals["7"] == (7e6, "pln")
    assert vals["6"] == (6.0, "km")
    assert vals["14"] == (14.0, "months")
    assert [t.value for t in parse_numbers("do 22.05.2026 r.") if t.unit == "date"] == [20260522]
    assert parse_numbers("1.234.567,89")[0].value == 1234567.89


def test_number_check():
    assert numbers_supported(7_000_000, "7 mln zł brutto", money=True)
    assert numbers_supported(7_020_000, "7 mln zł brutto", money=True)       # within 0.5%
    assert not numbers_supported(7_500_000, "7 mln zł brutto", money=True)
    assert numbers_supported(6.0, "ok. 6 km", unit="km")
    assert numbers_supported(0.335, "335,0 mb", unit="km")                   # km vs mb
    assert not numbers_supported(1.175, "335,0 mb | 130,0 mb", unit="km")    # invented total
    assert numbers_supported(14, "w terminie 14 miesięcy")
    assert not numbers_supported(15, "w terminie 14 miesięcy")
