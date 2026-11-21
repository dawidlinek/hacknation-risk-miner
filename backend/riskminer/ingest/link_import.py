"""Imported project records (import agent 2.1) -> the same checks, links and derived facts as the organizer's pilots.

The import job (`riskminer/imports/jobs.py`) writes the `project` rows; this stage then
  1. runs the file-level checks of `xlsx_import` on each record (NIP checksum, KPO number vs voivodeship, TERYT code vs
     voivodeship name, public identifier vs its declared type, subsidy > value) -> review_item (kind discrepancy);
  2. links the record to BZP with `linking.run(project_ids=...)` (method, score, features in link_candidate);
  3. attaches the procedure's risk events (CALC, from structured BZP fields) to the project, never taking events that
     already belong to another project (that conflict becomes a review item instead).
Plan vs actual, timeline and changes are read from the linked procedure, so the card is complete after this stage.
Nothing is fixed silently: every mismatch is a review item for the expert.
"""
from __future__ import annotations

from typing import Any

from riskminer.imports import registry
from riskminer.ingest import ids, linking
from riskminer.ingest.dbutil import audit, upsert_copy


def _raw(row: dict[str, Any] | None, field: str) -> str | None:
    """Value of the original column mapped to `field` (dataset_row keeps the record exactly as uploaded)."""
    for k, v in (row or {}).items():
        if registry.field_for(k) == field and v not in (None, ""):
            return str(v).strip()
    return None


def record_issues(p: dict) -> list[tuple[str, str, str, dict]]:
    """-> [(code, title, severity, detail)] decidable from the record alone (same rules as the organizer XLSX import)."""
    out: list[tuple[str, str, str, dict]] = []
    row = p.get("dataset_row") or {}
    rm = p["rm_id"]
    raw_nip = _raw(row, "organization.nip")
    if raw_nip and not ids.nip_valid(ids.digits(raw_nip)):
        out.append(("nip_checksum", f"Rekord {rm}: NIP odbiorcy {ids.digits(raw_nip)} ma niepoprawną sumę kontrolną", "high",
                    {"nip": ids.digits(raw_nip)}))
    woj = (p.get("teryt_woj") or "").zfill(2) if p.get("teryt_woj") else None
    pub = (p.get("public_id") or "").strip()
    id_type = (p.get("public_id_type") or _raw(row, "project.public_id_type") or "").strip()
    nb = ids.norm_bzp(pub) if pub else None
    k = ids.kpo_check(pub, woj) if pub else {"valid_format": False}
    if pub and id_type.lower().startswith("projekt kpo") and not k["valid_format"]:
        out.append(("public_id_type_mismatch", f"Rekord {rm}: rodzaj identyfikatora to „{id_type}”, a identyfikator „{pub}” "
                    "nie jest numerem projektu KPO", "high", {"value": pub, "type": id_type}))
    if pub and id_type.lower().startswith("ogłoszenie bzp") and not nb:
        out.append(("public_id_type_mismatch", f"Rekord {rm}: rodzaj identyfikatora to „{id_type}”, a identyfikator „{pub}” "
                    "nie jest numerem ogłoszenia BZP", "high", {"value": pub, "type": id_type}))
    if nb and f"{nb[0]}/{nb[1] or '01'}" != pub:
        out.append(("bzp_normalised", f"Rekord {rm}: numer BZP znormalizowano z „{pub}” do „{nb[0]}/{nb[1] or '01'}”", "low",
                    {"value": pub, "normalised": f"{nb[0]}/{nb[1] or '01'}"}))
    if k.get("valid_format") and k.get("iw_matches_woj") is False:
        out.append(("kpo_iw_woj", f"Rekord {rm}: segment IW.{k['iw']} numeru KPO nie pasuje do województwa {woj} "
                    f"(oczekiwano IW.{k['iw_expected']})", "medium", {"value": pub, "check": k}))
    name_woj = (_raw(row, "project.woj_name") or "").lower()
    if woj and ids.WOJ.get(woj) and name_woj and ids.WOJ[woj] != name_woj:
        out.append(("teryt_woj_mismatch", f"Rekord {rm}: kod TERYT {woj} to {ids.WOJ[woj]}, a w rekordzie „{name_woj}”",
                    "medium", {"teryt": woj, "name": name_woj}))
    if p.get("value_amount") is not None and p.get("subsidy_amount") is not None and p["subsidy_amount"] > p["value_amount"]:
        out.append(("subsidy_gt_value", f"Rekord {rm}: dofinansowanie większe niż wartość przedsięwzięcia", "medium", {}))
    return out


async def run(conn, rid, project_ids: list[int]) -> dict:
    projects = [dict(r) for r in await conn.fetch("SELECT * FROM project WHERE id = ANY($1::bigint[]) AND NOT is_pilot ORDER BY rm_id",
                                                  project_ids)]
    ids_ = [p["id"] for p in projects]
    if not ids_:
        return {"projects": 0}
    issues = [(p, *i) for p in projects for i in record_issues(p)]
    await upsert_copy(conn, "review_item",
                      ("key", "kind", "code", "target_table", "target_id", "project_id", "title", "detail", "severity",
                       "created_by", "source_id"),
                      [(f"record|{p['rm_id']}|{code}", "discrepancy", code, "project", p["id"], p["id"], title, detail, sev,
                        "importer:record", p["source_id"]) for p, code, title, sev, detail in issues],
                      ("key",), update=["title", "detail", "severity", "source_id"])
    link = await linking.run(conn, rid, project_ids=ids_)
    async with conn.transaction():
        # events already attached to another project stay there; the shared procedure becomes a review item
        shared = await conn.fetch("""SELECT DISTINCT pp.project_id, p2.id AS other_id, p2.rm_id AS other_rm, pr.ocid
            FROM project_procedure pp JOIN procedure pr ON pr.id = pp.procedure_id
            JOIN project_procedure pp2 ON pp2.procedure_id = pp.procedure_id AND pp2.project_id <> pp.project_id
                 AND pp2.method <> 'cross_reference_related' AND pp2.review_status <> 'rejected'
            JOIN project p2 ON p2.id = pp2.project_id
            WHERE pp.project_id = ANY($1::bigint[]) AND pp.method <> 'cross_reference_related'""", ids_)
        rm_of = {p["id"]: p["rm_id"] for p in projects}
        await upsert_copy(conn, "review_item",
                          ("key", "kind", "code", "target_table", "target_id", "project_id", "title", "detail", "severity",
                           "created_by"),
                          [(f"record|{rm_of[s['project_id']]}|procedure_shared|{s['other_rm']}", "discrepancy", "procedure_shared",
                            "project", s["project_id"], s["project_id"],
                            f"Postępowanie {s['ocid']} jest już powiązane z projektem {s['other_rm']}; sprawdź, czy rekord "
                            f"{rm_of[s['project_id']]} nie dubluje tamtego projektu", {"ocid": s["ocid"], "other": s["other_rm"]},
                            "high", "linker:import") for s in shared],
                          ("key",), update=["title", "detail"])
        attached = await conn.execute("""UPDATE risk_event e SET project_id = pp.project_id FROM project_procedure pp
            WHERE pp.project_id = ANY($1::bigint[]) AND pp.procedure_id = e.procedure_id
              AND pp.method <> 'cross_reference_related' AND pp.review_status <> 'rejected' AND e.project_id IS NULL""", ids_)
        await audit(conn, "system:linker", "link_import.events", "project", None, None,
                    {"rm_ids": [p["rm_id"] for p in projects], "events_attached": int(attached.split()[-1])})
    events = await conn.fetchval("SELECT count(*) FROM risk_event WHERE project_id = ANY($1::bigint[])", ids_)
    return {"projects": len(projects), "record_issues": len(issues), "issue_codes": sorted({i[1] for i in issues}),
            "link": {k: link.get(k) for k in ("linked", "by_method", "issues", "issue_codes", "per_project")},
            "events_attached": int(attached.split()[-1]), "events": events, "shared_procedures": len(shared)}
