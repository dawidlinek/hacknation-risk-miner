"""Contract test (docs/impl/api_contract.md §2, §8.3a): every documented endpoint is in /openapi.json with its method,
every route is registered once, and fixed paths are not shadowed by parametrised ones. Unit test: no DB."""
from __future__ import annotations

import collections

import pytest

from riskminer.api.main import app

pytestmark = pytest.mark.unit

# (method, path) as in api_contract §2; path params use FastAPI names
CONTRACT = [
    ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("GET", "/api/auth/me"), ("GET", "/api/nav/counts"),
    ("GET", "/api/health"), ("GET", "/api/config/features"),
    ("GET", "/api/dashboard"), ("GET", "/api/national/headline"), ("GET", "/api/sources/summary"), ("GET", "/api/review-items"),
    ("GET", "/api/ask/suggestions"), ("POST", "/api/ask"),
    ("POST", "/api/documents/upload"), ("POST", "/api/analyses"), ("PATCH", "/api/analyses/{code}/features"),
    ("GET", "/api/catalogue/funding-programmes"), ("POST", "/api/analyses/{code}/run"), ("GET", "/api/analyses/{code}"),
    ("GET", "/api/analyses"), ("GET", "/api/analyses/{code}/versions"), ("GET", "/api/analyses/{code}/reference-class/contracts"),
    ("POST", "/api/analyses/{code}/chat"), ("GET", "/api/analyses/{code}/redpen/{document_id}"),
    ("GET", "/api/documents/{document_id}/file"), ("POST", "/api/analyses/{code}/items/{item_id}/decision"),
    ("POST", "/api/analyses/{code}/simulate"), ("GET", "/api/analyses/{code}/allocation"), ("PUT", "/api/analyses/{code}/allocation"),
    ("GET", "/api/analyses/{code}/pack"), ("GET", "/api/analyses/{code}/pack.{fmt}"),
    ("POST", "/api/questions"), ("GET", "/api/questions"), ("GET", "/api/questions/{code}"), ("POST", "/api/questions/{code}/rerun"),
    ("GET", "/api/questions/{code}/rows.{fmt}"),
    ("GET", "/api/runs"), ("GET", "/api/jobs"), ("GET", "/api/jobs/{job_id}"), ("POST", "/api/jobs"),
    ("POST", "/api/imports"), ("POST", "/api/imports/{code}/inspect"), ("POST", "/api/imports/{code}/propose-mapping"),
    ("POST", "/api/imports/{code}/answers"), ("POST", "/api/imports/{code}/test-run"), ("POST", "/api/imports/{code}/approve"),
    ("POST", "/api/imports/{code}/run"), ("GET", "/api/imports/{code}"), ("GET", "/api/importers"),
    ("GET", "/api/projects"), ("GET", "/api/projects/stats"), ("GET", "/api/export/{dataset}.{fmt}"),
    ("GET", "/api/projects/{rm_id}/card"), ("GET", "/api/projects/{rm_id}"), ("GET", "/api/projects/{rm_id}/timeline"),
    ("GET", "/api/projects/{rm_id}/similar"), ("POST", "/api/projects/{rm_id}/chat"), ("GET", "/api/projects/{rm_id}/graph"),
    ("POST", "/api/projects/{rm_id}/links"), ("GET", "/api/projects/{rm_id}/documents"), ("GET", "/api/notices/{object_id}/facts"),
    ("GET", "/api/projects/{rm_id}/history"), ("GET", "/api/projects/{rm_id}/history/compare"), ("POST", "/api/audit/{audit_id}/restore"),
    ("GET", "/api/review-items/counts"), ("GET", "/api/review-items/{item_id}"), ("POST", "/api/review-items/{item_id}/decision"),
    ("POST", "/api/review-items/{item_id}/skip"), ("POST", "/api/reviews/{review_id}/undo"), ("GET", "/api/reviews"),
    ("POST", "/api/review-items/bulk-decision"),
    ("GET", "/api/catalogue/{table}"), ("GET", "/api/catalogue/view"), ("PATCH", "/api/catalogue/{table}/{code}"),
    ("PUT", "/api/catalogue/similarity/weights"), ("POST", "/api/catalogue/proposals/{proposal_id}/decision"),
    ("GET", "/api/catalogue/versions"), ("GET", "/api/catalogue/versions/{label}/diff"), ("POST", "/api/catalogue/versions/{label}/restore"),
    ("GET", "/api/catalogue/pack.{fmt}"),
    ("GET", "/api/monitoring/regions"), ("GET", "/api/monitoring/regions/{terc}"), ("GET", "/api/monitoring/signals"),
    ("GET", "/api/monitoring/contracts/{contract_id}"), ("GET", "/api/geo/{level}.geojson"), ("POST", "/api/monitoring/watches"),
    ("DELETE", "/api/monitoring/watches/{watch_id}"), ("POST", "/api/monitoring/contracts/{contract_id}/report-case"),
    ("GET", "/api/contracts/{contract_id}"), ("GET", "/api/procedures/{ocid}"),
    ("GET", "/api/audit"),
    ("GET", "/api/settings/llm"), ("PUT", "/api/settings/llm/routing"), ("POST", "/api/settings/llm/providers/{provider_id}/health"),
]


def _flat(routes=None):
    """Routes in match order; FastAPI >= 0.16x nests included routers (`original_router`)."""
    out = []
    for r in app.routes if routes is None else routes:
        inner = getattr(r, "original_router", None)
        out.extend(_flat(inner.routes) if inner is not None else [r])
    return out


def _routes():
    return [(m, r.path) for r in _flat() if hasattr(r, "methods") for m in r.methods if m not in ("HEAD", "OPTIONS")]


def test_every_contract_path_in_openapi():
    spec = app.openapi()["paths"]
    missing = [(m, p) for m, p in CONTRACT if m.lower() not in spec.get(p, {})]
    assert not missing, f"missing from /openapi.json: {missing}"


def test_no_duplicate_routes():
    dup = [k for k, n in collections.Counter(_routes()).items() if n > 1]
    # GET /api/review-items exists in data.py (legacy) and review.py (B); review.py is included first and wins.
    dup = [d for d in dup if d != ("GET", "/api/review-items")]
    assert not dup, f"routes registered twice: {dup}"


@pytest.mark.parametrize("fixed,shadow", [
    ("/api/catalogue/view", "/api/catalogue/{table}"), ("/api/catalogue/versions", "/api/catalogue/{table}"),
    ("/api/catalogue/funding-programmes", "/api/catalogue/{table}"), ("/api/projects/stats", "/api/projects/{rm_id}"),
    ("/api/review-items/counts", "/api/review-items/{item_id}"),
])
def test_fixed_paths_not_shadowed(fixed, shadow):
    order = [r.path for r in _flat() if "GET" in (getattr(r, "methods", None) or set())]
    assert fixed in order
    if shadow in order:
        assert order.index(fixed) < order.index(shadow), f"{fixed} is shadowed by {shadow}"


def test_operation_ids_unique():
    ops = [op.get("operationId") for p in app.openapi()["paths"].values() for op in p.values()]
    dup = [o for o, n in collections.Counter(ops).items() if n > 1]
    assert not dup, f"duplicate operationIds: {dup}"
