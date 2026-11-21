"""OpenAI-compatible chat completions over httpx (vLLM serving Bielik/PLLuM on WCSS; Gemini /v1beta/openai as a
no-lock-in demo). Plain REST keeps the dependency list short; the protocol is the same as the openai SDK's."""
from __future__ import annotations

import time

import httpx

from riskminer.llm.backends.base import GenParams, PdfFile, RawResult, render_text
from riskminer.llm.config import ProviderCfg
from riskminer.llm.errors import BillingDepleted, LLMError, Transient
from riskminer.llm.sanitize import redact_secrets


class OpenAICompatBackend:
    kind = "openai_compatible"

    def __init__(self, cfg: ProviderCfg):
        self.cfg = cfg
        self.base = (cfg.base_url or "").rstrip("/")

    def _headers(self) -> dict:
        key = self.cfg.api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def generate(self, p: GenParams) -> RawResult:
        if any(isinstance(x, PdfFile) for x in p.parts):
            raise LLMError("openai_compatible backends take page text only, not PDF parts")
        body: dict = {
            "model": p.model,
            "messages": [{"role": "system", "content": p.system}, {"role": "user", "content": render_text(p.parts)}],
            "max_tokens": min(p.max_output_tokens, int(p.params.get("max_tokens", p.max_output_tokens))),
        }
        temp = p.temperature if p.temperature is not None else p.params.get("temperature")
        if temp is not None:
            body["temperature"] = temp
        if p.params.get("reasoning_effort"):
            body["reasoning_effort"] = p.params["reasoning_effort"]
        for k, v in {**(self.cfg.extra_body or {}), **(p.params.get("extra_body") or {})}.items():
            body[k] = v
        if p.schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": p.schema, "strict": False}}
        try:
            async with httpx.AsyncClient(timeout=p.timeout_s) as c:
                r = await c.post(f"{self.base}/chat/completions", json=body, headers=self._headers())
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise Transient(f"{type(e).__name__}") from e
        if r.status_code == 402:
            raise BillingDepleted(redact_secrets(f"http 402 {r.text[:200]}"), http_status=402)
        if r.status_code in (429, 500, 502, 503, 504):
            raise Transient(redact_secrets(f"http {r.status_code} {r.text[:300]}"), http_status=r.status_code)
        if r.status_code >= 400:
            raise LLMError(redact_secrets(f"http {r.status_code} {r.text[:300]}"), http_status=r.status_code)
        d = r.json()
        ch = (d.get("choices") or [{}])[0]
        u = d.get("usage") or {}
        details = u.get("completion_tokens_details") or {}
        pdet = u.get("prompt_tokens_details") or {}
        return RawResult(text=(ch.get("message") or {}).get("content") or "",
                         tokens_in=u.get("prompt_tokens") or 0, tokens_out=u.get("completion_tokens") or 0,
                         tokens_cached=pdet.get("cached_tokens") or 0, tokens_thought=details.get("reasoning_tokens") or 0,
                         finish_reason=ch.get("finish_reason"),
                         cost_usd=float(u["cost"]) if isinstance(u.get("cost"), (int, float)) else None)

    async def health(self) -> dict:
        if not self.cfg.configured:
            return {"status": "down", "error": "not_configured"}
        t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{self.base}/models", headers=self._headers())
            if r.status_code != 200:
                return {"status": "down", "error": f"http {r.status_code}"}
            models = [m.get("id") for m in (r.json().get("data") or [])][:50]
            return {"status": "up", "latency_ms": int((time.perf_counter() - t) * 1000), "models": models}
        except Exception as e:  # noqa: BLE001
            return {"status": "down", "error": type(e).__name__}


_ = time
