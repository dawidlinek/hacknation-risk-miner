"""W10 organization memory and W17 lessons digest: shape, provenance, insufficient-n rule. Read-only (rolled back)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from riskminer.analytics import flags as FL

pytestmark = pytest.mark.fulldb


def _num_ok(n: dict):
    p = n["prov"]
    assert p["role"] == "calc" and p["method"] and p["refs"] and isinstance(p["n"], int)
    if p["n"] < 5:
        assert n["value"] is None and n["display"] == "za mało danych" and p["insufficient"]


async def _nip(db, role_sql: str) -> str:
    return (await db.execute(text(role_sql))).scalar_one()


async def test_organization_memory_contractor_and_buyer(client, db):
    nip = await _nip(db, "SELECT contractor_nip FROM contract WHERE contractor_nip IS NOT NULL "
                         "GROUP BY 1 HAVING count(*) > 20 ORDER BY count(*) DESC LIMIT 1")
    r = await client.get(f"/api/organizations/{nip}/memory")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["organization"]["nip"] == nip and m["min_n"] == 5
    c = m["contractor"]
    for k in ("contracts_total", "completed", "ongoing", "late_share", "median_delay_days", "annexes"):
        _num_ok(c[k])
    assert c["contracts_total"]["value"] > 20
    assert len(c["recent_contracts"]) <= 5 and all(x["href"].startswith("/projekty/") for x in c["recent_contracts"])
    assert c["change_kinds"] == sorted(c["change_kinds"], key=lambda k: -k["count"])
    _num_ok(m["load"]["ongoing"])
    # a buyer NIP: same endpoint, buyer block filled
    b = await _nip(db, "SELECT p.buyer_nip FROM procedure p JOIN contract c ON c.procedure_id = p.id JOIN organization o ON o.nip = p.buyer_nip "
                       "GROUP BY 1 HAVING count(*) > 10 ORDER BY count(*) DESC LIMIT 1")
    mb = (await client.get(f"/api/organizations/{b}/memory")).json()["buyer"]
    _num_ok(mb["contracts_total"])
    assert mb["contracts_total"]["value"] > 10


async def test_organization_memory_insufficient_and_404(client, db):
    nip = await _nip(db, "SELECT o.nip FROM organization o JOIN contract c ON c.contractor_nip = o.nip "
                         "GROUP BY o.nip HAVING count(*) BETWEEN 1 AND 4 LIMIT 1")
    m = (await client.get(f"/api/organizations/{nip}/memory")).json()
    assert m["contractor"]["contracts_total"]["display"] == "za mało danych"
    assert m["contractor"]["late_share"]["value"] is None and m["flags"] == []
    assert (await client.get("/api/organizations/no-such-nip/memory")).status_code == 404


def test_r12_flag_rule():
    f = FL.contractor_load_flag(12, 40e6, 4.0, 20e6, 60)
    assert f is not None and f.code == "R12" and f.risk_codes == ["R12"] and f.n == 60
    assert FL.contractor_load_flag(12, 40e6, 4.0, 20e6, 3) is None        # n < 5: insufficient
    assert FL.contractor_load_flag(4, 5e6, 1.0, 5e6, 60) is None          # fewer than 5 ongoing
    assert FL.contractor_load_flag(6, 5e6, 5.0, 5e6, 60) is None          # within its usual load


async def test_lessons_digest(client):
    r = await client.get("/api/analytics/lessons", params={"sector": "wod-kan", "limit": 5})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["sector"] == "wod-kan" and 0 < len(d["categories"]) <= 5
    _num_ok(d["totals"]["events"])
    ns = [c["events"]["prov"]["n"] for c in d["categories"]]
    assert ns == sorted(ns, reverse=True)
    for c in d["categories"]:
        assert c["code"].startswith("R") and c["name"]
        for k in ("events", "cases", "delay_median_days", "cost_median"):
            _num_ok(c[k])
        for cause in c["causes"]:
            assert cause["text"] and cause["count"] >= 1 and cause["href"]
        assert all(m["assumption"] for m in c["mitigations_proposed"])
    assert (await client.get("/api/analytics/lessons", params={"sector": "Bad Sector"})).status_code == 422


async def test_lessons_exclude_ai_proposals(client, db):
    ids = (await db.execute(text("SELECT id FROM risk_event WHERE review_status = 'proposed' AND origin = 'AI' LIMIT 1"))).scalar()
    d = (await client.get("/api/analytics/lessons")).json()
    assert d["totals"]["excluded_events"] >= (1 if ids else 0)
    for c in d["categories"]:
        for x in c["causes"]:
            assert x["review_status"] in ("approved", "edited", "auto") and not (x["origin"] == "AI" and x["review_status"] == "auto")
