"""OpenRouter emergency fallback: used for public data only, and only after Gemini answers 402/429/5xx."""
import json

import pytest

from riskminer.llm import calllog, gateway, routing
from riskminer.llm.backends.base import RawResult, Text
from riskminer.llm.errors import BillingDepleted, InvalidOutput, SovereignUnavailable
from riskminer.llm.gateway import LLMRequest

pytestmark = pytest.mark.unit


class FakeBackend:
    def __init__(self, pid, mode):
        self.pid, self.mode = pid, mode

    async def generate(self, p):
        if self.pid == "gemini":
            if self.mode == "402":
                raise BillingDepleted("402 credits depleted", http_status=402)
            return RawResult(text="to nie json", tokens_in=1, tokens_out=1)
        return RawResult(text='{"chips": [], "rows": [], "missing": ["budzet"]}', tokens_in=10, tokens_out=5, cost_usd=0.0001)


@pytest.fixture
def live(monkeypatch):
    """Leave fake mode for these tests; every backend is replaced, so nothing reaches the network."""
    monkeypatch.delenv("RISKMINER_LLM_FAKE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RISKMINER_LLM_REPLAY_FALLBACK", "0")
    from riskminer.llm import config as C
    monkeypatch.setattr(C.llm_config(), "demo_replay_fallback", False)

    def use(mode):
        monkeypatch.setattr(gateway, "backend_for", lambda p: FakeBackend(p.id, mode))
    return use


def _req(sens="public"):
    from riskminer.llm.schemas import Features
    return LLMRequest(task="extract_features", sensitivity=sens, prompt="extract_features", parts=[Text("opis")],
                      output=Features)


async def test_402_falls_back_to_openrouter_for_public(live):
    live("402")
    res = await gateway.run(_req())
    assert res.provider == "openrouter" and res.data.missing == ["budzet"]
    assert res.data_location.startswith("global (OpenRouter")
    rows = [(r["provider"], r["status"]) for r in calllog.MEMORY]
    assert ("gemini", "error") in rows and rows[-1] == ("openrouter", "ok")
    assert calllog.MEMORY[-1]["cost_usd"] == 0.0001 and calllog.MEMORY[-1]["fallback_from"] == "fast"


async def test_invalid_json_does_not_use_emergency(live):
    live("bad_json")
    with pytest.raises(InvalidOutput):
        await gateway.run(_req())
    assert not [r for r in calllog.MEMORY if r["provider"] == "openrouter"]


async def test_confidential_never_reaches_openrouter(live):
    live("402")
    with pytest.raises(SovereignUnavailable):
        await gateway.run(_req("confidential"))
    assert not [r for r in calllog.MEMORY if r["provider"] in ("openrouter", "gemini")]
    conf = routing.route("extract_features", "confidential", check_health=False)
    assert conf and all(t.provider.is_pl for t in conf) and "openrouter" not in [t.provider.id for t in conf]
    assert "openrouter" in [t.provider.id for t in routing.route("extract_features", "public", check_health=False)]


# ---- sovereign chain: wcss_bielik -> wcss_pllum -> hn_bielik -> hn_pllum -> local_bielik, never the cloud ------------
class ChainBackend:
    def __init__(self, pid, failing):
        self.pid, self.failing = pid, failing

    async def generate(self, p):
        from riskminer.llm.errors import Transient
        if self.pid in self.failing:
            raise Transient(f"{self.pid} down")
        if self.pid in ("gemini", "openrouter"):
            raise AssertionError("confidential data reached a cloud provider")
        return RawResult(text='{"chips": [], "rows": [], "missing": []}', tokens_in=5, tokens_out=3)


@pytest.fixture
def sovereign(monkeypatch, live):
    from riskminer.llm import config as C
    monkeypatch.setenv("WCSS_VLLM_KEY", "k")
    monkeypatch.setenv("HN_VLLM_KEY", "k")
    monkeypatch.setitem(C.llm_config().retries, "max_attempts", 1)

    async def no_kat(cfg):
        return None
    monkeypatch.setattr(gateway, "ensure_sovereign_health", no_kat)

    def setup(up: set[str], failing: set[str] = frozenset()):
        for pid in ("wcss_bielik", "wcss_pllum", "hn_bielik", "hn_pllum", "local_bielik"):
            routing.mark_health(pid, {"status": "up" if pid in up else "down", "kat_passed": pid in up})
        monkeypatch.setattr(gateway, "backend_for", lambda p: ChainBackend(p.id, failing))
    return setup


async def test_local_bielik_is_the_floor(sovereign):
    sovereign(up={"local_bielik"})
    res = await gateway.run(_req("confidential"))
    assert res.provider == "local_bielik" and res.data_location == "PL (serwer lokalny)"
    assert calllog.MEMORY[-1]["provider"] == "local_bielik" and calllog.MEMORY[-1]["sensitivity"] == "confidential"


async def test_sovereign_hops_in_order_on_failure(sovereign):
    sovereign(up={"wcss_bielik", "hn_bielik", "local_bielik"}, failing={"wcss_bielik"})
    res = await gateway.run(_req("confidential"))
    assert res.provider == "hn_bielik" and res.data_location.startswith("PL (WCSS")
    assert [r["provider"] for r in calllog.MEMORY] == ["wcss_bielik", "hn_bielik"]


async def test_all_sovereign_down_is_503_never_cloud(sovereign):
    sovereign(up=set())
    with pytest.raises(SovereignUnavailable):
        await gateway.run(_req("confidential"))
    sovereign(up={"wcss_bielik"}, failing={"wcss_bielik"})
    with pytest.raises(SovereignUnavailable):
        await gateway.run(_req("confidential"))
    assert not [r for r in calllog.MEMORY if r["provider"] in ("gemini", "openrouter")]


async def test_non_latin_answer_is_retried_once(live, monkeypatch):
    calls = []

    class ScriptBackend:
        async def generate(self, p):
            calls.append(p.parts[-1].text if p.parts else "")
            bad = len(calls) == 1
            chip = {"key": "podsektor", "value_code": "SAN", "value_text": "kanalizacja" if not bad else "канализация",
                    "source": "opis", "quote": "opis"}
            return RawResult(text=json.dumps({"chips": [chip], "rows": [], "missing": []}), tokens_in=5, tokens_out=5)
    monkeypatch.setattr(gateway, "backend_for", lambda p: ScriptBackend())
    res = await gateway.run(_req())
    assert len(calls) == 2 and "alfabetu łacińskiego" in calls[1]
    assert res.data.chips[0].value_text == "kanalizacja"
    assert [r["status"] for r in calllog.MEMORY] == ["invalid", "ok"]
    assert calllog.MEMORY[0]["error"].startswith("non_latin_script")
