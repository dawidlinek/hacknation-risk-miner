"""Load scraped sources into the DB.

manifest.jsonl  -> one `source` row per line (+ `ingestion_run` rows reconstructed for --no-db runs)
records.jsonl   -> external_record / source_check / document / link_candidate (via connector.parse())
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from riskminer.config import REPO_ROOT, settings
from riskminer.ingest.dbutil import upsert_copy

log = logging.getLogger("riskminer.external")


def _ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def _uuid(s: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(s))
    except (ValueError, TypeError):
        return None


async def load_manifest(conn, source: str, rid) -> dict:
    path = settings().raw_dir / source / "manifest.jsonl"
    entries = []
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    # reconstruct ingestion_run rows for runs executed without the DB (--no-db)
    runs: dict[uuid.UUID, list] = {}
    for e in entries:
        u = _uuid(e.get("run_id"))
        if u:
            runs.setdefault(u, []).append(e)
    for u, es in runs.items():
        st = Counter(e.get("status") for e in es)
        ts = [t for t in (_ts(e.get("fetched_at")) for e in es) if t]
        await conn.execute(
            "INSERT INTO ingestion_run (id, connector, stage, params, started_at, finished_at, status, stats) "
            "VALUES ($1,$2,'fetch','{}',$3,$4,'ok',$5) ON CONFLICT (id) DO UPDATE SET "
            "stats = ingestion_run.stats || EXCLUDED.stats, finished_at = greatest(ingestion_run.finished_at, EXCLUDED.finished_at)",
            u, source, min(ts) if ts else None, max(ts) if ts else None,
            {"manifest_lines": len(es), **{f"status_{k}": v for k, v in st.items()}})
    recs = []
    for e in entries:
        recs.append((source, e.get("url"), (e.get("method") or "")[:10] or None, e.get("params") or {}, _ts(e.get("fetched_at")),
                     e.get("http_status"), (e.get("content_type") or "")[:120] or None, e.get("bytes"), e.get("sha256"),
                     e.get("path"), e.get("licence"), e.get("status") if e.get("status") in ("ok", "empty", "blocked", "error") else "error",
                     e.get("note") or None, (e.get("key") or e.get("sha256") or "")[:64], _uuid(e.get("run_id"))))
    await upsert_copy(conn, "source", ("kind", "url", "method", "params", "retrieved_at", "http_status", "content_type",
                                       "bytes", "sha256", "path", "licence", "status", "note", "manifest_key", "run_id"),
                      recs, ("kind", "manifest_key", "retrieved_at"), update=[])
    by_path: dict[str, int] = {}
    for r in await conn.fetch("SELECT id, path FROM source WHERE kind=$1 AND path IS NOT NULL ORDER BY id", source):
        by_path[r["path"]] = r["id"]
    st = Counter(e.get("status") for e in entries)
    return {"by_path": by_path, "stats": {"lines": len(entries), **dict(st), "runs": len(runs)}}


def _dec(x: Any) -> Decimal | None:
    if x in (None, ""):
        return None
    try:
        v = Decimal(str(x)).quantize(Decimal("0.01"))
        return v if abs(v) < Decimal("1e15") else None
    except (InvalidOperation, ValueError):
        return None


def _date(x: Any) -> date | None:
    if not x:
        return None
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def _src(by_path: dict[str, int], p: str | None) -> int | None:
    if not p:
        return None
    if p in by_path:
        return by_path[p]
    try:   # absolute -> repo-relative
        rel = str(Path(p).resolve().relative_to(REPO_ROOT.resolve()))
        return by_path.get(rel)
    except ValueError:
        return None


async def load_derived(conn, source: str, rid, by_path: dict[str, int]) -> dict:
    path = settings().data_dir and Path(settings().data_dir) / "derived" / source / "records.jsonl"
    if not path or not path.exists():
        return {"derived": 0}
    ext, checks, docs, hints = [], [], [], []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            t = d.get("record_type")
            if t == "external_record":
                ext.append(d)
            elif t == "source_check":
                checks.append(d)
            elif t == "document":
                docs.append(d)
            elif t == "link_hint":
                hints.append(d)
    out: dict[str, Any] = {"external_records": len(ext), "source_checks": len(checks), "documents": len(docs),
                           "link_hints": len(hints)}
    async with conn.transaction():
        if ext:
            await upsert_copy(conn, "external_record",
                              ("source_kind", "kind", "external_id", "title", "published_on", "buyer_nip", "buyer_regon",
                               "buyer_name", "teryt", "province", "value_amount", "value_currency", "value_vat", "url",
                               "text", "data", "source_id", "origin", "review_status"),
                              [(d["source"], d["kind"], str(d["external_id"])[:200], d.get("title"), _date(d.get("published_on")),
                                (d.get("buyer_nip") or None) and str(d["buyer_nip"])[:10], (d.get("buyer_regon") or None) and str(d["buyer_regon"])[:14],
                                d.get("buyer_name"), (d.get("teryt") or None) and str(d["teryt"])[:7],
                                (d.get("province") or None) and str(d["province"])[:40], _dec(d.get("value_amount")),
                                (d.get("value_currency") or None) and str(d["value_currency"])[:3], d.get("value_vat_basis"),
                                d.get("url"), (d.get("text") or "").replace("\x00", "") or None,
                                json.loads(json.dumps(d.get("data") or {}, default=str).replace("\\u0000", "")),
                                _src(by_path, d.get("raw_path")), "SOURCE", "auto") for d in ext],
                              ("kind", "external_id"))
            r = await conn.execute(
                "DELETE FROM external_record WHERE source_kind = $1 AND NOT ((kind || ':' || external_id) = ANY($2::text[])) "
                "AND review_status NOT IN ('approved', 'edited')", source,
                [f"{d['kind']}:{str(d['external_id'])[:200]}" for d in ext])
            out["external_removed_stale"] = int(r.split()[-1])
            await conn.execute("UPDATE external_record e SET buyer_org_id = o.id FROM organization o "
                               "WHERE e.buyer_nip = o.nip AND e.source_kind = $1 AND e.buyer_org_id IS DISTINCT FROM o.id", source)
            await conn.execute("UPDATE external_record e SET procedure_id = p.id FROM procedure p "
                               "WHERE e.source_kind = $1 AND e.data->>'ocid' = p.ocid AND e.procedure_id IS DISTINCT FROM p.id", source)
        if checks:
            await upsert_copy(conn, "source_check",
                              ("source_kind", "subject_type", "subject_key", "query", "n_hits", "n_relevant", "result",
                               "matched_ids", "note", "checked_at", "source_id"),
                              [(d["source"], d["subject_type"], str(d["subject_key"])[:100], d.get("query"), d.get("n_hits") or 0,
                                d.get("n_relevant") or 0, d["result"], [str(x) for x in d.get("matched_ids") or []],
                                d.get("note") or None, _ts(d.get("checked_at")) or datetime.now(UTC),
                                _src(by_path, d.get("raw_path"))) for d in checks],
                              ("source_kind", "subject_type", "subject_key"))
        if docs:
            proj = {r["rm_id"]: r["id"] for r in await conn.fetch("SELECT id, rm_id FROM project")}
            procs = {r["ocid"]: r["id"] for r in await conn.fetch(
                "SELECT id, ocid FROM procedure WHERE ocid = ANY($1::text[])",
                list({d["subject_key"] for d in docs if d.get("subject_type") == "procedure"}))}
            exts = {f"{r['kind']}:{r['external_id']}": r["id"] for r in await conn.fetch(
                "SELECT id, kind, external_id FROM external_record WHERE source_kind = $1", source)}
            rows = []
            for d in docs:
                st, sk = d.get("subject_type"), d.get("subject_key")
                ident = "|".join(str(d.get(k) or "") for k in ("raw_path", "url", "filename", "doc_type", "fetch_state", "title"))
                key = f"{source}|{sk}|{hashlib.sha1(ident.encode()).hexdigest()}"
                rows.append((key[:200], proj.get(sk) if st == "project" else None, procs.get(sk) if st == "procedure" else None,
                             exts.get(sk) if st == "external_record" else None, d.get("doc_type"), d.get("title"),
                             d.get("filename"), d.get("url"), d.get("raw_sha256"), d.get("raw_path"), d.get("text_path"),
                             d.get("pages"), d.get("fetch_state") or "found", d.get("note") or None,
                             {**(d.get("data") or {}), "source": source}, _src(by_path, d.get("raw_path")), "SOURCE", "auto"))
            await upsert_copy(conn, "document", ("key", "project_id", "procedure_id", "external_record_id", "doc_type", "title",
                                                 "filename", "url", "sha256", "path", "text_path", "pages", "fetch_state",
                                                 "note", "data", "source_id", "origin", "review_status"), rows, ("key",))
            # the connector's current parse is authoritative: drop documents it no longer emits (expert-approved rows stay)
            r = await conn.execute("DELETE FROM document WHERE data->>'source' = $1 AND NOT (key = ANY($2::text[])) "
                                   "AND review_status NOT IN ('approved', 'edited')", source, [x[0] for x in rows])
            out["documents_removed_stale"] = int(r.split()[-1])
            from riskminer.ingest import ocr_load          # OCR results survive reloads (matched by sha256)
            out["documents_ocr_applied"] = await ocr_load.apply(conn)
        if hints:
            out["link_candidates"] = await _load_hints(conn, source, rid, hints)
        if source == "vat_whitelist":
            out["organizations_verified"] = await _apply_vat(conn)
        if source == "teryt":
            out["ref_teryt"] = await _apply_teryt(conn)
    return out


async def _load_hints(conn, source: str, rid, hints: list[dict]) -> int:
    proj = {r["rm_id"]: r["id"] for r in await conn.fetch("SELECT id, rm_id FROM project")}
    orgs = {r["nip"]: r["id"] for r in await conn.fetch("SELECT id, nip FROM organization WHERE nip IS NOT NULL")}
    exts = {f"{r['kind']}:{r['external_id']}": r["id"] for r in await conn.fetch(
        "SELECT id, kind, external_id FROM external_record")}
    rows = []
    for h in hints:
        left = proj.get(h["left_key"]) if h["left_type"] == "project" else orgs.get(h["left_key"])
        if left is None:
            continue
        rt = "external_record" if h["right_type"] == "external_record" else h["right_type"]
        score = float(h.get("score") or 0)
        rows.append((h["left_type"], left, rt, exts.get(h["right_key"]), h["right_key"], h["method"], h.get("features") or {},
                     score, None, h.get("explanation") or None,
                     "accept" if score >= 0.9 else "review" if score >= 0.6 else "reject",
                     "auto" if score >= 0.9 else "proposed", rid))
    await upsert_copy(conn, "link_candidate", ("left_table", "left_id", "right_table", "right_id", "right_ref", "method",
                                               "features", "score", "rank", "explanation", "decision", "review_status", "run_id"),
                      rows, ("left_table", "left_id", "right_table", "right_ref", "method"),
                      update=["right_id", "features", "score", "explanation", "decision", "run_id"])
    return len(rows)


async def _apply_vat(conn) -> int:
    r = await conn.execute("""
        UPDATE organization o SET
          regon = coalesce(o.regon, nullif(e.data->>'regon', '')),
          krs = coalesce(o.krs, nullif(e.data->>'krs', '')),
          vat_status = coalesce(e.data->>'statusVat', o.vat_status),
          verified_by_source_id = e.source_id,
          data = o.data || jsonb_build_object('vat_whitelist', jsonb_build_object(
                   'name', e.data->>'name', 'statusVat', e.data->>'statusVat', 'checked', e.published_on))
        FROM external_record e
        WHERE e.kind = 'vat_entity' AND e.external_id = o.nip""")
    return int(r.split()[-1])


async def _apply_teryt(conn) -> int:
    rows = await conn.fetch("SELECT external_id, title, data, source_id FROM external_record WHERE kind = 'teryt_unit'")
    recs = []
    for r in rows:
        d = r["data"] or {}
        terc = str(d.get("terc7") or d.get("terc") or r["external_id"])[:7]
        woj = str(d.get("woj") or terc[:2])[:2]
        lvl = d.get("level") or ("woj" if len(terc) <= 2 else "pow" if len(terc) <= 4 else "gmi")
        recs.append((terc, lvl, r["title"] or d.get("name") or terc, d.get("kind"), woj,
                     (str(d.get("pow")) if d.get("pow") else None), (str(d.get("gmi")) if d.get("gmi") else None),
                     (str(d.get("rodz")) if d.get("rodz") else None), r["source_id"]))
    await upsert_copy(conn, "ref_teryt", ("terc", "level", "name", "kind", "woj", "pow", "gmi", "rodz", "source_id"),
                      recs, ("terc",))
    return len(recs)


async def link_external(conn) -> dict:
    """Generic post-load links: buyer orgs and OCIDs on external records."""
    a = await conn.execute("UPDATE external_record e SET buyer_org_id = o.id FROM organization o "
                           "WHERE e.buyer_nip = o.nip AND e.buyer_org_id IS DISTINCT FROM o.id")
    b = await conn.execute("UPDATE external_record e SET procedure_id = p.id FROM procedure p "
                           "WHERE e.data->>'ocid' = p.ocid AND e.procedure_id IS DISTINCT FROM p.id")
    return {"buyer_org": int(a.split()[-1]), "procedure": int(b.split()[-1])}


async def write_pilot_ref(conn) -> dict:
    """data/ref/pilot_projects.json from the DB (same shape as scripts/make_pilot_ref.py) for connectors."""
    projects = await conn.fetch("SELECT * FROM project WHERE is_pilot ORDER BY rm_id")
    out = []
    for p in projects:
        link = await conn.fetchrow("""SELECT pr.*, pp.method FROM project_procedure pp JOIN procedure pr ON pr.id=pp.procedure_id
                                      WHERE pp.project_id=$1 AND pp.method <> 'cross_reference_related'
                                      ORDER BY pp.score DESC NULLS LAST LIMIT 1""", p["id"])
        notices, contractors, urls = [], [], []
        if link:
            for n in await conn.fetch("SELECT notice_type, notice_number, object_id, url, published_at, extracted->'platform_urls' pu "
                                      "FROM notice WHERE ocid=$1 AND is_latest ORDER BY published_at", link["ocid"]):
                notices.append({"type": n["notice_type"], "number": n["notice_number"], "objectId": n["object_id"],
                                "url": n["url"], "date": n["published_at"].date().isoformat() if n["published_at"] else None})
                for u in (n["pu"] or []):
                    if u not in urls:
                        urls.append(u)
            for c in await conn.fetch("SELECT contractor_name, contractor_nip, contractor_id_raw FROM contract WHERE procedure_id=$1",
                                      link["id"]):
                contractors.append({"name": c["contractor_name"], "id_raw": c["contractor_id_raw"], "nip": c["contractor_nip"],
                                    "regon": None})
        out.append({"rm_id": p["rm_id"], "lp": int((p["dataset_row"] or {}).get("Lp.") or 0), "buyer_nip": p["beneficiary_nip"],
                    "buyer_name": p["beneficiary_name"], "buyer_city": p["city"], "woj_teryt": p["teryt_woj"],
                    "woj": (p["dataset_row"] or {}).get("Województwo"), "title": p["title"], "scope": p["scope_text"],
                    "public_id_type": p["public_id_type"], "public_id": p["public_id"],
                    "kpo_number": (p["external_ids"] or {}).get("kpo"), "annotation": p["annotation"],
                    "tender_id": link["ocid"] if link else None, "link_method": link["method"] if link else None,
                    "notices": notices, "contractors": contractors, "platform_urls": urls})
    path = settings().ref_dir / "pilot_projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": str(path), "projects": len(out)}
