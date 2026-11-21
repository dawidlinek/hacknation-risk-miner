"""Write access contract (S0, lead request 21.11): every non-GET route in /openapi.json refuses anonymous callers (401/403),

Requests carry no valid body on purpose: FastAPI resolves dependencies (require_writer / require_admin) before validating the
body, so a gated route answers 403/401 and an ungated one leaks through as 422/404/2xx. Runs inside the transactional fixture;
enqueue() and LLM calls are stubbed, so nothing reaches the main DB or the network even if a route slips."""
from __future__ import annotations

import re

import pytest
from test_contract_smoke import _samples  # tests/api is on sys.path (rootdir-relative, no package)

from riskminer.api.main import app

pytestmark = pytest.mark.fulldb

# Routes public viewers (anonymous visitors) may call by design (api_contract §2.3: Flow 1 is public; ask and chats are public,
# rate-limited; analysis writes are owner-checked inside the handler).
PUBLIC_WRITES = {
    ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("POST", "/api/auth/demo-login"),
    ("POST", "/api/documents/upload"),
    ("POST", "/api/analyses"), ("PATCH", "/api/analyses/{code}/features"), ("POST", "/api/analyses/{code}/run"),
    ("POST", "/api/analyses/{code}/items/{item_id}/decision"), ("POST", "/api/analyses/{code}/simulate"),
    ("PUT", "/api/analyses/{code}/allocation"), ("POST", "/api/analyses/{code}/pack/clauses"),
    ("POST", "/api/analyses/{code}/chat"),
    ("POST", "/api/ask"), ("POST", "/api/questions"), ("POST", "/api/questions/{code}/rerun"),
    ("POST", "/api/projects/{rm_id}/chat"),
}


def _write_routes() -> list[tuple[str, str]]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        for m in ops:
            if m.upper() in ("POST", "PUT", "PATCH", "DELETE"):
                out.append((m.upper(), path))
    return sorted(out, key=lambda x: (x[1], x[0]))


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    from riskminer.jobs import worker

    async def fake_enqueue(kind, payload=None, priority=100, created_by="cli"):
        return {"id": -1, "kind": kind}

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)
    monkeypatch.setenv("RISKMINER_LLM_FAKE", "1")


async def _probe(c, db, want: set[int]) -> list[str]:
    s = await _samples(db)
    leaks = []
    for method, path in _write_routes():
        if (method, path) in PUBLIC_WRITES:
            continue
        url = re.sub(r"\{(\w+)\}", lambda m: s.get(m.group(1), "1"), path)
        r = await c.request(method, url)
        if r.status_code not in want:
            leaks.append(f"{r.status_code} {method} {path}  {r.text[:120]!r}")
    return leaks


async def test_anonymous_cannot_write(client, db):
    leaks = await _probe(client, db, {401, 403})
    assert not leaks, "routes that do not refuse anonymous callers with 401/403:\n" + "\n".join(leaks)


def test_public_writes_still_exist():
    """Allowlist entries must be real routes (catches renames that would silently widen the check)."""
    routes = set(_write_routes())
    stale = sorted(PUBLIC_WRITES - routes)
    assert not stale, f"PUBLIC_WRITES entries no longer in /openapi.json: {stale}"
