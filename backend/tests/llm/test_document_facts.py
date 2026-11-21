"""Golden expectations for the three organizer documents (docs/impl/new_documents.md §1), fake LLM (recorded cassettes).
The rules pass alone must already meet them (confidential + no sovereign model)."""
import json
from pathlib import Path

import pytest

from riskminer.llm import calllog
from riskminer.llm.tasks.document_facts import document_facts, nip_ok
from riskminer.llm.verify import match_in_text

pytestmark = pytest.mark.unit
FIX = Path(__file__).parents[1] / "fixtures" / "llm" / "docs"


def _doc(key: str, sensitivity: str = "public") -> dict:
    d = json.loads((FIX / f"{key}.json").read_text(encoding="utf-8"))
    return {"id": f"fixture:{key}", "filename": d["filename"], "sensitivity": sensitivity,
            "pages": {i + 1: t for i, t in enumerate(d["pages"])}}


def _codes(o: dict) -> set[str]:
    return {c["code"] for c in o["causes"]}


def _all_quotes_on_page(o: dict, doc: dict) -> None:
    for c in o["causes"] + o["effects"] + [f for f in o["facts"] if f.get("quote")]:
        assert match_in_text(c["quote"], doc["pages"][c["page"]]).ok, c


@pytest.mark.parametrize("sens", ["public", "confidential"])
async def test_zagrodno(sens):
    doc = _doc("zagrodno", sens)
    o = await document_facts(doc, sensitivity=sens)
    assert o["doc_kind"] == "protokol_koniecznosci_aneksowania" and o["phase"] == "realizacja" and o["doc_date"] == "2026-05-05"
    assert o["level"] == "contract"
    assert o["identifiers"]["kpo"] == ["KPOD.03.15-IW.13-0004/25"]
    assert o["identifiers"]["contract"] == {"number": "IR.271.1.2026", "date": "2026-03-05"}
    ch = o["change"]
    assert ch["kinds"] == ["termin"] and ch["delta_months"] == 1 and ch["new_term_months"] == 3
    assert ch["planned_end_calc"] == "2026-06-05" and ch["legal_basis_state"] == "DOKUMENT_NIE_WSPOMINA"
    assert {"R03", "R02"} <= _codes(o)
    q = {c["code"]: c["quote"] for c in o["causes"]}
    assert "kolizji z siecią wodociągową" in q["R03"] and "wysoki poziom wód gruntowych" in q["R02"]
    r18 = [e for e in o["effects"] if e["code"] == "R18"]
    assert r18 and r18[0]["months"] == 4 and "Modlikowicach" in r18[0]["linked_investment"]
    assert [c["code"] for c in o["catalogue_proposals"]] == ["R18"]
    _all_quotes_on_page(o, doc)
    if sens == "confidential":       # no sovereign model in tests: rules only, nothing sent to the cloud
        assert o["processing"][-1] == {"pass": "llm", "skipped": "sovereign_unavailable"}
        assert not [r for r in calllog.MEMORY if r["provider"].startswith(("gemini", "openrouter"))]
    else:
        assert o["processing"][-1]["pass"] == "llm" and o["processing"][-1]["provider"] == "gemini"


@pytest.mark.parametrize("sens", ["public", "confidential"])
async def test_zlawies(sens):
    doc = _doc("zlawies", sens)
    o = await document_facts(doc, sensitivity=sens)
    assert o["doc_kind"] == "protokol_koniecznosci" and o["doc_date"] == "2025-10-28" and o["level"] == "contract"
    ids = o["identifiers"]
    assert ids["contract"] == {"number": "272.4.27.1.0.2025", "date": "2025-02-14"} and ids["contractor"].startswith("WIMAX Sp. z o.o")
    ch = o["change"]
    assert set(ch["kinds"]) == {"termin", "wynagrodzenie", "zakres"}
    assert ch["value"] == {"amount": "151481.54", "currency": "PLN", "vat_basis": "gross"}
    assert (ch["old_end"], ch["new_end"], ch["delta_days"]) == ("2025-10-30", "2025-12-05", 36)
    assert ch["legal_basis"] == ["455.1.3"] and ch["legal_basis_state"] == "stated"
    assert "mixed_legal_basis" in {f["code"] for f in o["flags"]}
    assert {"R02", "R07"} <= _codes(o) and ({"R01", "R05"} & _codes(o))
    assert any(m["for_code"] == "R02" for m in o["mitigations"])
    _all_quotes_on_page(o, doc)


@pytest.mark.parametrize("sens", ["public", "confidential"])
async def test_grodzisko_grant_level_and_nip(sens):
    doc = _doc("grodzisko", sens)
    o = await document_facts(doc, sensitivity=sens)
    assert o["doc_kind"] == "pismo_do_instytucji" and o["level"] == "grant" and o["doc_date"] == "2025-11-06"
    ids = o["identifiers"]
    assert ids["kpo"] == ["KPOD.03.15-IW.21-0025/25"] and ids["sign"] == "RI.041.1.2025" and ids["contract"] is None
    assert ids["recipient"].startswith("Urząd Marszałkowski Województwa Podkarpackiego")
    assert o["change"]["kinds"] == ["termin_projektu"] and o["change"]["requested_end"] == "2025-12-31"
    assert ids["nip"] == [{"value": "8161571014", "checksum_ok": False}]
    assert "nip_checksum" in {f["code"] for f in o["flags"]}
    assert {"R03", "R13"} <= _codes(o) and ({"R01", "R09"} & _codes(o))
    _all_quotes_on_page(o, doc)


def test_nip_checksum():
    assert not nip_ok("8161571014") and nip_ok("8161570014")
