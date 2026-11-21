"""Import agent end to end on a synthetic organizer-format file (owner D). Transactional fixtures: nothing persists in
the main DB; uploaded files go to a temp dir."""
from __future__ import annotations

import io

import openpyxl
import pytest
from sqlalchemy import text

from riskminer.imports import registry, service


@pytest.fixture(autouse=True)
def _tmp_imports(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "imports_dir", lambda: tmp_path / "imports")
    monkeypatch.setattr(service, "raw_root", lambda: tmp_path / "raw")


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Projekty"
    ws.append(registry.KNOWN_FORMATS["zestaw organizatora"]["headers"] + ["Kwota", "E-mail kontaktowy"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROW_OK = [1, "TEST-IMP-001", "NIP", "9121715754", "Gmina Oława", "JST", "Polska", "02", "dolnośląskie", "Oława",
          "Budowa kanalizacji testowej", "całe postępowanie", "Ogłoszenie BZP", "2022/BZP 00058537/01", "wod-kan",
          "Roboty budowlane", "Pzp", "PLN", "Zakończone", "test", "2026-11-21", "1.0", None, "1 234 567,89 zł", "jan@example.com"]
ROW_BAD_NIP = [2, "TEST-IMP-002", "NIP", "9121715755", "Gmina X", "JST", "Polska", "02", "dolnośląskie", "X",
               "Projekt z błędnym NIP", "całe postępowanie", "Projekt KPO", "KPOD.03.15-IW.13-0004/25", "wod-kan",
               "Roboty budowlane", "Pzp", "PLN", "W realizacji", "test", "2026-11-21", "1.0", None, "100 000,00", None]


async def test_import_needs_login(client):
    assert (await client.get("/api/importers")).status_code == 401


async def test_import_agent_flow(expert, db):
    f = {"files": ("projekty_test.xlsx", _xlsx([ROW_OK, ROW_BAD_NIP]),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await expert.post("/api/imports", files=f)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert code.startswith("IMP-") and r.json()["files"][0]["kind"] == "xlsx"

    st = (await expert.post(f"/api/imports/{code}/inspect")).json()
    calls = [c["call"] for c in st["tool_calls"]]
    assert any(c.startswith("sample_rows") for c in calls) and any(c.startswith("match_schema") for c in calls)
    assert "zestaw organizatora" in next(c["out"] for c in st["tool_calls"] if c["call"].startswith("match_schema"))

    st = (await expert.post(f"/api/imports/{code}/propose-mapping")).json()
    m = {x["column"]: x for x in st["mapping"]}
    assert m["Identyfikator odbiorcy"]["field"] == "organization.nip"
    assert m["E-mail kontaktowy"]["status"] == "dropped"                 # personal data never mapped
    assert m["Kwota"]["status"] == "question" and st["status"] == "awaiting_answer"
    assert (await expert.post(f"/api/imports/{code}/test-run", json={"rows": 50})).status_code == 409   # questions first

    st = (await expert.post(f"/api/imports/{code}/answers", json={"value_vat_basis": "gross"})).json()
    assert st["status"] == "mapped" and not st["questions"]

    tr = (await expert.post(f"/api/imports/{code}/test-run", json={"rows": 50})).json()
    assert tr["rows"] == 2 and tr["failed"] == 1
    assert any(x["rule"] == "nip_checksum" and "***" in x["value_masked"] for x in tr["failures"])
    assert tr["would"]["insert"]["project"] == 2
    n = (await db.execute(text("SELECT count(*) FROM project WHERE rm_id LIKE 'TEST-IMP-%'"))).scalar()
    assert n == 0                                                         # test run is rolled back

    ap = (await expert.post(f"/api/imports/{code}/approve", json={"importer_name": "zestaw organizatora (test)"})).json()
    assert ap["version"].startswith("v")
    rn = (await expert.post(f"/api/imports/{code}/run")).json()
    assert rn["job_id"] and rn["run_id"]

    res = await service.full_run(db, code, rn["run_id"])                  # the job handler's code path, same transaction
    assert res["inserted"] == 2 and res["failed"] == 1
    p = (await db.execute(text("SELECT value_amount, value_vat, beneficiary_nip, source_id FROM project WHERE rm_id = 'TEST-IMP-001'"))).one()
    assert str(p[0]) == "1234567.89" and p[1] == "gross" and p[2] == "9121715754" and p[3]
    bad = (await db.execute(text("SELECT beneficiary_nip FROM project WHERE rm_id = 'TEST-IMP-002'"))).scalar()
    assert bad is None                                                    # failing NIP not imported, review item instead
    assert (await db.execute(text("SELECT count(*) FROM review_item WHERE kind = 'import' AND key LIKE :k"),
                             {"k": f"imp:{code}:%"})).scalar() >= 1
    assert (await expert.get("/api/importers")).json()


@pytest.mark.parametrize("path,kw", [
    ("/api/imports", {"files": {"files": ("juror.xlsx", b"x", "application/octet-stream")}}),
    ("/api/imports/{code}/inspect", {}),
    ("/api/imports/{code}/propose-mapping", {}),
    ("/api/imports/{code}/answers", {"json": {"value_vat_basis": "gross"}}),
    ("/api/imports/{code}/test-run", {"json": {"rows": 5}}),
    ("/api/imports/{code}/approve", {"json": {"importer_name": "juror"}}),
    ("/api/imports/{code}/run", {}),
])
async def test_juror_cannot_write_imports(client, expert, db, path, kw):
    """The read-only demo Juror may list importers and read an import, but every write step answers 403 read_only."""
    f = {"files": ("projekty_juror.xlsx", _xlsx([ROW_OK]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    code = (await expert.post("/api/imports", files=f)).json()["code"]
    r = await client.post("/api/auth/demo-login", json={"persona": "juror"})
    assert r.status_code == 200 and r.json()["read_only"] is True
    assert (await client.get("/api/importers")).status_code == 200
    assert (await client.get(f"/api/imports/{code}")).status_code == 200
    before = (await db.execute(text("SELECT count(*), max(updated_at) FROM import_session"))).one()
    r = await client.post(path.format(code=code), **kw)
    assert r.status_code == 403 and r.json()["code"] == "read_only", r.text
    assert (await db.execute(text("SELECT count(*), max(updated_at) FROM import_session"))).one() == before
