"""Known-answer test for a provider (docs/impl/llm.md §5.6), run WITHOUT response_format: schema-constrained decoding
produces valid JSON even from a broken server. Calls the backend directly (routing would refuse an untested sovereign
provider). Pass → routing.mark_health(..., kat_passed=True)."""
from __future__ import annotations

import json
import re
import time

from riskminer.llm import calllog
from riskminer.llm.backends.base import GenParams, Text
from riskminer.llm.config import llm_config
from riskminer.llm.routing import mark_health

CHECKS = [
    ("Jaka jest stolica Polski? Odpowiedz jednym słowem.", lambda t: bool(re.search(r"warszaw", t, re.I))),
    ("Ile to 17 razy 3? Podaj tylko liczbę.", lambda t: re.sub(r"\D", "", t) == "51"),
    ('Przyczyna zmiany umowy: "Termin wydłużono z powodu intensywnych opadów deszczu, które uniemożliwiły prowadzenie '
     'robót ziemnych." Który kod: R16 (pogoda), R02 (grunt), R07 (roboty dodatkowe)? Odpowiedz wyłącznie JSON-em '
     '{"code": "..."}.', lambda t: _code(t) in ("R16", "N-WEATHER")),
]


def _code(t: str) -> str | None:
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        return str(json.loads(m.group()).get("code", "")).upper()
    except ValueError:
        return None


async def run_kat(provider_id: str, model: str | None = None) -> dict:
    from riskminer.llm.gateway import backend_for

    cfg = llm_config()
    p = cfg.providers[provider_id]
    if model is None:
        model = next((m.split(":", 1)[1] for m in cfg.models.values() if m.startswith(provider_id + ":")), None)
    be = backend_for(p)
    health = await be.health()
    out = {"id": provider_id, "model": model, "status": health.get("status"), "latency_ms": health.get("latency_ms"),
           "models": health.get("models", []), "kat": []}
    if health.get("status") != "up" or not model:
        mark_health(provider_id, {**health, "kat_passed": False})
        out["kat_passed"] = False
        return out
    ok_all = True
    for prompt, check in CHECKS:
        t0 = time.perf_counter()
        try:
            r = await be.generate(GenParams(model=model, system="Odpowiadaj krótko po polsku.", parts=[Text(prompt)],
                                            max_output_tokens=64, params=dict(cfg.model_params.get(model, {})), timeout_s=30))
            ok = check(r.text) and (r.finish_reason in (None, "stop", "STOP", "FinishReason.STOP")) and r.tokens_out < 64
            text, err = r.text, None
        except Exception as e:  # noqa: BLE001
            ok, text, err, r = False, "", str(e)[:200], None
        ok_all &= ok
        out["kat"].append({"prompt": prompt[:60], "answer": text[:80], "ok": ok})
        await calllog.log_call({"task": "kat", "provider": provider_id, "model": model, "alias": None,
                                "data_location": p.data_location, "sensitivity": "public",
                                "tokens_in": r.tokens_in if r else None, "tokens_out": r.tokens_out if r else None,
                                "cost_usd": 0.0, "latency_ms": int((time.perf_counter() - t0) * 1000),
                                "status": "ok" if ok else "error", "error": err, "request": {"parts": prompt},
                                "response": {"text": text}, "prompt_version": "kat@v1", "attempt": 1})
    mark_health(provider_id, {**health, "kat_passed": ok_all})
    out["kat_passed"] = ok_all
    return out
