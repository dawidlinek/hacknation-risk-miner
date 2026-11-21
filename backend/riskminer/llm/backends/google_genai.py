"""Gemini through the google-genai SDK (Apache-2.0). Developer API now; Vertex EU is a config flag (vertexai: true).

Live-check gotchas (docs/impl/llm.md §0): flash needs thinking_level low; flash-lite rejects thinking_budget 0 (we send
no thinking config unless model_params asks); JSON via response_json_schema; batch payloads must use snake_case keys.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from riskminer.llm.backends.base import GenParams, PageText, PdfFile, RawResult, render_text
from riskminer.llm.config import ProviderCfg
from riskminer.llm.errors import BillingDepleted, LLMError, Transient
from riskminer.llm.sanitize import redact_secrets

_CLIENTS: dict[str, object] = {}


def _client(cfg: ProviderCfg):
    from google import genai

    c = _CLIENTS.get(cfg.id)
    if c is None:
        if cfg.vertexai:
            c = genai.Client(vertexai=True, project=cfg.project, location=cfg.location)
        else:
            key = cfg.api_key()
            if not key:
                raise LLMError(f"provider {cfg.id}: {cfg.api_key_env} not set")
            c = genai.Client(api_key=key)
        _CLIENTS[cfg.id] = c
    return c


class GoogleGenAIBackend:
    kind = "google_genai"

    def __init__(self, cfg: ProviderCfg):
        self.cfg = cfg

    def _contents(self, p: GenParams):
        from google.genai import types

        parts = []
        buf: list = []
        for part in p.parts:
            if isinstance(part, PdfFile):
                if buf:
                    parts.append(types.Part.from_text(text=render_text(buf)))
                    buf = []
                parts.append(types.Part.from_bytes(data=Path(part.path).read_bytes(), mime_type="application/pdf"))
            else:
                buf.append(part)
        if buf:
            parts.append(types.Part.from_text(text=render_text(buf)))
        return [types.Content(role="user", parts=parts)]

    def _config(self, p: GenParams):
        from google.genai import types

        kw: dict = {"system_instruction": p.system, "max_output_tokens": p.max_output_tokens}
        if p.schema is not None:
            kw["response_mime_type"] = "application/json"
            kw["response_json_schema"] = p.schema
        temp = p.temperature if p.temperature is not None else p.params.get("temperature")
        if temp is not None:
            kw["temperature"] = temp
        tl = p.params.get("thinking_level")
        if tl:
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=tl)
        if p.cached_content:
            kw["cached_content"] = p.cached_content
        return types.GenerateContentConfig(**kw)

    async def generate(self, p: GenParams) -> RawResult:
        from google.genai import errors

        client = _client(self.cfg)
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(model=p.model, contents=self._contents(p), config=self._config(p)),
                timeout=p.timeout_s)
        except TimeoutError as e:
            raise Transient(f"timeout after {p.timeout_s}s") from e
        except errors.APIError as e:
            msg = redact_secrets(f"{e.code} {getattr(e, 'message', '') or str(e)}")[:500]
            if e.code == 402:
                raise BillingDepleted(msg, http_status=402) from e
            if e.code in (429, 500, 502, 503, 504):
                raise Transient(msg, http_status=e.code) from e
            raise LLMError(msg, http_status=e.code) from e
        except Exception as e:  # network errors from httpx inside the SDK
            name = type(e).__name__
            if "Timeout" in name or "Connect" in name or "Network" in name or "Remote" in name:
                raise Transient(redact_secrets(f"{name}: {e}")[:500]) from e
            raise
        u = resp.usage_metadata
        text = resp.text or ""
        finish = None
        try:
            finish = str(resp.candidates[0].finish_reason) if resp.candidates else None
        except Exception:  # noqa: BLE001
            pass
        return RawResult(
            text=text,
            tokens_in=(u.prompt_token_count or 0) if u else 0,
            tokens_out=(u.candidates_token_count or 0) if u else 0,
            tokens_cached=(u.cached_content_token_count or 0) if u else 0,
            tokens_thought=(u.thoughts_token_count or 0) if u else 0,
            finish_reason=finish,
        )

    async def create_cache(self, model: str, system: str, parts: list, ttl_s: int = 600) -> str | None:
        """Explicit cache for a shared prefix (≥ 1,024 tokens). Returns the cache name or None when refused."""
        from google.genai import types

        client = _client(self.cfg)
        try:
            c = await client.aio.caches.create(model=model, config=types.CreateCachedContentConfig(
                system_instruction=system,
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=render_text(parts))])] if parts else None,
                ttl=f"{ttl_s}s"))
            return c.name
        except Exception:  # noqa: BLE001  (too small, model without caching ...): run uncached
            return None

    async def health(self) -> dict:
        t = time.perf_counter()
        if not self.cfg.configured:
            return {"status": "down", "error": "not_configured"}
        try:
            client = _client(self.cfg)
            models = []
            pager = await asyncio.wait_for(client.aio.models.list(config={"page_size": 50}), timeout=5)
            async for m in pager:
                models.append(m.name.removeprefix("models/"))
                if len(models) >= 50:
                    break
            return {"status": "up", "latency_ms": int((time.perf_counter() - t) * 1000), "models": models[:50]}
        except Exception as e:  # noqa: BLE001
            return {"status": "down", "error": redact_secrets(str(e))[:200]}


_ = PageText
