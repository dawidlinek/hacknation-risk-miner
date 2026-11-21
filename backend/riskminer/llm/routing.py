"""Sensitivity routing (docs/impl/llm.md §1.3). Confidential input never reaches a provider without
`sovereign: true` and a PL data location, including through fallback, replay or the PDF part."""
from __future__ import annotations

import time
from dataclasses import dataclass

from riskminer.llm.config import LLMConfig, ProviderCfg, Sensitivity, fake_mode, llm_config
from riskminer.llm.errors import ProviderDown, RefusedForSensitivity, SovereignUnavailable

_RANK = {"public": 0, "confidential": 1}


@dataclass
class Target:
    alias: str
    provider: ProviderCfg
    model: str
    fallback_from: str | None = None

    @property
    def processing(self) -> dict:
        return {"provider": self.provider.id, "model": self.model, "data_location": self.provider.data_location}


def max_sensitivity(*vals: str | None) -> Sensitivity:
    best = "public"
    for v in vals:
        if v and _RANK.get(v, 1) > _RANK[best]:      # unknown labels count as confidential
            best = "confidential"
    return best  # type: ignore[return-value]


# health cache: provider id -> (checked_at, status dict)
HEALTH: dict[str, tuple[float, dict]] = {}
HEALTH_TTL_S = 30.0


def health_ok(p: ProviderCfg) -> bool:
    """Synchronous view used by routing. google_genai: configured. openai_compatible: configured and the last ping
    (refreshed by `refresh_health`) said up; a sovereign provider also needs a passed known-answer test."""
    if p.kind == "replay":
        return True
    if not p.configured:
        return False
    if p.kind == "google_genai" or (p.emergency and not p.sovereign):
        return True           # hosted APIs: usable when a key is set; failures are handled per call
    hit = HEALTH.get(p.id)
    if not hit:
        return False
    st = hit[1]
    if st.get("status") != "up":
        return False
    return not (p.sovereign and not st.get("kat_passed"))


def mark_health(pid: str, status: dict) -> None:
    HEALTH[pid] = (time.time(), status)


def route(task: str, sensitivity: Sensitivity, alias: str | None = None, *, has_pdf: bool = False,
          cfg: LLMConfig | None = None, check_health: bool = True) -> list[Target]:
    cfg = cfg or llm_config()
    if alias is None:
        per = cfg.tasks.get(task) or cfg.tasks.get("default") or {}
        alias = per.get(sensitivity)
        if alias is None:
            if sensitivity == "confidential":
                raise RefusedForSensitivity(f"task {task} has no confidential route")
            alias = "strong"
    chain = [alias] + [a for a in cfg.fallback.get(alias, []) if a != alias]
    targets: list[Target] = []
    prev = None
    for a in chain:
        try:
            prov, model = cfg.resolve(a)
        except KeyError:
            continue
        targets.append(Target(alias=a, provider=prov, model=model, fallback_from=prev))
        prev = a
    if sensitivity == "confidential":
        targets = [t for t in targets if t.provider.is_pl]
        if has_pdf:
            raise RefusedForSensitivity("PDF parts are not sent for confidential documents; use page text")
        if not targets:
            raise SovereignUnavailable()
    if check_health and not fake_mode():
        up = [t for t in targets if health_ok(t.provider)]
        if not up:
            if sensitivity == "confidential":
                raise SovereignUnavailable()
            raise ProviderDown(f"no healthy provider for {task}/{alias}")
        targets = up
    elif check_health and fake_mode() and sensitivity == "confidential":
        # fake mode keeps the sovereign rule observable: without a configured sovereign provider, 503
        if not any(t.provider.configured and HEALTH.get(t.provider.id, (0, {}))[1].get("kat_passed") for t in targets):
            raise SovereignUnavailable()
    return targets
