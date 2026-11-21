"""Ustawienia: LLM routing and providers (api_contract §2.9, J14). Owner: L (LLM).
Keys are never returned, only `configured`. Confidential routes must stay on providers with a PL data location."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.api import auth as A
from riskminer.db.session import get_session
from riskminer.llm import config as C
from riskminer.llm import routing as RT

router = APIRouter(prefix="/api/settings", tags=["settings"])
DB = Depends(get_session)

TASK_LABELS: dict[str, tuple[str, str]] = {
    "extract_features": ("Cechy inwestycji z PFU i PPU", "dokumenty"),
    "extract_features_text": ("Cechy inwestycji z opisu", "opis użytkownika"),
    "redpen_scan": ("Czerwony długopis: uwagi w dokumentach", "dokumenty"),
    "classify_causes": ("Klasyfikacja przyczyn zmian umów", "dane publiczne BZP, ok. 16 tys. opisów"),
    "chat": ("Rozmowa o analizie i projekcie", "fakty z analizy"),
    "nl2sql": ("Zapytaj pamięć (pytanie na SQL)", "widoki tylko do odczytu"),
    "import_mapping": ("Agent importu: mapowanie kolumn", "nagłówki i próbki wierszy"),
    "catalogue_proposals": ("Propozycje do katalogu ryzyk", "dane publiczne"),
    "review_phrasing": ("Pytania w przeglądzie", "dane publiczne"),
    "rescore_gold": ("Przeliczenie po decyzji eksperta", "dane publiczne"),
}


class RoutingIn(BaseModel):
    models: dict[str, str] = Field(default_factory=dict)
    routing: dict[str, dict[str, Any]] = Field(default_factory=dict)   # {public|confidential: {task: alias}}


async def load_overrides(db: AsyncSession) -> dict:
    v = (await db.execute(text("SELECT value FROM app_setting WHERE key = 'llm.routing'"))).scalar()
    if v:
        C.set_overrides(v.get("models") or {}, v.get("tasks") or {})
    return v or {}


def _target(alias: str, cfg: C.LLMConfig) -> dict:
    try:
        p, m = cfg.resolve(alias)
    except KeyError:
        return {"alias": alias, "provider": None, "model": None, "data_location": None, "sovereign": False}
    return {"alias": alias, "provider": p.id, "model": m, "data_location": p.data_location, "sovereign": p.is_pl}


def _health(pid: str) -> dict:
    hit = RT.HEALTH.get(pid)
    if not hit:
        return {"status": "unknown", "checked_at": None, "latency_ms": None}
    ts, st = hit
    return {"status": st.get("status", "unknown"), "checked_at": datetime.fromtimestamp(ts, UTC).isoformat(),
            "latency_ms": st.get("latency_ms"), "kat_passed": st.get("kat_passed")}


async def _view(db: AsyncSession) -> dict:
    cfg = C.llm_config()
    tasks = []
    for task, per in cfg.tasks.items():
        if task == "kat":
            continue
        label, data_label = TASK_LABELS.get(task, (task, ""))
        for sens in ("public", "confidential"):
            if sens not in per:
                continue
            t = _target(per[sens], cfg)
            tasks.append({"task": task, "label": label, "data_label": ("dokumenty poufne" if sens == "confidential" else data_label),
                          "sensitivity": sens, **t, "enforced": sens == "confidential",
                          "fallback": cfg.fallback.get(per[sens], [])})
    providers = []
    for pid, p in cfg.providers.items():
        h = _health(pid)
        if p.kind == "google_genai" and h["status"] == "unknown" and p.configured:
            h = {**h, "status": "configured"}
        if p.kind == "replay":
            h = {**h, "status": "up" if C.fake_mode() else "standby"}
        providers.append({"id": pid, "kind": p.kind, "data_location": p.data_location, "configured": p.configured,
                          "sovereign": p.is_pl, "health": h})
    u = (await db.execute(text(
        "SELECT count(*) AS calls, coalesce(sum(tokens_in), 0) AS tin, coalesce(sum(tokens_out), 0) AS tout, "
        "coalesce(sum(cost_usd), 0) AS cost FROM llm_call WHERE created_at >= now() - interval '24 hours'"))).mappings().one()
    today = (await db.execute(text("SELECT coalesce(sum(cost_usd), 0) FROM llm_call WHERE created_at >= date_trunc('day', now())"))).scalar()
    by_task = (await db.execute(text(
        "SELECT task, count(*) AS calls, round(coalesce(sum(cost_usd), 0)::numeric, 4) AS cost_usd, "
        "percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms FROM llm_call "
        "WHERE created_at >= now() - interval '24 hours' GROUP BY 1 ORDER BY 2 DESC"))).mappings().all()
    evals = (await db.execute(text(
        "SELECT DISTINCT ON (alias, model, variant) alias, provider, model, variant, n, metrics, cost_usd, created_at "
        "FROM model_eval WHERE task = 'classify_causes' ORDER BY alias, model, variant, created_at DESC"))).mappings().all()
    cap = float((cfg.budget or {}).get("usd_per_day", 40))
    calls = int(u["calls"])
    return {
        "tasks": tasks, "providers": providers,
        "models": {k: _target(k, cfg) for k in cfg.models},
        "usage_24h": {"calls": {"value": calls, "display": f"{calls}", "unit": "count",
                                "prov": {"role": "calc", "review_status": "auto", "n": calls, "method": "count(llm_call)",
                                         "refs": [{"kind": "query", "id": "llm_call:24h", "label": "wywołania modeli, 24 h"}]}},
                      "tokens_in": int(u["tin"]), "tokens_out": int(u["tout"]), "cost_usd": round(float(u["cost"]), 4),
                      "by_task": [dict(r) for r in by_task]},
        "budget": {"usd_per_day": cap, "spent_today_usd": round(float(today or 0), 4),
                   "warn": float(today or 0) >= cap * float((cfg.budget or {}).get("warn_at", 0.8))},
        "benchmarks": [dict(r) for r in evals],
        "fake_mode": C.fake_mode(),
    }


@router.get("/llm", summary="Modele, trasowanie i zużycie")
async def get_llm(db: AsyncSession = DB, user: A.User = Depends(A.require_login)):
    await load_overrides(db)
    return await _view(db)


@router.put("/llm/routing", summary="Zmień trasowanie modeli (admin)")
async def put_routing(body: RoutingIn, request: Request, db: AsyncSession = DB, user: A.User = Depends(A.require_admin)):
    import json

    cfg = C.llm_config()
    models = {k: v for k, v in body.models.items()}
    for alias, target in models.items():
        pid = target.split(":", 1)[0] if ":" in target else ""
        if pid not in cfg.providers:
            raise A.ApiError(422, f"Nieznany dostawca w {target}.", "unknown_provider")
    tasks: dict[str, dict[str, str]] = {}
    for sens, per in body.routing.items():
        if sens not in ("public", "confidential"):
            raise A.ApiError(422, "Wrażliwość musi być public albo confidential.", "bad_sensitivity")
        for task, alias in per.items():
            tasks.setdefault(task, {})[sens] = str(alias)
    # validate the confidential rule against the routing as it would be after the change
    trial = cfg.model_copy(deep=True)
    trial.models.update(models)
    for task, per in tasks.items():
        trial.tasks.setdefault(task, {}).update(per)
    for task, per in trial.tasks.items():
        if "confidential" in per:
            try:
                p, _ = trial.resolve(per["confidential"])
            except KeyError:
                raise A.ApiError(422, f"Nieznany model {per['confidential']}.", "unknown_alias") from None
            if not p.is_pl:
                raise A.ApiError(422, f"Zadanie {task}: poufne dane mogą trafić tylko do modelu w Polsce.", "confidential_must_stay_pl")
    prev = await load_overrides(db)
    value = {"models": {**(prev.get("models") or {}), **models},
             "tasks": {**(prev.get("tasks") or {}), **{k: {**((prev.get("tasks") or {}).get(k) or {}), **v} for k, v in tasks.items()}}}
    await db.execute(text("INSERT INTO app_setting (key, value, updated_by, updated_at) VALUES ('llm.routing', CAST(:v AS jsonb), :u, now()) "
                          "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()"),
                     {"v": json.dumps(value), "u": user.actor})
    await db.execute(text("INSERT INTO audit_log (actor, action, table_name, before, after, request_id) VALUES "
                          "(:a, 'settings.llm_routing', 'app_setting', CAST(:b AS jsonb), CAST(:v AS jsonb), :r)"),
                     {"a": user.actor, "b": json.dumps(prev), "v": json.dumps(value), "r": A.request_id(request)})
    await db.commit()
    C.set_overrides(value["models"], value["tasks"])
    return await _view(db)


@router.post("/llm/providers/{provider_id}/health", summary="Sprawdź dostawcę modelu")
async def provider_health(provider_id: str, user: A.User = Depends(A.require_admin)):
    from riskminer.llm.eval.kat import run_kat
    from riskminer.llm.gateway import backend_for

    cfg = C.llm_config()
    p = cfg.providers.get(provider_id)
    if p is None:
        raise A.ApiError(404, "Nieznany dostawca.", "not_found")
    if p.kind == "replay":
        return {"id": provider_id, "status": "up" if C.fake_mode() else "standby", "latency_ms": 0, "models": []}
    if C.fake_mode():
        return {"id": provider_id, "status": "unknown", "latency_ms": None, "models": [], "note": "tryb nagranych odpowiedzi"}
    if p.sovereign:
        return await run_kat(provider_id)
    h = await backend_for(p).health()
    RT.mark_health(provider_id, h)
    return {"id": provider_id, **h}


@router.get("/llm/learning", summary="Uczenie: decyzje eksperta dla propozycji modeli (akceptacje, poprawki, odrzucenia)")
async def get_learning(db: AsyncSession = DB, user: A.User = Depends(A.require_login)):
    from riskminer.llm.learning import rates
    return await rates(db)
