"""One entry point for every model call (docs/impl/llm.md §1): route by sensitivity → call → validate → log.

    res = await run(LLMRequest(task="extract_features", sensitivity="public", prompt="extract_features",
                               parts=[Text(desc)], output=Features, subject="analysis:AN-2026-0014"))
    res.data        # validated Pydantic object
    res.processing  # {provider, model, data_location} for the "przetworzono w ..." badge

Retries: Transient (429/5xx/timeout) with backoff; invalid JSON or schema errors get one repair retry with the
validation error appended. After retries the next alias in `llm.fallback`. Every backend attempt is one llm_call row.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from riskminer.llm import calllog, prompts
from riskminer.llm.backends import replay
from riskminer.llm.backends.base import GenParams, Part, PdfFile, RawResult, Text, render_text
from riskminer.llm.config import LLMConfig, ProviderCfg, Sensitivity, fake_mode, llm_config, record_mode
from riskminer.llm.errors import (BillingDepleted, BudgetExceeded, InvalidOutput, LLMError, ProviderDown, ReplayMiss,
                                  SovereignUnavailable, Transient)
from riskminer.llm.routing import Target, max_sensitivity, route
from riskminer.llm.sanitize import drop_script_violations, script_violations


@dataclass
class LLMRequest:
    task: str
    sensitivity: Sensitivity
    prompt: str                                   # prompt file name in llm/prompts
    parts: list[Part]
    output: type[BaseModel] | None = None
    prompt_vars: dict[str, Any] = field(default_factory=dict)
    input_refs: list[str] = field(default_factory=list)   # "document:30011", "analysis:AN-2026-0014"
    subject: str | None = None
    alias: str | None = None
    max_output_tokens: int = 8192
    temperature: float | None = None
    timeout_kind: str = "interactive"            # interactive | document | batch_call
    run_budget_key: str | None = None            # e.g. "classify_causes" → llm.budget.usd_per_run
    extra_user: str | None = None                # appended instruction (repair / re-quote)


@dataclass
class LLMResult:
    data: Any
    text: str
    llm_call_id: int | None
    provider: str
    model: str
    alias: str
    data_location: str
    prompt_version: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cached: int = 0
    tokens_thought: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    fallback_from: str | None = None
    replayed: bool = False
    sensitivity: str = "public"

    @property
    def processing(self) -> dict:
        p = {"provider": self.provider, "model": self.model, "data_location": self.data_location}
        if self.replayed:
            p["note"] = "odtworzenie nagranej odpowiedzi"
        return p

    @property
    def llm_info(self) -> dict:
        """`Prov.llm` in the API contract."""
        return {**self.processing, "llm_call_id": self.llm_call_id}


_BACKENDS: dict[str, Any] = {}
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def backend_for(p: ProviderCfg):
    b = _BACKENDS.get(p.id)
    if b is None:
        if p.kind == "google_genai":
            from riskminer.llm.backends.google_genai import GoogleGenAIBackend
            b = GoogleGenAIBackend(p)
        elif p.kind == "openai_compatible":
            from riskminer.llm.backends.openai_compat import OpenAICompatBackend
            b = OpenAICompatBackend(p)
        else:
            raise LLMError(f"backend kind {p.kind} has no live implementation")
        _BACKENDS[p.id] = b
    return b


def _sem(pid: str, cfg: LLMConfig) -> asyncio.Semaphore:
    s = _SEMAPHORES.get(pid)
    if s is None:
        s = _SEMAPHORES[pid] = asyncio.Semaphore(int(cfg.concurrency.get(pid, 8)))
    return s


def schema_of(model: type[BaseModel] | None) -> dict | None:
    return model.model_json_schema() if model is not None else None


def request_hash(provider: str, model: str, prompt_version: str, system: str, rendered: str, schema: dict | None,
                 params: dict) -> str:
    blob = json.dumps({"provider": provider, "model": model, "prompt": prompt_version, "system": system,
                       "parts": rendered, "schema": schema, "params": params}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


async def effective_sensitivity(req: LLMRequest) -> Sensitivity:
    """The caller cannot downgrade: sensitivity of referenced documents/analyses wins."""
    labels: list[str | None] = [req.sensitivity]
    doc_ids = [int(r.split(":", 1)[1]) for r in req.input_refs if r.startswith("document:") and r.split(":", 1)[1].isdigit()]
    an_codes = [r.split(":", 1)[1] for r in req.input_refs if r.startswith("analysis:")]
    if doc_ids or an_codes:
        try:
            labels += await _ref_labels(doc_ids, an_codes)
        except Exception:  # noqa: BLE001  fail closed: unknown sensitivity counts as confidential
            labels.append("confidential")
    return max_sensitivity(*labels)


async def _ref_labels(doc_ids: list[int], an_codes: list[str]) -> list[str | None]:
    from riskminer.db.session import raw_conn
    out: list[str | None] = []
    async with raw_conn() as conn:
        if doc_ids:
            rows = await conn.fetch("SELECT sensitivity FROM document WHERE id = ANY($1::bigint[])", doc_ids)
            out += [r["sensitivity"] for r in rows]
            if len(rows) < len(set(doc_ids)):
                out.append("confidential")
        if an_codes:
            out += [r["sensitivity"] for r in await conn.fetch(
                "SELECT sensitivity FROM analysis WHERE code = ANY($1::text[])", an_codes)]
    return out


def _parse(text: str, output: type[BaseModel] | None) -> Any:
    if output is None:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    if not t.startswith("{") and "{" in t:
        t = t[t.find("{"): t.rfind("}") + 1]
    return output.model_validate_json(t)


async def _budget_check(req: LLMRequest, cfg: LLMConfig, est: float) -> None:
    b = cfg.budget or {}
    cap = float(b.get("usd_per_day", 40))
    spent = await calllog.spent_today()
    if spent + est > cap:
        raise BudgetExceeded(f"daily budget {cap} USD reached ({spent:.2f} spent)")
    if req.run_budget_key and req.subject:
        run_cap = (b.get("usd_per_run") or {}).get(req.run_budget_key)
        if run_cap is not None:
            prefix = req.subject.rsplit(":", 1)[0] if req.subject.count(":") >= 2 else req.subject
            if await calllog.spent_run(prefix) + est > float(run_cap):
                raise BudgetExceeded(f"run budget {run_cap} USD reached for {prefix}")


def _estimate(cfg: LLMConfig, model: str, rendered_len: int, max_out: int) -> float:
    tin = rendered_len / 3.2
    return calllog.cost_usd(cfg, model, int(tin), min(max_out, 2000))


async def _call_once(t: Target, gp: GenParams, req: LLMRequest, sens: str, ph: str, rendered: str,
                     prompt_version: str) -> RawResult:
    if fake_mode():
        return replay.load(req.task, ph, rendered)
    cfg = llm_config()
    async with _sem(t.provider.id, cfg):
        res = await backend_for(t.provider).generate(gp)
    if record_mode():
        replay.save(req.task, ph, {"task": req.task, "provider": t.provider.id, "model": t.model,
                                   "prompt_version": prompt_version, "sensitivity": sens}, res)
    return res


_overrides_loaded = False


async def _ensure_overrides() -> None:
    """Routing overrides saved in Ustawienia (app_setting 'llm.routing'), loaded once per process; best-effort."""
    global _overrides_loaded
    if _overrides_loaded or calllog.sink() != "db":
        _overrides_loaded = True
        return
    _overrides_loaded = True
    try:
        from riskminer.db.session import raw_conn
        from riskminer.llm.config import set_overrides
        async with raw_conn() as conn:
            v = await conn.fetchval("SELECT value FROM app_setting WHERE key = 'llm.routing'")
        if v:
            set_overrides(v.get("models") or {}, v.get("tasks") or {})
    except Exception:  # noqa: BLE001
        pass


SOVEREIGN_KAT_TTL_S = 60


async def ensure_sovereign_health(cfg: LLMConfig) -> None:
    """Health lives in process memory; before confidential work, (re)run the known-answer test for configured sovereign
    providers whose last check is missing or older than 60 s, all in parallel. A failure leaves the hop down; with every
    hop down the call ends in SovereignUnavailable (503), never in a cloud provider."""
    import time as _t

    from riskminer.llm import routing
    from riskminer.llm.eval.kat import run_kat
    async def check(pid: str) -> None:
        try:
            await run_kat(pid)
        except Exception as e:  # noqa: BLE001
            routing.mark_health(pid, {"status": "down", "error": type(e).__name__, "kat_passed": False})

    due = []
    for pid, p in cfg.providers.items():
        if not (p.is_pl and p.configured and p.kind == "openai_compatible"):
            continue
        hit = routing.HEALTH.get(pid)
        if not hit or _t.time() - hit[0] >= SOVEREIGN_KAT_TTL_S:
            due.append(pid)
    if due:
        await asyncio.gather(*(check(pid) for pid in due))


async def run(req: LLMRequest) -> LLMResult:
    await _ensure_overrides()
    cfg = llm_config()
    sens = await effective_sensitivity(req)
    if sens == "confidential" and not fake_mode():
        await ensure_sovereign_health(cfg)
    has_pdf = any(isinstance(p, PdfFile) for p in req.parts)
    targets = route(req.task, sens, req.alias, has_pdf=has_pdf, cfg=cfg)
    pr = prompts.load(req.prompt)
    system = pr.render(**req.prompt_vars)
    schema = schema_of(req.output)
    retries = cfg.retries or {}
    max_attempts = int(retries.get("max_attempts", 3))
    backoff = list(retries.get("backoff_s", [1, 4, 15]))
    repairs_left = int(retries.get("repair_on_invalid_json", 1))
    script_retry_left = True
    timeout = float(cfg.timeouts_s.get(req.timeout_kind, 60))
    attempt = 0
    first: tuple[Target, str, str] | None = None
    last_err: Exception | None = None
    extra_user = req.extra_user
    for t in targets:
        if t.provider.emergency and t.fallback_from and not isinstance(last_err, (Transient, BillingDepleted)):
            continue                                   # emergency providers only after 402/429/5xx/timeout
        params = dict(cfg.model_params.get(t.model, {}))
        n_transient = 0
        while True:
            attempt += 1
            parts = list(req.parts) + ([Text(extra_user)] if extra_user else [])
            rendered = render_text(parts)
            ph = request_hash(t.provider.id, t.model, pr.ref, system, rendered, schema, params)
            if first is None and sens == "public":
                first = (t, ph, rendered)
            if not fake_mode():
                await _budget_check(req, cfg, _estimate(cfg, t.model, len(system) + len(rendered), req.max_output_tokens))
            gp = GenParams(model=t.model, system=system, parts=parts, schema=schema, max_output_tokens=req.max_output_tokens,
                           temperature=req.temperature, params=params, timeout_s=timeout)
            t0 = time.perf_counter()
            status, err, raw = "ok", None, None
            try:
                raw = await _call_once(t, gp, req, sens, ph, rendered, pr.ref)
            except ReplayMiss:
                raise
            except Transient as e:
                status, err, last_err = "retry", str(e), e
            except LLMError as e:
                status, err, last_err = "error", str(e), e
            latency = int((time.perf_counter() - t0) * 1000)
            data, verr, script_note = None, None, None
            if raw is not None:
                try:
                    data = _parse(raw.text, req.output)
                except (ValidationError, ValueError) as e:
                    verr = e
                    status, err = "invalid", f"{type(e).__name__}: {str(e)[:800]}"
            if data is not None and isinstance(data, BaseModel):
                viol = script_violations(data.model_dump())
                if viol:
                    letters = "".join(dict.fromkeys("".join(b for _, b in viol)))
                    if script_retry_left and not fake_mode():
                        script_retry_left = False
                        status, err = "invalid", f"non_latin_script: {letters} in {', '.join(p for p, _ in viol[:5])}"
                        verr = ValueError(err)
                        data = None
                    else:
                        cleaned, n_drop, top_left = drop_script_violations(data.model_dump())
                        if top_left:
                            status, err, data = "invalid", f"non_latin_script after retry: {letters}", None
                            verr = ValueError(err)
                        else:
                            data = req.output.model_validate(cleaned)
                            script_note = f"dropped {n_drop} item(s) with non-Latin letters: {letters}"
            cost = 0.0
            if raw and not raw.replayed:
                cost = raw.cost_usd if raw.cost_usd is not None else calllog.cost_usd(
                    cfg, t.model, raw.tokens_in, raw.tokens_out, raw.tokens_cached, raw.tokens_thought)
            calllog.add_spent(cost)
            call_id = await calllog.log_call({
                "task": req.task, "provider": t.provider.id if not (raw and raw.replayed) else f"{t.provider.id}+replay",
                "model": t.model, "alias": t.alias, "data_location": t.provider.data_location, "sensitivity": sens,
                "request_hash": ph, "tokens_in": raw.tokens_in if raw else None, "tokens_out": raw.tokens_out if raw else None,
                "tokens_cached": raw.tokens_cached if raw else None, "tokens_thought": raw.tokens_thought if raw else None,
                "cost_usd": cost, "latency_ms": latency, "status": status, "error": err or script_note,
                "request": {"system_sha": hashlib.sha256(system.encode()).hexdigest()[:16],
                            "parts": rendered if sens == "public" else f"[poufne, {len(rendered)} znaków]",
                            "pdf_docs": [str(p.doc_id) for p in parts if isinstance(p, PdfFile)]},
                "response": {"text": raw.text if raw else None, "finish_reason": raw.finish_reason if raw else None},
                "prompt_version": pr.ref, "attempt": attempt, "fallback_from": t.fallback_from, "subject": req.subject,
                "price_basis": "replay" if raw and raw.replayed else "standard"})
            if status == "ok":
                return LLMResult(data=data, text=raw.text, llm_call_id=call_id, provider=t.provider.id, model=t.model,
                                 alias=t.alias, data_location=t.provider.data_location, prompt_version=pr.ref,
                                 tokens_in=raw.tokens_in, tokens_out=raw.tokens_out, tokens_cached=raw.tokens_cached,
                                 tokens_thought=raw.tokens_thought, cost_usd=cost, latency_ms=latency, attempts=attempt,
                                 fallback_from=t.fallback_from, replayed=raw.replayed, sensitivity=sens)
            if status == "invalid":
                if err and err.startswith("non_latin_script:") and not fake_mode():
                    extra_user = ((req.extra_user + "\n") if req.extra_user else "") + (
                        "Poprzednia odpowiedź zawierała litery spoza alfabetu łacińskiego (" + err.split(":", 1)[1][:200] +
                        "). Pisz wyłącznie po polsku, alfabetem łacińskim z polskimi znakami. Zwróć całą odpowiedź ponownie.")
                    continue
                if repairs_left > 0 and not fake_mode():
                    repairs_left -= 1
                    extra_user = ((req.extra_user + "\n") if req.extra_user else "") + (
                        "Poprzednia odpowiedź nie przeszła walidacji schematu JSON. Błąd:\n" + str(verr)[:1500] +
                        "\nZwróć poprawny JSON zgodny ze schematem.")
                    continue
                last_err = InvalidOutput(err or "invalid output")
                break
            if status == "retry" and n_transient < max_attempts - 1:
                delay = backoff[min(n_transient, len(backoff) - 1)] * (0.8 + 0.4 * random.random())
                n_transient += 1
                await asyncio.sleep(delay)
                continue
            break                                    # hard error or retries used: next target
    if first is not None and replay_fallback_on(cfg) and not fake_mode():
        t, ph, rendered = first
        try:
            raw = replay.load(req.task, ph, rendered)
            data = _parse(raw.text, req.output)
            await calllog.log_call({"task": req.task, "provider": f"{t.provider.id}+replay", "model": t.model, "alias": t.alias,
                                    "data_location": "lokalnie (nagrane odpowiedzi)", "sensitivity": sens, "request_hash": ph,
                                    "cost_usd": 0.0, "latency_ms": 0, "status": "ok", "error": f"fallback after: {last_err}"[:300],
                                    "prompt_version": pr.ref, "attempt": attempt + 1, "fallback_from": t.alias,
                                    "subject": req.subject, "price_basis": "replay"})
            return LLMResult(data=data, text=raw.text, llm_call_id=None, provider=t.provider.id, model=t.model, alias=t.alias,
                             data_location=t.provider.data_location, prompt_version=pr.ref, attempts=attempt + 1,
                             fallback_from=t.alias, replayed=True, sensitivity=sens)
        except (ReplayMiss, ValidationError, ValueError):
            pass
    if isinstance(last_err, InvalidOutput):
        raise last_err
    if sens == "confidential":
        raise SovereignUnavailable(str(last_err) if last_err else "no sovereign hop answered")
    if isinstance(last_err, BillingDepleted):
        raise last_err
    raise ProviderDown(str(last_err) if last_err else "no target answered")


def replay_fallback_on(cfg: LLMConfig) -> bool:
    """Recorded answers as a last resort: llm.demo_replay_fallback or RISKMINER_LLM_REPLAY_FALLBACK=1.
    Never for confidential input (cassettes are recorded from public documents only)."""
    import os
    return bool(cfg.demo_replay_fallback) or os.environ.get("RISKMINER_LLM_REPLAY_FALLBACK", "") not in ("", "0", "false")


async def run_many(reqs: Sequence[LLMRequest], concurrency: int = 16) -> list[LLMResult | Exception]:
    """Online fan-out; per-provider semaphores still apply. Exceptions are returned in place, never raised."""
    sem = asyncio.Semaphore(concurrency)

    async def one(r: LLMRequest):
        async with sem:
            try:
                return await run(r)
            except Exception as e:  # noqa: BLE001
                return e

    return list(await asyncio.gather(*(one(r) for r in reqs)))
