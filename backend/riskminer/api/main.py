"""Risk Miner API. Run: cd backend && uv run uvicorn riskminer.api.main:app --port 8000
OpenAPI: /openapi.json, docs: /docs."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from riskminer.api.routers import data, exports, jobs, search
from riskminer.config import app_config

app = FastAPI(
    title="Risk Miner API",
    version="0.1.0",
    description=(
        "Cyfrowa pamięć instytucjonalna inwestycji wodno-kanalizacyjnych. Każdy rekord ma źródło "
        "(source_id → URL, data pobrania, sha256), pochodzenie (SOURCE / CALC / AI) i status przeglądu. "
        "Kwoty: {amount, currency, vat_basis: net|gross|unknown}."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(app_config().get("api") or {}).get("cors_origins", ["*"]),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(data.router)
app.include_router(exports.router)
app.include_router(jobs.router)
app.include_router(search.router)


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    from sqlalchemy import text

    from riskminer.db.session import sessionmaker
    async with sessionmaker()() as s:
        n = (await s.execute(text("SELECT count(*) FROM notice"))).scalar()
    return {"status": "ok", "notices": n}


@app.get("/api/config/features", tags=["meta"])
async def features() -> dict:
    return app_config().get("features") or {}
