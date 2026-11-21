"""Exports: gating, rm_ids, sep=semicolon, public datasets drop unverified AI rows and confidential documents (api_contract §4, §8.7)."""
import csv
import io

from sqlalchemy import text


async def test_login_only_datasets(client, expert):
    for ds in ("review_items", "review_decisions", "audit", "runs", "sources", "link_candidates"):
        assert (await client.get(f"/api/export/{ds}.json?limit=1")).status_code == 401, ds
        assert (await expert.get(f"/api/export/{ds}.json?limit=1")).status_code == 200, ds
    listing = (await client.get("/api/export")).json()
    assert "review_items" not in listing and "projects" in listing
    assert "review_items" in (await expert.get("/api/export")).json()


async def test_rm_ids_and_semicolon(client):
    r = await client.get("/api/export/projects.csv", params={"rm_ids": "RM-2026-003,RM-2026-019", "sep": "semicolon"})
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿")), delimiter=";"))
    assert len(rows) == 3 and "rm_id" in rows[0] and "value_amount" in rows[0] and "origin" in rows[0] and "source_id" in rows[0]
    j = (await client.get("/api/export/projects.json", params={"rm_ids": "RM-2026-003"})).json()
    assert [p["rm_id"] for p in j] == ["RM-2026-003"]


async def test_public_export_drops_unverified_ai_and_confidential(client, expert, db):
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id='RM-2026-003'"))).scalar()
    await db.execute(text("""INSERT INTO risk_event (project_id, event_type, catalogue_code, summary, origin, review_status)
                             VALUES (:p, 'EV_T', 'R04', 'Testowy AI do eksportu', 'AI', 'proposed')"""), {"p": pid})
    await db.execute(text("""INSERT INTO document (title, filename, sensitivity, doc_type, fetch_state, project_id)
                             VALUES ('tajny', 'tajny-eksport.pdf', 'confidential', 'PFU', 'found', :p)"""), {"p": pid})
    pub = (await client.get("/api/export/risk_events.json", params={"rm_id": "RM-2026-003"})).json()
    assert all(e["summary"] != "Testowy AI do eksportu" for e in pub)
    full = (await expert.get("/api/export/risk_events.json", params={"rm_id": "RM-2026-003"})).json()
    assert any(e["summary"] == "Testowy AI do eksportu" for e in full)
    docs = (await client.get("/api/export/documents.json", params={"rm_id": "RM-2026-003"})).json()
    assert all(d["filename"] != "tajny-eksport.pdf" for d in docs)


async def test_audit_export_columns(expert):
    r = await expert.get("/api/export/audit.csv?limit=2")
    assert r.status_code == 200
    head = r.text.lstrip("﻿").splitlines()[0]
    assert head.split(",")[:5] == ["id", "at", "actor", "action", "table_name"]


async def test_signals_export_public_with_filters(client):
    r = await client.get("/api/export/signals.csv", params={"terc": "12", "level": "woj", "limit": 5})
    assert r.status_code == 200, r.text
    head = r.text.lstrip("﻿").splitlines()[0].split(",")
    assert "days_overdue" in head and "origin" in head and "source_url" in head
    r2 = await client.get("/api/export/signals.json", params={"limit": 2})
    assert r2.status_code == 200 and len(r2.json()) == 2
    r3 = await client.get("/api/export/signals.json", params={"terc": "1209", "limit": 2})
    assert r3.status_code == 200


async def test_confidential_upload_only_for_owner_and_admin(client, expert, admin, db):
    pid = (await db.execute(text("SELECT id FROM project WHERE rm_id='RM-2026-003'"))).scalar()
    await db.execute(text("""INSERT INTO document (title, filename, sensitivity, doc_type, fetch_state, project_id, data)
        VALUES ('cudzy', 'cudzy-poufny.pdf', 'confidential', 'PFU', 'found', :p, '{"owner_user": "user:inny"}'::jsonb),
               ('moj', 'moj-poufny.pdf', 'confidential', 'PFU', 'found', :p, '{"owner_user": "user:test"}'::jsonb)"""), {"p": pid})

    async def names(c):
        return {d["filename"] for d in (await c.get("/api/documents", params={"rm_id": "RM-2026-003", "limit": 1000})).json()["items"]}
    assert not ({"cudzy-poufny.pdf", "moj-poufny.pdf"} & await names(client))
    ex = await names(expert)
    assert "moj-poufny.pdf" in ex and "cudzy-poufny.pdf" not in ex
    assert {"moj-poufny.pdf", "cudzy-poufny.pdf"} <= await names(admin)
    exp_docs = {d["filename"] for d in (await expert.get("/api/export/documents.json", params={"rm_id": "RM-2026-003"})).json()}
    assert "cudzy-poufny.pdf" not in exp_docs and "moj-poufny.pdf" in exp_docs


async def test_audit_export_filters_category_and_day(expert, db):
    r = await expert.get("/api/export/audit.json", params={"category": "expert", "since": "2000-01-01", "until": "2100-01-01", "limit": 50})
    assert r.status_code == 200 and all(x["actor"].startswith("user:") for x in r.json())
    assert (await expert.get("/api/export/audit.json", params={"category": "nope"})).status_code == 422
    a = (await expert.get("/api/audit", params={"until": "2000-01-01"})).json()
    assert a["total"] == 0
    row = (await expert.get("/api/audit", params={"limit": 1})).json()["items"][0]
    assert "table" in row and "row_id" in row


async def test_audit_list_since_day(expert):
    r = await expert.get("/api/audit", params={"since": "2026-11-21", "until": "2026-11-22", "category": "expert"})
    assert r.status_code == 200
