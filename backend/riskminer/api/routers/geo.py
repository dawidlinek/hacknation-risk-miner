"""Map geometry (api_contract §2.7, `GET /api/geo/{level}.geojson`). Created by S0 as a working file server; owner: D (data-db).
Serves `data/ref/geo/{woj,pow,gmi}.geojson` (PRG/GUGiK), optional `parent` TERC prefix filter, ETag + 1 day cache."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from riskminer.config import settings

router = APIRouter(prefix="/api/geo", tags=["monitoring"])


@lru_cache(maxsize=8)
def _features(level: str) -> list[dict]:
    p = settings().ref_dir / "geo" / f"{level}.geojson"
    if not p.exists():
        raise HTTPException(404, detail={"detail": "Brak geometrii dla tego poziomu.", "code": "geo_missing"})
    return json.loads(p.read_text(encoding="utf-8")).get("features", [])


@router.get("/{level}.geojson", summary="Granice: województwa, powiaty, gminy (TERYT/PRG)")
async def geojson(level: Literal["woj", "pow", "gmi"], request: Request, parent: str | None = None, simplify: bool = True):
    feats = _features(level)
    if parent:
        feats = [f for f in feats if str((f.get("properties") or {}).get("terc", "")).startswith(parent)]
    body = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")).encode()
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/geo+json", headers=headers)
