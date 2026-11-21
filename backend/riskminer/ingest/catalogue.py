"""Load sector packs (catalogue/<sector>/*.yaml) into catalogue_* tables. Idempotent: expert edits
(status approved/rejected changed in the panel, version > 1) are never overwritten; only rows still at
version 1 created by the pack are refreshed."""
from __future__ import annotations

from pathlib import Path

import yaml

from riskminer.config import settings
from riskminer.ingest.dbutil import audit, upsert_copy

KEEP_EDITED = "WHERE {t}.version = 1 AND {t}.approved_by IS NULL"


def _y(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


async def _upsert(conn, table: str, cols: tuple, rows: list, conflict: tuple) -> int:
    if not rows:
        return 0
    upd = [c for c in cols if c not in conflict]
    # only refresh rows untouched by experts
    from riskminer.ingest.dbutil import upsert_copy as _u  # noqa: F401
    import uuid
    tmp = f"tmp_cat_{uuid.uuid4().hex[:8]}"
    await conn.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP")
    await conn.copy_records_to_table(tmp, records=rows, columns=list(cols))
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in upd)
    r = await conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {tmp} "
        f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {sets}, updated_at = now() "
        + KEEP_EDITED.format(t=table))
    return int(r.split()[-1])


async def run(conn, rid) -> dict:
    root = Path(settings().catalogue_dir)
    out = {}
    async with conn.transaction():
        for pack in sorted(p for p in root.iterdir() if p.is_dir()):
            sector = (_y(pack / "pack.yaml") or {}).get("sector") or pack.name
            risks = (_y(pack / "risks.yaml") or {}).get("risks") or []
            rows = []
            for r in risks:
                code = r["id"]
                data = {k: v for k, v in r.items() if k not in ("id", "name", "status", "parent")}
                rows.append((sector, code, r.get("parent"), 2 if r.get("parent") else 1, r["name"],
                             r.get("effects_text"), r.get("status", "proposed"),
                             "AI" if r.get("status") == "proposed" and code in ("R16", "R17", "R18") else "SOURCE",
                             r.get("proposed_by"), data))
            out[f"{sector}.risk"] = await _upsert(conn, "catalogue_risk", ("sector", "code", "parent_code", "level", "name",
                                                                           "description", "status", "origin", "proposed_by", "data"),
                                                  rows, ("sector", "code", "version"))
            subs = _y(pack / "subsectors.yaml")
            out[f"{sector}.subsector"] = await _upsert(conn, "catalogue_subsector", ("sector", "code", "name", "status", "data"),
                                                       [(sector, s["code"], s["name"], s.get("status", "approved"), {})
                                                        for s in subs.get("subsectors") or []], ("sector", "code", "version"))
            cpv = (_y(pack / "cpv_map.yaml") or {}).get("cpv_map") or []
            out[f"{sector}.cpv"] = await _upsert(conn, "catalogue_cpv_map", ("sector", "cpv", "label", "subsector_code", "strength",
                                                                            "status", "data"),
                                                 [(sector, c["cpv"], c.get("label"), c.get("subsector"), c.get("strength"),
                                                   c.get("status", "approved"), {}) for c in cpv], ("sector", "cpv", "version"))
            docs = (_y(pack / "doc_types.yaml") or {}).get("doc_types") or []
            out[f"{sector}.doc_type"] = await _upsert(conn, "catalogue_doc_type", ("sector", "code", "name", "phase", "status", "data"),
                                                      [(sector, d["code"], d["name"], d.get("phase"), d.get("status", "approved"), {})
                                                       for d in docs], ("sector", "code", "version"))
            items = []
            for cl in (_y(pack / "checklist.yaml") or {}).get("checklists") or []:
                for it in cl.get("items") or []:
                    items.append((sector, it["code"], cl.get("code"), it["text"], it.get("status", "approved"),
                                  {"checklist": cl.get("code"), "checklist_name": cl.get("name"), "refs": it.get("refs"),
                                   "source": cl.get("source")}))
            out[f"{sector}.checklist"] = await _upsert(conn, "catalogue_checklist", ("sector", "code", "phase", "text", "status", "data"),
                                                       items, ("sector", "code", "version"))
            cls = (_y(pack / "clauses.yaml") or {}).get("clauses") or []
            out[f"{sector}.clause"] = await _upsert(conn, "catalogue_clause", ("sector", "code", "risk_code", "text", "status", "data"),
                                                    [(sector, c["code"], c.get("risk_code"), c["text"], c.get("status", "approved"), {})
                                                     for c in cls], ("sector", "code", "version"))
            entries = []
            for fname, key, table in (("event_types.yaml", "event_types", "event_type"), ("red_flags.yaml", "red_flags", "red_flag"),
                                      ("evidence_states.yaml", "evidence_states", "evidence_state"),
                                      ("evidence_states.yaml", "document_fetch_states", "fetch_state"),
                                      # expert assumptions (docs/impl/api_contract.md §6): data.assumption = true
                                      ("mitigations.yaml", "mitigations", "mitigation"),
                                      ("funding_programmes.yaml", "programmes", "funding_programme"),
                                      ("allocation.yaml", "risks", "allocation"),
                                      # change-cause label set for the AI classifier (session L reads the YAML too)
                                      ("cause_labels.yaml", "labels", "cause_label")):
                doc = _y(pack / fname) or {}
                assumption = bool(doc.get("assumption"))
                for e in doc.get(key) or []:
                    data = {**e, "assumption": True} if assumption else e
                    entries.append((sector, table, e["code"], e.get("name") or e.get("text") or e.get("label") or e.get("short"),
                                    e.get("status", "approved"), data))
                if doc.get("defaults") is not None:
                    entries.append((sector, table, "defaults", "domyślne parametry", "proposed",
                                    {"defaults": doc["defaults"], "assumption": assumption}))
            for fname, table in (("similarity.yaml", "similarity"), ("lexicon.yaml", "lexicon")):
                d = _y(pack / fname)
                if d:
                    entries.append((sector, table, "default", table, "approved", d))
            out[f"{sector}.entry"] = await _upsert(conn, "catalogue_entry", ("sector", "table_name", "code", "name", "status", "data"),
                                                   entries, ("sector", "table_name", "code", "version"))
        await audit(conn, "system:catalogue", "seed", "catalogue_risk", None, None, out)
    return out


__all__ = ["run", "upsert_copy"]
