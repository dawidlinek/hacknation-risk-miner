"""Contract smoke (S0): every GET route in /openapi.json answers without a 5xx and without `X-Fixture: true`, for an
anonymous caller and for an expert. Read-only; runs inside the transactional fixture anyway. Path parameters are filled with
real ids picked from the DB (404 is acceptable: the point is no crash and no stub)."""
from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text

from riskminer.api.main import app

pytestmark = pytest.mark.fulldb

SKIP = {"/api/export/{dataset}.{fmt}"}   # streamed exports are covered by tests/api/test_exports.py (B)


async def _samples(db) -> dict[str, str]:
    async def one(sql: str, default: str) -> str:
        try:
            v = (await db.execute(text(sql))).scalar()
        except Exception:  # noqa: BLE001 - table may not exist on an older schema
            await db.rollback()
            return default
        return str(v) if v is not None else default

    return {
        "code": await one("SELECT code FROM analysis WHERE code IS NOT NULL ORDER BY id DESC LIMIT 1", "AN-2026-0001"),
        "rm_id": "RM-2026-003",
        "document_id": await one("SELECT id FROM document WHERE sensitivity = 'public' AND pages > 0 ORDER BY id LIMIT 1", "1"),
        "item_id": await one("SELECT id FROM review_item ORDER BY id LIMIT 1", "1"),
        "object_id": await one("SELECT object_id FROM notice WHERE ocid IS NOT NULL ORDER BY id LIMIT 1", "x"),
        "contract_id": await one("SELECT contract_id FROM rc_contract ORDER BY contract_id LIMIT 1", "1"),
        "ocid": await one("SELECT ocid FROM procedure ORDER BY id LIMIT 1", "x"),
        "nip": await one("SELECT nip FROM organization WHERE nip IS NOT NULL LIMIT 1", "0"),
        "job_id": await one("SELECT id FROM job ORDER BY id LIMIT 1", "1"),
        "source_id": await one("SELECT id FROM source ORDER BY id LIMIT 1", "1"),
        "record_id": await one("SELECT id FROM external_record ORDER BY id LIMIT 1", "1"),
        "terc": "12", "level": "woj", "table": "risk", "label": "v1.1", "fmt": "json", "page_no": "1",
        "provider_id": "gemini", "audit_id": "1", "review_id": "1", "proposal_id": "1", "watch_id": "1",
    }


def _dump(url: str, r) -> None:
    """SMOKE_DUMP=<dir>: save each 200 JSON response as <dir>/<path>.json (real shapes for the frontend)."""
    d = os.environ.get("SMOKE_DUMP")
    if not d or r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        return
    import json
    from pathlib import Path
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", url.removeprefix("/api/")).strip("_") or "root"
    body = r.json()
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        body = {**body, "items": body["items"][:3]}
    elif isinstance(body, list):
        body = body[:5]
    Path(d).mkdir(parents=True, exist_ok=True)
    (Path(d) / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str)[:60000], encoding="utf-8")


def _get_paths() -> list[str]:
    return sorted(p for p, ops in app.openapi()["paths"].items() if "get" in ops and p not in SKIP)


async def _check(c, db, extra: dict | None = None) -> None:
    s = {**await _samples(db), **(extra or {})}
    bad = []
    for path in _get_paths():
        url = re.sub(r"\{(\w+)\}", lambda m: s.get(m.group(1), "1"), path)
        params = {"from": "v1", "to": "v2"} if path.endswith("/compare") else None
        r = await c.get(url, params=params)
        if os.environ.get("SMOKE_VERBOSE"):
            print(r.status_code, url)
        _dump(url, r)
        if r.status_code >= 500 or r.headers.get("x-fixture") == "true":
            bad.append(f"{r.status_code} {url} {r.headers.get('x-fixture', '')} {r.text[:160]!r}")
    assert not bad, "\n".join(bad)


async def test_get_routes_anonymous(client, db):
    await _check(client, db)


async def test_get_routes_expert(expert, db):
    await _check(expert, db)


async def test_analysis_routes_with_a_real_analysis(client, db, monkeypatch):
    """Create + run an analysis inside the rolled-back transaction (LLM in fake/replay mode: no network), then hit every
    GET under /api/analyses/{code}: all must answer 200 for the owner (anonymous session that created it)."""
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")
    r = await client.post("/api/analyses", json={"input_text": "Budowa kanalizacji sanitarnej ok. 6 km w formule zaprojektuj "
                                                                "i wybuduj, budżet 7 mln zł brutto, termin 14 miesięcy, FEnIKS.",
                                                 "sensitivity": "public"})
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    run = await client.post(f"/api/analyses/{code}/run", json={})
    assert run.status_code < 500, run.text
    bad = []
    for path in _get_paths():
        if not path.startswith("/api/analyses/{code}") or "{document_id}" in path:
            continue
        url = path.replace("{code}", code).replace("{fmt}", "json")
        g = await client.get(url)
        _dump(url, g)
        if g.status_code != 200 or g.headers.get("x-fixture") == "true":
            bad.append(f"{g.status_code} {url} {g.text[:200]!r}")
    assert not bad, "\n".join(bad)
