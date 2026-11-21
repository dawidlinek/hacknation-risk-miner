"""API smoke tests against the loaded DB (in-process ASGI, no server). Run: uv run pytest -q"""
import httpx
import pytest

from riskminer.api.main import app


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_health_and_openapi(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["notices"] > 0
    spec = (await client.get("/openapi.json")).json()
    assert "/api/projects/{rm_id}" in spec["paths"]


async def test_pilot_projects_linked(client):
    r = (await client.get("/api/projects", params={"pilot": True})).json()
    assert r["total"] == 22
    assert all(p["procedures"] for p in r["items"]), "every pilot project has a linked procedure"


async def test_project_detail_chain(client):
    d = (await client.get("/api/projects/RM-2026-022")).json()
    assert d["link_method"] == "cross_reference"
    pd = d["procedure_details"][0]
    assert pd["contracts"] and pd["timeline"]
    # review items are login-only since the access split (api_contract §2.0): anonymous callers get none
    assert d["review_items"] == []


async def test_lists_and_exports(client):
    for path in ("/api/procedures?limit=2", "/api/notices?limit=2", "/api/contracts?limit=2", "/api/changes?limit=2",
                 "/api/performance?limit=2&late=true", "/api/organizations?limit=2", "/api/stats", "/api/source-checks",
                 "/api/external-records?limit=2", "/api/documents", "/api/risk-events?rm_id=RM-2026-019"):
        r = await client.get(path)
        assert r.status_code == 200, (path, r.text[:500])
    # login-only for anonymous callers (api_contract §2.0, §4)
    for path in ("/api/sources?limit=2", "/api/runs?limit=2", "/api/link-candidates?rm_id=RM-2026-002", "/api/review-items",
                 "/api/jobs"):
        assert (await client.get(path)).status_code == 401, path
    r = await client.get("/api/export/projects.csv", params={"pilot": True})
    assert r.status_code == 200 and r.text.count("\n") >= 23
    assert (await client.get("/api/export/review_items.json")).status_code == 401
