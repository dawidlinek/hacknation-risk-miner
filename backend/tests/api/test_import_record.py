"""The organizer's extra project record (11:00 test): every text shape reaches the import agent, and an imported record is
checked, linked to BZP and gets its risk events like a pilot. Nothing persists: files go to tmp, DB work is rolled back."""
from __future__ import annotations

import csv
import json
import uuid

import asyncpg
import openpyxl
import pytest
from docx import Document

from riskminer.config import settings
from riskminer.db.session import set_codecs
from riskminer.imports import registry, sandbox
from riskminer.ingest import dbutil, link_import

HEAD = registry.KNOWN_FORMATS["zestaw organizatora"]["headers"]
ROW = [23, "RM-T-2026-023", "NIP", "7722260381", "Gmina Gidle", "Jednostka samorządu terytorialnego", "Polska", "10", "łódzkie",
       "Gidle", "Budowa sieci kanalizacji sanitarnej w miejscowości Ruda", "całe postępowanie", "Projekt KPO",
       "KPOD.03.15-IW.17-0008/25", "Gospodarka wodno-ściekowa", "Roboty budowlane", "Ustawa Pzp – zamówienie krajowe", "PLN",
       "Zakończone", "Rejestr publiczny", "2026-11-21", "2.0",
       "KPO, inwestycja B3.1.1. Wartość przedsięwzięcia: 3 560 796,21 zł; dofinansowanie: 2 428 948,62 zł. Opis: „Kanalizacja | test”"]


def _check(path):
    headers, rows = sandbox.read_all_rows(path)
    rec = dict(zip(headers, rows[0]))
    assert len(rows) == 1
    assert rec["Identyfikator rekordu"] == "RM-T-2026-023"
    assert rec["Identyfikator publiczny"] == "KPOD.03.15-IW.17-0008/25"
    assert str(rec["Adnotacja instytucji"]).startswith("KPO, inwestycja B3.1.1. Wartość przedsięwzięcia: 3 560 796,21 zł")
    return rec


def test_xlsx_one_row_with_column_sheet_not_named_projekty(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Arkusz1"
    ws.append(HEAD)
    ws.append(ROW)
    desc = wb.create_sheet("Opis kolumn")      # longer than the one-row data sheet: must not be picked
    desc.append(["Kolumna", "Opis"])
    for h in HEAD:
        desc.append([h, "opis kolumny"])
    p = tmp_path / "rekord.xlsx"
    wb.save(p)
    _check(p)


@pytest.mark.parametrize("delim", [";", ",", "\t", "|"])
def test_csv_one_row_any_delimiter(tmp_path, delim):
    p = tmp_path / "rekord.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(HEAD)
        w.writerow(ROW)
    _check(p)


def test_txt_pipe_dump_and_markdown_table(tmp_path):
    row = [str(v).replace("|", "/") for v in ROW]
    p = tmp_path / "rekord.txt"
    p.write_text("=== SHEET Projekty 2 23\n" + " | ".join(HEAD) + "\n" + " | ".join(row) + "\n", encoding="utf-8")
    _check(p)
    m = tmp_path / "rekord.md"
    m.write_text("| " + " | ".join(HEAD) + " |\n|" + "---|" * len(HEAD) + "\n| " + " | ".join(row) + " |\n", encoding="utf-8")
    _check(m)


def test_txt_field_lines_with_wrapped_value(tmp_path):
    lines = [f"{h}: {v}" for h, v in zip(HEAD, ROW)]
    cut = lines[-1].index(" ", 60)
    lines[-1] = lines[-1][:cut] + "\n" + lines[-1][cut + 1:]      # a wrapped annotation continues on the next line
    p = tmp_path / "rekord.txt"
    p.write_text("Rekord projektu\n\n" + "\n".join(lines), encoding="cp1250", errors="replace")
    rec = _check(p)
    assert rec["Nazwa odbiorcy"] == "Gmina Gidle"


def test_json_and_docx_vertical_table(tmp_path):
    j = tmp_path / "rekord.json"
    j.write_text(json.dumps({"rekord": [dict(zip(HEAD, ROW))]}, ensure_ascii=False), encoding="utf-8")
    _check(j)
    doc = Document()
    t = doc.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Kolumna", "Wartość"
    for h, v in zip(HEAD, ROW):
        c = t.add_row().cells
        c[0].text, c[1].text = h, str(v)
    d = tmp_path / "rekord.docx"
    doc.save(d)
    _check(d)


def test_description_is_not_a_record(tmp_path):
    p = tmp_path / "opis.txt"
    p.write_text("Opis inwestycji\n\nBudowa kanalizacji w gminie, 7 km, 4 przepompownie.\nTermin: 18 miesięcy.", encoding="utf-8")
    headers, _ = sandbox.read_all_rows(p)
    assert sum(1 for h in headers if sandbox._known(h)) < 3


def test_record_checks_flag_planted_errors():
    p = {"rm_id": "RM-T", "teryt_woj": "10", "public_id": "KPOD.03.15-IW.13-0008/25", "public_id_type": "Projekt KPO",
         "value_amount": 100, "subsidy_amount": 120,
         "dataset_row": {"Identyfikator odbiorcy": "7722260382", "Województwo": "mazowieckie"}}
    codes = {c for c, *_ in link_import.record_issues(p)}
    assert {"nip_checksum", "kpo_iw_woj", "teryt_woj_mismatch", "subsidy_gt_value"} <= codes
    p2 = {**p, "public_id": "2025/BZP 00177537/01", "public_id_type": "Projekt KPO", "subsidy_amount": 1,
          "dataset_row": {"Identyfikator odbiorcy": "7722260381", "Województwo": "łódzkie"}}
    assert {c for c, *_ in link_import.record_issues(p2)} == {"public_id_type_mismatch"}


async def test_imported_kpo_record_links_and_gets_events():
    """Gidle Ruda (KPO number cited in the buyer's BZP notices) -> kpo_cited link, contract, risk events; rolled back."""
    conn = await asyncpg.connect(settings().dsn)
    await set_codecs(conn)
    tr = conn.transaction()
    await tr.start()
    try:
        proc = await conn.fetchval("SELECT id FROM procedure WHERE ocid = 'ocds-148610-cd1dbec8-2938-4d10-bbd4-cc60465639d1'")
        if proc is None:
            pytest.skip("BZP copy without the Gidle procedure")
        pid = await conn.fetchval("""INSERT INTO project (rm_id, title, beneficiary_name, beneficiary_nip, external_ids, public_id_type,
                                     public_id, teryt_woj, province, is_pilot, origin, review_status, dataset_row)
                                     VALUES ('RM-T-2026-023', 'Budowa sieci kanalizacji sanitarnej w miejscowości Ruda', 'Gmina Gidle',
                                     '7722260381', $1, 'Projekt KPO', 'KPOD.03.15-IW.17-0008/25', '10', 'PL10', false, 'SOURCE', 'auto', $2)
                                     RETURNING id""",
                                  {"kpo": "KPOD.03.15-IW.17-0008/25"}, {"Identyfikator odbiorcy": "7722260381", "Województwo": "łódzkie"})
        rid = await dbutil.start_run(conn, "link_import", "link", {"test": True}, run_id=str(uuid.uuid4()))
        out = await link_import.run(conn, rid, [pid])
        assert out["link"]["linked"] == 1
        pp = await conn.fetchrow("SELECT method, score, review_status FROM project_procedure WHERE project_id = $1 AND procedure_id = $2",
                                 pid, proc)
        assert pp["method"] == "kpo_cited" and pp["score"] >= 0.9 and pp["review_status"] == "auto"
        lc = await conn.fetchrow("SELECT features, explanation FROM link_candidate WHERE left_table = 'project' AND left_id = $1", pid)
        assert lc["features"]["given"] == "KPOD.03.15-IW.17-0008/25" and lc["features"]["citing_notices"]
        n_ev = await conn.fetchval("SELECT count(*) FROM risk_event WHERE project_id = $1", pid)
        assert n_ev == out["events"] and (n_ev > 0 or out["shared_procedures"] > 0)
    finally:
        await tr.rollback()
        await conn.close()


def test_sample_rows_reports_text_record(tmp_path):
    p = tmp_path / "rekord.txt"
    p.write_text("\n".join(f"{h}: {v}" for h, v in zip(HEAD, ROW)), encoding="utf-8")
    out, data = sandbox.sample_rows(p)
    assert "23 kolumn" in out and data["rows"]


async def test_imported_bzp_record_links_exact_and_resolves_missing_nip():
    """A record with a BZP number and a NIP that failed its checksum (stored empty by the importer): exact_id link, NIP
    taken from the notice, the planted NIP error reported as a review item. Rolled back."""
    conn = await asyncpg.connect(settings().dsn)
    await set_codecs(conn)
    tr = conn.transaction()
    await tr.start()
    try:
        proc = await conn.fetchval("SELECT id FROM procedure WHERE contract_notice_no = '2025/BZP 00177537'")
        if proc is None:
            pytest.skip("BZP copy without the Gidle procedure")
        pid = await conn.fetchval("""INSERT INTO project (rm_id, title, beneficiary_name, beneficiary_nip, external_ids, public_id_type,
                                     public_id, teryt_woj, province, is_pilot, origin, review_status, dataset_row)
                                     VALUES ('RM-T-2026-024', 'Budowa sieci kanalizacji sanitarnej w miejscowości Ruda', 'Gmina Gidle',
                                     NULL, $1, 'Ogłoszenie BZP', '2025/BZP 00177537/01', '10', 'PL10', false, 'SOURCE', 'auto', $2)
                                     RETURNING id""",
                                  {"bzp": "2025/BZP 00177537/01", "bzp_base": "2025/BZP 00177537"},
                                  {"Identyfikator odbiorcy": "7722260382", "Województwo": "łódzkie"})
        rid = await dbutil.start_run(conn, "link_import", "link", {"test": True}, run_id=str(uuid.uuid4()))
        out = await link_import.run(conn, rid, [pid])
        assert out["link"]["per_project"][0]["method"] == "exact_id"
        assert "nip_checksum" in out["issue_codes"]
        codes = {r["code"] for r in await conn.fetch("SELECT code FROM review_item WHERE project_id = $1", pid)}
        assert "nip_checksum" in codes and "nip_mismatch" not in codes
    finally:
        await tr.rollback()
        await conn.close()
