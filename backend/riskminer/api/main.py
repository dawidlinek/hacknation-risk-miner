"""ex ante (Risk Miner) API. Run: cd backend && uv run uvicorn riskminer.api.main:app --port 8000
OpenAPI: /openapi.json, docs: /docs. Contract: docs/impl/api_contract.md.

Owned by the lead (S0). Every router is included exactly once below; sessions never edit this file.
Order matters: routers with fixed paths (`/api/catalogue/view`, `/api/projects/stats`, `/api/review-items/counts`) are
included BEFORE `data`, whose parametrised paths (`/catalogue/{table}`, `/projects/{rm_id}`) would otherwise shadow them.
"""
from __future__ import annotations

import asyncpg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from riskminer.api.middleware import RequestContextMiddleware
from riskminer.api.routers import (
    analyses,
    ask,
    audit,
    auth,
    catalogue_edit,
    dashboard,
    data,
    documents,
    exports,
    geo,
    imports,
    jobs,
    monitoring,
    projects,
    review,
    search,
    settings,
)
from riskminer.config import app_config

app = FastAPI(
    title="ex ante API",
    version="0.2.0",
    description=(
        "Cyfrowa pamięć instytucjonalna inwestycji wodno-kanalizacyjnych. Każdy rekord ma źródło "
        "(source_id → URL, data pobrania, sha256), pochodzenie (SOURCE / CALC / AI) i status przeglądu. "
        "Każda liczba w nowych odpowiedziach to Num {value, display, unit, prov: {role, review_status, n, method, refs}}. "
        "Kwoty: {amount, currency, vat_basis: net|gross|unknown}. Zapisy wymagają nagłówka X-Requested-With: ex-ante. "
        "Odpowiedzi z nagłówkiem X-Fixture: true to dane przykładowe (endpoint jeszcze w budowie)."
    ),
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(app_config().get("api") or {}).get("cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Fixture", "X-Fixture-Flag", "X-Request-ID"],
)

@app.exception_handler(DBAPIError)
async def _db_data_error(request: Request, exc: DBAPIError):
    """Bad parameter values that only Postgres rejects (negative LIMIT/OFFSET, int overflow, invalid dates: SQLSTATE
    class 22 or asyncpg's client-side DataError) are the caller's fault: 422, not 500. Anything else stays a 500."""
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    state = str(getattr(orig, "sqlstate", None) or getattr(cause, "sqlstate", None) or "")
    if state.startswith("22") or isinstance(cause, asyncpg.exceptions.DataError) or "invalid input for query argument" in str(orig):
        return JSONResponse({"detail": "Nieprawidłowa wartość parametru zapytania.", "code": "bad_parameter"}, status_code=422)
    raise exc


try:  # B's error type: body {"detail", "code"}
    from riskminer.api.auth import ApiError, api_error_handler
    app.add_exception_handler(ApiError, api_error_handler)
except ImportError:  # pragma: no cover - auth module not there yet
    pass

# fixed-path routers first (see module docstring)
for r in (auth, dashboard, analyses, documents, ask, settings, projects, review, catalogue_edit, audit,
          monitoring, geo, imports):
    app.include_router(r.router)
# existing read side
app.include_router(data.router)
app.include_router(exports.router)
app.include_router(jobs.router)
app.include_router(search.router)


@app.get("/api/health", tags=["meta"], summary="Stan usługi")
async def health() -> dict:
    from sqlalchemy import text

    from riskminer.db.session import sessionmaker
    async with sessionmaker()() as s:
        n = (await s.execute(text("SELECT count(*) FROM notice"))).scalar()
    return {"status": "ok", "notices": n}


@app.get("/api/config/features", tags=["meta"], summary="Flagi funkcji")
async def features() -> dict:
    return app_config().get("features") or {}
