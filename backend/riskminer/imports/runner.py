"""Deterministic importer (api_contract §3.5 steps 4 and 6): applies an approved declarative spec, never generated code.

spec = {"format": "xlsx"|"csv", "sheet": "...", "headers": [...], "columns": {header: {"field": f, "rule": r}},
        "answers": {"value_vat_basis": "gross"|"net"}}
Rows become `project` rows (+ buyer `organization`), is_pilot = false, origin SOURCE, source_id = the imported file.
A value failing a strict rule is not imported (identifier left empty) and becomes a review_item (kind import);
nothing is fixed silently. Upserts never overwrite rows an expert approved or edited (DB trigger + explicit skip).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from riskminer.imports import rules, sandbox
from riskminer.ingest import ids
from riskminer.ingest.xlsx_import import parse_annotation

STRICT_ID_FIELDS = {"organization.nip", "project.public_id", "procedure.bzp_number", "project.kpo_number"}


@dataclass
class RunResult:
    rows: int = 0
    ok: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)
    would: dict[str, Any] = field(default_factory=lambda: {"insert": {"project": 0, "organization": 0}, "update": 0,
                                                            "protected_skipped": 0})
    project_keys: list[str] = field(default_factory=list)
    written_keys: list[str] = field(default_factory=list)      # inserted or updated (protected rows excluded)

    def as_dict(self) -> dict:
        return {"rows": self.rows, "ok": self.ok, "failed": self.failed, "failures": self.failures[:200], "would": self.would}


def _row_to_record(row: dict[str, Any], spec: dict, file_sha: str, rownum: int, res: RunResult) -> dict | None:
    cols = spec.get("columns") or {}
    answers = spec.get("answers") or {}
    vals: dict[str, Any] = {}
    row_failed = False
    for header, m in cols.items():
        f, rule = m.get("field"), m.get("rule")
        if not f or m.get("status") == "proposal":
            continue
        v = row.get(header)
        ok, reason = rules.check(rule, v, answers)
        if not ok and v not in (None, ""):
            res.failures.append({"row": rownum, "column": header, "rule": reason or rule, "value_masked": rules.mask(v)})
            row_failed = True
            if f in STRICT_ID_FIELDS or rule == "money_requires_vat_basis":
                continue                                     # never import a value that fails a strict rule
        vals[f] = v
    if not any(vals.get(k) for k in ("project.title", "organization.name", "project.public_id")):
        return None                                          # empty row
    res.ok += 0 if row_failed else 1
    res.failed += 1 if row_failed else 0
    ann = parse_annotation(str(vals.get("project.annotation") or ""))
    vat = answers.get("value_vat_basis")
    value = rules.parse_money(vals["project.value"]) if vals.get("project.value") not in (None, "") else ann.get("value")
    value_vat = vat if vals.get("project.value") not in (None, "") else ("unknown" if ann.get("value") else None)
    subsidy = rules.parse_money(vals["project.subsidy"]) if vals.get("project.subsidy") not in (None, "") else ann.get("subsidy")
    subsidy_vat = vat if vals.get("project.subsidy") not in (None, "") else ("unknown" if ann.get("subsidy") else None)
    woj = str(vals.get("project.teryt_woj") or "").strip()
    woj = woj.zfill(2) if woj.isdigit() else None
    pub = str(vals.get("project.public_id") or vals.get("procedure.bzp_number") or vals.get("project.kpo_number") or "").strip()
    ext: dict[str, Any] = {}
    nb = ids.norm_bzp(pub) if pub else None
    if nb:
        ext.update(bzp=f"{nb[0]}/{nb[1] or '01'}", bzp_base=nb[0])
    elif pub and ids.kpo_check(pub)["valid_format"]:
        ext["kpo"] = pub
    scope = str(vals.get("project.scope_text") or "")
    pm = re.search(r"część\s*(\d+)", scope, re.I)
    rm_id = str(vals.get("project.rm_id") or "").strip() or f"IMP-{file_sha[:8]}-{rownum:04d}"
    nip = ids.digits(vals.get("organization.nip")) or None
    return {
        "rm_id": rm_id[:20], "title": str(vals.get("project.title") or vals.get("organization.name") or rm_id),
        "description": vals.get("project.description") or ann.get("description"),
        "beneficiary_name": vals.get("organization.name"), "beneficiary_nip": nip if nip and len(nip) == 10 else None,
        "external_ids": json.dumps(ext), "public_id_type": vals.get("project.public_id_type"), "public_id": pub or None,
        "scope_text": scope or None, "scope_part": int(pm.group(1)) if pm else None, "funding_programme": ann.get("programme"),
        "value_amount": value, "value_currency": "PLN" if value is not None else None, "value_vat": value_vat,
        "subsidy_amount": subsidy, "subsidy_currency": "PLN" if subsidy is not None else None, "subsidy_vat": subsidy_vat,
        "status": vals.get("project.status"), "teryt_woj": woj, "province": f"PL{woj}" if woj else None,
        "city": vals.get("project.city"), "record_version": str(vals.get("project.record_version") or "") or None,
        "record_date": rules.parse_date(vals.get("project.record_date")),
        "annotation": vals.get("project.annotation") or vals.get("project.note"),
        "dataset_row": json.dumps({k: (None if v is None else str(v)) for k, v in row.items()}, ensure_ascii=False),
        "_org_name": vals.get("organization.name"),
    }


async def run(db: AsyncSession, path: Path, spec: dict, *, file_sha: str, source_id: int | None, limit: int | None = None,
              dry_run: bool = True) -> RunResult:
    headers, data = sandbox.read_all_rows(path, limit)
    keep = [i for i, h in enumerate(headers) if not rules.is_pii_header(h)]   # personal data never imported
    res = RunResult()
    records = []
    for n, r in enumerate(data, start=2):                    # row 1 = header (Excel numbering)
        row = {headers[i]: (r[i] if i < len(r) else None) for i in keep}
        res.rows += 1
        rec = _row_to_record(row, spec, file_sha, n, res)
        if rec:
            records.append(rec)
    keys = [r["rm_id"] for r in records]
    res.project_keys = keys
    rows_ex = (await db.execute(text("SELECT rm_id, review_status, is_pilot FROM project WHERE rm_id = ANY(:k)"),
                                {"k": keys})).all() if keys else []
    existing = {r[0]: r[1] for r in rows_ex}
    # expert-approved rows and the organizer's pilot rows (loaded by the XLSX stage) are never overwritten by an import
    protected = {r[0] for r in rows_ex if r[1] in ("approved", "edited") or r[2]}
    res.would["insert"]["project"] = sum(1 for k in keys if k not in existing)
    res.would["update"] = sum(1 for k in keys if k in existing and k not in protected)
    res.would["protected_skipped"] = len(protected)
    res.written_keys = [k for k in dict.fromkeys(keys) if k not in protected]
    nips = {r["beneficiary_nip"] for r in records if r["beneficiary_nip"]}
    known = {r[0] for r in (await db.execute(text("SELECT nip FROM organization WHERE nip = ANY(:n)"),
                                             {"n": list(nips)})).all()} if nips else set()
    res.would["insert"]["organization"] = len(nips - known)
    sp = await db.begin_nested() if dry_run else None
    try:
        for r in records:
            if r["rm_id"] in protected:
                continue
            if r["beneficiary_nip"]:
                await db.execute(text("""INSERT INTO organization (nip, name, name_norm, roles, nip_valid, origin, review_status, source_id)
                                         VALUES (:nip, :name, lower(:name), ARRAY['buyer'], true, 'SOURCE', 'auto', :sid)
                                         ON CONFLICT (nip) DO NOTHING"""),
                                 {"nip": r["beneficiary_nip"], "name": r["_org_name"] or r["beneficiary_nip"], "sid": source_id})
            params = {k: v for k, v in r.items() if not k.startswith("_")}
            params["sid"] = source_id
            await db.execute(text("""
                INSERT INTO project (rm_id, title, description, beneficiary_name, beneficiary_nip, external_ids, public_id_type,
                    public_id, scope_text, scope_part, funding_programme, value_amount, value_currency, value_vat, subsidy_amount,
                    subsidy_currency, subsidy_vat, status, teryt_woj, province, city, record_version, record_date, annotation,
                    dataset_row, is_pilot, source_id, origin, review_status)
                VALUES (:rm_id, :title, :description, :beneficiary_name, :beneficiary_nip, CAST(:external_ids AS jsonb),
                    :public_id_type, :public_id, :scope_text, :scope_part, :funding_programme, :value_amount, :value_currency,
                    :value_vat, :subsidy_amount, :subsidy_currency, :subsidy_vat, :status, :teryt_woj, :province, :city,
                    :record_version, :record_date, :annotation, CAST(:dataset_row AS jsonb), false, :sid, 'SOURCE', 'auto')
                ON CONFLICT (rm_id) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,
                    beneficiary_name = EXCLUDED.beneficiary_name, beneficiary_nip = EXCLUDED.beneficiary_nip,
                    external_ids = EXCLUDED.external_ids, public_id = EXCLUDED.public_id, scope_text = EXCLUDED.scope_text,
                    public_id_type = EXCLUDED.public_id_type, scope_part = EXCLUDED.scope_part,
                    funding_programme = EXCLUDED.funding_programme, record_version = EXCLUDED.record_version,
                    record_date = EXCLUDED.record_date,
                    value_amount = EXCLUDED.value_amount, value_vat = EXCLUDED.value_vat, subsidy_amount = EXCLUDED.subsidy_amount,
                    subsidy_vat = EXCLUDED.subsidy_vat, status = EXCLUDED.status, teryt_woj = EXCLUDED.teryt_woj,
                    province = EXCLUDED.province, city = EXCLUDED.city, annotation = EXCLUDED.annotation,
                    dataset_row = EXCLUDED.dataset_row, source_id = EXCLUDED.source_id, updated_at = now()
                WHERE project.review_status NOT IN ('approved', 'edited') AND project.is_pilot = false"""), params)
        await db.execute(text("""UPDATE project p SET beneficiary_org_id = o.id FROM organization o
                                 WHERE p.beneficiary_nip = o.nip AND p.rm_id = ANY(:k) AND p.beneficiary_org_id IS DISTINCT FROM o.id"""),
                         {"k": keys})
    finally:
        if sp is not None:
            await sp.rollback()
    return res


def money_decimal(v) -> Decimal | None:
    return rules.parse_money(v)
