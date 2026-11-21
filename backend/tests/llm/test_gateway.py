"""Gateway in fake mode: routing by sensitivity, replay, validation, llm_call rows (memory sink), budget."""
import json

import pytest
from pydantic import BaseModel

from riskminer.llm import calllog, gateway
from riskminer.llm.backends.base import PdfFile, Text
from riskminer.llm.config import LLMConfig, llm_config
from riskminer.llm.errors import BudgetExceeded, InvalidOutput, RefusedForSensitivity, ReplayMiss, SovereignUnavailable
from riskminer.llm.gateway import LLMRequest
from riskminer.llm.routing import route

pytestmark = pytest.mark.unit


class Out(BaseModel):
    code: str


@pytest.fixture
def cassettes(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKMINER_LLM_REPLAY_DIR", str(tmp_path))

    def put(task: str, match: str, text):
        d = tmp_path / task
        d.mkdir(exist_ok=True)
        (d / f"{abs(hash(match))}.json").write_text(json.dumps({"match": match, "text": text, "tokens_in": 10,
                                                                "tokens_out": 5}), encoding="utf-8")
    return put


def test_confidential_never_routes_to_cloud():
    with pytest.raises(SovereignUnavailable):
        route("extract_features", "confidential")
    # even if someone points the sovereign alias at Gemini, the PL filter removes it
    cfg = llm_config().model_copy(deep=True)
    cfg.models["sovereign"] = cfg.models["strong"]
    cfg.fallback["sovereign"] = ["strong", "fast"]
    with pytest.raises(SovereignUnavailable):
        route("extract_features", "confidential", cfg=cfg)
    with pytest.raises(RefusedForSensitivity):
        route("classify_causes", "confidential")          # no confidential entry = refuse


def test_confidential_pdf_refused():
    cfg = llm_config()
    from riskminer.llm import routing
    routing.mark_health("wcss_bielik", {"status": "up", "kat_passed": True})
    with pytest.raises(RefusedForSensitivity):
        route("extract_features", "confidential", has_pdf=True, cfg=cfg)


def test_public_route_and_fallback_chain():
    ts = route("extract_features", "public")
    assert [t.alias for t in ts] == ["strong", "fast", "emergency"]
    assert ts[1].fallback_from == "strong"


async def test_caller_cannot_downgrade(monkeypatch):
    async def labels(doc_ids, codes):
        return ["confidential"]
    monkeypatch.setattr(gateway, "_ref_labels", labels)
    req = LLMRequest(task="redpen_scan", sensitivity="public", prompt="redpen_scan", parts=[Text("x")],
                     input_refs=["document:1"])
    assert await gateway.effective_sensitivity(req) == "confidential"
    with pytest.raises(SovereignUnavailable):
        await gateway.run(req)
    assert not [r for r in calllog.MEMORY if not r["provider"].startswith("wcss")]     # nothing sent to the cloud

    async def boom(doc_ids, codes):
        raise OSError("db down")
    monkeypatch.setattr(gateway, "_ref_labels", boom)
    assert await gateway.effective_sensitivity(req) == "confidential"                   # fail closed


async def test_replay_validates_and_logs(cassettes):
    cassettes("nl2sql", "PYTANIE-A", {"code": "R07"})
    res = await gateway.run(LLMRequest(task="nl2sql", sensitivity="public", prompt="extract_features",
                                       parts=[Text("PYTANIE-A")], output=Out, subject="test:1"))
    assert res.data.code == "R07" and res.replayed and res.provider == "gemini"
    row = calllog.MEMORY[-1]
    assert row["provider"] == "gemini+replay" and row["model"] and row["data_location"].startswith("global")
    assert row["prompt_version"].startswith("extract_features@v") and row["status"] == "ok" and row["attempt"] == 1


async def test_invalid_output_and_miss(cassettes):
    cassettes("nl2sql", "PYTANIE-B", "to nie jest json")
    with pytest.raises(InvalidOutput):
        await gateway.run(LLMRequest(task="nl2sql", sensitivity="public", prompt="extract_features",
                                     parts=[Text("PYTANIE-B")], output=Out))
    assert calllog.MEMORY[-1]["status"] == "invalid"
    with pytest.raises(ReplayMiss):
        await gateway.run(LLMRequest(task="nl2sql", sensitivity="public", prompt="extract_features",
                                     parts=[Text("nieznane")], output=Out))


async def test_budget_cap(monkeypatch):
    calllog.MEMORY.append({"cost_usd": 39.99, "created_at": __import__("time").time()})
    calllog._spent_cache.clear()
    cfg = LLMConfig.model_validate({**llm_config().model_dump(by_alias=True)})
    with pytest.raises(BudgetExceeded):
        await gateway._budget_check(LLMRequest(task="x", sensitivity="public", prompt="x", parts=[]), cfg, 0.05)


def test_cost():
    cfg = llm_config()
    c = calllog.cost_usd(cfg, "gemini-3.8-flash", 1_000_000, 100_000, tokens_cached=500_000, tokens_thought=0)
    assert abs(c - (0.5 * 0.75 + 0.5 * 0.075 + 0.1 * 3.75)) < 1e-6


def test_pdf_part_marker():
    from riskminer.llm.backends.base import render_text
    assert render_text([PdfFile(7, "/x.pdf")]) == '<pdf doc="7"/>'
