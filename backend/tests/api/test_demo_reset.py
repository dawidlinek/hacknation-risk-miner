"""Demo reset: baseline, decisions after it are reverted by compensating rows, nothing deleted (admin only)."""
from sqlalchemy import text


async def _scalar(db, sql, **p):
    return (await db.execute(text(sql), p)).scalar()


async def test_reset_requires_admin_and_baseline(client, expert, admin):
    assert (await client.post("/api/admin/demo-reset")).status_code == 401
    assert (await expert.post("/api/admin/demo-reset")).status_code == 403
    assert (await expert.post("/api/admin/demo-baseline")).status_code == 403


async def test_reset_reverts_decisions_skips_and_catalogue(admin, db):
    r = await admin.post("/api/admin/demo-baseline")
    assert r.status_code == 200 and r.json()["catalogue_label"].startswith("v1.")
    label0 = r.json()["catalogue_label"]
    ids = [x[0] for x in (await db.execute(text("SELECT id FROM review_item WHERE status='open' AND kind='discrepancy' ORDER BY id LIMIT 3"))).all()]
    states0 = {i: await _scalar(db, "SELECT detail->'resolution' FROM review_item WHERE id=:i", i=i) for i in ids}
    d = await admin.post(f"/api/review-items/{ids[0]}/decision", json={"option": "keep_dataset", "action": "approve"})
    assert d.status_code == 200, d.text
    assert (await admin.post(f"/api/review-items/{ids[1]}/skip")).status_code == 200
    # a catalogue edit and a link correction after the baseline
    assert (await admin.patch("/api/catalogue/risk/R01", json={"patch": {"description": "zmiana demo"}})).status_code == 200
    n_reviews = await _scalar(db, "SELECT count(*) FROM review")
    n_audit = await _scalar(db, "SELECT count(*) FROM audit_log")

    dry = (await admin.post("/api/admin/demo-reset", json={"dry_run": True})).json()
    assert dry["decisions_to_revert"] == 1 and dry["skipped_to_clear"] == 1 and dry["catalogue_restore"] and dry["dry_run"]
    assert await _scalar(db, "SELECT status FROM review_item WHERE id=:i", i=ids[0]) == "resolved"

    out = await admin.post("/api/admin/demo-reset")
    assert out.status_code == 200, out.text
    j = out.json()
    assert len(j["reverted"]) == 1 and j["failed"] == []
    assert await _scalar(db, "SELECT status FROM review_item WHERE id=:i", i=ids[0]) == "open"
    assert await _scalar(db, "SELECT detail ? 'skipped_at' FROM review_item WHERE id=:i", i=ids[1]) is False
    for i in ids:
        assert await _scalar(db, "SELECT detail->'resolution' FROM review_item WHERE id=:i", i=i) == states0[i]
    cur = [x for x in (await admin.get("/api/catalogue/risk")).json() if x["code"] == "R01" and x["status"] == "approved"][0]
    assert cur["description"] != "zmiana demo"
    # append-only: more rows than before, none removed
    assert await _scalar(db, "SELECT count(*) FROM review") > n_reviews and await _scalar(db, "SELECT count(*) FROM audit_log") > n_audit
    assert await _scalar(db, "SELECT count(*) FROM review WHERE option_key='demo_reset'") == 1
    again = (await admin.post("/api/admin/demo-reset")).json()
    assert again["decisions_to_revert"] == 0 and again["reverted"] == []
    st = (await admin.get("/api/admin/demo-status")).json()
    assert st["decisions_since"] == 0
