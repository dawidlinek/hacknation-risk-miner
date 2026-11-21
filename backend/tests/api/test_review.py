"""Review decisions, undo, protection, link correction, catalogue proposals (api_contract §3.1, §8.5). Transactional."""
import re
from pathlib import Path

from sqlalchemy import text


async def _scalar(db, sql, **p):
    return (await db.execute(text(sql), p)).scalar()


async def _audit_count(db):
    return await _scalar(db, "SELECT count(*) FROM audit_log")


async def _mk_event(db, code="R02", conf=0.8, summary="Dopłata za roboty nieprzewidziane w PFU"):
    pid = await _scalar(db, "SELECT id FROM project WHERE rm_id='RM-2026-003'")
    eid = await _scalar(db, """INSERT INTO risk_event (project_id, event_type, catalogue_code, summary, origin, review_status, conf_data_quality)
                               VALUES (:p, 'EV_TEST', :c, :s, 'AI', 'proposed', :conf) RETURNING id""", p=pid, c=code, s=summary, conf=conf)
    iid = await _scalar(db, """INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, question, model_pick, confidence, key, created_by)
                               VALUES ('event', 'ai_event', 'risk_event', :e, :p, :s, :s, :c, :conf, :k, 'test') RETURNING id""",
                        e=eid, p=pid, s=summary, c=code, conf=conf, k=f"test:evt:{eid}")
    return eid, iid


async def test_card_for_event_has_options_and_effects(expert, db):
    eid, iid = await _mk_event(db)
    r = await expert.get(f"/api/review-items/{iid}")
    assert r.status_code == 200
    card = r.json()
    assert card["kind"] == "event" and card["kind_label"] == "Zdarzenie ryzyka"
    keys = [o["key"] for o in card["options"]]
    assert keys == ["R02", "other", "not_risk"]
    pick = card["options"][0]
    assert pick["model_pick"] and pick["badge"] == "propozycja modelu, 0,80" and pick["effects"]
    assert card["gold"]["after"]
    assert "—" not in r.text and "·" not in r.text


async def test_approve_event_writes_review_audit_and_target(expert, db):
    eid, iid = await _mk_event(db)
    a0 = await _audit_count(db)
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "R02", "action": "approve"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["review_id"] and j["undo_until"] and j["applied"]
    assert any(x["field"] == "review_status" and x["before"] == "proposed" and x["after"] == "approved" for x in j["applied"])
    assert await _scalar(db, "SELECT review_status FROM risk_event WHERE id=:i", i=eid) == "approved"
    assert await _scalar(db, "SELECT status FROM review_item WHERE id=:i", i=iid) == "resolved"
    rv = (await db.execute(text("SELECT action, reviewer, before, after FROM review WHERE id=:i"), {"i": j["review_id"]})).mappings().one()
    assert rv["action"] == "approve" and rv["reviewer"] == "user:test"
    assert await _audit_count(db) > a0
    assert await _scalar(db, "SELECT count(*) FROM audit_log WHERE actor='user:test' AND table_name='risk_event' AND row_id=:i", i=eid) >= 1
    # second decision on a resolved item is a 409, not a silent overwrite
    r2 = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "R02", "action": "approve"})
    assert r2.status_code == 409


async def test_reject_needs_reason(expert, db):
    eid, iid = await _mk_event(db)
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "not_risk", "action": "reject"})
    assert r.status_code == 422
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "not_risk", "action": "reject", "reason": "zwykła zmiana terminu"})
    assert r.status_code == 200
    assert await _scalar(db, "SELECT review_status FROM risk_event WHERE id=:i", i=eid) == "rejected"


async def test_edit_event_validates_catalogue_code(expert, db):
    eid, iid = await _mk_event(db)
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "other", "action": "edit", "value": "R99 coś"})
    assert r.status_code == 422
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "other", "action": "edit", "value": "R04 decyzja organu"})
    assert r.status_code == 200, r.text
    row = (await db.execute(text("SELECT catalogue_code, review_status FROM risk_event WHERE id=:i"), {"i": eid})).mappings().one()
    assert dict(row) == {"catalogue_code": "R04", "review_status": "edited"}


async def test_undo_restores_and_reopens(expert, db):
    eid, iid = await _mk_event(db)
    rid = (await expert.post(f"/api/review-items/{iid}/decision", json={"option": "R02", "action": "approve", "gold": True})).json()
    assert rid["gold"] and rid["gold"]["job_id"]
    assert await _scalar(db, "SELECT count(*) FROM gold_example WHERE review_id=:r", r=rid["review_id"]) == 1
    u = await expert.post(f"/api/reviews/{rid['review_id']}/undo")
    assert u.status_code == 200, u.text
    assert await _scalar(db, "SELECT review_status FROM risk_event WHERE id=:i", i=eid) == "proposed"
    assert await _scalar(db, "SELECT status FROM review_item WHERE id=:i", i=iid) == "open"
    assert await _scalar(db, "SELECT count(*) FROM review WHERE undo_of=:r", r=rid["review_id"]) == 1
    assert await _scalar(db, "SELECT (output->>'retracted')::bool FROM gold_example WHERE review_id=:r", r=rid["review_id"]) is True
    again = await expert.post(f"/api/reviews/{rid['review_id']}/undo")
    assert again.status_code == 409


async def test_undo_only_by_same_reviewer(expert, admin, db):
    eid, iid = await _mk_event(db)
    rid = (await expert.post(f"/api/review-items/{iid}/decision", json={"option": "R02", "action": "approve"})).json()["review_id"]
    r = await admin.post(f"/api/reviews/{rid}/undo")
    assert r.status_code == 403


async def test_protected_row_conflict_is_409_not_fake_saved(expert, db):
    """A row approved by someone else outside the review path must never turn into a fake success."""
    from riskminer.review.common import update_fields
    from riskminer.api.auth import ApiError
    import pytest
    eid, _ = await _mk_event(db)
    await db.execute(text("SELECT set_config('riskminer.expert_write','on',true)"))
    await db.execute(text("UPDATE risk_event SET review_status='approved' WHERE id=:i"), {"i": eid})
    await db.execute(text("SELECT set_config('riskminer.expert_write','off',true)"))
    # the pipeline path (no expert scope) silently keeps OLD: update_fields without the scope must raise 409
    with pytest.raises(ApiError) as e:
        await update_fields(db, "risk_event", eid, {"review_status": "rejected"})
    assert e.value.status_code == 409 and e.value.code == "protected_row"


async def test_ai_update_cannot_overwrite_approved(db):
    eid, _ = await _mk_event(db)
    await db.execute(text("SELECT set_config('riskminer.expert_write','on',true)"))
    await db.execute(text("UPDATE risk_event SET review_status='approved' WHERE id=:i"), {"i": eid})
    await db.execute(text("SELECT set_config('riskminer.expert_write','off',true)"))
    await db.execute(text("UPDATE risk_event SET catalogue_code='R09', review_status='proposed' WHERE id=:i"), {"i": eid})
    row = (await db.execute(text("SELECT catalogue_code, review_status FROM risk_event WHERE id=:i"), {"i": eid})).mappings().one()
    assert row["review_status"] == "approved" and row["catalogue_code"] == "R02"


async def test_decisions_require_login(client, db):
    eid, iid = await _mk_event(db)
    assert (await client.post(f"/api/review-items/{iid}/decision", json={"option": "R02", "action": "approve"})).status_code == 401
    assert (await client.get(f"/api/review-items/{iid}")).status_code == 401


async def test_discrepancy_options_and_resolution(expert, db):
    iid = await _scalar(db, "SELECT id FROM review_item WHERE code='value_deviation' AND status='open' ORDER BY id LIMIT 1")
    card = (await expert.get(f"/api/review-items/{iid}")).json()
    assert [o["key"] for o in card["options"]] == ["keep_dataset", "use_bzp", "dismiss"]
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "keep_dataset", "action": "approve"})
    assert r.status_code == 200, r.text
    det = await _scalar(db, "SELECT detail->'resolution'->>'option' FROM review_item WHERE id=:i", i=iid)
    assert det == "keep_dataset"
    counts = (await expert.get("/api/review-items/counts")).json()
    assert counts["total"] >= 0 and "discrepancy" in counts


async def test_part_mismatch_use_matched_updates_lots_and_undo(expert, db):
    iid = await _scalar(db, "SELECT id FROM review_item WHERE code='part_mismatch' AND status='open' LIMIT 1")
    pid = await _scalar(db, "SELECT project_id FROM review_item WHERE id=:i", i=iid)
    before = await _scalar(db, "SELECT lots FROM project_procedure WHERE project_id=:p LIMIT 1", p=pid)
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "use_matched", "action": "edit", "value": "tak"})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT lots FROM project_procedure WHERE project_id=:p LIMIT 1", p=pid) == [1]
    u = await expert.post(f"/api/reviews/{r.json()['review_id']}/undo")
    assert u.status_code == 200
    assert await _scalar(db, "SELECT lots FROM project_procedure WHERE project_id=:p LIMIT 1", p=pid) == before


async def test_skip_moves_to_end(expert, db):
    ids = [r[0] for r in (await db.execute(text("SELECT id FROM review_item WHERE status='open' ORDER BY id"))).all()]
    r = await expert.post(f"/api/review-items/{ids[0]}/skip")
    assert r.status_code == 200 and r.json()["next_item_id"] != ids[0]
    page = (await expert.get("/api/review-items", params={"limit": 1})).json()
    assert page["items"][0]["id"] != ids[0]  # skipped item no longer first
    last = (await expert.get("/api/review-items", params={"limit": 1, "offset": page["total"] - 1})).json()["items"][0]
    assert last["id"] == ids[0] and last["detail"].get("skipped_at")


async def test_link_correction_and_decision_chain(expert, db):
    r = await expert.post("/api/projects/RM-2026-022/links", json={"action": "replace", "bzp_number": "2099/BZP 00000001", "reason": "test"})
    assert r.status_code == 404  # unknown BZP number -> 404, nothing written
    ocid_notice = await _scalar(db, "SELECT bzp_number FROM notice WHERE ocid IS NOT NULL AND notice_type='ContractNotice' LIMIT 1")
    r = await expert.post("/api/projects/RM-2026-022/links", json={"action": "add", "bzp_number": ocid_notice, "reason": "ręcznie"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["project_procedure"]["method"] == "expert" and j["project_procedure"]["review_status"] == "approved"
    assert j["review_id"] and isinstance(j["closed_review_items"], list)
    assert await _scalar(db, "SELECT count(*) FROM audit_log WHERE action='link.correct' AND actor='user:test'") >= 1


async def test_review_export_columns_and_gating(client, expert):
    assert (await client.get("/api/export/review_decisions.json")).status_code == 401
    r = await expert.get("/api/export/review_decisions.csv?sep=semicolon&limit=1")
    assert r.status_code == 200 and ";" in r.text.splitlines()[0]


def test_expert_write_literal_only_in_review_package():
    root = Path(__file__).resolve().parents[2] / "riskminer"
    offenders = [str(p.relative_to(root)) for p in root.rglob("*.py")
                 if "riskminer.expert_write" in p.read_text(encoding="utf-8") and "review" not in p.parts
                 and p.name not in ("worker.py",)]
    assert offenders == [], offenders


async def test_link_item_card_approve_and_undo(expert, db):
    from riskminer.review import queue_sync
    await queue_sync.sync(db)
    iid = await _scalar(db, "SELECT id FROM review_item WHERE kind='link' AND status='open' ORDER BY id LIMIT 1")
    assert iid, "sync should create link items from 'review' candidates"
    card = (await expert.get(f"/api/review-items/{iid}")).json()
    assert [o["key"] for o in card["options"]] == ["accept", "other", "none"] and card["context"]["href"].startswith("/projekty/")
    cand = await _scalar(db, "SELECT target_id FROM review_item WHERE id=:i", i=iid)
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "accept", "action": "approve"})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT review_status FROM link_candidate WHERE id=:c", c=cand) == "approved"
    assert await _scalar(db, "SELECT count(*) FROM project_procedure WHERE link_candidate_id=:c AND review_status='approved' AND method='expert'", c=cand) == 1
    # the candidate is protected now: a pipeline-style update keeps it approved
    await db.execute(text("UPDATE link_candidate SET review_status='proposed' WHERE id=:c"), {"c": cand})
    assert await _scalar(db, "SELECT review_status FROM link_candidate WHERE id=:c", c=cand) == "approved"
    u = await expert.post(f"/api/reviews/{r.json()['review_id']}/undo")
    assert u.status_code == 200, u.text
    assert await _scalar(db, "SELECT review_status FROM link_candidate WHERE id=:c", c=cand) == "proposed"
    assert await _scalar(db, "SELECT count(*) FROM project_procedure WHERE link_candidate_id=:c", c=cand) == 0


async def test_sync_is_idempotent_and_dismisses_decided(db):
    from riskminer.review import queue_sync
    a = await queue_sync.sync(db)
    n1 = await _scalar(db, "SELECT count(*) FROM review_item")
    await queue_sync.sync(db)
    assert await _scalar(db, "SELECT count(*) FROM review_item") == n1
    eid, iid = await _mk_event(db)
    await queue_sync.sync(db)
    assert await _scalar(db, "SELECT count(*) FROM review_item WHERE key = :k", k=f"evt:{eid}") == 1


async def test_event_decision_mirrors_into_change_cause_ai_and_gold_job(expert, db):
    if not await _scalar(db, "SELECT to_regclass('change_cause_ai') IS NOT NULL"):
        import pytest
        pytest.skip("change_cause_ai not present")
    row = (await db.execute(text("SELECT change_id, cause_ai_id, primary_code FROM v_change_cause_ai WHERE cause_ai_id IS NOT NULL "
                                 "AND review_status='proposed' LIMIT 1"))).first()
    if not row:
        import pytest
        pytest.skip("no AI cause rows yet")
    change_id, cause_id, _code = row
    pid = await _scalar(db, "SELECT id FROM project WHERE rm_id='RM-2026-003'")
    eid = await _scalar(db, """INSERT INTO risk_event (project_id, change_id, event_type, catalogue_code, summary, origin, review_status)
                               VALUES (:p, :c, 'EV_CHANGE_CAUSE_AI', 'R06', 'Przyczyna zmiany (AI)', 'AI', 'proposed') RETURNING id""", p=pid, c=change_id)
    iid = await _scalar(db, """INSERT INTO review_item (kind, code, target_table, target_id, project_id, title, model_pick, key)
                               VALUES ('event','ai_event','risk_event',:e,:p,'t','R06',:k) RETURNING id""", e=eid, p=pid, k=f"test:mirror:{eid}")
    r = await expert.post(f"/api/review-items/{iid}/decision", json={"option": "other", "action": "edit", "value": "R04 test", "gold": True})
    assert r.status_code == 200, r.text
    assert await _scalar(db, "SELECT review_status || ':' || primary_code FROM change_cause_ai WHERE id=:i", i=cause_id) == "edited:R04"
    job = (await db.execute(text("SELECT kind, payload FROM job WHERE id=:i"), {"i": r.json()["gold"]["job_id"]})).one()
    assert job[0] == "llm_rescore_gold" and job[1]["risk_event_id"] == eid and job[1]["code"] == "R04"
    u = await expert.post(f"/api/reviews/{r.json()['review_id']}/undo")
    assert u.status_code == 200, u.text
    assert await _scalar(db, "SELECT review_status FROM change_cause_ai WHERE id=:i", i=cause_id) == "proposed"
