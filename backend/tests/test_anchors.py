"""Evidence anchoring for repeated notice fields (riskminer/ingest/anchors.py, owner D): pure parser + anchor tests."""
from __future__ import annotations

from riskminer.ingest import anchors
from riskminer.parsing import bzp_parse as bp

TR = ("<html><body><main><h1>Ogłoszenie o wyniku postępowania</h1>"
      "<h2>SEKCJA VIII ZAWARCIE UMOWY (dla części 5)</h2>"
      '<h3>8.1.) Data zawarcia umowy: <span class="normal">2022-07-20</span></h3>'
      '<h3>8.2.) Wartość umowy: <span class="normal">100 000,00 PLN</span></h3>'
      "<h2>SEKCJA VIII ZAWARCIE UMOWY (dla części 9)</h2>"
      '<h3>8.1.) Data zawarcia umowy: <span class="normal">2022-07-11</span></h3>'
      '<h3>8.2.) Wartość umowy: <span class="normal">250 000,00 PLN</span></h3>'
      "</main></body></html>")

CP = ("<main><h2>SEKCJA V REALIZACJA UMOWY</h2>"
      '<h3>5.4.1.) Liczba zmian umowy: <span class="normal">2</span></h3>'
      '<h3>5.4.2.) Numer zmiany: <span class="normal">1</span></h3>'
      '<h3>5.4.4.) Przyczyna zmiany: <span class="normal">kolizja z siecią wodociągową</span></h3>'
      '<h3>5.4.2.) Numer zmiany: <span class="normal">2</span></h3>'
      '<h3>5.4.4.) Przyczyna zmiany: <span class="normal">wysoki poziom wód gruntowych</span></h3>'
      "</main>")


def test_entry_offsets_point_at_the_field_in_html():
    pn = bp.parse_html(TR)
    e = [x for x in pn.entries if x.code == "8.1"][1]
    assert e.part == 9 and bp.html_to_text(TR[e.start:e.end]) == "8.1.) Data zawarcia umowy: 2022-07-11"


def test_anchor_by_part_and_by_change_block():
    pn = bp.parse_html(TR)
    e, k, tot = anchors.anchor(pn, "8.1", "part", 9)
    assert (e.value, k, tot) == ("2022-07-11", 2, 2)
    assert anchors.anchor(pn, "8.1", "part", 3) == (None, 0, 2)          # no such part: left unanchored, never guessed
    pc = bp.parse_html(CP)
    e, k, tot = anchors.anchor(pc, "5.4.4", "block", 1)                  # contract_change key cp|<object>|1 = 2nd block
    assert (e.value, k, tot) == ("wysoki poziom wód gruntowych", 2, 2)
    assert "wysoki poziom" in bp.html_to_text(CP[e.start:e.end])


def test_quote_finds_the_field_that_holds_it():
    tr = ("<main><h2>SEKCJA V (dla części 1)</h2>"
          '<h3>5.1.) Informacja: <span class="normal">Postępowanie unieważniono</span></h3>'
          '<h3>5.2.) Podstawa prawna unieważnienia: <span class="normal">art. 255 pkt 3 ustawy</span></h3>'
          '<h3>5.2.1.) Uzasadnienie: <span class="normal">Oferta z najniższą ceną przewyższa kwotę</span></h3></main>')
    pn = bp.parse_html(tr)
    e = anchors.find_quote(pn, "oferta z najniższą ceną przewyższa", "part", 1)
    assert e.code == "5.2.1"                       # the justification, not the legal basis 5.2
    assert anchors.find_quote(pn, "nie ma takiego tekstu", "part", 1) is None
