"""`chat`: report chat (1.2 "Zapytaj o tę analizę") and project chat (2.3), docs/impl/llm.md §2.4.

The model sees a fact sheet built by code (never raw tables). Code decides the label: every number in the answer must
occur in a cited fact (or the question), else one repair retry, then the template no_data answer. Role "obliczenie" only
when the model said calc and every cited fact is calc."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from riskminer.llm import gateway
from riskminer.llm.backends.base import Json, Text
from riskminer.llm.errors import InvalidOutput, LLMError
from riskminer.llm.gateway import LLMRequest, LLMResult
from riskminer.llm.sanitize import copy_rules
from riskminer.llm.schemas import ChatAnswer
from riskminer.llm.verify import numbers_in_text

ROLE_LABEL = {"calc": "obliczenie", "ai": "wniosek AI", "no_data": "brak danych"}
NO_DATA_TEXT = "Nie odpowiem rzetelnie z danych tej analizy."
LABEL_KEYS = ("question", "title", "label", "name", "key", "metric", "rule")
TEXT_KEYS = ("sentence", "text", "plain", "why", "answer", "summary")
MAX_FACTS = 120


@dataclass
class Fact:
    id: str
    text: str
    role: str
    n: int | None = None
    refs: list[dict] = field(default_factory=list)
    number: dict | None = None        # the Num object when the fact is a number

    def prompt(self) -> dict:
        return {"id": self.id, "rola": self.role, "tekst": self.text, **({"n": self.n} if self.n else {})}


def _role(prov: dict | None, default: str = "calc") -> str:
    return (prov or {}).get("role") or default


def facts_from(obj: Any, *, public: bool = False) -> list[Fact]:
    """Walk a report / card JSON and turn every Num (display + prov) and every labelled sentence into a fact.
    `public` drops AI items not approved/edited."""
    out: list[Fact] = []
    seen: set[str] = set()

    def add(text: str, prov: dict | None, number: dict | None = None):
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text in seen or len(out) >= MAX_FACTS:
            return
        if public and _role(prov) == "ai" and (prov or {}).get("review_status") not in ("approved", "edited"):
            return
        seen.add(text)
        out.append(Fact(id=f"F{len(out) + 1}", text=text[:400], role=_role(prov), n=(prov or {}).get("n"),
                        refs=list((prov or {}).get("refs") or [])[:3], number=number))

    def walk(o: Any, ctx: list[str], prov: dict | None):
        if isinstance(o, dict):
            p = o.get("prov") if isinstance(o.get("prov"), dict) else prov
            label = next((str(o[k]) for k in LABEL_KEYS if isinstance(o.get(k), str) and o.get(k)), None)
            c = ctx + ([label] if label else [])
            if "display" in o and isinstance(o.get("prov"), dict):
                add(f"{' / '.join(c[-2:])}: {o['display']}" if c else str(o["display"]), o["prov"], o)
            for k in TEXT_KEYS:
                v = o.get(k)
                if isinstance(v, str) and len(v) > 3 and v != label:
                    add(f"{' / '.join(c[-2:])}: {v}" if c else v, p)
            for k, v in o.items():
                if k in ("prov", "refs", "options", "contributions", "points", "pages"):
                    continue
                if isinstance(v, (dict, list)):
                    walk(v, c, p)
        elif isinstance(o, list):
            for v in o[:40]:
                walk(v, ctx, prov)

    walk(obj, [], None)
    return out


def _numbers_ok(answer: str, cited: list[Fact], question: str) -> tuple[bool, list[float]]:
    allowed = set()
    for f in cited:
        allowed |= {round(x, 6) for x in numbers_in_text(f.text)}
        if f.number and isinstance(f.number.get("value"), (int, float)):
            v = float(f.number["value"])
            allowed |= {round(v, 6), round(v * 100, 6)}
        if f.n:
            allowed.add(float(f.n))
    allowed |= {round(x, 6) for x in numbers_in_text(question)}
    bad = [x for x in numbers_in_text(answer) if round(x, 6) not in allowed and not any(abs(x - a) <= abs(a) * 0.005 for a in allowed)]
    return not bad, bad


@dataclass
class ChatResult:
    answer: dict
    llm: LLMResult | None
    facts: list[Fact]


async def chat(question: str, facts: list[Fact], *, subject_label: str, sensitivity: str = "public",
               history: list[dict] | None = None, subject: str | None = None, input_refs: list[str] | None = None) -> ChatResult:
    parts = [Json([f.prompt() for f in facts], tag="fakty")]
    if history:
        parts.append(Json([{"rola": h.get("role"), "tekst": h.get("text")} for h in history[-6:]], tag="historia"))
    parts.append(Text(f"<pytanie>{question.strip()[:1000]}</pytanie>"))
    req = LLMRequest(task="chat", sensitivity=sensitivity, prompt="chat", parts=parts, output=ChatAnswer,  # type: ignore[arg-type]
                     prompt_vars={"subject_label": subject_label}, subject=subject, input_refs=input_refs or [],
                     max_output_tokens=1200)
    by_id = {f.id: f for f in facts}
    res: LLMResult | None = None
    data: ChatAnswer | None = None
    for attempt in range(2):
        try:
            res = await gateway.run(req)
        except InvalidOutput:
            # e.g. the answer kept non-Latin letters after the corrective retry: answer honestly instead of failing
            ans = _answer(NO_DATA_TEXT, "no_data", [], [], None, missing=["odpowiedź modelu nie przeszła sprawdzenia"])
            return ChatResult(ans, None, facts)
        data = res.data
        cited = [by_id[i] for i in data.fact_ids if i in by_id]
        ok, bad = _numbers_ok(data.answer, cited, question)
        if ok:
            break
        req.extra_user = (f"Twoja odpowiedź zawiera liczby, których nie ma w cytowanych faktach: "
                          f"{', '.join(str(b) for b in bad)}. Popraw odpowiedź: przepisz liczby tylko z faktów i podaj ich id.")
        data = None if attempt == 1 else data
    if data is None:
        ans = _answer(NO_DATA_TEXT, "no_data", [], [], res, missing=["odpowiedź modelu nie przeszła sprawdzenia liczb"])
        return ChatResult(ans, res, facts)
    cited = [by_id[i] for i in data.fact_ids if i in by_id]
    role = data.role
    if role != "no_data" and not cited:
        role = "no_data" if not data.apply else "ai"
    if role == "calc" and any(f.role != "calc" for f in cited):
        role = "ai"
    text = copy_rules(data.answer) or NO_DATA_TEXT
    ans = _answer(text, role, cited, data.follow_ups, res, missing=data.missing,
                  apply=data.apply.model_dump() if data.apply else None)
    return ChatResult(ans, res, facts)


def _answer(text: str, role: str, cited: list[Fact], follow_ups: list[str], res: LLMResult | None, *,
            missing: list[str] | None = None, apply: dict | None = None) -> dict:
    numbers = [f.number for f in cited if f.number and "prov" in f.number]
    sources = []
    for f in cited:
        sources += f.refs
    ns = [f.n for f in cited if f.n]
    return {"id": "", "code": None, "role": role, "role_label": ROLE_LABEL[role], "text": text, "bars": [],
            "numbers": numbers, "method": {"kind": "llm"}, "sources": sources[:10], "n": max(ns) if ns else None,
            "missing": [copy_rules(m) for m in (missing or [])],
            "actions": [{"kind": "ask", "label": copy_rules(q)} for q in follow_ups[:2]],
            "apply": apply, "processing": res.processing if res else None,
            "fact_ids": [f.id for f in cited]}


_ = json
