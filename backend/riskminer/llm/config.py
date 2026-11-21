"""Typed view of the `llm:` block in config/config.example.yaml (docs/impl/llm.md §1.2) plus app_setting overrides."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field

from riskminer.config import REPO_ROOT, app_config

Sensitivity = Literal["public", "confidential"]


class ProviderCfg(BaseModel):
    id: str = ""
    kind: Literal["google_genai", "openai_compatible", "replay"]
    api_key_env: str | None = None
    base_url: str | None = None
    data_location: str = "unknown"
    sovereign: bool = False
    vertexai: bool = False
    project: str | None = None
    location: str | None = None
    dir: str | None = None
    local: bool = False              # local server without a key (Ollama on this machine)
    emergency: bool = False          # used only after a 402/429/5xx/timeout from the targets before it; public only
    extra_body: dict[str, Any] = {}  # merged into openai_compatible request bodies (e.g. OpenRouter provider prefs)

    @property
    def is_pl(self) -> bool:
        return self.sovereign and self.data_location.startswith("PL")

    @property
    def configured(self) -> bool:
        if self.kind == "replay" or (self.local and not self.api_key_env):
            return True
        return bool(self.api_key_env and os.environ.get(self.api_key_env) or _dotenv().get(self.api_key_env or ""))

    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env) or _dotenv().get(self.api_key_env)


class Price(BaseModel):
    in_: float = Field(0.0, alias="in")
    out: float = 0.0
    cached: float | None = None
    batch_in: float | None = None
    batch_out: float | None = None


class LLMConfig(BaseModel):
    providers: dict[str, ProviderCfg]
    models: dict[str, str]
    model_params: dict[str, dict[str, Any]] = {}
    tasks: dict[str, dict[str, str]] = {}
    fallback: dict[str, list[str]] = {}
    demo_replay_fallback: bool = False
    budget: dict[str, Any] = {"usd_per_day": 40, "usd_per_run": {}, "warn_at": 0.8}
    retries: dict[str, Any] = {"max_attempts": 3, "backoff_s": [1, 4, 15], "repair_on_invalid_json": 1}
    timeouts_s: dict[str, float] = {"interactive": 30, "document": 120, "batch_call": 300}
    concurrency: dict[str, int] = {}
    prices_usd_per_mtok: dict[str, Price] = {}
    eval: dict[str, Any] = {}

    def resolve(self, alias: str) -> tuple[ProviderCfg, str]:
        """alias -> (provider cfg, model name). Accepts a literal 'provider:model' too."""
        target = self.models.get(alias, alias)
        if ":" not in target:
            raise KeyError(f"unknown model alias {alias!r}")
        pid, model = target.split(":", 1)
        if pid not in self.providers:
            raise KeyError(f"unknown provider {pid!r} for alias {alias!r}")
        return self.providers[pid], model

    def price(self, model: str) -> Price:
        return self.prices_usd_per_mtok.get(model) or Price()


@lru_cache
def _dotenv() -> dict[str, str]:
    """Read .env without exporting it (pydantic-settings only maps known fields). Values never logged."""
    p = REPO_ROOT / ".env"
    out: dict[str, str] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


_OVERRIDES: dict[str, Any] = {}


def set_overrides(models: dict[str, str] | None = None, tasks: dict[str, dict[str, str]] | None = None) -> None:
    """Routing overrides from app_setting (Ustawienia). Validated by the caller (settings router)."""
    if models is not None:
        _OVERRIDES["models"] = dict(models)
    if tasks is not None:
        _OVERRIDES["tasks"] = {k: dict(v) for k, v in tasks.items()}
    llm_config.cache_clear()


@lru_cache
def llm_config() -> LLMConfig:
    raw = dict(app_config().get("llm") or {})
    provs = {k: {**v, "id": k} for k, v in (raw.get("providers") or {}).items()}
    raw["providers"] = provs
    if "models" in _OVERRIDES:
        raw["models"] = {**raw.get("models", {}), **_OVERRIDES["models"]}
    if "tasks" in _OVERRIDES:
        t = {k: dict(v) for k, v in (raw.get("tasks") or {}).items()}
        for task, m in _OVERRIDES["tasks"].items():
            t.setdefault(task, {}).update(m)
        raw["tasks"] = t
    return LLMConfig.model_validate(raw)


def fake_mode() -> bool:
    return os.environ.get("RISKMINER_LLM_FAKE", "") not in ("", "0", "false")


def record_mode() -> bool:
    return os.environ.get("RISKMINER_LLM_RECORD", "") not in ("", "0", "false")


def replay_dir() -> str:
    d = os.environ.get("RISKMINER_LLM_REPLAY_DIR")
    if d:
        return d
    cfg = llm_config().providers.get("replay")
    rel = (cfg.dir if cfg and cfg.dir else "backend/tests/fixtures/llm")
    return str(REPO_ROOT / rel)
