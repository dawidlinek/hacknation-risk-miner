"""Pipeline entry points (CLI + jobs). Each stage is idempotent and logged in ingestion_run.

    load_all = seed_catalogue → import_xlsx → import_bzp_copy → load bzp_api delta → derive_bzp
               → link_pilot → load scraped sources → write data/ref/pilot_projects.json → report
"""
from __future__ import annotations

import json
import logging
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from riskminer.config import REPO_ROOT, settings
from riskminer.db.session import raw_conn
from riskminer.ingest import dbutil

log = logging.getLogger("riskminer.pipeline")


def _rel(p: Path | str) -> str:
    p = Path(p)
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


async def _stage(connector: str, stage: str, params: dict, fn, job_id: int | None = None) -> dict:
    """Run `fn(conn, run_id)` inside an ingestion_run row (status/stats/error recorded)."""
    t0 = time.time()
    async with raw_conn() as conn:
        rid = await dbutil.start_run(conn, connector, stage, params, job_id=job_id)
        try:
            stats = await fn(conn, rid) or {}
            stats["seconds"] = round(time.time() - t0, 1)
            await dbutil.finish_run(conn, rid, "ok", stats)
            stats["run_id"] = str(rid)
            return stats
        except Exception as e:
            await dbutil.finish_run(conn, rid, "error", {"seconds": round(time.time() - t0, 1)},
                                    f"{type(e).__name__}: {e}\n{traceback.format_exc()[-3000:]}")
            raise


async def ensure_file_source(conn, kind: str, path: Path, *, url: str | None, sha256: str | None, licence: str,
                             note: str, run_id, retrieved_at: datetime | None = None) -> int:
    """One `source` row for a local file (organizer XLSX, BZP copy). Re-used across runs (same sha)."""
    sid = await conn.fetchval("SELECT id FROM source WHERE kind=$1 AND sha256=$2 AND path=$3 ORDER BY id LIMIT 1",
                              kind, sha256, _rel(path))
    if sid:
        return sid
    return await conn.fetchval(
        "INSERT INTO source (kind, url, method, retrieved_at, bytes, sha256, path, licence, status, note, run_id, manifest_key)"
        " VALUES ($1,$2,'FILE',$3,$4,$5,$6,$7,'ok',$8,$9,$10) RETURNING id",
        kind, url, retrieved_at or dbutil.now(), path.stat().st_size if path.exists() else None, sha256, _rel(path),
        licence, note, run_id, (sha256 or "")[:64])


# ---------------------------------------------------------------------------------------------
# BZP offline copy
# ---------------------------------------------------------------------------------------------

async def import_bzp_copy(limit: int | None = None, path: str | None = None, job_id: int | None = None) -> dict:
    from riskminer.ingest import bzp_notices

    p = Path(path or settings().bzp_copy_path)
    man_path = p.parent / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {}

    async def fn(conn, rid):
        sid = await ensure_file_source(
            conn, "bzp_copy", p, url=man.get("source"), sha256=man.get("sha256"),
            licence="public information (organizer copy of the BZP API, records unchanged)",
            note=(f"Organizer national BZP copy: {man.get('notices')} notices {man.get('publication_date_from')}"
                  f"..{man.get('publication_date_to')}; sha256 is of notices.jsonl.xz per organizer manifest.json"),
            run_id=rid,
            retrieved_at=datetime.fromisoformat(man["generated_at"]) if man.get("generated_at") else None)
        res = await bzp_notices.load_copy(conn, p, sid, settings().dsn, limit=limit)
        res.update(await bzp_notices.mark_latest_versions(conn))
        res["source_id"] = sid
        res["by_type"] = {r["notice_type"]: r["n"] for r in await conn.fetch(
            "SELECT notice_type, count(*) n FROM notice WHERE channel='bzp_copy' GROUP BY 1")}
        res["expected_by_type"] = man.get("by_type")
        return res

    return await _stage("bzp_copy", "load", {"path": _rel(p), "limit": limit}, fn, job_id)


async def load_bzp_api(job_id: int | None = None, source: str = "bzp_api") -> dict:
    """Live API pages (data/raw/<source>) -> notice rows (channel=<source>), one source row per page.
    Works for every connector exposing iter_notices(store): bzp_api (wod-kan delta), bzp_roads (sector=drogi)."""
    from riskminer import connectors
    try:
        mod = connectors.get(source)
    except ModuleNotFoundError:
        return {"skipped": f"connector {source} not available yet"}
    if not hasattr(mod, "iter_notices"):
        return {"skipped": f"{source}.iter_notices missing"}
    from riskminer.connectors.base import RawStore
    from riskminer.ingest import bzp_notices, external

    async def fn(conn, rid):
        store = RawStore(source)
        src = await external.load_manifest(conn, source, rid)
        by_path = src["by_path"]
        items = []
        for rec, raw_path, _sha in mod.iter_notices(store):
            items.append((rec, f"file:{raw_path}", by_path.get(raw_path)))
        n = await bzp_notices.load_records(conn, items, source)
        res = {"manifest": src["stats"], "notices": n}
        res.update(await bzp_notices.mark_latest_versions(conn))
        from riskminer.connectors import runner
        runner.parse(source)
        res.update(await external.load_derived(conn, source, rid, by_path))
        return res

    return await _stage(source, "load", {}, fn, job_id)


async def derive_bzp(job_id: int | None = None) -> dict:
    from riskminer.ingest import derive
    return await _stage("bzp", "derive", {}, derive.run, job_id)


async def link_pilot(job_id: int | None = None) -> dict:
    from riskminer.ingest import linking
    return await _stage("link_pilot", "link", {}, linking.run, job_id)


async def link_imported(rm_ids: list[str] | None = None, project_ids: list[int] | None = None,
                        job_id: int | None = None) -> dict:
    """Imported records (import agent): record checks, BZP link, risk events (riskminer/ingest/link_import.py)."""
    from riskminer.ingest import link_import

    async def fn(conn, rid):
        ids_ = list(project_ids or [])
        if rm_ids:
            ids_ += [r["id"] for r in await conn.fetch("SELECT id FROM project WHERE rm_id = ANY($1::text[])", list(rm_ids))]
        return await link_import.run(conn, rid, ids_)
    return await _stage("link_import", "link", {"rm_ids": rm_ids, "project_ids": project_ids}, fn, job_id)


async def derive_lengths(job_id: int | None = None) -> dict:
    from riskminer.ingest import lengths
    return await _stage("lengths", "derive", {}, lengths.run, job_id)


async def geo_buyers(job_id: int | None = None) -> dict:
    from riskminer.ingest import geo
    return await _stage("geo_buyers", "derive", {}, geo.run, job_id)


async def quality(job_id: int | None = None) -> dict:
    from riskminer.ingest import quality as q
    return await _stage("quality", "derive", {}, q.run, job_id)


async def refresh_rc(job_id: int | None = None) -> dict:
    async def fn(conn, rid):
        await conn.execute("REFRESH MATERIALIZED VIEW rc_contract")
        return {"rc_contract": await conn.fetchval("SELECT count(*) FROM rc_contract"),
                "dq_flagged": await conn.fetchval("SELECT count(*) FROM rc_contract WHERE NOT dq_ok")}
    return await _stage("rc_contract", "derive", {}, fn, job_id)


async def derive_geo(job_id: int | None = None) -> dict:
    """Order from docs/impl/api_contract.md §6: lengths -> buyer TERYT -> quality -> refresh rc_contract."""
    return {"lengths": await derive_lengths(job_id), "geo_buyers": await geo_buyers(job_id),
            "quality": await quality(job_id), "rc": await refresh_rc(job_id)}


async def link_national(job_id: int | None = None) -> dict:
    from riskminer.ingest import link_national as ln
    return await _stage("link_national", "link", {}, ln.run, job_id)


async def doc_text(job_id: int | None = None, force: bool = False) -> dict:
    from riskminer.ingest import doctext
    return await _stage("doctext", "derive", {"force": force},
                        lambda conn, rid: doctext.run(conn, rid, force=force), job_id)


async def derive_events(job_id: int | None = None) -> dict:
    """Risk events from notices, then anchor evidence (both recreate/annotate structured-field evidence rows)."""
    from riskminer.ingest import events
    res = await _stage("events", "derive", {}, events.run, job_id)
    res["anchors"] = await anchor_evidence(job_id)
    return res


async def assign_sectors(job_id: int | None = None) -> dict:
    """Re-apply the sector packs' assign rules to existing procedures (catalogue/<sector>/pack.yaml)."""
    from riskminer.ingest import sectors
    return await _stage("sectors", "derive", {}, sectors.run, job_id)


async def anchor_evidence(job_id: int | None = None) -> dict:
    """Point structured-field evidence at the exact occurrence of repeated fields (multi-part / multi-change notices)."""
    from riskminer.ingest import anchors
    return await _stage("anchors", "derive", {}, anchors.run, job_id)


async def import_xlsx(path: str | None = None, job_id: int | None = None) -> dict:
    from riskminer.ingest import xlsx_import
    p = Path(path or settings().organizer_xlsx_path)
    return await _stage("xlsx", "load", {"path": _rel(p)}, lambda conn, rid: xlsx_import.run(conn, rid, p), job_id)


async def seed_catalogue(job_id: int | None = None) -> dict:
    from riskminer.ingest import catalogue
    return await _stage("catalogue", "load", {}, catalogue.run, job_id)


# ---------------------------------------------------------------------------------------------
# Scraped sources
# ---------------------------------------------------------------------------------------------

async def load_source(source: str, job_id: int | None = None) -> dict:
    if source in ("bzp_api", "bzp_roads"):
        return await load_bzp_api(job_id, source)
    from riskminer.connectors import runner
    from riskminer.ingest import external

    parsed = runner.parse(source)

    async def fn(conn, rid):
        src = await external.load_manifest(conn, source, rid)
        res = {"manifest": src["stats"], "parse": parsed.get("counts")}
        res.update(await external.load_derived(conn, source, rid, src["by_path"]))
        return res

    return await _stage(source, "load", {}, fn, job_id)


async def scrape_and_load(source: str, job_id: int | None = None, **opts: Any) -> dict:
    import asyncio

    from riskminer.connectors import runner

    async with raw_conn() as conn:
        rid = await dbutil.start_run(conn, source, "fetch", {k: v for k, v in opts.items() if v is not None}, job_id=job_id)
    try:
        stats = await asyncio.to_thread(runner.scrape, source, str(rid), **opts)
        status = "ok" if not stats.get("error") else "partial"
    except Exception as e:
        async with raw_conn() as conn:
            await dbutil.finish_run(conn, rid, "error", {}, f"{type(e).__name__}: {e}")
        raise
    async with raw_conn() as conn:
        await dbutil.finish_run(conn, rid, status, stats)
    stats["load"] = await load_source(source, job_id)
    if source in ("bzp_api", "bzp_roads"):
        stats["derive"] = await derive_bzp(job_id)
    return stats


SCRAPED = ["vat_whitelist", "teryt", "geo", "mapa_dotacji", "ted", "kio", "nik", "cru", "docs_22",
           "docs_sample", "kposk", "gus_bdl", "gus_price_index", "fe_projects", "nfosigw", "bip_22", "gus_bir",
           "krs", "bk2021"]


async def load_scraped(job_id: int | None = None) -> dict:
    from riskminer import connectors
    out = {}
    for s in SCRAPED:
        if s not in connectors.available():
            continue
        if not (settings().raw_dir / s / "manifest.jsonl").exists():
            continue
        try:
            out[s] = await load_source(s, job_id)
        except Exception as e:  # noqa: BLE001 - one broken source must not stop the rest
            log.exception("load %s failed", s)
            out[s] = {"error": f"{type(e).__name__}: {e}"}
    return out


async def load_all(limit: int | None = None, skip_bzp: bool = False, job_id: int | None = None) -> dict:
    res: dict[str, Any] = {}
    res["catalogue"] = await seed_catalogue(job_id)
    res["xlsx"] = await import_xlsx(job_id=job_id)
    if not skip_bzp:
        res["bzp_copy"] = await import_bzp_copy(limit=limit, job_id=job_id)
    res["bzp_api"] = await load_bzp_api(job_id)
    if (settings().raw_dir / "bzp_roads" / "manifest.jsonl").exists():
        res["bzp_roads"] = await load_bzp_api(job_id, "bzp_roads")
    res["derive"] = await derive_bzp(job_id)
    res["link"] = await link_pilot(job_id)
    res["events"] = await derive_events(job_id)
    res["derive_geo"] = await derive_geo(job_id)
    res["scraped"] = await load_scraped(job_id)
    res["doctext"] = await doc_text(job_id)
    from riskminer.ingest import external
    async with raw_conn() as conn:
        res["external_links"] = await external.link_external(conn)
        res["pilot_ref"] = await external.write_pilot_ref(conn)
    res["link_national"] = await link_national(job_id)
    try:
        from riskminer.ingest import report
        res["report"] = await report.generate()
    except Exception as e:  # noqa: BLE001
        res["report"] = {"error": str(e)}
    return res
