"""Zapytaj as an agent (riskminer/llm/agent.py): scripted model steps through the gateway, real tools, rolled back."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from riskminer.llm import agent as AG
from riskminer.llm import gateway


def _script(monkeypatch, steps: list[AG.AgentStep]):
    seen: list = []
    it = iter(steps)

    async def fake_run(req):
        seen.append(req)
        return SimpleNamespace(data=next(it), llm_call_id=None)

    monkeypatch.setattr(gateway, "run", fake_run)
    return seen


async def test_agent_explains_the_current_screen(client, monkeypatch):
    seen = _script(monkeypatch, [
        AG.AgentStep(thought="Sprawdzę, co jest na tym ekranie.", action="opis_aplikacji", action_input="/monitoring"),
        AG.AgentStep(thought="Mam opis ekranu.", action="final",
                     final_answer="Na mapie wybierasz region, filtrujesz podsektorem i latami, a sygnały pokazują umowy po terminie."),
    ])
    r = await client.post("/api/ask/agent", json={"question": "co mogę tu zrobić?", "route": "/monitoring"})
    assert r.status_code == 200, r.text
    j = r.json()
    kinds = [s["kind"] for s in j["steps"]]
    assert kinds == ["thinking", "tool", "thinking"]
    assert j["steps"][1]["tool"] == "opis_aplikacji" and "Monitoring" in j["steps"][1]["result"]
    assert j["answer"]["text"].startswith("Na mapie") and j["answer"]["id"].startswith("q")
    assert "<ekran>/monitoring</ekran>" in seen[0].parts[0].text and seen[0].prompt == "agent"
    assert "Monitoring" in seen[1].parts[0].text           # the tool result went back to the model


async def test_agent_uses_data_and_monitoring_tools(client, monkeypatch):
    from riskminer.llm.tasks import nl2sql as N

    async def fake_ask(q, subject=None):
        return SimpleNamespace(answer={"text": "30% umów po terminie.", "n": 11210,
                                       "sources": [{"kind": "query", "id": "q", "label": "n = 11 210"}]})

    monkeypatch.setattr(N, "ask", fake_ask)
    _script(monkeypatch, [
        AG.AgentStep(thought="Policzę odsetek.", action="dane", action_input="Ile umów skończyło się po terminie?"),
        AG.AgentStep(thought="Porównam regiony.", action="monitoring", action_input="wod-kan"),
        AG.AgentStep(thought="Odpowiadam.", action="final", final_answer="30% z 11 210 umów skończyło się po terminie."),
    ])
    j = (await client.post("/api/ask/agent", json={"question": "jak często są opóźnienia?"})).json()
    tools = [s["tool"] for s in j["steps"] if s["kind"] == "tool"]
    assert tools == ["dane", "monitoring"]
    assert "Sektor wod-kan" in j["steps"][3]["result"]
    assert any(s["label"] == "n = 11 210" for s in j["answer"]["sources"])


async def test_agent_forces_a_final_answer_after_the_tool_budget(client, monkeypatch):
    steps = [AG.AgentStep(thought=f"Krok {i}.", action="opis_aplikacji", action_input="całość") for i in range(4)]
    steps.append(AG.AgentStep(thought="Koniec.", action="opis_aplikacji", action_input="całość", final_answer="Gotowe."))
    seen = _script(monkeypatch, steps)
    j = (await client.post("/api/ask/agent", json={"question": "opowiedz o aplikacji"})).json()
    assert j["answer"]["text"] == "Gotowe." and len(seen) == 5 and seen[-1].extra_user


@pytest.mark.parametrize("q,want", [("/projekty/RM-2026-003", "Projekty"), ("całość", "ex ante"), ("", "ex ante")])
def test_guide_routes(q, want):
    assert want in AG.guide(q)
