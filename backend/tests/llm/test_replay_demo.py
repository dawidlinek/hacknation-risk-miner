"""Replays the recorded live calls on the demo documents (Steklin PFU 30011, Sulmierzyce PPU 30606). Reads page text
from the national DB (read-only) because the request hash covers the exact page text."""
import pytest

from riskminer.llm.docs import load_documents
from riskminer.llm.tasks.extract_features import extract_features
from riskminer.llm.tasks.redpen_scan import redpen_scan

pytestmark = pytest.mark.fulldb


async def test_steklin_redpen_replay():
    docs = await load_documents([30011])
    if not docs:
        pytest.skip("demo document not in this DB")
    res = await redpen_scan(docs[30011])
    assert len(res.notes) >= 10 and not res.failed_pages
    assert sum(n["verification"] != "unverified" for n in res.notes) / len(res.notes) >= 0.9
    assert all(n["code"].startswith("R") for n in res.notes)


async def test_demo_chips_replay():
    docs = await load_documents([30011, 30606])
    if len(docs) < 2:
        pytest.skip("demo documents not in this DB")
    res = await extract_features("Budowa kanalizacji sanitarnej w Steklinie, zaprojektuj i wybuduj.", [30011, 30606], docs=docs)
    assert res.chips["formula"]["value"] == "design_build"
    assert res.chips["dlugosc_km"]["origin"] == "CALC" and abs(res.chips["dlugosc_km"]["value"] - 1.175) < 1e-6


async def test_catalogue_proposals_checks_ids(tmp_path, monkeypatch):
    import json

    from riskminer.llm.tasks.catalogue_proposals import propose
    monkeypatch.setenv("RISKMINER_LLM_REPLAY_DIR", str(tmp_path))
    (tmp_path / "catalogue_proposals").mkdir()
    (tmp_path / "catalogue_proposals" / "x.json").write_text(json.dumps({"match": "<probka>", "text": {"proposals": [
        {"name": "Warunki atmosferyczne i sezonowość robót", "definition": "Opady i mróz.", "example_ids": ["c1", "c2", "c3"],
         "merge_with": None, "rationale": "x"},
        {"name": "Nowa kategoria", "definition": "x", "example_ids": ["c999"], "merge_with": None}]}}), encoding="utf-8")
    res = await propose(50, insert=False)
    if res.get("note"):
        pytest.skip("no classified causes in this DB")
    assert len(res["proposals"]) == 1                                   # unknown example ids dropped
    assert res["proposals"][0]["merge_with"] == "R16"                   # name matches the existing weather risk
