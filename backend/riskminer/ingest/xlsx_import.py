"""Organizer XLSX (22 pilot projects) -> project rows, with validation-first import.

The dataset contains deliberate errors. Nothing is fixed silently: every problem becomes a
`review_item` (kind=discrepancy) for the expert. Checks here are the ones decidable from the
file alone (identifier formats, NIP checksum, TERYT vs voivodeship name, KPO number structure);
cross-source checks (część vs lots, KPO value vs contracts, missing notice) run in linking.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import openpyxl

from riskminer.ingest import ids
from riskminer.ingest.dbutil import audit, upsert_copy

SHEET = "Projekty"


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def read_rows(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = [_s(h) for h in next(it)]
    out = []
    for i, row in enumerate(it, start=2):
        if not row or not any(row):
            continue
        d = {h: _s(v) for h, v in zip(header, row)}
        d["_excel_row"] = i
        out.append(d)
    return out


def parse_annotation(a: str) -> dict:
    out: dict = {}
    if not a:
        return out
    m = re.search(r"Wartość przedsięwzięcia:\s*([\d\s\xa0.,]+)\s*zł", a)
    if m:
        out["value"] = ids.pl_money(m.group(1))
    m = re.search(r"dofinansowanie:\s*([\d\s\xa0.,]+)\s*zł", a, re.I)
    if m:
        out["subsidy"] = ids.pl_money(m.group(1))
    m = re.search(r"^(KPO[^.]*\.?\s*(?:inwestycja\s+[A-Z0-9.]+)?)", a)
    if m:
        out["programme"] = m.group(1).strip(" .")
    m = re.search(r"Opis:\s*[„\"](.+?)[”\"]\s*$", a, re.S)
    if m:
        out["description"] = m.group(1).strip()
    return out


async def run(conn, rid, path: Path) -> dict:
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    from riskminer.ingest.pipeline import ensure_file_source
    sid = await ensure_file_source(conn, "xlsx", path, url=None, sha256=sha,
                                   licence="organizer dataset (HackNation 2026, MFiPR)",
                                   note="Organizer dataset Risk_Miner_dane_projekty.xlsx, sheet Projekty", run_id=rid)
    rows = read_rows(path)
    projects, issues = [], []
    for r in rows:
        rm = r.get("Identyfikator rekordu")
        lp = r.get("Lp.")
        nip = ids.digits(r.get("Identyfikator odbiorcy"))
        woj = r.get("Kod województwa (TERYT)", "").zfill(2)
        ann = parse_annotation(r.get("Adnotacja instytucji", ""))
        id_type = r.get("Rodzaj identyfikatora publicznego", "")
        pub = r.get("Identyfikator publiczny", "")
        ext: dict = {}
        scope = r.get("Zakres rekordu", "")
        pm = re.search(r"część\s*(\d+)", scope, re.I)
        part = int(pm.group(1)) if pm else None

        def issue(code: str, title: str, severity: str = "medium", **detail):
            issues.append((rm, code, title, severity, {"excel_row": r["_excel_row"], "lp": lp, **detail}))

        if r.get("Rodzaj identyfikatora odbiorcy", "").upper() == "NIP" and not ids.nip_valid(nip):
            issue("nip_checksum", f"Wiersz {lp}: NIP odbiorcy {nip} ma niepoprawną sumę kontrolną", "high", nip=nip)
        if id_type.startswith("Ogłoszenie BZP"):
            nb = ids.norm_bzp(pub)
            if not nb:
                issue("bzp_format", f"Wiersz {lp}: numer ogłoszenia BZP „{pub}” ma niepoprawny format", "high", value=pub)
            else:
                ext["bzp"] = f"{nb[0]}/{nb[1] or '01'}"
                ext["bzp_base"] = nb[0]
                if f"{nb[0]}/{nb[1] or '01'}" != pub:
                    issue("bzp_normalised", f"Wiersz {lp}: numer BZP znormalizowano z „{pub}” do „{ext['bzp']}”", "low",
                          value=pub, normalised=ext["bzp"])
        elif id_type.startswith("Projekt KPO"):
            k = ids.kpo_check(pub, woj)
            ext["kpo"] = pub
            if not k["valid_format"]:
                issue("kpo_format", f"Wiersz {lp}: numer projektu KPO „{pub}” ma niepoprawny format", "high", value=pub)
            elif k.get("iw_matches_woj") is False:
                issue("kpo_iw_woj", f"Wiersz {lp}: segment IW.{k['iw']} numeru KPO nie pasuje do województwa {woj} "
                      f"(oczekiwano IW.{k['iw_expected']})", "medium", value=pub, check=k)
        else:
            issue("public_id_type", f"Wiersz {lp}: nieznany rodzaj identyfikatora publicznego „{id_type}”", "medium")
        name_woj = r.get("Województwo", "").strip().lower()
        if ids.WOJ.get(woj) and name_woj and ids.WOJ[woj] != name_woj:
            issue("teryt_woj_mismatch", f"Wiersz {lp}: kod TERYT {woj} to {ids.WOJ[woj]}, a w wierszu „{name_woj}”",
                  "medium", teryt=woj, name=name_woj)
        if ann.get("value") and ann.get("subsidy") and ann["subsidy"] > ann["value"]:
            issue("subsidy_gt_value", f"Wiersz {lp}: dofinansowanie większe niż wartość przedsięwzięcia", "medium")
        rd = None
        try:
            rd = date.fromisoformat(r.get("Data sporządzenia rekordu", "")[:10])
        except ValueError:
            pass
        projects.append((
            rm, r.get("Nazwa przedsięwzięcia"), ann.get("description"), r.get("Nazwa odbiorcy"), nip or None, ext,
            id_type, pub, scope, part, ann.get("programme"), ann.get("value"), "PLN" if ann.get("value") else None,
            "unknown" if ann.get("value") else None, ann.get("subsidy"), "PLN" if ann.get("subsidy") else None,
            "unknown" if ann.get("subsidy") else None, r.get("Status przedsięwzięcia"), woj, f"PL{woj}",
            r.get("Siedziba odbiorcy"), r.get("Wersja rekordu"), rd, r.get("Adnotacja instytucji") or None,
            {k: v for k, v in r.items()}, True, sid, "SOURCE", "auto",
        ))
    cols = ("rm_id", "title", "description", "beneficiary_name", "beneficiary_nip", "external_ids", "public_id_type",
            "public_id", "scope_text", "scope_part", "funding_programme", "value_amount", "value_currency", "value_vat",
            "subsidy_amount", "subsidy_currency", "subsidy_vat", "status", "teryt_woj", "province", "city",
            "record_version", "record_date", "annotation", "dataset_row", "is_pilot", "source_id", "origin", "review_status")
    async with conn.transaction():
        await upsert_copy(conn, "project", cols, projects, ("rm_id",))
        # buyers as organizations (do not overwrite names that came from BZP)
        await upsert_copy(conn, "organization", ("nip", "name", "name_norm", "roles", "nip_valid", "origin", "review_status"),
                          [(p[4], p[3], (p[3] or "").lower(), ["buyer"], ids.nip_valid(p[4]), "SOURCE", "auto")
                           for p in projects if p[4]], ("nip",), update=[])
        await conn.execute("UPDATE project p SET beneficiary_org_id = o.id FROM organization o "
                           "WHERE p.beneficiary_nip = o.nip AND p.beneficiary_org_id IS DISTINCT FROM o.id")
        pid = {r["rm_id"]: r["id"] for r in await conn.fetch("SELECT id, rm_id FROM project")}
        await upsert_copy(
            conn, "review_item",
            ("key", "kind", "code", "target_table", "target_id", "project_id", "title", "detail", "severity", "created_by", "source_id"),
            [(f"xlsx|{rm}|{code}", "discrepancy", code, "project", pid.get(rm), pid.get(rm), title, detail, sev,
              "importer:xlsx", sid) for rm, code, title, sev, detail in issues],
            ("key",), update=["title", "detail", "severity", "source_id"])
        await audit(conn, "system:xlsx_import", "import", "project", None, None,
                    {"rows": len(projects), "issues": len(issues), "sha256": sha})
    return {"projects": len(projects), "issues": len(issues), "source_id": sid,
            "issue_codes": sorted({i[1] for i in issues})}
